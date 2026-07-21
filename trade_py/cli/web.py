"""trade web — TradeDB Web API + UI host.

Starts a single FastAPI server on the given port.

Usage:
  trade web                   # start on default port 8080
  trade web --port 9000       # custom port
  trade web --data-root /path # custom data root
  trade web --build           # rebuild frontend before starting
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from trade_py.cli import global_flag_parent
from trade_py.infra.settings import default_data_root

logger = logging.getLogger(__name__)

_DATA_ROOT = str(default_data_root())


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade web",
        description="启动 DAG Web UI + 在线推理服务 (FastAPI)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[global_flag_parent()],
        epilog=(
            "示例:\n"
            "  trade web                      # http://localhost:8080\n"
            "  trade web --port 9000\n"
            "  trade web --build              # 重新构建前端后启动\n"
            "  trade web --reload             # 开发模式（文件变更自动重载）\n"
        ),
    )
    parser.add_argument("--data-root", default=_DATA_ROOT, help="数据根目录")
    parser.add_argument("--port", type=int, default=8080, help="监听端口（默认 8080）")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    parser.add_argument(
        "--web-dist", default="", help="前端构建目录（默认 trade_web/frontend/dist，存在时优先）"
    )
    parser.add_argument("--reload", action="store_true", help="开发模式：文件变更时自动重载")
    parser.add_argument("--build", action="store_true", help="启动前重新构建前端 (npm run build)")
    return parser


def _install_force_exit_safeguard(
    *,
    watchdog_delay: float | None = None,
) -> threading.Event:
    """Install a SIGINT handler that force-exits on the second Ctrl+C press.

    Uvicorn installs its own SIGINT handler during ``uvicorn.run()`` which
    replaces this one for the duration of server operation. After
    ``uvicorn.run()`` returns (server stopped) our handler from *before* the
    call is no longer in effect — we reinstall it post-run. The safeguard
    ensures that if graceful shutdown ever hangs (e.g. a third-party library
    spawns non-daemon threads), pressing Ctrl+C twice always terminates the
    process.
    """
    pressed = [False]
    shutdown_complete = threading.Event()

    def _handler(signum, frame):
        if watchdog_delay is not None:
            _schedule_force_exit(
                delay=watchdog_delay,
                exit_code=130,
                reason="interrupt shutdown deadline exceeded",
                cancel_event=shutdown_complete,
            )
        if pressed[0]:
            sys.stderr.write("\nForced exit.\n")
            os._exit(130)
        pressed[0] = True
        sys.stderr.write("\nInterrupt received. Press Ctrl+C again to force-exit.\n")

    signal.signal(signal.SIGINT, _handler)
    return shutdown_complete


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv or [])

    try:
        import uvicorn
    except ImportError:
        print("错误: 需要安装 uvicorn  →  uv add uvicorn fastapi")
        return 1

    if args.build:
        frontend_dir = Path(__file__).resolve().parents[2] / "trade_web" / "frontend"
        if not frontend_dir.exists():
            print(f"错误: 前端目录不存在: {frontend_dir}")
            return 1
        print(f"正在构建前端 ({frontend_dir}) ...")
        result = subprocess.run(["npm", "run", "build"], cwd=frontend_dir)
        if result.returncode != 0:
            print("错误: 前端构建失败，退出。")
            return result.returncode
        print("前端构建完成。")
    else:
        # Auto-detect if frontend source is newer than dist build
        frontend_dir = Path(__file__).resolve().parents[2] / "trade_web" / "frontend"
        dist_dir = frontend_dir / "dist"
        src_dir = frontend_dir / "src"
        index_html = dist_dir / "index.html"
        need_build = False
        if not index_html.exists():
            need_build = True
        elif src_dir.exists():
            dist_mtime = index_html.stat().st_mtime
            for src_file in src_dir.rglob("*"):
                if src_file.is_file() and src_file.stat().st_mtime > dist_mtime:
                    need_build = True
                    break
        if need_build and frontend_dir.exists():
            print("检测到前端代码更新，自动构建中...")
            result = subprocess.run(["npm", "run", "build"], cwd=frontend_dir)
            if result.returncode != 0:
                print("警告: 前端自动构建失败，使用现有dist版本。")
            else:
                print("前端自动构建完成。")

    os.environ["TRADE_DATA_ROOT"] = args.data_root
    os.environ.setdefault("TRADE_OBSERVATORY_ENABLED", "1")
    if args.web_dist:
        os.environ["TRADE_WEB_DIST"] = args.web_dist
    else:
        default_dist = Path(__file__).resolve().parents[2] / "trade_web" / "frontend" / "dist"
        if default_dist.exists():
            os.environ["TRADE_WEB_DIST"] = str(default_dist)

    logger.info("Starting trade web on %s:%d  data_root=%s", args.host, args.port, args.data_root)

    shutdown_complete = _install_force_exit_safeguard(watchdog_delay=5.0)
    try:
        uvicorn.run(
            "trade_web:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level="info",
            timeout_graceful_shutdown=3,
        )
    finally:
        shutdown_complete.set()

    leftovers = _non_daemon_thread_names()
    if leftovers:
        _schedule_force_exit(
            delay=2.0,
            exit_code=1,
            reason=f"incomplete shutdown; non-daemon threads remain: {','.join(leftovers)}",
        )
    return 0


def _non_daemon_thread_names() -> list[str]:
    current = threading.current_thread()
    return [
        thread.name
        for thread in threading.enumerate()
        if thread is not current and thread.is_alive() and not thread.daemon
    ]


def _schedule_force_exit(
    delay: float,
    *,
    exit_code: int,
    reason: str,
    cancel_event: threading.Event | None = None,
) -> None:
    """Spawn a daemon thread that force-exits the process after ``delay`` seconds.

    Guarantees the process terminates even if some non-daemon thread
    (third-party library, a forgotten ThreadPoolExecutor) is still alive
    after uvicorn stops. The Web lifespan explicitly closes its EventBus, and
    batch-ingest workers are daemonized, so this is defence-in-depth.
    """

    def _exit() -> None:
        if cancel_event is not None:
            if cancel_event.wait(timeout=delay):
                return
        else:
            time.sleep(delay)
        leftovers = _non_daemon_thread_names()
        diagnostic = (
            f"web shutdown forced after {delay:.1f}s: {reason}; "
            f"non_daemon_threads={','.join(leftovers) if leftovers else 'none'}; "
            f"exit_code={exit_code}"
        )
        logger.error(diagnostic)
        sys.stderr.write(f"\n{diagnostic}\n")
        os._exit(exit_code)

    threading.Thread(target=_exit, daemon=True, name="trade-web-force-exit").start()


if __name__ == "__main__":
    raise SystemExit(main())
