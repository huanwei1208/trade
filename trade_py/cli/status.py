"""trade status — unified health/freshness dashboard (post CLI convergence).

Absorbs:
  - doctor.py (data quality gate, jobs, freshness, events, DB stats, recovery)
  - inspect health/hive (data health view)
  - ops status / ops freshness
  - data status (→ status data)
  - data jobs status (→ status jobs)

Default (no subcommand) = comprehensive health check (was ``trade doctor``)
with exit codes 0/1/2 for ok/warn/fail (cron-friendly).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from trade_py.cli import global_flag_parent
from trade_py.infra.settings import default_data_root

_DATA_ROOT = str(default_data_root())


def _make_overview_parser() -> argparse.ArgumentParser:
    """Parser for the overview/doctor view."""
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--data-root", default=_DATA_ROOT)
    p.add_argument("--json", action="store_true", dest="as_json")
    p.add_argument("--strict", action="store_true", help="warn/fail 时非零退出码")
    return p


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade status",
        description="统一健康/新鲜度仪表盘（综合体检 / data / jobs / freshness）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[global_flag_parent()],
        epilog=(
            "trade status                     # 综合体检（原 trade doctor）\n"
            "trade status overview            # 同上，显式子命令\n"
            "trade status data                # 数据层完整性/时效性/覆盖率\n"
            "trade status jobs                # 任务执行状态 / sync_state watermark\n"
            "trade status freshness           # 多资产新鲜度\n"
            "trade status --json              # JSON 输出\n"
            "trade status --strict            # warn/fail 时非零退出码\n"
        ),
    )
    ov_parent = _make_overview_parser()

    sub = parser.add_subparsers(dest="subcmd")

    # overview (explicit)
    p_ov = sub.add_parser("overview", description="综合健康体检（默认）",
                          formatter_class=argparse.RawDescriptionHelpFormatter,
                          parents=[global_flag_parent(), ov_parent])

    # data
    p_data = sub.add_parser("data", description="数据层完整性/时效性/覆盖率（原 data status）",
                            formatter_class=argparse.RawDescriptionHelpFormatter,
                            parents=[global_flag_parent()])
    p_data.add_argument("--data-root", default=_DATA_ROOT)
    p_data.add_argument("--json", action="store_true", dest="as_json")
    p_data.add_argument("--limit", type=int, default=10, help="显示缺失/滞后样例条数")
    p_data.add_argument("--strict", action="store_true")

    # jobs
    p_jobs = sub.add_parser("jobs", description="任务执行状态与 watermark（原 data jobs status）",
                            formatter_class=argparse.RawDescriptionHelpFormatter,
                            parents=[global_flag_parent()])
    p_jobs.add_argument("--data-root", default=_DATA_ROOT)
    p_jobs.add_argument("--limit", type=int, default=12)

    # freshness
    p_fr = sub.add_parser("freshness", description="多资产新鲜度（原 ops freshness）",
                          formatter_class=argparse.RawDescriptionHelpFormatter,
                          parents=[global_flag_parent()])
    p_fr.add_argument("--data-root", default=_DATA_ROOT)
    p_fr.add_argument("--date", default=None)

    # Also add overview flags at top level so `trade status --json` works
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--strict", action="store_true", help="warn/fail 时非零退出码")

    return parser


# ── overview (doctor) ──────────────────────────────────────────────────────────

def _cmd_overview(ns: argparse.Namespace) -> int:
    """Comprehensive health check — calls doctor's run_doctor() directly."""
    from trade_py.cli.doctor import run_doctor
    doc_argv = ["--data-root", ns.data_root]
    if ns.as_json:
        doc_argv.append("--json")
    if ns.strict:
        doc_argv.append("--strict")
    return run_doctor(doc_argv)


# ── data plane status ──────────────────────────────────────────────────────────

def _data_status_exit_code(status: dict, *, strict: bool) -> int:
    gate = status.get("quality_gate") or {}
    if not strict:
        return 0
    if gate.get("status") == "fail":
        return 2
    if gate.get("status") == "warn":
        return 1
    return 0


def _cmd_data(ns: argparse.Namespace) -> int:
    import json as _json
    from trade_py.utils.data_inspector import build_status_lines, get_data_status

    status = get_data_status(ns.data_root, sample_limit=ns.limit, include_value_quality=True)
    if ns.as_json:
        print(_json.dumps(status, ensure_ascii=False, indent=2))
        return _data_status_exit_code(status, strict=ns.strict)

    for line in build_status_lines(status):
        print(line)

    coverage = status.get("kline_coverage", {})
    if coverage.get("missing_sample"):
        print("### 缺失 K线样例")
        for symbol in coverage["missing_sample"]:
            print(f"- {symbol}")
        print()
    if coverage.get("suspicious_sample"):
        print("### 可疑 suffix 样例")
        for symbol in coverage["suspicious_sample"]:
            print(f"- {symbol}")
        print()

    freshness = status.get("kline_freshness", {})
    stale_sample = [
        row for row in freshness.get("stale_sample", [])
        if int(str(row.get("stale_days", "0"))) >= 1
    ]
    if stale_sample:
        print("### 滞后样例")
        print(f"{'symbol':<12} {'watermark':<12} {'last_download':<12} {'stale_days':>10}")
        print("-" * 56)
        for row in stale_sample:
            print(
                f"{row['symbol']:<12} {row['watermark']:<12} {row['last_download']:<12} "
                f"{row['stale_days']:>10}"
            )
        print()
    return _data_status_exit_code(status, strict=ns.strict)


