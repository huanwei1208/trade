from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def normalize_position_rows(rows: list[dict[str, Any]] | pd.DataFrame | None) -> pd.DataFrame:
    """Normalize local position/watchlist context for research risk awareness."""
    if rows is None:
        return pd.DataFrame(
            columns=[
                "position_id", "asset_id", "asset_name", "sector", "thesis",
                "risk_notes", "watch_triggers", "status",
            ]
        )
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if frame.empty:
        return normalize_position_rows(None)
    out: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        asset_id = str(row.get("asset_id") or row.get("symbol") or row.get("asset") or "").strip()
        sector = str(row.get("sector") or "").strip().lower()
        if not asset_id or not sector:
            continue
        thesis = str(row.get("thesis") or row.get("buy_reason") or "").strip()
        risk_notes = str(row.get("risk_notes") or row.get("risk") or "").strip()
        watch_triggers = str(row.get("watch_triggers") or row.get("triggers") or "").strip()
        out.append(
            {
                "position_id": str(row.get("position_id") or _stable_id(asset_id, sector, thesis)),
                "asset_id": asset_id,
                "asset_name": str(row.get("asset_name") or row.get("name") or asset_id).strip(),
                "sector": sector,
                "thesis": thesis,
                "risk_notes": risk_notes,
                "watch_triggers": watch_triggers,
                "status": str(row.get("status") or "watch").strip().lower(),
            }
        )
    return pd.DataFrame(out)


def build_ads_position_risk_signal(
    dim_position: pd.DataFrame,
    ads_data_signal_report: pd.DataFrame,
) -> pd.DataFrame:
    """Link sector-level research signals to local positions for manual review."""
    columns = [
        "position_id", "asset_id", "sector", "risk_signal_type", "risk_level",
        "validation_status", "evidence", "reason", "manual_action",
    ]
    if dim_position.empty or ads_data_signal_report.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    for _, position in dim_position.iterrows():
        sector = str(position.get("sector") or "")
        sector_signals = ads_data_signal_report[ads_data_signal_report["sector"] == sector]
        for _, signal in sector_signals.iterrows():
            strength = str(signal.get("signal_strength") or "low")
            risk_level = "review" if strength in {"medium", "high"} else "watch"
            rows.append(
                {
                    "position_id": position.get("position_id"),
                    "asset_id": position.get("asset_id"),
                    "sector": sector,
                    "risk_signal_type": str(signal.get("signal_type") or "research_signal"),
                    "risk_level": risk_level,
                    "validation_status": str(signal.get("validation_status") or "candidate"),
                    "evidence": str(signal.get("evidence_refs") or signal.get("target_id") or ""),
                    "reason": (
                        f"{position.get('asset_id')} is linked to {sector}; "
                        f"{signal.get('value_reason') or 'sector-level research signal changed.'} "
                        "Review manually before any action."
                    ),
                    "manual_action": "needs_review" if risk_level == "review" else "watch_only",
                }
            )
    return pd.DataFrame(rows, columns=columns)
