from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from trade_py.data.market.crypto.btc import (
    BTC_PROVIDER_SCHEMA_VERSION,
    COINGECKO_BTC_SHADOW_CONTRACT,
    OKX_BTC_CONTRACT,
)


CONTRACT_VERSION = "btc-data-v1"
SCHEMA_VERSION = BTC_PROVIDER_SCHEMA_VERSION

PRIMARY_REQUIRED = {
    "provider",
    "venue",
    "instrument",
    "base_asset",
    "quote_asset",
    "interval",
    "bar_open_at",
    "bar_close_at",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "is_final",
    "fetched_at",
    "available_at",
    "payload_hash",
    "schema_version",
    "run_id",
}

SHADOW_REQUIRED = {
    "provider",
    "instrument",
    "base_asset",
    "quote_asset",
    "interval",
    "bar_open_at",
    "bar_close_at",
    "close",
    "volume",
    "is_final",
    "fetched_at",
    "available_at",
    "payload_hash",
    "schema_version",
    "run_id",
}

PRIMARY_CONTRACT = {
    key: getattr(OKX_BTC_CONTRACT, key)
    for key in ("provider", "venue", "instrument", "base_asset", "quote_asset", "interval")
}

SHADOW_CONTRACT = {
    key: getattr(COINGECKO_BTC_SHADOW_CONTRACT, key)
    for key in ("provider", "venue", "instrument", "base_asset", "quote_asset", "interval")
}


@dataclass(frozen=True)
class BtcAssuranceConfig:
    warn_basis_pct: float = 0.5
    block_basis_pct: float = 1.0
    warn_revision_pct: float = 0.2
    block_revision_pct: float = 1.0
    anomaly_return_pct: float = 20.0
    anomaly_mad_multiple: float = 8.0
    anomaly_mad_window_days: int = 90
    anomaly_mad_min_history: int = 20
    minimum_history_days: int = 365
    recent_window_days: int = 90
    recent_coverage_required: float = 1.0
    full_coverage_required: float = 0.995
    shadow_days: int = 30
    shadow_required_days: int = 29
    acquisition_window_days: int = 30
    minimum_successful_acquisition_days: int = 29
    minimum_revision_overlap_days: int = 2
    maximum_staleness_days: int = 1

    def __post_init__(self) -> None:
        if not 0 <= self.warn_basis_pct <= self.block_basis_pct:
            raise ValueError("basis thresholds must satisfy 0 <= warn <= block")
        if not 0 <= self.warn_revision_pct <= self.block_revision_pct:
            raise ValueError("revision thresholds must satisfy 0 <= warn <= block")
        if self.anomaly_return_pct <= 0 or self.anomaly_mad_multiple <= 0:
            raise ValueError("anomaly thresholds must be positive")
        if not 1 <= self.anomaly_mad_min_history <= self.anomaly_mad_window_days:
            raise ValueError("anomaly MAD history must fit inside its rolling window")
        if self.minimum_history_days < 1 or self.recent_window_days < 1:
            raise ValueError("history windows must be positive")
        if not 0 < self.recent_coverage_required <= 1:
            raise ValueError("recent coverage must be in (0, 1]")
        if not 0 < self.full_coverage_required <= 1:
            raise ValueError("full coverage must be in (0, 1]")
        if not 1 <= self.shadow_required_days <= self.shadow_days:
            raise ValueError("shadow required days must fit inside its rolling window")
        if not 1 <= self.minimum_successful_acquisition_days <= self.acquisition_window_days:
            raise ValueError("successful acquisition days must fit inside its rolling window")
        if self.maximum_staleness_days < 0:
            raise ValueError("maximum staleness cannot be negative")
        if self.minimum_revision_overlap_days < 0:
            raise ValueError("minimum revision overlap cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DataGateResult:
    gate: str
    status: str
    reason_code: str
    detail: str
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BtcAssuranceResult:
    run_id: str
    data_readiness: str
    publishable: bool
    primary: pd.DataFrame
    shadow: pd.DataFrame
    canonical: pd.DataFrame
    reconciliation: pd.DataFrame
    revisions: pd.DataFrame
    gates: list[DataGateResult]
    manifest: dict[str, Any]
    raw_payloads: dict[str, tuple[bytes, ...]] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "data_readiness": self.data_readiness,
            "publishable": self.publishable,
            "row_count": int(len(self.canonical)),
            "watermark": _watermark(self.canonical),
            "gates": [gate.to_dict() for gate in self.gates],
            "health": dict(self.manifest.get("health") or {}),
            "manifest": dict(self.manifest),
        }


def _json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _implementation_revision() -> str:
    digest = hashlib.sha256()
    module_root = Path(__file__).parent
    for name in ("assurance.py", "btc.py", "service.py", "store.py"):
        path = module_root / name
        digest.update(name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _frame_hash(frame: pd.DataFrame) -> str:
    if frame.empty:
        return hashlib.sha256(b"").hexdigest()
    normalized = frame.copy()
    normalized = normalized.reindex(sorted(normalized.columns), axis=1)
    sort_keys = [
        column
        for column in ("provider", "instrument", "interval", "bar_open_at", "date")
        if column in normalized.columns
    ]
    if sort_keys:
        normalized = normalized.sort_values(sort_keys, kind="stable", na_position="first")
    normalized = normalized.reset_index(drop=True)
    payload = normalized.to_json(orient="records", date_format="iso", date_unit="ns")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _utc_dates(frame: pd.DataFrame) -> pd.Series:
    source = frame["bar_open_at"] if "bar_open_at" in frame.columns else frame.get("date")
    if source is None:
        return pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns, UTC]")
    return pd.to_datetime(source, errors="coerce", utc=True).dt.normalize()


