from __future__ import annotations

import argparse
import logging
import sys
import textwrap


def _setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    from trade_py.cli import data, model, report, account, run

    domains = [("data", data), ("model", model), ("report", report), ("account", account), ("run", run)]
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

    dispatch = {"data": data, "model": model, "report": report, "account": account, "run": run}
    return dispatch[args.domain].main(args.args)


if __name__ == "__main__":
    raise SystemExit(main())
