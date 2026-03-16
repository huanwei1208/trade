"""trade serve — DAG Web UI + Online Inference Service.

Starts a single FastAPI server on the given port.

Usage:
  trade serve                   # start on default port 8080
  trade serve --port 9000       # custom port
  trade serve --data-root /path # custom data root
"""
from __future__ import annotations

import argparse
import logging

from trade_py.config import default_data_root

logger = logging.getLogger(__name__)

_DATA_ROOT = str(default_data_root())


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade serve",
        description="启动 DAG Web UI + 在线推理服务 (FastAPI)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  trade serve                    # http://localhost:8080\n"
            "  trade serve --port 9000\n"
            "  trade serve --reload           # 开发模式（文件变更自动重载）\n"
        ),
    )
    parser.add_argument("--data-root", default=_DATA_ROOT, help="数据根目录")
    parser.add_argument("--port", type=int, default=8080, help="监听端口（默认 8080）")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    parser.add_argument("--reload", action="store_true", help="开发模式：文件变更时自动重载")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv or [])

    try:
        import uvicorn
    except ImportError:
        print("错误: 需要安装 uvicorn  →  uv add uvicorn fastapi")
        return 1

    # Pass data_root to the app via environment variable
    import os
    os.environ["TRADE_DATA_ROOT"] = args.data_root

    logger.info("Starting trade serve on %s:%d  data_root=%s",
                args.host, args.port, args.data_root)

    uvicorn.run(
        "trade_py.web.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
