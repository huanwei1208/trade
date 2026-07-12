from __future__ import annotations

import hashlib
from io import BytesIO
import json
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from trade_py.analysis.crypto_validation import validate_btc_volatility
try:
    from trade_py.data.market.crypto.service import BtcMarketDataService
except ImportError:
    from trade_py.data.market.cross_asset.service import BtcMarketDataService  # type: ignore[no-redef]
from trade_py.data.warehouse.crypto_store import (
    CRYPTO_BTC_PROFILE,
    CRYPTO_VALIDATION_CURRENT,
    CRYPTO_VALIDATION_TABLES,
    MINIMUM_LIFECYCLE_RECHECK_DAYS,
    _apply_signal_lifecycle,
    _assurance_order_key,
    _commit_crypto_validation_outputs,
    _data_lineage_activation_check,
    _json,
    _promote_validation_pointer,
    _recover_crypto_validation_transactions,
    _validation_pointer_path,
    build_crypto_validation_outputs,
    persist_crypto_validation_outputs,
    read_crypto_validation_outputs,
)


def _read_verified_run_artifact(
    run_dir: Path,
    manifest: dict[str, Any],
    name: str,
) -> pd.DataFrame:
    expected = str((manifest.get("artifact_hashes") or {}).get(name) or "")
    if len(expected) != 64:
        raise ValueError(f"missing {name} artifact hash")
    path = run_dir / f"{name}.parquet"
    snapshot = path.read_bytes()
    actual = hashlib.sha256(snapshot).hexdigest()
    if actual != expected:
        raise ValueError(f"{name} artifact hash mismatch")
    return pd.read_parquet(BytesIO(snapshot))


def _load_validation_snapshot(
    service: BtcMarketDataService,
    data_assurance_override: dict[str, Any] | None,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, list[str]]:
    canonical = pd.DataFrame(columns=["date", "close", "available_at"])
    reconciliation = pd.DataFrame()
    errors: list[str] = []
    with service.store.shared_lock():
        data_assurance = (
            dict(data_assurance_override)
            if data_assurance_override is not None
            else service.validate_current(_lock=False)
        )
        run_id = str(data_assurance.get("run_id") or "")
        if not run_id:
            return data_assurance, canonical, reconciliation, errors
        run_dir = service.store.run_dir(run_id)
        manifest_path = run_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if str(manifest.get("run_id") or "") != run_id:
                raise ValueError("manifest run_id mismatch")
            data_assurance = {
                **data_assurance,
                "manifest": manifest,
                "manifest_path": str(manifest_path),
                "gates": manifest.get("gates") or data_assurance.get("gates") or [],
            }
        except Exception as exc:
            errors.append(f"manifest: {type(exc).__name__}: {exc}")
            return data_assurance, canonical, reconciliation, errors
        try:
            canonical = _read_verified_run_artifact(run_dir, manifest, "canonical")
        except Exception as exc:
            errors.append(f"canonical: {type(exc).__name__}: {exc}")
        try:
            reconciliation = _read_verified_run_artifact(
                run_dir,
                manifest,
                "reconciliation",
            )
        except Exception as exc:
            errors.append(f"reconciliation: {type(exc).__name__}: {exc}")
    return data_assurance, canonical, reconciliation, errors


def _assurance_identity(data_assurance: dict[str, Any]) -> dict[str, Any]:
    manifest = data_assurance.get("manifest") or {}
    return {
        "data_run_id": data_assurance.get("run_id"),
        "data_readiness": data_assurance.get("data_readiness"),
        "reason_code": data_assurance.get("reason_code"),
        "reason_codes": list(data_assurance.get("reason_codes") or []),
        "observed_at": data_assurance.get("observed_at"),
        "acquisition_as_of": (data_assurance.get("acquisition") or {}).get("as_of"),
        "canonical_hash": manifest.get("canonical_hash"),
        "code_revision": manifest.get("code_revision"),
        "schema_hash": manifest.get("schema_hash"),
        "gates": [
            {
                "gate": gate.get("gate"),
                "status": gate.get("status"),
                "reason_code": gate.get("reason_code"),
            }
            for gate in (manifest.get("gates") or data_assurance.get("gates") or [])
        ],
        "operational_freshness": {
            key: (data_assurance.get("operational_freshness") or {}).get(key)
            for key in (
                "expected_latest_open",
                "watermark",
                "staleness_days",
                "maximum_staleness_days",
                "fresh",
            )
        },
    }


def validate_crypto_btc_profile(
    data_root: str | Path,
    *,
    dry_run: bool = False,
    now: Callable[[], Any] | None = None,
    data_assurance_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    service = BtcMarketDataService(data_root, now=now)
    data_assurance, canonical, reconciliation, io_errors = _load_validation_snapshot(
        service,
        data_assurance_override,
    )
    if io_errors:
        reason_codes = list(data_assurance.get("reason_codes") or [])
        if any(error.startswith("manifest:") for error in io_errors):
            reason_codes.append("CURRENT_MANIFEST_READ_ERROR")
        if any(error.startswith("canonical:") for error in io_errors):
            reason_codes.append("CANONICAL_READ_ERROR")
        if any(error.startswith("reconciliation:") for error in io_errors):
            reason_codes.append("RECONCILIATION_READ_ERROR")
        reason_codes = list(dict.fromkeys(reason_codes))
        data_assurance = {
            **data_assurance,
            "data_readiness": "invalid",
            "reason_code": reason_codes[0] if reason_codes else "CURRENT_ARTIFACT_READ_ERROR",
            "reason_codes": reason_codes,
            "artifact_read_errors": io_errors,
        }
    effective_as_of: str | None = None
    if not reconciliation.empty and "shadow_close" in reconciliation.columns:
        aligned = reconciliation.loc[reconciliation["shadow_close"].notna(), "date"]
        if not aligned.empty:
            latest_common = pd.to_datetime(aligned, errors="coerce").max()
            if not pd.isna(latest_common):
                effective_as_of = pd.Timestamp(latest_common).date().isoformat()
                canonical_dates = pd.to_datetime(canonical.get("date"), errors="coerce")
                canonical = canonical.loc[canonical_dates <= pd.Timestamp(latest_common)].reset_index(drop=True)
    validation = validate_btc_volatility(
        canonical,
        str(data_assurance.get("data_readiness") or "invalid"),
        assurance_evidence=_assurance_identity(data_assurance),
    )
    validation, outputs, paths = _commit_crypto_validation_outputs(
        data_root,
        data_assurance=data_assurance,
        validation=validation,
        reconciliation=reconciliation,
        dry_run=dry_run,
        enforce_data_lineage=True,
    )
    return {
        "profile": CRYPTO_BTC_PROFILE,
        "as_of": "latest-common",
        "effective_as_of": effective_as_of,
        "dry_run": dry_run,
        "io_error": "; ".join(io_errors) if io_errors else None,
        "data_assurance": data_assurance,
        "validation": validation,
        "outputs": paths,
        "output_rows": {name: int(len(frame)) for name, frame in outputs.items()},
    }


__all__ = [
    "CRYPTO_BTC_PROFILE",
    "build_crypto_validation_outputs",
    "persist_crypto_validation_outputs",
    "read_crypto_validation_outputs",
    "validate_crypto_btc_profile",
]
