#!/usr/bin/env python3
"""Generate a read-only PIT evidence coverage report for BTC observatory (WP0).

This scans immutable run manifests, the current pointer, and publish/rollback
audits under a data root and reports, per asset/provider/contract/data-family:

- earliest_proven_knowledge_time (first immutable receipt time)
- proven / partial / unproven intervals
- first_seen / publication / revision ledger coverage
- gap reason_codes and supportable knowledge modes

It performs NO network, NO writes, and NO DB access. It never reads filesystem
mtime; only in-manifest recorded times are used.

Usage:
    python generate_pit_coverage.py [--data-root PATH] [--json]
"""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Any


def _load_manifests(runs_dir: Path) -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    for path in sorted(glob.glob(str(runs_dir / "*" / "manifest.json"))):
        try:
            manifests.append(json.loads(Path(path).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return manifests


def build_coverage(data_root: Path) -> dict[str, Any]:
    crypto_root = data_root / "market" / "crypto"
    runs_dir = crypto_root / "runs" / "btc"
    manifests = _load_manifests(runs_dir)
    created = sorted(m.get("created_at") for m in manifests if m.get("created_at"))
    earliest_proven = created[0] if created else None

    has_stage_times = any(
        any(k in m for k in ("staged_at", "assurance_completed_at", "capture_completed_at"))
        for m in manifests
    )
    publish_audits = glob.glob(str(crypto_root / "audit" / "publish" / "*.json"))
    rollback_audits = glob.glob(str(crypto_root / "audit" / "rollback" / "*.json"))

    supportable_modes = ["market_available"]
    # installation_observed is only supportable from the earliest proven receipt.
    if earliest_proven:
        supportable_modes.append("installation_observed_from_earliest_proven")

    gap_reason_codes: list[str] = []
    if not has_stage_times:
        gap_reason_codes.append("LEGACY_TIME_UNPROVEN")
    if earliest_proven:
        gap_reason_codes.append("PIT_NOT_PROVEN_BEFORE_EARLIEST_RECEIPT")

    return {
        "asset_id": "crypto.BTC",
        "providers": {
            "primary": {"provider": "okx", "instrument": "BTC-USDT", "interval": "1Dutc"},
            "shadow": {"provider": "binance", "instrument": "BTCUSDT", "interval": "1d"},
        },
        "contract_version": manifests[-1].get("contract_version") if manifests else None,
        "data_families": ["ohlcv", "reconciliation", "revisions", "findings"],
        "run_count": len(manifests),
        "earliest_proven_knowledge_time": earliest_proven,
        "has_precise_stage_times": has_stage_times,
        "publication_ledger_events": len(publish_audits),
        "rollback_ledger_events": len(rollback_audits),
        "revision_ledger_present": any((runs_dir / m.get("run_id", "") / "revisions.parquet").exists() for m in manifests),
        "intervals": {
            "proven": (
                f">= {earliest_proven}" if earliest_proven else "none"
            ),
            "partial": "none (no precise stage receipts recorded)",
            "unproven": (
                f"< {earliest_proven} for installation_observed" if earliest_proven else "all"
            ),
        },
        "supportable_knowledge_modes": supportable_modes,
        "gap_reason_codes": gap_reason_codes,
        "notes": (
            "installation_observed queries before earliest_proven_knowledge_time "
            "return PIT_NOT_PROVEN; filesystem mtime is never used."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", default="data", help="data root directory")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()
    coverage = build_coverage(Path(args.data_root))
    if args.json:
        print(json.dumps(coverage, indent=2))
    else:
        print(f"asset_id: {coverage['asset_id']}")
        print(f"run_count: {coverage['run_count']}")
        print(f"earliest_proven_knowledge_time: {coverage['earliest_proven_knowledge_time']}")
        print(f"has_precise_stage_times: {coverage['has_precise_stage_times']}")
        print(f"supportable_knowledge_modes: {coverage['supportable_knowledge_modes']}")
        print(f"gap_reason_codes: {coverage['gap_reason_codes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
