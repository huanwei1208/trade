from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path


def _load_dotenv() -> None:
    """Load a .env file into os.environ via python-dotenv.

    Search order: $TRADE_ENV_FILE, else <project-root>/.env. Existing
    environment variables always win (shell/cron export overrides the file),
    so non-interactive contexts (dagu ssh, cron) can supply ANTHROPIC_API_KEY
    via a file without touching the shell profile.
    """
    from dotenv import load_dotenv

    configured = os.environ.get("TRADE_ENV_FILE", "").strip()
    target = Path(configured).expanduser() if configured else Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(target, override=False)


def _setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    from trade_py.cli import data, model, account, event, start, web, kg, evaluate, factor, run, status, inspect, backup
    from trade_py.cli import daily, ops, dev

    domains = [
        # EBRT high-level commands (Phase 6)
        ("daily",   daily),
        ("ops",     ops),
        ("dev",     dev),
        # Legacy domains (kept as-is)
        ("run",     run),
        ("status",  status),
        ("inspect", inspect),
        ("backup",  backup),
        ("data",    data),
        ("model",   model),
        ("factor",  factor),
        ("account", account),
        ("event",   event),
        ("evaluate", evaluate),
        ("kg",      kg),
        ("start",   start),
        ("web",     web),
    ]
    domain_lines = "\n".join(
        f"  {name:<10}  {mod.make_parser().description}"
        for name, mod in domains
    )

    parser = argparse.ArgumentParser(
        prog="trade",
        description="A-share 交易智能平台",
        epilog=(
            f"可用域:\n{domain_lines}\n\n"
            "用 `trade <域> --help` 查看各域详细用法。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG 级日志")
    parser.add_argument("domain", choices=[n for n, _ in domains], metavar="<域>",
                        help="{" + " | ".join(n for n, _ in domains) + "}")
    parser.add_argument("args", nargs=argparse.REMAINDER, metavar="...", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)

    dispatch = {name: mod for name, mod in domains}
    return dispatch[args.domain].main(args.args)


if __name__ == "__main__":
    raise SystemExit(main())
