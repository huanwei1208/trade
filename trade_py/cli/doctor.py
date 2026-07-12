"""Unified `trade doctor` command — aggregates all health checks into one view."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from trade_py.cli import global_flag_parent


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trade doctor", description="Unified system health check (data + jobs + readiness)",
                                parents=[global_flag_parent()])
    p.add_argument("--json", action="store_true", help="Output JSON report")
    p.add_argument("--data-root", default="data", help="Data root directory")
    p.add_argument("--strict", action="store_true", help="Exit non-zero on any warn/fail")
    return p


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    data_root = Path(args.data_root)

    report: dict = {
        "as_of": date.today().isoformat(),
        "checks": {},
        "status": "pass",
        "issues": [],
        "recovery_actions": [],
    }

    # 1. Data quality gate
    status = None
    try:
        from trade_py.utils.data_inspector import get_data_status
        status = get_data_status(str(data_root), sample_limit=5)
        gate = status.get("quality_gate") or {}
        report["checks"]["data_quality"] = {
            "status": gate.get("status", "unknown"),
            "reason_codes": gate.get("reason_codes", []),
            "recovery_plan": [r.get("command") for r in gate.get("recovery_plan", [])],
        }
        if gate.get("status") == "fail":
            report["status"] = "fail"
            report["issues"].append(f"Data quality FAIL: {', '.join(gate.get('reason_codes') or [])}")
        elif gate.get("status") == "warn":
            if report["status"] != "fail":
                report["status"] = "warn"
            report["issues"].append(f"Data quality WARN: {', '.join(gate.get('reason_codes') or [])}")
        for r in gate.get("recovery_plan") or []:
            cmd = r.get("command") or []
            if cmd:
                report["recovery_actions"].append(" ".join(str(c) for c in cmd))
    except Exception as exc:
        report["checks"]["data_quality"] = {"status": "error", "error": str(exc)}
        report["status"] = "fail"
        report["issues"].append(f"Data quality check error: {exc}")

    # 2. Job health (recent failures)
    try:
        from trade_py.db.trade_db import TradeDB
        db = TradeDB(str(data_root))
        try:
            recent = db._conn.execute(
                """SELECT job_name, status, COUNT(*) as cnt, MAX(started_at) as last_run
                   FROM job_runs
                   WHERE started_at >= datetime('now', '-7 days')
                   GROUP BY job_name, status
                   ORDER BY job_name, status"""
            ).fetchall()
            job_status: dict[str, dict] = {}
            failed_jobs = []
            for job_name, status_val, cnt, last_run in recent:
                job_status.setdefault(job_name, {})[status_val] = cnt
                if status_val in ("failed", "error") and cnt > 0:
                    failed_jobs.append(job_name)
            report["checks"]["jobs"] = {
                "status": "warn" if failed_jobs else "pass",
                "failed_jobs": list(set(failed_jobs)),
                "job_status": job_status,
            }
            if failed_jobs:
                if report["status"] != "fail":
                    report["status"] = "warn"
                report["issues"].append(f"Failed jobs (last 7d): {', '.join(sorted(set(failed_jobs)))}")
        finally:
            db.close()
    except Exception as exc:
        report["checks"]["jobs"] = {"status": "error", "error": str(exc)}

    # 3. Crypto / multi-asset data health
    try:
        from trade_py.utils.data_inspector import multi_asset_stats, news_stats
        cross = multi_asset_stats(str(data_root))
        news = news_stats(str(data_root))
        if status is not None:
            cross = status.get("multi_asset") or status.get("cross_asset") or cross
            news = status.get("news") or news

        required_crypto = ["btc", "eth"]
        crypto_missing = [a for a in required_crypto if not (cross.get(a) or {}).get("exists")]
        crypto_stale = [a for a in required_crypto
                        if (cross.get(a) or {}).get("exists") and int((cross.get(a) or {}).get("lag_days") or 999) > 7]
        fng_ok = (cross.get("fear_greed") or {}).get("exists", False)
        news_ok = bool((news.get("bronze") or {}).get("rows", 0) > 0)

        crypto_status = "pass"
        if crypto_missing or crypto_stale:
            crypto_status = "warn"
        report["checks"]["crypto"] = {
            "status": crypto_status,
            "missing_assets": crypto_missing,
            "stale_assets": crypto_stale,
            "fear_greed": "ok" if fng_ok else "missing",
            "news": "ok" if news_ok else "no data yet (fetch with `trade data news fetch`)",
        }
        if crypto_missing:
            if report["status"] != "fail":
                report["status"] = "warn"
            report["issues"].append(f"Crypto data missing: {', '.join(crypto_missing)} (run `trade data sync --crypto`)")
            report["recovery_actions"].append("trade data sync --crypto")
        if crypto_stale:
            if report["status"] != "fail":
                report["status"] = "warn"
            report["issues"].append(f"Crypto data stale: {', '.join(crypto_stale)}")
        if not news_ok:
            report["recovery_actions"].append("trade data news fetch")
    except Exception as exc:
        report["checks"]["crypto"] = {"status": "error", "error": str(exc)}

    # 4. Event pipeline health
    try:
        from trade_py.utils.data_inspector import events_stats
        ev = events_stats(str(data_root))
        ev_count = int(ev.get("event_count") or 0)
        ev_lag = ev.get("lag_days")
        ev_status = "pass"
        if ev_count == 0 or (ev_lag is not None and int(ev_lag) > 7):
            ev_status = "warn"
        report["checks"]["events"] = {
            "status": ev_status,
            "event_count": ev_count,
            "lag_days": ev_lag,
            "max_date": ev.get("max_date"),
        }
        if ev_status == "warn" and report["status"] != "fail":
            report["status"] = "warn"
    except Exception as exc:
        report["checks"]["events"] = {"status": "error", "error": str(exc)}

    # 5. DB integrity (basic row counts)
    try:
        from trade_py.db.trade_db import TradeDB
        db = TradeDB(str(data_root))
        try:
            tables = {}
            for tbl in ("instruments", "market_events", "job_runs", "sync_state", "asset_registry"):
                try:
                    cnt = db._conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                    tables[tbl] = cnt
                except Exception:
                    tables[tbl] = "table missing"
            report["checks"]["db"] = {"status": "pass", "tables": tables}
        finally:
            db.close()
    except Exception as exc:
        report["checks"]["db"] = {"status": "error", "error": str(exc)}

    # Output
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        _print_doctor_report(report)

    if args.strict and report["status"] in ("warn", "fail"):
        return 1
    return 0


def _print_doctor_report(report: dict) -> None:
    status_icon = {"pass": "OK", "warn": "WARN", "fail": "FAIL"}.get(report["status"], "??")
    print(f"=== Trade Doctor  ({report['as_of']})  status: {status_icon} ===\n")

    for check_name, check in report["checks"].items():
        icon = {"pass": "✓", "warn": "!", "fail": "✗", "error": "?"}.get(check.get("status", ""), "·")
        print(f"  [{icon}] {check_name}: {check.get('status', 'unknown')}")

    if report["issues"]:
        print(f"\n--- Issues ({len(report['issues'])}) ---")
        for i, issue in enumerate(report["issues"], 1):
            print(f"  {i}. {issue}")

    if report["recovery_actions"]:
        print(f"\n--- Recovery Actions ---")
        seen = set()
        for cmd in report["recovery_actions"]:
            if cmd not in seen:
                seen.add(cmd)
                print(f"  $ {cmd}")

    if not report["issues"]:
        print("\nAll checks passed. System healthy.")


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
