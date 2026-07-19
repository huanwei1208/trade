"""Frozen fixture factory for observatory tests (WP0 fixture inventory).

Builds synthetic BTC run directories under a tmp_path that match the REAL on-disk
layout (manifest.json + canonical/primary/shadow/reconciliation/revisions.parquet +
btc_current.json + audit/publish). Frozen relations (see consensus_review_p0.md):

- formal_run: published release, watermark F, data_readiness=ready
- candidate_run: staged, degraded, watermark C > F (observed_watermark > formal)
- observed_only_run: primary-success/shadow-partial, watermark O >= C
- invalid_run: data_readiness=invalid with a rendering blocker
- empty_run: 0 canonical rows
- legacy_run: manifest without stage times

Never touches real data; everything lives under the given tmp root.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

CONTRACT_VERSION = "btc-data-v1"
SCHEMA_VERSION = "crypto-provider-v2"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_frame(start: date, days: int, *, base_close: float = 60000.0, run_id: str = "r") -> pd.DataFrame:
    rows = []
    fetched = datetime(2026, 7, 19, 8, 46, 30, tzinfo=timezone.utc)
    for i in range(days):
        d = start + timedelta(days=i)
        open_ts = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        close_ts = open_ts + timedelta(days=1)
        close = base_close + i * 10.0
        rows.append(
            {
                "date": pd.Timestamp(d),
                "open": close - 5.0,
                "high": close + 20.0,
                "low": close - 25.0,
                "close": close,
                "volume": 1000.0 + i,
                "provider": "okx",
                "venue": "okx",
                "instrument": "BTC-USDT",
                "base_asset": "BTC",
                "quote_asset": "USDT",
                "interval": "1Dutc",
                "bar_open_at": open_ts,
                "bar_close_at": close_ts,
                "is_final": True,
                "fetched_at": fetched,
                "available_at": close_ts,
                "payload_hash": _sha256_bytes(f"{run_id}:{d}".encode()),
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
            }
        )
    columns = [
        "date", "open", "high", "low", "close", "volume", "provider", "venue",
        "instrument", "base_asset", "quote_asset", "interval", "bar_open_at",
        "bar_close_at", "is_final", "fetched_at", "available_at", "payload_hash",
        "schema_version", "run_id",
    ]
    return pd.DataFrame(rows, columns=columns)


def _write_run(
    crypto_root: Path,
    run_id: str,
    *,
    created_at: str,
    watermark: str | None,
    readiness: str | None,
    canonical: pd.DataFrame,
    gates: list[dict[str, Any]] | None = None,
    providers: dict[str, Any] | None = None,
    code_revision: str = "code-v1",
    include_stage_times: bool = False,
    d0_fail: bool = False,
) -> dict[str, Any]:
    run_dir = crypto_root / "runs" / "btc" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_hashes: dict[str, str] = {}
    for name, frame in (
        ("canonical", canonical),
        ("primary", canonical),
        ("shadow", canonical.head(min(len(canonical), 3))),
        ("reconciliation", canonical[["date", "close"]].rename(columns={"close": "primary_close"})),
        ("revisions", canonical[["date", "close"]].rename(columns={"close": "new_close"})),
    ):
        path = run_dir / f"{name}.parquet"
        frame.to_parquet(path)
        artifact_hashes[name] = _sha256_bytes(path.read_bytes())

    if gates is None:
        gates = [
            {"gate": "D0", "status": "fail" if d0_fail else "pass", "reason_code": "CONTRACT_VALID", "metrics": {}, "detail": ""},
            {"gate": "D1", "status": "pass", "reason_code": "DUAL_SOURCE_READY", "metrics": {}, "detail": ""},
            {"gate": "D2", "status": "pass", "reason_code": "STRUCTURE_VALID", "metrics": {}, "detail": ""},
            {"gate": "D3", "status": "pass", "reason_code": "SOURCES_RECONCILED", "metrics": {}, "detail": ""},
            {"gate": "D4", "status": "pass", "reason_code": "REVISION_ACCEPTABLE", "metrics": {}, "detail": ""},
        ]
    canonical_hash = _sha256_bytes(canonical.to_json().encode())
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "contract_version": CONTRACT_VERSION,
        "created_at": created_at,
        "watermark": watermark,
        "data_readiness": readiness,
        "canonical_rows": int(len(canonical)),
        "canonical_hash": canonical_hash,
        "primary_hash": artifact_hashes["primary"],
        "shadow_hash": artifact_hashes["shadow"],
        "config_hash": "cfg-v1",
        "schema_hash": "schema-v1",
        "code_revision": code_revision,
        "schema_version": SCHEMA_VERSION,
        "artifact_hashes": artifact_hashes,
        "gates": gates,
        "input_watermarks": {"okx": watermark, "binance": watermark},
        "output_watermark": watermark,
        "acquisition_evidence": {
            "as_of": created_at,
            "providers": providers if providers is not None else {"okx": {"status": "succeeded", "rows": len(canonical)}, "binance": {"status": "succeeded", "rows": 3}},
            "daily_attempts": [],
        },
        "health": {
            "blocking_gate": next((g["gate"] for g in gates if g["status"] == "fail"), None),
            "blocking_reason_code": next((g["reason_code"] for g in gates if g["status"] == "fail"), None),
        },
        "config": {"maximum_staleness_days": 1, "minimum_successful_acquisition_days": 29},
    }
    if include_stage_times:
        manifest["staged_at"] = created_at
        manifest["assurance_completed_at"] = created_at
        manifest["capture_completed_at"] = created_at
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def _publish(crypto_root: Path, from_run: str | None, to_run: str, occurred_at: str, canonical_sha: str) -> None:
    audit_dir = crypto_root / "audit" / "publish"
    audit_dir.mkdir(parents=True, exist_ok=True)
    event_id = hashlib.sha256(f"{to_run}:{occurred_at}".encode()).hexdigest()[:24]
    fname = occurred_at.replace(":", "").replace("-", "").replace(".", "") + f"-{event_id}.json"
    (audit_dir / fname).write_text(
        json.dumps(
            {
                "event_id": event_id,
                "event_type": "btc_canonical_publish",
                "from_run_id": from_run,
                "to_run_id": to_run,
                "occurred_at": occurred_at,
                "canonical_sha256": canonical_sha,
            }
        ),
        encoding="utf-8",
    )


def build_observatory_fixture(data_root: Path) -> dict[str, Any]:
    """Build the full frozen fixture set and return key identifiers."""

    crypto_root = data_root / "market" / "crypto"
    crypto_root.mkdir(parents=True, exist_ok=True)

    formal_start = date(2024, 7, 19)
    # Formal: 730 days, watermark 2026-07-11, ready, published.
    formal_days = (date(2026, 7, 11) - formal_start).days + 1
    formal_canonical = _canonical_frame(formal_start, formal_days, run_id="formal_run_0000000000000001")
    formal_m = _write_run(
        crypto_root, "formal_run_0000000000000001",
        created_at="2026-07-12T16:48:44.000000+00:00",
        watermark="2026-07-11", readiness="ready", canonical=formal_canonical,
    )

    # Candidate: watermark 2026-07-18, degraded (D1 fail), staged (unpublished).
    cand_days = (date(2026, 7, 18) - formal_start).days + 1
    cand_canonical = _canonical_frame(formal_start, cand_days, run_id="candidate_run_00000000000001")
    cand_gates = [
        {"gate": "D0", "status": "pass", "reason_code": "CONTRACT_VALID", "metrics": {}, "detail": ""},
        {"gate": "D1", "status": "fail", "reason_code": "ACQUISITION_STABILITY_INSUFFICIENT", "metrics": {"successful_days": 3, "required_days": 29}, "detail": "3/29"},
        {"gate": "D2", "status": "pass", "reason_code": "STRUCTURE_VALID", "metrics": {}, "detail": ""},
        {"gate": "D3", "status": "pass", "reason_code": "SOURCES_RECONCILED", "metrics": {}, "detail": ""},
        {"gate": "D4", "status": "pass", "reason_code": "REVISION_ACCEPTABLE", "metrics": {}, "detail": ""},
    ]
    cand_m = _write_run(
        crypto_root, "candidate_run_00000000000001",
        created_at="2026-07-19T08:46:33.000000+00:00",
        watermark="2026-07-18", readiness="degraded", canonical=cand_canonical, gates=cand_gates,
    )

    # Observed-only: watermark 2026-07-19, primary succeeded / shadow failed (partial).
    obs_days = (date(2026, 7, 19) - formal_start).days + 1
    obs_canonical = _canonical_frame(formal_start, obs_days, run_id="observed_run_000000000000001")
    obs_m = _write_run(
        crypto_root, "observed_run_000000000000001",
        created_at="2026-07-19T09:00:00.000000+00:00",
        watermark="2026-07-19", readiness="degraded", canonical=obs_canonical,
        providers={"okx": {"status": "succeeded", "rows": obs_days}, "binance": {"status": "failed", "rows": 0}},
    )

    # Invalid run with a D0 rendering blocker.
    inv_canonical = _canonical_frame(formal_start, 10, run_id="invalid_run_0000000000000001")
    inv_m = _write_run(
        crypto_root, "invalid_run_0000000000000001",
        created_at="2026-07-19T09:05:00.000000+00:00",
        watermark="2026-07-18", readiness="invalid", canonical=inv_canonical, d0_fail=True,
    )

    # Empty run (0 rows): acquisition wholly failed, assurance did not run.
    empty_canonical = _canonical_frame(formal_start, 0, run_id="empty_run_00000000000000001")
    empty_m = _write_run(
        crypto_root, "empty_run_00000000000000001",
        created_at="2026-07-19T09:10:00.000000+00:00",
        watermark=None, readiness=None, canonical=empty_canonical, gates=[],
        providers={"okx": {"status": "failed", "rows": 0}, "binance": {"status": "failed", "rows": 0}},
    )

    # Publish the formal run.
    _publish(crypto_root, None, "formal_run_0000000000000001", "2026-07-12T16:48:44.000000+00:00", formal_m["canonical_hash"])

    # Current pointer -> formal run.
    current = {
        "run_id": "formal_run_0000000000000001",
        "canonical_sha256": formal_m["artifact_hashes"]["canonical"],
        "manifest_path": str(crypto_root / "runs" / "btc" / "formal_run_0000000000000001" / "manifest.json"),
        "run_dir": str(crypto_root / "runs" / "btc" / "formal_run_0000000000000001"),
        "published_at": "2026-07-12T16:48:44.000000+00:00",
    }
    (crypto_root / "btc_current.json").write_text(json.dumps(current, indent=1), encoding="utf-8")
    # Materialized compatibility parquet.
    formal_canonical.to_parquet(crypto_root / "btc.parquet")

    return {
        "data_root": data_root,
        "crypto_root": crypto_root,
        "formal_run_id": "formal_run_0000000000000001",
        "candidate_run_id": "candidate_run_00000000000001",
        "observed_run_id": "observed_run_000000000000001",
        "invalid_run_id": "invalid_run_0000000000000001",
        "empty_run_id": "empty_run_00000000000000001",
        "formal_watermark": "2026-07-11",
        "candidate_watermark": "2026-07-18",
        "observed_watermark": "2026-07-19",
    }


def build_legacy_run(data_root: Path, run_id: str = "legacy_run_0000000000000001") -> dict[str, Any]:
    """A run whose manifest lacks precise stage times (legacy adapter path)."""

    crypto_root = data_root / "market" / "crypto"
    canonical = _canonical_frame(date(2024, 1, 1), 30, run_id=run_id)
    manifest = _write_run(
        crypto_root, run_id,
        created_at="2026-07-01T00:00:00.000000+00:00",
        watermark="2024-01-30", readiness="ready", canonical=canonical, include_stage_times=False,
    )
    return manifest


def build_pit_run(
    data_root: Path,
    run_id: str,
    *,
    created_at: str,
    days: int,
    base_close: float = 60000.0,
    fetched_at: datetime | None = None,
) -> dict[str, Any]:
    """A ready run whose canonical rows carry an explicit fetched_at/available_at.

    Used for PIT knowledge-cut visibility and revision isolation tests. Later runs
    can use a higher base_close to simulate a revision.
    """

    crypto_root = data_root / "market" / "crypto"
    fetched = fetched_at or datetime(2026, 7, 19, tzinfo=timezone.utc)
    canonical = _canonical_frame(date(2024, 1, 1), days, base_close=base_close, run_id=run_id)
    canonical["fetched_at"] = fetched
    wm = (date(2024, 1, 1) + timedelta(days=days - 1)).isoformat() if days else None
    return _write_run(
        crypto_root, run_id,
        created_at=created_at, watermark=wm, readiness="ready", canonical=canonical,
        include_stage_times=False,
    )