# ── jobs status ────────────────────────────────────────────────────────────────

def _cmd_jobs(ns: argparse.Namespace) -> int:
    from trade_py.db.trade_db import TradeDB

    db = TradeDB(ns.data_root)
    stale_count = db.job_runs_mark_stale_by_policy()
    if stale_count:
        print(f"已收敛 {stale_count} 条 stale jobs", file=sys.stderr)

    recent = [
        row for row in db.job_runs_recent(limit=ns.limit * 3)
        if (row.get("result_summary") or "") != "aborted local scheduler validation"
    ][:ns.limit]
    print(f"最近 jobs ({len(recent)}):")
    print(f"{'id':<6} {'job':<22} {'stage':<8} {'status':<8} {'started_at':<20} {'ms':>7}  摘要")
    print("-" * 100)
    for r in recent:
        ms = str(r["elapsed_ms"]) if r["elapsed_ms"] is not None else "-"
        summary = (r.get("result_summary") or "")[:40]
        stage = (r.get("stage") or "")[:7]
        print(f"{r['id']:<6} {r['job_name']:<22} {stage:<8} {r['status']:<8} "
              f"{r['started_at']:<20} {ms:>7}  {summary}")

    try:
        rows = db._conn.execute(
            "SELECT job_name, last_success_at, rows_processed FROM sync_state "
            "ORDER BY job_name LIMIT ?",
            (ns.limit * 3,),
        ).fetchall()
        if rows:
            print(f"\nsync_state watermarks:")
            print(f"{'job_name':<30} {'last_success_at':<22} rows")
            print("-" * 70)
            for r in rows[:ns.limit]:
                cnt = r[2] if r[2] is not None else "-"
                print(f"{r[0]:<30} {str(r[1] or '-'):<22} {cnt}")
    except Exception:
        pass
    db.close()
    return 0


# ── freshness ──────────────────────────────────────────────────────────────────

def _cmd_freshness(ns: argparse.Namespace) -> int:
    from trade_py.db.trade_db import TradeDB
    today = ns.date or date.today().isoformat()
    db = TradeDB(ns.data_root)
    rows = db.freshness_status_list(today)
    db.close()
    if not rows:
        print(f"No FreshnessStatus for {today}")
        return 0
    print(f"Freshness for {today}:")
    for r in rows:
        lag = r.get("lag_days")
        lag_str = f"{lag}d" if lag is not None else "-"
        print(f"  {r['dataset']:<22} last={r.get('freshness_date','-'):>12}"
              f" lag={lag_str:>4} status={r.get('status','-')}")
    return 0


# ── main ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    raw = list(argv or [])

    # If --help/-h is in raw (and no subcommand is present), let the top-level parser handle it.
    if any(tok in ("-h", "--help") for tok in raw):
        known_subs = {"overview", "data", "jobs", "freshness"}
        has_subcmd = any(tok in known_subs for tok in raw if not tok.startswith("-"))
        if not has_subcmd:
            parser = make_parser()
            parser.parse_args(raw)  # will print help and exit
            return 0
        # If a subcommand is present, fall through (the subparser will handle --help)

    parser = make_parser()

    # If no args at all, run overview with defaults.
    if not raw:
        ns = argparse.Namespace(data_root=_DATA_ROOT, as_json=False, strict=False, subcmd="overview")
        return _cmd_overview(ns)

    # Peek to see if first non-flag token is a known subcommand
    known_subs = {"overview", "data", "jobs", "freshness"}
    subcmd = None
    for tok in raw:
        if tok.startswith("-"):
            continue
        if tok in known_subs:
            subcmd = tok
        break

    if subcmd is None:
        # No subcmd given → overview; parse the overview flags from raw.
        ov_parser = argparse.ArgumentParser(parents=[global_flag_parent(), _make_overview_parser()],
                                            add_help=False)
        ns, _ = ov_parser.parse_known_args(raw)
        ns.subcmd = "overview"
        if ns.data_root is None:
            ns.data_root = _DATA_ROOT
    else:
        ns = parser.parse_args(raw)

    if ns.subcmd in (None, "overview"):
        return _cmd_overview(ns)
    if ns.subcmd == "data":
        return _cmd_data(ns)
    if ns.subcmd == "jobs":
        return _cmd_jobs(ns)
    if ns.subcmd == "freshness":
        return _cmd_freshness(ns)
    return 0