def _watermark(frame: pd.DataFrame) -> str | None:
    if frame.empty or "date" not in frame.columns:
        return None
    values = pd.to_datetime(frame["date"], errors="coerce", utc=True)
    if values.notna().sum() == 0:
        return None
    return values.max().date().isoformat()


def _gate_payload(gate: DataGateResult | dict[str, Any]) -> dict[str, Any]:
    return gate.to_dict() if isinstance(gate, DataGateResult) else dict(gate)


def _nonzero_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, raw in value.items():
        try:
            count = int(raw)
        except (TypeError, ValueError):
            continue
        if count:
            result[str(key)] = count
    return result


def _unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _round_float(value: Any, digits: int = 6) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return round(number, digits)


def _dimension_status(
    gate_map: dict[str, dict[str, Any]],
    names: tuple[str, ...],
    *,
    warn: bool = False,
) -> str:
    selected = [gate_map.get(name) for name in names if gate_map.get(name)]
    if not selected:
        return "unknown"
    statuses = {str(gate.get("status") or "unknown") for gate in selected}
    if "fail" in statuses:
        return "fail"
    if statuses == {"pass"}:
        return "warn" if warn else "pass"
    return "warn"


def summarize_btc_health(
    *,
    run_id: str | None,
    data_readiness: str,
    publishable: bool,
    gates: list[DataGateResult | dict[str, Any]],
    canonical: pd.DataFrame | None = None,
    reconciliation: pd.DataFrame | None = None,
    revisions: pd.DataFrame | None = None,
    acquisition_evidence: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    current: dict[str, Any] | None = None,
    operational_freshness: dict[str, Any] | None = None,
    reason_codes: list[str] | None = None,
    integrity_errors: list[str] | None = None,
    replay_errors: list[str] | None = None,
    evidence_refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an operator-facing summary from the audited BTC gate evidence."""

    gate_items = [_gate_payload(gate) for gate in gates]
    gate_map = {str(gate.get("gate") or ""): gate for gate in gate_items}
    d0_metrics = gate_map.get("D0", {}).get("metrics") or {}
    d1_metrics = gate_map.get("D1", {}).get("metrics") or {}
    d2_metrics = gate_map.get("D2", {}).get("metrics") or {}
    d3_metrics = gate_map.get("D3", {}).get("metrics") or {}
    d4_metrics = gate_map.get("D4", {}).get("metrics") or {}
    acquisition = dict(acquisition_evidence or {})
    provider_reports = acquisition.get("providers") or {}

    failed_gates = [
        gate
        for gate in gate_items
        if str(gate.get("status") or "") != "pass"
    ]
    warning_codes: list[str] = []
    if int(d3_metrics.get("warn_rows") or 0) > 0:
        warning_codes.append("SOURCE_DIVERGENCE_WARN")
    if int(d4_metrics.get("warn_rows") or 0) > 0:
        warning_codes.append("REVISION_WARN")
    freshness_reason = (
        "CANONICAL_STALE"
        if operational_freshness and not operational_freshness.get("fresh", False)
        else None
    )
    all_reason_codes = _unique_strings([
        *(gate.get("reason_code") for gate in failed_gates),
        *warning_codes,
        freshness_reason,
        *(reason_codes or []),
    ])

    blocking_gate = None
    blocking_reason = None
    if failed_gates:
        blocking_gate = str(failed_gates[0].get("gate") or "")
        blocking_reason = str(failed_gates[0].get("reason_code") or "")
    elif integrity_errors or replay_errors:
        blocking_gate = "integrity"
        blocking_reason = "CURRENT_INTEGRITY_INVALID"
    elif freshness_reason:
        blocking_gate = "freshness"
        blocking_reason = freshness_reason

    latest_reconciliation: dict[str, Any] = {}
    max_basis_pct = None
    if reconciliation is not None and not reconciliation.empty:
        work = reconciliation.copy()
        if "basis_pct" in work.columns:
            basis = pd.to_numeric(work["basis_pct"], errors="coerce")
            if basis.notna().any():
                max_basis_pct = _round_float(basis.max())
        if "date" in work.columns:
            work = work.sort_values("date")
        latest = work.iloc[-1].to_dict()
        latest_reconciliation = {
            "date": str(latest.get("date") or ""),
            "status": latest.get("status"),
            "reason_code": latest.get("reason_code"),
            "basis_pct": _round_float(latest.get("basis_pct")),
            "primary_close": _round_float(latest.get("primary_close")),
            "shadow_close": _round_float(latest.get("shadow_close")),
        }

    provider_health = {
        str(name): {
            "status": report.get("status"),
            "attempts": report.get("attempts"),
            "retry_count": report.get("retry_count"),
            "latency_ms": report.get("latency_ms"),
            "rows": report.get("rows"),
            "raw_payload_count": len(report.get("raw_payload_hashes") or []),
            "error_kind": report.get("error_kind"),
        }
        for name, report in sorted(provider_reports.items())
    }
    qualified_dates = list(d1_metrics.get("qualified_acquisition_dates") or [])
    predecessor = (
        d4_metrics.get("predecessor")
        or acquisition.get("predecessor")
        or {}
    )
    revision_predecessor = (
        d4_metrics.get("revision_predecessor")
        or acquisition.get("revision_predecessor")
        or {}
    )
    artifact_hashes = (manifest or {}).get("artifact_hashes") or {}

    return {
        "run_id": run_id,
        "data_readiness": data_readiness,
        "publishable": bool(publishable),
        "blocking_gate": blocking_gate,
        "blocking_reason_code": blocking_reason,
        "reason_codes": all_reason_codes,
        "gate_status": {
            str(gate.get("gate") or ""): {
                "status": gate.get("status"),
                "reason_code": gate.get("reason_code"),
            }
            for gate in gate_items
        },
        "accuracy": {
            "status": _dimension_status(
                gate_map,
                ("D0", "D2", "D4"),
                warn=int(d4_metrics.get("warn_rows") or 0) > 0,
            ),
            "missing_primary_columns": list(d0_metrics.get("missing_primary") or []),
            "missing_shadow_columns": list(d0_metrics.get("missing_shadow") or []),
            "primary_contract_violations": _nonzero_counts(
                d0_metrics.get("primary_contract_violations")
            ),
            "shadow_contract_violations": _nonzero_counts(
                d0_metrics.get("shadow_contract_violations")
            ),
            "structural_violations": _nonzero_counts(
                d2_metrics.get("violations")
            ),
            "history_days": d2_metrics.get("history_days"),
            "full_coverage": d2_metrics.get("full_coverage"),
            "recent_coverage": d2_metrics.get("recent_coverage"),
            "revision_rows": d4_metrics.get("revision_rows"),
            "revision_warn_rows": d4_metrics.get("warn_rows"),
            "revision_block_rows": d4_metrics.get("block_rows"),
        },
        "source_stability": {
            "status": _dimension_status(gate_map, ("D1",)),
            "providers": provider_health,
            "successful_acquisition_days": d1_metrics.get("successful_acquisition_days"),
            "required_successful_acquisition_days": d1_metrics.get(
                "required_successful_acquisition_days"
            ),
            "acquisition_window_days": d1_metrics.get("acquisition_window_days"),
            "qualified_acquisition_dates_tail": qualified_dates[-5:],
            "staleness_days": d1_metrics.get("staleness_days"),
            "maximum_staleness_days": d1_metrics.get("maximum_staleness_days"),
        },
        "cross_source_validation": {
            "status": _dimension_status(
                gate_map,
                ("D3",),
                warn=int(d3_metrics.get("warn_rows") or 0) > 0,
            ),
            "rows": d3_metrics.get("rows"),
            "aligned_rows": d3_metrics.get("aligned_rows"),
            "warn_rows": d3_metrics.get("warn_rows"),
            "block_rows": d3_metrics.get("block_rows"),
            "max_basis_pct": max_basis_pct,
            "latest": latest_reconciliation,
        },
        "freshness": {
            "status": (
                "pass"
                if not operational_freshness or operational_freshness.get("fresh", False)
                else "fail"
            ),
            **dict(operational_freshness or {}),
        },
        "lineage": {
            "status": "fail" if integrity_errors or replay_errors else "pass",
            "current_run_id": (current or {}).get("run_id"),
            "previous_current_run_id": (manifest or {}).get("previous_current_run_id"),
            "predecessor": predecessor,
            "revision_predecessor": revision_predecessor,
            "canonical_hash": (manifest or {}).get("canonical_hash"),
            "canonical_sha256": (current or {}).get("canonical_sha256"),
            "artifact_hashes": artifact_hashes,
            "integrity_errors": list(integrity_errors or []),
            "replay_errors": list(replay_errors or []),
        },
        "observed": {
            "row_count": int(len(canonical)) if canonical is not None else (manifest or {}).get("canonical_rows"),
            "watermark": _watermark(canonical) if canonical is not None else (manifest or {}).get("watermark"),
            "input_watermarks": dict((manifest or {}).get("input_watermarks") or {}),
            "output_watermark": (manifest or {}).get("output_watermark"),
        },
        "evidence_refs": dict(evidence_refs or {}),
    }


def _coverage_metrics(
    dates: pd.Series,
    window_days: int | None = None,
    *,
    end_date: pd.Timestamp | None = None,
) -> tuple[int, int, float]:
    valid = pd.Series(pd.to_datetime(dates, errors="coerce", utc=True).dropna().unique()).sort_values()
    if valid.empty:
        return 0, 0, 0.0
    end = (
        pd.Timestamp(end_date).tz_convert("UTC").normalize()
        if end_date is not None
        else pd.Timestamp(valid.iloc[-1]).normalize()
    )
    if window_days is None:
        start = pd.Timestamp(valid.iloc[0]).normalize()
    else:
        start = end - pd.Timedelta(days=max(window_days - 1, 0))
    observed = int(pd.Series(valid).between(start, end, inclusive="both").sum())
    expected = int((end - start).days + 1)
    return observed, expected, observed / max(expected, 1)


def _structural_violations(frame: pd.DataFrame) -> dict[str, int]:
    dates = _utc_dates(frame)
    bar_open_at = pd.to_datetime(frame.get("bar_open_at"), errors="coerce", utc=True)
    numeric = pd.DataFrame({
        col: pd.to_numeric(frame[col], errors="coerce")
        for col in ("open", "high", "low", "close")
        if col in frame.columns
    }, index=frame.index)
    completed_at = pd.to_datetime(frame.get("bar_close_at"), errors="coerce", utc=True)
    fetched_at = pd.to_datetime(frame.get("fetched_at"), errors="coerce", utc=True)
    available_at = pd.to_datetime(frame.get("available_at"), errors="coerce", utc=True)
    identity = [
        column
        for column in ("provider", "instrument", "interval", "bar_open_at")
        if column in frame.columns
    ]
    result = {
        "null_dates": int(dates.isna().sum()),
        "duplicate_keys": int(frame.duplicated(identity).sum()) if len(identity) == 4 else int(len(frame)),
        "non_monotonic_dates": int(not dates.dropna().is_monotonic_increasing),
        "non_utc_midnight": int((bar_open_at != bar_open_at.dt.normalize()).fillna(False).sum()),
        "null_bar_close_at": int(completed_at.isna().sum()),
        "invalid_interval_duration": int(
            ((completed_at - bar_open_at) != pd.Timedelta(days=1)).fillna(False).sum()
        ),
        "future_completed_bars": int((completed_at > pd.Timestamp.now(tz="UTC")).sum()),
        "available_before_close": int((available_at < completed_at).fillna(False).sum()),
        "fetched_before_available": int((fetched_at < available_at).fillna(False).sum()),
        "non_final_rows": int((~frame.get("is_final", pd.Series(False, index=frame.index)).fillna(False).astype(bool)).sum()),
    }
    already_checked = {
        "bar_open_at", "bar_close_at", "open", "high", "low", "close", "is_final"
    }
    for column in sorted(PRIMARY_REQUIRED - already_checked):
        result[f"null_required_{column}"] = int(frame[column].isna().sum())
    for col in numeric.columns:
        series = numeric[col]
        result[f"null_{col}"] = int(series.isna().sum())
        result[f"nonpositive_{col}"] = int((series <= 0).sum())
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    result["null_volume"] = int(volume.isna().sum())
    result["negative_volume"] = int((volume < 0).sum())
    if set(numeric.columns) == {"open", "high", "low", "close"}:
        endpoints = numeric[["open", "close"]]
        result["ohlc_relationship"] = int(
            (
                (numeric["high"] < endpoints.max(axis=1))
                | (numeric["low"] > endpoints.min(axis=1))
                | (numeric["high"] < numeric["low"])
            ).sum()
        )
    return result


def _contract_violations(frame: pd.DataFrame, expected: dict[str, str]) -> dict[str, int]:
    violations: dict[str, int] = {}
    for column, value in expected.items():
        if column not in frame.columns:
            violations[column] = int(len(frame) or 1)
            continue
        actual = frame[column].astype("string")
        violations[column] = int((actual.isna() | actual.ne(value)).sum())
    if "schema_version" in frame.columns:
        schema = frame["schema_version"].astype("string")
        violations["schema_version"] = int((schema.isna() | schema.ne(SCHEMA_VERSION)).sum())
    if "payload_hash" in frame.columns:
        payload_hash = frame["payload_hash"].astype("string")
        violations["payload_hash_format"] = int(
            (~payload_hash.str.fullmatch(r"[0-9a-f]{64}", na=False)).sum()
        )
    if "run_id" in frame.columns:
        run_id = frame["run_id"].astype("string")
        violations["run_id_empty"] = int((run_id.isna() | run_id.str.strip().eq("")).sum())
    return violations


def _shadow_violations(frame: pd.DataFrame) -> dict[str, int]:
    bar_open_at = pd.to_datetime(frame["bar_open_at"], errors="coerce", utc=True)
    bar_close_at = pd.to_datetime(frame["bar_close_at"], errors="coerce", utc=True)
    fetched_at = pd.to_datetime(frame["fetched_at"], errors="coerce", utc=True)
    available_at = pd.to_datetime(frame["available_at"], errors="coerce", utc=True)
    close = pd.to_numeric(frame["close"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    result = {
        "duplicate_keys": int(
            frame.duplicated(["provider", "instrument", "interval", "bar_open_at"]).sum()
        ),
        "non_utc_midnight": int((bar_open_at != bar_open_at.dt.normalize()).fillna(False).sum()),
        "invalid_interval_duration": int(
            ((bar_close_at - bar_open_at) != pd.Timedelta(days=1)).fillna(False).sum()
        ),
        "future_completed_bars": int((bar_close_at > pd.Timestamp.now(tz="UTC")).sum()),
        "available_before_close": int((available_at < bar_close_at).fillna(False).sum()),
        "fetched_before_available": int((fetched_at < available_at).fillna(False).sum()),
        "null_close": int(close.isna().sum()),
        "nonpositive_close": int((close <= 0).sum()),
        "null_volume": int(volume.isna().sum()),
        "negative_volume": int((volume < 0).sum()),
        "non_final_rows": int(
            (~frame["is_final"].fillna(False).astype(bool)).sum()
        ),
    }
    already_checked = {"bar_open_at", "bar_close_at", "close", "volume", "is_final"}
    for column in sorted(SHADOW_REQUIRED - already_checked):
        result[f"null_required_{column}"] = int(frame[column].isna().sum())
    return result


def _maximum_missing_days(dates: pd.Series) -> int:
    values = pd.Series(pd.to_datetime(dates, errors="coerce", utc=True).dropna().unique()).sort_values()
    if len(values) < 2:
        return 0
    gaps = values.diff().dropna().dt.days - 1
    return int(max(gaps.max(), 0)) if not gaps.empty else 0


def _strictly_above(value: float, threshold: float) -> bool:
    return value > threshold and not math.isclose(
        value,
        threshold,
        rel_tol=0.0,
        abs_tol=1e-12,
    )


def _latest_expected_open(frame: pd.DataFrame) -> pd.Timestamp | None:
    fetched = pd.to_datetime(frame.get("fetched_at"), errors="coerce", utc=True)
    if fetched is None or not fetched.notna().any():
        return None
    return fetched.max().normalize() - pd.Timedelta(days=1)


def _acquisition_identity(evidence: dict[str, Any] | None) -> dict[str, Any]:
    providers = (evidence or {}).get("providers") or {}
    return {
        "as_of": str((evidence or {}).get("as_of") or ""),
        "providers": {
            str(name): {
                "status": report.get("status"),
                "rows": report.get("rows"),
                "raw_payload_hashes": list(report.get("raw_payload_hashes") or []),
                "error_kind": report.get("error_kind"),
            }
            for name, report in sorted(providers.items())
        },
        "predecessor": dict((evidence or {}).get("predecessor") or {}),
        "revision_predecessor": dict((evidence or {}).get("revision_predecessor") or {}),
        "qualified_acquisition_dates": sorted({
            str(attempt.get("date"))
            for attempt in ((evidence or {}).get("daily_attempts") or [])
            if attempt.get("qualified") and attempt.get("date")
        }),
    }


def _qualified_acquisition_dates(
    evidence: dict[str, Any] | None,
    *,
    window_days: int,
) -> list[str]:
    attempts = (evidence or {}).get("daily_attempts") or []
    parsed: list[tuple[pd.Timestamp, bool]] = []
    for attempt in attempts:
        timestamp = pd.to_datetime(attempt.get("date"), errors="coerce", utc=True)
        if pd.isna(timestamp):
            continue
        parsed.append((pd.Timestamp(timestamp).normalize(), bool(attempt.get("qualified"))))
    if not parsed:
        return []
    end = max(timestamp for timestamp, _qualified in parsed)
    start = end - pd.Timedelta(days=window_days - 1)
    return sorted({
        timestamp.date().isoformat()
        for timestamp, qualified in parsed
        if qualified and start <= timestamp <= end
    })


def _canonical_primary(primary: pd.DataFrame) -> pd.DataFrame:
    if primary.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close"])
    work = primary.copy()
    work = work[work["is_final"].fillna(False).astype(bool)].copy()
    work["date"] = _utc_dates(work).dt.tz_localize(None)
    for col in ("open", "high", "low", "close"):
        work[col] = pd.to_numeric(work[col], errors="coerce")
    keep = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "provider",
        "venue",
        "instrument",
        "base_asset",
        "quote_asset",
        "interval",
        "bar_open_at",
        "bar_close_at",
        "is_final",
        "fetched_at",
        "available_at",
        "payload_hash",
        "schema_version",
        "run_id",
    ]
    optional = [col for col in keep if col in work.columns]
    return work[optional].sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)


def reconcile_btc(primary: pd.DataFrame, shadow: pd.DataFrame, config: BtcAssuranceConfig) -> pd.DataFrame:
    columns = [
        "date",
        "primary_close",
        "shadow_close",
        "basis_pct",
        "primary_abs_return_pct",
        "robust_cutoff_pct",
        "is_suspect_move",
        "status",
        "reason_code",
    ]
    if primary.empty or shadow.empty:
        return pd.DataFrame(columns=columns)
    left = pd.DataFrame({
        "date": _utc_dates(primary).dt.tz_localize(None),
        "primary_close": pd.to_numeric(primary["close"], errors="coerce"),
    }).dropna().drop_duplicates("date", keep="last")
    right = pd.DataFrame({
        "date": _utc_dates(shadow).dt.tz_localize(None),
        "shadow_close": pd.to_numeric(shadow["close"], errors="coerce"),
    }).dropna().drop_duplicates("date", keep="last")
    joined = left.merge(right, on="date", how="left").sort_values("date").reset_index(drop=True)
    if joined.empty:
        return pd.DataFrame(columns=columns)
    joined["basis_pct"] = (joined["primary_close"] / joined["shadow_close"] - 1.0).abs() * 100.0
    joined["primary_abs_return_pct"] = joined["primary_close"].pct_change().abs() * 100.0
    past_returns = joined["primary_abs_return_pct"].shift(1)
    rolling = past_returns.rolling(
        config.anomaly_mad_window_days,
        min_periods=config.anomaly_mad_min_history,
    )
    rolling_median = rolling.median()
    rolling_mad = rolling.apply(
        lambda values: float((values - pd.Series(values).median()).abs().median()),
        raw=False,
    )
    joined["robust_cutoff_pct"] = (
        rolling_median + config.anomaly_mad_multiple * rolling_mad.clip(lower=1e-9)
    )
    joined["is_suspect_move"] = (
        (joined["primary_abs_return_pct"] > config.anomaly_return_pct)
        | (
            joined["robust_cutoff_pct"].notna()
            & (joined["primary_abs_return_pct"] > joined["robust_cutoff_pct"])
        )
    )

    def _classify(row: pd.Series) -> tuple[str, str]:
        if pd.isna(row["shadow_close"]):
            if bool(row["is_suspect_move"]):
                return "warn", "UNCONFIRMED_PRICE_ANOMALY"
            return "pass", "SHADOW_OUTSIDE_QUALIFICATION_WINDOW"
        basis = float(row["basis_pct"])
        if _strictly_above(basis, config.block_basis_pct):
            return "block", "SOURCE_DIVERGENCE_BLOCK"
        if bool(row["is_suspect_move"]) and _strictly_above(basis, config.warn_basis_pct):
            return "block", "UNCONFIRMED_PRICE_ANOMALY"
        if _strictly_above(basis, config.warn_basis_pct):
            return "warn", "SOURCE_DIVERGENCE_WARN"
        if bool(row["is_suspect_move"]):
            return "pass", "ANOMALY_CONFIRMED"
        return "pass", "SOURCE_ALIGNED"

    classified = joined.apply(_classify, axis=1, result_type="expand")
    joined[["status", "reason_code"]] = classified
    return joined[columns]


def compare_revisions(candidate: pd.DataFrame, existing: pd.DataFrame | None, config: BtcAssuranceConfig) -> pd.DataFrame:
    columns = ["date", "old_close", "new_close", "revision_pct", "status", "reason_code"]
    if existing is None or existing.empty or candidate.empty:
        return pd.DataFrame(columns=columns)
    old = existing[["date", "close"]].copy()
    new = candidate[["date", "close"]].copy()
    old["date"] = pd.to_datetime(old["date"], errors="coerce").dt.normalize()
    new["date"] = pd.to_datetime(new["date"], errors="coerce").dt.normalize()
    old["close"] = pd.to_numeric(old["close"], errors="coerce")
    new["close"] = pd.to_numeric(new["close"], errors="coerce")
    joined = old.rename(columns={"close": "old_close"}).merge(
        new.rename(columns={"close": "new_close"}), on="date", how="inner"
    ).dropna()
    joined["revision_pct"] = (joined["new_close"] / joined["old_close"] - 1.0).abs() * 100.0

    def _classify(value: float) -> tuple[str, str]:
        if _strictly_above(value, config.block_revision_pct):
            return "block", "REVISION_BLOCK"
        if _strictly_above(value, config.warn_revision_pct):
            return "warn", "REVISION_WARN"
        return "pass", "REVISION_ACCEPTED"

    classified = joined["revision_pct"].map(_classify)
    joined["status"] = classified.map(lambda item: item[0])
    joined["reason_code"] = classified.map(lambda item: item[1])
    return joined[columns].sort_values("date").reset_index(drop=True)


def assure_btc(
    primary: pd.DataFrame,
    shadow: pd.DataFrame,
    *,
    existing: pd.DataFrame | None = None,
    config: BtcAssuranceConfig | None = None,
    acquisition_evidence: dict[str, Any] | None = None,
    raw_payloads: dict[str, tuple[bytes, ...]] | None = None,
) -> BtcAssuranceResult:
    config = config or BtcAssuranceConfig()
    primary = primary.copy()
    shadow = shadow.copy()
    config_hash = _json_hash(config.to_dict())
    code_revision = _implementation_revision()
    schema_hash = _json_hash({
        "schema_version": SCHEMA_VERSION,
        "primary_required": sorted(PRIMARY_REQUIRED),
        "shadow_required": sorted(SHADOW_REQUIRED),
        "primary_contract": PRIMARY_CONTRACT,
        "shadow_contract": SHADOW_CONTRACT,
    })
    run_id = _json_hash({
        "contract": CONTRACT_VERSION,
        "code_revision": code_revision,
        "schema_hash": schema_hash,
        "provider_contracts": {
            "primary": dict(PRIMARY_CONTRACT),
            "shadow": dict(SHADOW_CONTRACT),
        },
        "retention_policy": {
            "minimum_completed_runs": 10,
            "strategy": "retain_all_no_automatic_pruning",
        },
        "primary": _frame_hash(primary),
        "shadow": _frame_hash(shadow),
        "config": config_hash,
        "acquisition": _acquisition_identity(acquisition_evidence),
    })[:24]

    gates: list[DataGateResult] = []
    missing_primary = sorted(PRIMARY_REQUIRED - set(primary.columns))
    missing_shadow = sorted(SHADOW_REQUIRED - set(shadow.columns))
    primary_contract_violations = (
        _contract_violations(primary, PRIMARY_CONTRACT) if not missing_primary else {}
    )
    shadow_contract_violations = (
        _contract_violations(shadow, SHADOW_CONTRACT) if not missing_shadow else {}
    )
    contract_ok = (
        not missing_primary
        and not missing_shadow
        and not any(primary_contract_violations.values())
        and not any(shadow_contract_violations.values())
    )
    gates.append(DataGateResult(
        "D0",
        "pass" if contract_ok else "fail",
        "CONTRACT_VALID" if contract_ok else "INVALID_SCHEMA",
        "provider-native contracts present" if contract_ok else "required provider columns missing",
        {
            "missing_primary": missing_primary,
            "missing_shadow": missing_shadow,
            "primary_contract_violations": primary_contract_violations,
            "shadow_contract_violations": shadow_contract_violations,
        },
    ))

    primary_expected: pd.Timestamp | None = None
    if contract_ok:
        primary = primary.sort_values("bar_open_at").reset_index(drop=True)
        shadow = shadow.sort_values("bar_open_at").reset_index(drop=True)
        primary_dates = _utc_dates(primary[primary["is_final"].fillna(False).astype(bool)])
        shadow_dates = _utc_dates(shadow[shadow["is_final"].fillna(False).astype(bool)])
        primary_last = primary_dates.max() if primary_dates.notna().any() else None
        shadow_last = shadow_dates.max() if shadow_dates.notna().any() else None
        common_end = min(primary_last, shadow_last) if primary_last is not None and shadow_last is not None else None
        primary_expected = _latest_expected_open(primary)
        shadow_expected = _latest_expected_open(shadow)
        common_expected = (
            min(primary_expected, shadow_expected)
            if primary_expected is not None and shadow_expected is not None
            else None
        )
        if common_end is None:
            dual_days = 0
        else:
            cutoff = common_end - pd.Timedelta(days=config.shadow_days - 1)
            dual_days = len(set(primary_dates[primary_dates >= cutoff]) & set(shadow_dates[shadow_dates >= cutoff]))
        primary_max_missing = _maximum_missing_days(primary_dates)
        shadow_max_missing = _maximum_missing_days(shadow_dates)
        staleness_days = (
            max(int((common_expected - common_end).days), 0)
            if common_expected is not None and common_end is not None
            else None
        )
        shadow_violations = _shadow_violations(shadow)
        qualified_acquisition_dates = _qualified_acquisition_dates(
            acquisition_evidence,
            window_days=config.acquisition_window_days,
        )
        acquisition_ok = (
            dual_days >= config.shadow_required_days
            and primary_max_missing <= 1
            and shadow_max_missing <= 1
            and staleness_days is not None
            and staleness_days <= config.maximum_staleness_days
            and not any(shadow_violations.values())
            and len(qualified_acquisition_dates) >= config.minimum_successful_acquisition_days
        )
        if acquisition_ok:
            acquisition_reason = "DUAL_SOURCE_READY"
        elif dual_days < config.shadow_required_days:
            acquisition_reason = "SHADOW_COVERAGE_INSUFFICIENT"
        elif staleness_days is None or staleness_days > config.maximum_staleness_days:
            acquisition_reason = "PROVIDER_DATA_STALE"
        elif len(qualified_acquisition_dates) < config.minimum_successful_acquisition_days:
            acquisition_reason = "ACQUISITION_STABILITY_INSUFFICIENT"
        else:
            acquisition_reason = "ACQUISITION_CONTRACT_INVALID"
        gates.append(DataGateResult(
            "D1",
            "pass" if acquisition_ok else "fail",
            acquisition_reason,
            "rolling dual-source coverage",
            {
                "dual_source_days": int(dual_days),
                "required_days": config.shadow_required_days,
                "primary_max_consecutive_missing_days": primary_max_missing,
                "shadow_max_consecutive_missing_days": shadow_max_missing,
                "latest_expected_open": common_expected.date().isoformat() if common_expected is not None else None,
                "staleness_days": staleness_days,
                "maximum_staleness_days": config.maximum_staleness_days,
                "qualified_acquisition_dates": qualified_acquisition_dates,
                "successful_acquisition_days": len(qualified_acquisition_dates),
                "required_successful_acquisition_days": config.minimum_successful_acquisition_days,
                "acquisition_window_days": config.acquisition_window_days,
                "shadow_violations": shadow_violations,
                "attempts": dict(acquisition_evidence or {}),
            },
        ))
        violations = _structural_violations(primary)
        hard_violations = sum(violations.values())
        full_observed, full_expected, full_coverage = _coverage_metrics(
            primary_dates,
            end_date=primary_expected,
        )
        recent_observed, recent_expected, recent_coverage = _coverage_metrics(
            primary_dates,
            config.recent_window_days,
            end_date=primary_expected,
        )
        coverage_ok = (
            full_coverage >= config.full_coverage_required
            and recent_coverage >= config.recent_coverage_required
        )
        structural_ok = hard_violations == 0 and coverage_ok
        history_ok = full_observed >= config.minimum_history_days
        if hard_violations:
            structural_reason = "STRUCTURE_INVALID"
        elif not full_observed or not history_ok:
            structural_reason = "INSUFFICIENT_HISTORY"
        elif not coverage_ok:
            structural_reason = "STRUCTURE_INVALID"
        else:
            structural_reason = "STRUCTURE_VALID"
        gates.append(DataGateResult(
            "D2",
            "pass" if structural_ok and history_ok else "fail",
            structural_reason,
            "UTC daily structural and coverage checks",
            {
                "violations": violations,
                "history_days": int(full_observed),
                "full_expected_days": int(full_expected),
                "full_coverage": round(float(full_coverage), 6),
                "recent_observed_days": int(recent_observed),
                "recent_expected_days": int(recent_expected),
                "recent_coverage": round(float(recent_coverage), 6),
            },
        ))
    else:
        gates.extend([
            DataGateResult("D1", "fail", "CONTRACT_BLOCKED", "acquisition checks require valid contracts"),
            DataGateResult("D2", "fail", "CONTRACT_BLOCKED", "structural checks require valid contracts"),
        ])

    canonical = _canonical_primary(primary) if not missing_primary else pd.DataFrame(columns=["date", "open", "high", "low", "close"])
    if not missing_primary and len(primary) > 1:
        split_at = max(len(primary) - 2, 1)
        incremental_canonical = pd.concat(
            [
                _canonical_primary(primary.iloc[:split_at]),
                _canonical_primary(primary.iloc[split_at:]),
            ],
            ignore_index=True,
        ).sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    else:
        incremental_canonical = canonical.copy()
    reconciliation = reconcile_btc(primary, shadow, config) if contract_ok else pd.DataFrame()
    block_rows = int((reconciliation.get("status", pd.Series(dtype=str)) == "block").sum())
    warn_rows = int((reconciliation.get("status", pd.Series(dtype=str)) == "warn").sum())
    aligned_rows = int(reconciliation.get("shadow_close", pd.Series(dtype=float)).notna().sum())
    reconciliation_ok = aligned_rows >= config.shadow_required_days and block_rows == 0
    gates.append(DataGateResult(
        "D3",
        "pass" if reconciliation_ok else "fail",
        (
            "SOURCES_RECONCILED"
            if reconciliation_ok
            else ("NO_COMMON_WINDOW" if aligned_rows < config.shadow_required_days else "SOURCE_DIVERGENCE")
        ),
        "UTC close reconciliation",
        {
            "rows": int(len(reconciliation)),
            "aligned_rows": aligned_rows,
            "warn_rows": warn_rows,
            "block_rows": block_rows,
        },
    ))

    if not reconciliation.empty:
        quarantined_dates = set(reconciliation.loc[reconciliation["status"] != "pass", "date"])
        canonical = canonical[~canonical["date"].isin(quarantined_dates)].reset_index(drop=True)
        incremental_canonical = incremental_canonical[
            ~incremental_canonical["date"].isin(quarantined_dates)
        ].reset_index(drop=True)
    revisions = compare_revisions(canonical, existing, config)
    revision_blocks = int((revisions.get("status", pd.Series(dtype=str)) == "block").sum())
    revision_warns = int((revisions.get("status", pd.Series(dtype=str)) == "warn").sum())
    if not revisions.empty:
        revision_quarantine = set(revisions.loc[revisions["status"] != "pass", "date"])
        canonical = canonical[~canonical["date"].isin(revision_quarantine)].reset_index(drop=True)
        incremental_canonical = incremental_canonical[
            ~incremental_canonical["date"].isin(revision_quarantine)
        ].reset_index(drop=True)
    replay_hash = _frame_hash(canonical)
    incremental_replay_hash = _frame_hash(incremental_canonical)
    replay_match = replay_hash == incremental_replay_hash
    predecessor = dict((acquisition_evidence or {}).get("predecessor") or {})
    predecessor_read_error = predecessor.get("status") == "read_error"
    revision_baseline_ok = len(revisions) >= config.minimum_revision_overlap_days
    revision_ok = (
        revision_blocks == 0
        and not predecessor_read_error
        and revision_baseline_ok
        and replay_match
    )
    gates.append(DataGateResult(
        "D4",
        "pass" if revision_ok else "fail",
        (
            "REVISION_ACCEPTABLE"
            if revision_ok
            else (
                "PREDECESSOR_READ_ERROR"
                if predecessor_read_error
                else (
                    "REVISION_BASELINE_MISSING"
                    if not revision_baseline_ok
                    else ("REPLAY_MISMATCH" if not replay_match else "REVISION_BLOCK")
                )
            )
        ),
        "candidate revision and deterministic replay fingerprint",
        {
            "revision_rows": int(len(revisions)),
            "warn_rows": revision_warns,
            "block_rows": revision_blocks,
            "canonical_hash": replay_hash,
            "full_replay_hash": replay_hash,
            "incremental_replay_hash": incremental_replay_hash,
            "replay_match": replay_match,
            "predecessor": predecessor,
            "revision_predecessor": dict(
                (acquisition_evidence or {}).get("revision_predecessor") or {}
            ),
            "minimum_revision_overlap_days": config.minimum_revision_overlap_days,
        },
    ))

    final_observed, final_expected, final_coverage = _coverage_metrics(
        pd.to_datetime(canonical.get("date"), errors="coerce", utc=True),
        end_date=primary_expected,
    )
    recent_final_observed, recent_final_expected, recent_final_coverage = _coverage_metrics(
        pd.to_datetime(canonical.get("date"), errors="coerce", utc=True),
        config.recent_window_days,
        end_date=primary_expected,
    )
    qualified_history_ok = (
        final_observed >= config.minimum_history_days
        and final_coverage >= config.full_coverage_required
        and recent_final_coverage >= config.recent_coverage_required
    )

    gate_map = {gate.gate: gate for gate in gates}
    d0_ok = gate_map["D0"].status == "pass"
    d1_ok = gate_map["D1"].status == "pass"
    d2_ok = gate_map["D2"].status == "pass"
    d3_ok = gate_map["D3"].status == "pass"
    d4_ok = gate_map["D4"].status == "pass"
    if not d0_ok or gate_map["D2"].reason_code == "STRUCTURE_INVALID":
        readiness = "invalid"
    elif not d1_ok or not d3_ok or not d4_ok:
        readiness = "degraded"
    elif gate_map["D2"].reason_code == "INSUFFICIENT_HISTORY" or not qualified_history_ok:
        readiness = "insufficient_data"
    elif all((d0_ok, d1_ok, d2_ok, d3_ok, d4_ok, qualified_history_ok)):
        readiness = "ready"
    else:
        readiness = "insufficient_data"

    manifest = {
        "contract_version": CONTRACT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data_readiness": readiness,
        "config": config.to_dict(),
        "config_hash": config_hash,
        "code_revision": code_revision,
        "schema_hash": schema_hash,
        "provider_contracts": {
            "primary": dict(PRIMARY_CONTRACT),
            "shadow": dict(SHADOW_CONTRACT),
        },
        "retention_policy": {
            "minimum_completed_runs": 10,
            "strategy": "retain_all_no_automatic_pruning",
        },
        "primary_hash": _frame_hash(primary),
        "shadow_hash": _frame_hash(shadow),
        "canonical_hash": replay_hash,
        "canonical_rows": int(len(canonical)),
        "watermark": _watermark(canonical),
        "input_watermarks": {
            "primary": (
                _utc_dates(primary).max().date().isoformat()
                if not primary.empty and _utc_dates(primary).notna().any()
                else None
            ),
            "shadow": (
                _utc_dates(shadow).max().date().isoformat()
                if not shadow.empty and _utc_dates(shadow).notna().any()
                else None
            ),
        },
        "output_watermark": _watermark(canonical),
        "previous_current_run_id": (
            ((acquisition_evidence or {}).get("predecessor") or {}).get("run_id")
        ),
        "qualified_history": {
            "observed_days": final_observed,
            "expected_days": final_expected,
            "coverage": round(float(final_coverage), 6),
            "recent_observed_days": recent_final_observed,
            "recent_expected_days": recent_final_expected,
            "recent_coverage": round(float(recent_final_coverage), 6),
        },
        "acquisition_evidence": dict(acquisition_evidence or {}),
        "gates": [gate.to_dict() for gate in gates],
        "causal": False,
    }
    manifest["health"] = summarize_btc_health(
        run_id=run_id,
        data_readiness=readiness,
        publishable=readiness == "ready",
        gates=gates,
        canonical=canonical,
        reconciliation=reconciliation,
        revisions=revisions,
        acquisition_evidence=acquisition_evidence,
        manifest=manifest,
    )
    return BtcAssuranceResult(
        run_id=run_id,
        data_readiness=readiness,
        publishable=readiness == "ready",
        primary=primary,
        shadow=shadow,
        canonical=canonical,
        reconciliation=reconciliation,
        revisions=revisions,
        gates=gates,
        manifest=manifest,
        raw_payloads=dict(raw_payloads or {}),
    )
