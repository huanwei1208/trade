from __future__ import annotations

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

# Direct ``python trade_py/cli/main.py`` execution otherwise puts this directory
# first on sys.path, where cli/inspect.py shadows the standard-library module.
if __package__ in {None, ""}:
    _script_dir = sys.path.pop(0)
    sys.path.insert(0, _script_dir.rsplit("/trade_py/cli", 1)[0])

import argparse
import importlib
import logging


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


# Mapping for deprecated/old domain names → (new_domain, deprecation_message_or_None).
# If the message is None, the alias is silent (for short aliases like morning→run morning
# handled in bash wrapper); if a string, print the deprecation note to stderr.
_HIDDEN_ALIASES: dict[str, tuple[str, str | None]] = {
    # Old domains removed from top-level (print deprecation warnings)
    "doctor":   ("status",  "DeprecationWarning: 'trade doctor' is deprecated; use 'trade status' instead."),
    "inspect":  ("__inspect_shim__", None),  # inspect.py handles per-subcommand warnings/forwarding
    "daily":    ("__daily_shim__", None),   # daily.py itself handles the shim/warning
    "ops":      ("__ops_shim__", None),     # ops.py itself handles the shim/warning
    "model":    ("__model_shim__", None),   # model.py prints its own deprecation
    "factor":   ("__factor_shim__", None),  # factor.py prints its own deprecation
    "evaluate": ("__eval_shim__", None),    # evaluate.py prints its own deprecation
    "account":  ("__account_shim__", None), # account.py prints its own deprecation
}

# Old top-level domains retained as shims (their main() prints warnings)
_LEGACY_DOMAINS = {"daily", "ops", "account", "model", "factor", "evaluate"}


def _import_domain(name: str):
    """Import only the CLI domain selected by the user."""
    return importlib.import_module(f"trade_py.cli.{name}")


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    # The 10 canonical (visible) domains
    canonical_domains = [
        # Trigger / run
        ("run",     "run",     "统一触发入口 (DAG / daily 流水线 / agenda / job / belief / recommend / picks)"),
        ("status",  "status",  "统一健康/新鲜度仪表盘 (综合体检 / data / jobs / freshness)"),
        # Data plane
        ("data",    "data",    "数据采集 — K线/资金流/财务/北向/指数/宏观/新闻/仓库/实时/BTC"),
        # Show (read-only views)
        ("show",    "show",    "只读视图 — dag/calendar/agenda/events/runs/backups/内部调试转储"),
        # Research
        ("research", "research", "研究/建模/评估 — model + factor + evaluate 统一入口"),
        ("kg",      "kg",      "Learned KG 候选边学习/审核/上线"),
        # Observatory (BTC snapshot resolution + research; catalog projection is a
        # read-only GET/SDK surface, but research --commit and catalog rebuild write)
        ("observatory", "observatory", "BTC Observatory — 目录/快照/研究运维 (research --commit 写入)"),
        # System config / control
        ("config",  "config",  "统一配置管理 — 数据源/密钥/路径/DAG开关/自选股/备份"),
        ("event",   "event",   "事件控制平面 — 触发/运行/同步/新建/重建/回填"),
        ("backup",  "backup",  "TradeDB 备份与恢复"),
        # Daemon / web / dev
        ("start",   "start",   "启动 EventBus daemon"),
        ("web",     "web",     "启动 Web Console (FastAPI + React)"),
        ("dev",     "dev",     "[内部] 开发调试工具"),
    ]

    # Legacy shim domains (hidden from help, still dispatchable)
    legacy_domains = [
        ("doctor",   "doctor",   "[hidden] alias for status"),
        ("inspect",  "inspect",  "[hidden] alias for show"),
        ("daily",    "daily",    "[hidden] deprecated; use run/status"),
        ("ops",      "ops",      "[hidden] deprecated; use status/run/show"),
        ("account",  "account",  "[hidden] deprecated; use config watch / show picks"),
        ("model",    "model",    "[hidden] deprecated; use research model"),
        ("factor",   "factor",   "[hidden] deprecated; use research factor"),
        ("evaluate", "evaluate", "[hidden] deprecated; use research evaluate"),
    ]

    domains = canonical_domains + legacy_domains

    # Build help text from canonical domains only
    visible_names = [n for n, _, _ in canonical_domains]
    domain_lines = "\n".join(
        f"  {name:<10}  {desc}"
        for name, _mod, desc in canonical_domains
    )

    parser = argparse.ArgumentParser(
        prog="trade",
        description="A-share 交易智能平台",
        epilog=(
            f"可用域 (10):\n{domain_lines}\n\n"
            "用 `trade <域> --help` 查看各域详细用法。\n"
            "全局选项 -v/--verbose (DEBUG) 和 -q/--quiet (WARNING) 可放在域前或域后。\n"
            "旧命令 (doctor/inspect/daily/ops/account/model/factor/evaluate) 仍然可用，但会打印弃用提示。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG 级日志")
    parser.add_argument("-q", "--quiet", action="store_true", help="只显示 WARNING 及以上")
    # choices includes canonical + legacy so old commands parse
    parser.add_argument("domain", choices=[n for n, _m, _d in domains], metavar="<域>",
                        help="{" + " | ".join(visible_names) + "}")
    parser.add_argument("args", nargs=argparse.REMAINDER, metavar="...", help=argparse.SUPPRESS)

    input_argv = list(argv) if argv is not None else sys.argv[1:]
    # Detect -v/-q anywhere (before or after the domain) before argparse consumes them
    all_argv, v1, q1 = _extract_global_flags(input_argv)
    args = parser.parse_args(all_argv)
    # Combine: explicit argparse flag (works before domain) + detected from remainder
    verbose = args.verbose or v1
    quiet = args.quiet or q1
    _setup_logging(verbose=verbose, quiet=quiet)

    # Build dispatch map from all domains
    dispatch = {name: module_name for name, module_name, _desc in domains}

    # Handle hidden alias remapping (for doctor/inspect → status/show)
    if args.domain in _HIDDEN_ALIASES:
        target, msg = _HIDDEN_ALIASES[args.domain]
        if msg:
            print(msg, file=sys.stderr)
        if target.startswith("__") and target.endswith("_shim__"):
            # Dispatch to the legacy module (it prints its own deprecation)
            return _import_domain(dispatch[args.domain]).main(args.args)
        else:
            # Forward to the new canonical module directly (avoid double-warning)
            return _import_domain(dispatch[target]).main(args.args)

    return _import_domain(dispatch[args.domain]).main(args.args)


if __name__ == "__main__":
    raise SystemExit(main())
