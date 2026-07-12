from __future__ import annotations

import argparse
import logging
import sys


def _setup_logging(verbose: bool = False, quiet: bool = False) -> None:
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
        force=True,
    )


def _extract_global_flags(argv: list[str]) -> tuple[list[str], bool, bool]:
    """Strip -v/--verbose/-q/--quiet from anywhere in argv; return (remaining, verbose, quiet)."""
    remaining: list[str] = []
    verbose = False
    quiet = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-v", "--verbose"):
            verbose = True
        elif a in ("-q", "--quiet"):
            quiet = True
        elif a.startswith("--verbose="):
            verbose = a.split("=", 1)[1].lower() in ("1", "true", "yes")
        elif a.startswith("--quiet="):
            quiet = a.split("=", 1)[1].lower() in ("1", "true", "yes")
        else:
            remaining.append(a)
        i += 1
    return remaining, verbose, quiet


def main(argv: list[str] | None = None) -> int:
    from trade_py.cli import data, model, account, event, start, web, kg, evaluate, factor, run, status, inspect, backup
    from trade_py.cli import daily, ops, dev, config, doctor

    domains = [
        # Operational (user-facing)
        ("run",     run),
        ("status",  status),
        ("doctor",  doctor),
        ("inspect", inspect),
        # Data plane
        ("data",    data),
        # Research / modeling
        ("model",   model),
        ("factor",  factor),
        ("evaluate", evaluate),
        ("kg",      kg),
        # System config / control
        ("config",  config),
        ("event",   event),
        ("account", account),
        ("backup",  backup),
        ("start",   start),
        ("web",     web),
        # Legacy/daily/ops/dev
        ("daily",   daily),
        ("ops",     ops),
        ("dev",     dev),
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
            "用 `trade <域> --help` 查看各域详细用法。\n"
            "全局选项 -v/--verbose (DEBUG) 和 -q/--quiet (WARNING) 可放在域前或域后。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG 级日志")
    parser.add_argument("-q", "--quiet", action="store_true", help="只显示 WARNING 及以上")
    parser.add_argument("domain", choices=[n for n, _ in domains], metavar="<域>",
                        help="{" + " | ".join(n for n, _ in domains) + "}")
    parser.add_argument("args", nargs=argparse.REMAINDER, metavar="...", help=argparse.SUPPRESS)

    input_argv = list(argv) if argv is not None else sys.argv[1:]
    # Detect -v/-q anywhere (before or after the domain) before argparse consumes them
    all_argv, v1, q1 = _extract_global_flags(input_argv)
    args = parser.parse_args(all_argv)
    # Combine: explicit argparse flag (works before domain) + detected from remainder
    verbose = args.verbose or v1
    quiet = args.quiet or q1
    _setup_logging(verbose=verbose, quiet=quiet)

    dispatch = {name: mod for name, mod in domains}
    return dispatch[args.domain].main(args.args)


if __name__ == "__main__":
    raise SystemExit(main())

