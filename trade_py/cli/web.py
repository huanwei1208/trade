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
import subprocess
import sys
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
    parser.add_argument("--web-dist", default="", help="前端构建目录（默认 trade_web/frontend/dist，存在时优先）")
    parser.add_argument("--reload", action="store_true", help="开发模式：文件变更时自动重载")
    parser.add_argument("--build", action="store_true", help="启动前重新构建前端 (npm run build)")
    return parser


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

    # Pass data_root to the app via environment variable
    import os
    os.environ["TRADE_DATA_ROOT"] = args.data_root
    if args.web_dist:
        os.environ["TRADE_WEB_DIST"] = args.web_dist
    else:
        default_dist = Path(__file__).resolve().parents[2] / "trade_web" / "frontend" / "dist"
        if default_dist.exists():
            os.environ["TRADE_WEB_DIST"] = str(default_dist)

    logger.info("Starting trade web on %s:%d  data_root=%s",
                args.host, args.port, args.data_root)

    uvicorn.run(
        "trade_web:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
        timeout_graceful_shutdown=3,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
