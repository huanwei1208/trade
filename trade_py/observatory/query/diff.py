"""Run diff (WP3/WP5): compare two runs beyond watermark.

Reports added/removed dates, changed OHLCV, provider/schema/config/code changes,
watermarks/coverage, artifact hashes, and gate/finding changes. Read-only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from trade_py.observatory.catalog.projection import build_catalog
from trade_py.observatory.domain.vocab import ObservatoryError, ReasonCode
from trade_py.observatory.service import artifacts


def _canonical_dates_close(data_root: str | Path, run_id: str) -> dict[str, str]:
    try:
        frame = artifacts.read_artifact_frame(data_root, run_id, "canonical")
    except ObservatoryError:
        return {}
    import pandas as pd

    out: dict[str, str] = {}
    if "date" not in frame.columns or "close" not in frame.columns:
        return out
    for _, row in frame.iterrows():
        d = str(pd.Timestamp(row["date"]).date())
        out[d] = str(row["close"])
    return out


def diff_runs(data_root: str | Path, base: str, compare: str) -> dict[str, Any]:
    # Strict boundary validation for both run ids.
    artifacts.run_dir(data_root, base)
    artifacts.run_dir(data_root, compare)
    catalog = build_catalog(data_root)
    base_run = catalog.runs.get(base)
    compare_run = catalog.runs.get(compare)
    if base_run is None or compare_run is None:
        raise ObservatoryError(ReasonCode.SNAPSHOT_NOT_FOUND, "run not found for diff")

    base_close = _canonical_dates_close(data_root, base)
    compare_close = _canonical_dates_close(data_root, compare)
    base_dates = set(base_close)
    compare_dates = set(compare_close)

    added = sorted(compare_dates - base_dates)
    removed = sorted(base_dates - compare_dates)
    changed = sorted(
        d for d in (base_dates & compare_dates) if base_close[d] != compare_close[d]
    )

    def gate_map(run):
        return {g.get("gate"): (g.get("status"), g.get("reason_code")) for g in run.gates}

    base_gates = gate_map(base_run)
    compare_gates = gate_map(compare_run)
    gate_changes = {
        g: {"base": base_gates.get(g), "compare": compare_gates.get(g)}
        for g in set(base_gates) | set(compare_gates)
        if base_gates.get(g) != compare_gates.get(g)
    }

    return {
        "base": {
            "run_id": base,
            "watermark": base_run.market_watermark,
            "canonical_rows": base_run.canonical_rows,
            "canonical_hash": base_run.canonical_hash,
            "code_revision": base_run.code_revision,
            "config_hash": base_run.config_hash,
            "schema_hash": base_run.schema_hash,
        },
        "compare": {
            "run_id": compare,
            "watermark": compare_run.market_watermark,
            "canonical_rows": compare_run.canonical_rows,
            "canonical_hash": compare_run.canonical_hash,
            "code_revision": compare_run.code_revision,
            "config_hash": compare_run.config_hash,
            "schema_hash": compare_run.schema_hash,
        },
        "added_dates": added,
        "removed_dates": removed,
        "changed_dates": [
            {"date": d, "base_close": base_close[d], "compare_close": compare_close[d]}
            for d in changed
        ],
        "gate_changes": gate_changes,
        "code_changed": base_run.code_revision != compare_run.code_revision,
        "config_changed": base_run.config_hash != compare_run.config_hash,
        "schema_changed": base_run.schema_hash != compare_run.schema_hash,
    }
