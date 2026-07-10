from __future__ import annotations

from contextlib import nullcontext
import fcntl
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from trade_py.data.market.cross_asset.store import BtcRunStore
from trade_py.data.warehouse.io import WarehouseLayout


CRYPTO_BTC_PROFILE = "crypto-btc-v1"
MINIMUM_LIFECYCLE_RECHECK_DAYS = 28
CRYPTO_VALIDATION_CURRENT = "_crypto_validation_current.json"
CRYPTO_VALIDATION_TABLES = {
    "ads_crypto_data_readiness_report",
    "ads_crypto_provider_reconciliation",
    "ads_crypto_volatility_validation",
    "ads_research_validation_run",
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _apply_signal_lifecycle(
    data_root: str | Path,
    validation: dict[str, Any],
    *,
    activation_allowed: bool = True,
    activation_reason: str | None = None,
) -> dict[str, Any]:
    layout = WarehouseLayout.from_data_root(data_root)
    path = layout.table_path("ads", "ads_crypto_volatility_validation")
    previous: dict[str, Any] = {}
    pointer_generation_id: str | None = None
    if path.exists():
        history = pd.read_parquet(path)
        pointer_path = path.parent / CRYPTO_VALIDATION_CURRENT
        if pointer_path.exists():
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            active_run_id = str(pointer.get("run_id") or "")
            pointer_generation_id = str(pointer.get("generation_id") or "")
            if not active_run_id or not pointer_generation_id:
                raise ValueError("Crypto validation current pointer is invalid")
            if "generation_id" not in history.columns:
                raise ValueError("Crypto validation table has no generation_id")
            history = history.loc[
                history["generation_id"].astype(str) == pointer_generation_id
            ]
            if history.empty:
                raise ValueError("Crypto validation current pointer row is missing")
        elif "is_active" in history.columns:
            if "run_id" in history.columns:
                history = history.loc[
                    history["run_id"].astype(str)
                    != str(validation.get("run_id") or "")
                ]
            history = history.loc[history["is_active"].fillna(False).astype(bool)]
        else:
            history = history.iloc[0:0]
        if not history.empty:
            previous = history.iloc[-1].to_dict()

    incoming_data_run_id = str(
        (((validation.get("input_evidence") or {}).get("data_assurance") or {}).get("data_run_id"))
        or ""
    )
    if (
        activation_allowed
        and pointer_generation_id
        and str(previous.get("run_id") or "") == str(validation.get("run_id") or "")
        and str(previous.get("data_run_id") or "") == incoming_data_run_id
        and str(previous.get("signal_status") or "") == str(validation.get("status") or "")
        and str(previous.get("data_readiness") or "")
        == str(validation.get("data_readiness") or "")
        and str(previous.get("evidence_hash") or "")
        == str(validation.get("evidence_hash") or "")
    ):
        persisted_lifecycle = previous.get("lifecycle") or "{}"
        if isinstance(persisted_lifecycle, str):
            persisted_lifecycle = json.loads(persisted_lifecycle)
        enriched = dict(validation)
        enriched["lifecycle"] = {
            **dict(persisted_lifecycle),
            "reused_generation_id": pointer_generation_id,
        }
        return enriched

    incoming_watermark = pd.to_datetime(
        validation.get("watermark"),
        errors="coerce",
        utc=True,
    )
    previous_watermark = pd.to_datetime(
        previous.get("watermark"),
        errors="coerce",
        utc=True,
    )
    stale_write = bool(
        not pd.isna(incoming_watermark)
        and not pd.isna(previous_watermark)
        and pd.Timestamp(incoming_watermark) < pd.Timestamp(previous_watermark)
    )
    recheck_days = (
        int((pd.Timestamp(incoming_watermark) - pd.Timestamp(previous_watermark)).days)
        if not pd.isna(incoming_watermark) and not pd.isna(previous_watermark)
        else None
    )
    recheck_interval_met = (
        recheck_days is None or recheck_days >= MINIMUM_LIFECYCLE_RECHECK_DAYS
    )

    interval = validation.get("confidence_interval") or {}
    lower = interval.get("lower")
    upper = interval.get("upper")
    crosses_null = bool(
        lower is not None
        and upper is not None
        and float(lower) <= 1.0 <= float(upper)
    )
    raw_status = str(validation.get("status") or "candidate")
    readiness = str(validation.get("data_readiness") or "invalid")
    previous_active = str(previous.get("active_signal_status") or "")
    previous_crossings = int(previous.get("consecutive_null_crossings") or 0)
    previous_crossed = bool(previous.get("ci_crosses_null") or False)

    suppressed = readiness != "ready"
    pending_recheck = False
    activate_run = True
    if suppressed:
        active_status = "candidate"
        consecutive = 0
    elif stale_write:
        active_status = previous_active or "candidate"
        consecutive = previous_crossings
        pending_recheck = bool(previous.get("pending_recheck") or False)
        activate_run = False
    elif raw_status == "validated":
        active_status = "validated"
        consecutive = 0
    elif raw_status == "monitoring" and crosses_null:
        if previous_active == "validated" and not recheck_interval_met:
            active_status = "validated"
            consecutive = previous_crossings
            pending_recheck = True
            activate_run = False
        else:
            consecutive = previous_crossings + 1 if previous_crossed else 1
            active_status = "monitoring"
        if previous_active == "validated" and recheck_interval_met and consecutive < 2:
            active_status = "validated"
            pending_recheck = True
    elif raw_status == "monitoring" and previous_active == "validated":
        active_status = "validated"
        consecutive = 0
        pending_recheck = True
    elif raw_status in {"monitoring", "rejected"}:
        active_status = raw_status
        consecutive = 0
    else:
        active_status = "candidate"
        consecutive = 0

    if not activation_allowed:
        active_status = previous_active or "candidate"
        consecutive = previous_crossings
        pending_recheck = bool(previous.get("pending_recheck") or False)
        activate_run = False

    enriched = dict(validation)
    enriched["lifecycle"] = {
        "active_signal_status": active_status,
        "raw_signal_status": raw_status,
        "ci_crosses_null": crosses_null,
        "consecutive_null_crossings": consecutive,
        "pending_recheck": pending_recheck,
        "suppressed_by_data_gate": suppressed,
        "previous_active_run_id": previous.get("run_id"),
        "previous_active_generation_id": previous.get("generation_id"),
        "activate_run": activate_run,
        "stale_write_rejected": stale_write and not suppressed,
        "minimum_recheck_days": MINIMUM_LIFECYCLE_RECHECK_DAYS,
        "days_since_previous_active": recheck_days,
        "recheck_interval_met": recheck_interval_met,
        "data_lineage_activation_allowed": activation_allowed,
        "data_lineage_reason": activation_reason,
    }
    return enriched


def build_crypto_validation_outputs(
    *,
    data_assurance: dict[str, Any],
    validation: dict[str, Any],
    reconciliation: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    validation_run_id = str(validation.get("run_id") or "")
    data_run_id = str(data_assurance.get("run_id") or "")
    lifecycle = validation.get("lifecycle") or {}
    generation_id = str(lifecycle.get("reused_generation_id") or "")
    if not generation_id:
        generation_id = hashlib.sha256(
            _json(
                {
                    "validation_run_id": validation_run_id,
                    "data_run_id": data_run_id,
                    "evidence_hash": validation.get("evidence_hash"),
                    "watermark": validation.get("watermark"),
                    "status": validation.get("status"),
                    "data_readiness": validation.get("data_readiness"),
                    "lifecycle": lifecycle,
                }
            ).encode("utf-8")
        ).hexdigest()[:24]
    manifest = data_assurance.get("manifest") or {}
    gates = data_assurance.get("gates") or manifest.get("gates") or []
    failed_reasons = [
        str(gate.get("reason_code"))
        for gate in gates
        if gate.get("status") != "pass" and gate.get("reason_code")
    ]
    for reason in [
        data_assurance.get("reason_code"),
        *(data_assurance.get("reason_codes") or []),
        *(data_assurance.get("integrity_errors") or []),
        *(data_assurance.get("replay_errors") or []),
    ]:
        if reason and str(reason) not in failed_reasons:
            failed_reasons.append(str(reason))
    evidence_ref = str(
        (data_assurance.get("current") or {}).get("manifest_path")
        or data_assurance.get("manifest_path")
        or (data_assurance.get("manifest") or {}).get("manifest_path")
        or ""
    )
    data_health = data_assurance.get("health") or manifest.get("health") or {}
    common = {
        "run_id": validation_run_id,
        "generation_id": generation_id,
        "data_run_id": data_run_id,
        "profile": CRYPTO_BTC_PROFILE,
        "contract_version": validation.get("contract_version"),
        "watermark": validation.get("watermark"),
        "evidence_ref": evidence_ref,
        "causal": False,
    }
    readiness = pd.DataFrame([{
        **common,
        "data_readiness": data_assurance.get("data_readiness", "invalid"),
        "publishable": bool(data_assurance.get("data_readiness") == "ready"),
        "reason_codes": _json(failed_reasons),
        "gates": _json(gates),
        "data_health_json": _json(data_health),
        "input_hash": (validation.get("input_evidence") or {}).get("input_hash"),
    }])

    if reconciliation.empty:
        reconciliation_output = pd.DataFrame([{
            **common,
            "date": pd.NaT,
            "status": "missing",
            "reason_code": "NO_RECONCILIATION_EVIDENCE",
            "primary_close": None,
            "shadow_close": None,
            "basis_pct": None,
            "primary_abs_return_pct": None,
            "is_suspect_move": None,
        }])
    else:
        reconciliation_output = reconciliation.copy()
        for key, value in common.items():
            reconciliation_output[key] = value
        ordered = list(common) + [
            column for column in reconciliation_output.columns if column not in common
        ]
        reconciliation_output = reconciliation_output[ordered]

    metrics = validation.get("metrics") or {}
    interval = validation.get("confidence_interval") or {}
    validation_output = pd.DataFrame([{
        **common,
        "hypothesis_id": validation.get("hypothesis_id"),
        "signal_status": validation.get("status"),
        "data_readiness": validation.get("data_readiness"),
        "effect_ratio": metrics.get("future_rv7_median_ratio"),
        "ci_lower": interval.get("lower"),
        "ci_upper": interval.get("upper"),
        "p_value": validation.get("p_value"),
        "q_value": validation.get("q_value"),
        "reason_codes": _json(validation.get("reasons") or []),
        "sample": _json(validation.get("sample") or {}),
        "folds": _json(validation.get("folds") or []),
        "placebos": _json(validation.get("placebos") or {}),
        "input_evidence": _json(validation.get("input_evidence") or {}),
        "data_health_json": _json(data_health),
        "evidence_hash": validation.get("evidence_hash"),
        "recommendation": None,
        "active_signal_status": lifecycle.get("active_signal_status", "candidate"),
        "ci_crosses_null": bool(lifecycle.get("ci_crosses_null", False)),
        "consecutive_null_crossings": int(lifecycle.get("consecutive_null_crossings", 0)),
        "pending_recheck": bool(lifecycle.get("pending_recheck", False)),
        "suppressed_by_data_gate": bool(lifecycle.get("suppressed_by_data_gate", True)),
        "previous_active_run_id": lifecycle.get("previous_active_run_id"),
        "lifecycle": _json(lifecycle),
        "is_active": bool(lifecycle.get("activate_run", True)),
    }])
    run_audit = pd.DataFrame([{
        **common,
        "run_type": "research_validation",
        "status": validation.get("status"),
        "data_readiness": validation.get("data_readiness"),
        "reason_codes": _json(validation.get("reasons") or []),
        "configuration": _json(validation.get("configuration") or {}),
        "input_evidence": _json(validation.get("input_evidence") or {}),
        "data_health_json": _json(data_health),
        "output_evidence_hash": validation.get("evidence_hash"),
        "active_signal_status": lifecycle.get("active_signal_status", "candidate"),
        "lifecycle": _json(lifecycle),
    }])
    return {
        "ads_crypto_data_readiness_report": readiness,
        "ads_crypto_provider_reconciliation": reconciliation_output,
        "ads_crypto_volatility_validation": validation_output,
        "ads_research_validation_run": run_audit,
    }


def _validation_pointer_path(ads_root: Path) -> Path:
    return ads_root / CRYPTO_VALIDATION_CURRENT


def _promote_validation_pointer(ads_root: Path, payload: dict[str, Any]) -> None:
    pointer_path = _validation_pointer_path(ads_root)
    incoming_time = pd.to_datetime(payload.get("completed_at"), errors="coerce", utc=True)
    if pd.isna(incoming_time):
        raise ValueError("Crypto validation pointer completion time is invalid")
    if pointer_path.exists():
        current = json.loads(pointer_path.read_text(encoding="utf-8"))
        current_time = pd.to_datetime(current.get("completed_at"), errors="coerce", utc=True)
        if pd.isna(current_time):
            raise ValueError("existing Crypto validation pointer completion time is invalid")
        if pd.Timestamp(current_time) > pd.Timestamp(incoming_time):
            return
    temp = ads_root / (
        f".{CRYPTO_VALIDATION_CURRENT}.{payload.get('generation_id') or payload.get('run_id')}.tmp"
    )
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temp, pointer_path)
    finally:
        temp.unlink(missing_ok=True)


def _recover_crypto_validation_transactions(ads_root: Path) -> None:
    receipt_root = ads_root / "_validation_receipts"
    for abandoned in ads_root.glob(".validation-*.tmp"):
        transaction_path = abandoned / "transaction.json"
        if not transaction_path.exists():
            shutil.rmtree(abandoned, ignore_errors=True)
            continue
        try:
            transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            shutil.rmtree(abandoned, ignore_errors=True)
            continue
        abandoned_receipt = receipt_root / f"{transaction.get('run_id')}.json"
        if abandoned_receipt.exists():
            receipt = json.loads(abandoned_receipt.read_text(encoding="utf-8"))
            pointer = receipt.get("current_pointer") or transaction.get("current_pointer")
            if receipt.get("activate_run") and isinstance(pointer, dict):
                _promote_validation_pointer(ads_root, pointer)
        else:
            for entry in transaction.get("tables", []):
                target = Path(entry["target"])
                backup = Path(entry["backup"])
                if backup.exists():
                    shutil.copy2(backup, target)
                elif not entry.get("had_original"):
                    target.unlink(missing_ok=True)
        shutil.rmtree(abandoned, ignore_errors=True)


def persist_crypto_validation_outputs(
    data_root: str | Path,
    outputs: dict[str, pd.DataFrame],
    *,
    dry_run: bool,
    _lock_handle: Any | None = None,
) -> dict[str, str]:
    layout = WarehouseLayout.from_data_root(data_root)
    if set(outputs) != CRYPTO_VALIDATION_TABLES:
        raise ValueError("crypto ADS transaction requires the complete four-table set")
    paths = {
        table: str(layout.table_path("ads", table))
        for table in outputs
    }
    if dry_run:
        return paths

    validation_run_ids = {
        str(frame.iloc[0]["run_id"])
        for frame in outputs.values()
        if not frame.empty and "run_id" in frame.columns
    }
    generation_ids = {
        str(frame.iloc[0]["generation_id"])
        for frame in outputs.values()
        if not frame.empty and "generation_id" in frame.columns
    }
    if len(validation_run_ids) != 1 or len(generation_ids) != 1:
        raise ValueError("crypto ADS transaction requires one shared run_id")
    validation_run_id = next(iter(validation_run_ids))
    generation_id = next(iter(generation_ids))
    ads_root = layout.layer_dir("ads")
    ads_root.mkdir(parents=True, exist_ok=True)
    lock_path = ads_root / ".crypto-validation.lock"
    receipt_root = ads_root / "_validation_receipts"
    receipt_path = receipt_root / f"{generation_id}.json"
    validation_frame = outputs.get("ads_crypto_volatility_validation", pd.DataFrame())
    activate_run = bool(
        not validation_frame.empty
        and "is_active" in validation_frame
        and validation_frame["is_active"].fillna(False).astype(bool).any()
    )
    completed_at = datetime.now(timezone.utc).isoformat()
    current_pointer = {
        "run_id": validation_run_id,
        "generation_id": generation_id,
        "completed_at": completed_at,
        "receipt_path": str(receipt_path),
        "tables": sorted(outputs),
        "watermark": (
            validation_frame.iloc[0].get("watermark")
            if not validation_frame.empty
            else None
        ),
        "data_readiness": (
            validation_frame.iloc[0].get("data_readiness")
            if not validation_frame.empty
            else None
        ),
        "active_signal_status": (
            validation_frame.iloc[0].get("active_signal_status")
            if not validation_frame.empty
            else None
        ),
    }

    lock_context = (
        lock_path.open("a+b")
        if _lock_handle is None
        else nullcontext(_lock_handle)
    )
    with lock_context as lock_handle:
        if _lock_handle is None:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            _recover_crypto_validation_transactions(ads_root)

            if receipt_path.exists():
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                if activate_run:
                    for table in outputs:
                        target = layout.table_path("ads", table)
                        if not target.exists():
                            raise ValueError(f"completed Crypto ADS table is missing: {table}")
                        existing = pd.read_parquet(target, columns=["generation_id"])
                        if not existing["generation_id"].astype(str).eq(generation_id).any():
                            raise ValueError(f"completed Crypto ADS run row is missing: {table}")
                    pointer = receipt.get("current_pointer") or current_pointer
                    _promote_validation_pointer(ads_root, pointer)
                return paths
            staging = ads_root / f".validation-{generation_id}.tmp"
            staging.mkdir(parents=True)
            transaction_entries: list[dict[str, Any]] = []
            staged_hashes: dict[str, str] = {}
            for table, frame in outputs.items():
                target = layout.table_path("ads", table)
                if target.exists():
                    existing = pd.read_parquet(target)
                    activates_run = bool(
                        table == "ads_crypto_volatility_validation"
                        and "is_active" in frame
                        and frame["is_active"].fillna(False).astype(bool).any()
                    )
                    if activates_run and "is_active" in existing:
                        existing["is_active"] = False
                    combined = pd.concat([existing, frame], ignore_index=True)
                else:
                    combined = frame.copy()
                key_columns = ["generation_id"]
                if table == "ads_crypto_provider_reconciliation":
                    key_columns.append("date")
                if table == "ads_crypto_volatility_validation":
                    key_columns.append("hypothesis_id")
                if table == "ads_research_validation_run":
                    key_columns.append("profile")
                combined = combined.drop_duplicates(subset=key_columns, keep="last")
                staged = staging / f"{table}.parquet"
                backup = staging / f"{table}.backup.parquet"
                combined.to_parquet(staged, index=False)
                if target.exists():
                    shutil.copy2(target, backup)
                transaction_entries.append({
                    "table": table,
                    "target": str(target),
                    "staged": str(staged),
                    "backup": str(backup),
                    "had_original": target.exists(),
                })
                staged_hashes[table] = hashlib.sha256(staged.read_bytes()).hexdigest()
            transaction_temp = staging / "transaction.json.tmp"
            transaction_temp.write_text(
                json.dumps(
                    {
                        "run_id": generation_id,
                        "validation_run_id": validation_run_id,
                        "tables": transaction_entries,
                        "activate_run": activate_run,
                        "current_pointer": current_pointer,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            os.replace(transaction_temp, staging / "transaction.json")
            pointer_path = _validation_pointer_path(ads_root)
            pointer_backup = staging / "current_pointer.backup.json"
            had_pointer = pointer_path.exists()
            if activate_run and had_pointer:
                shutil.copy2(pointer_path, pointer_backup)
            receipt_written = False
            try:
                for entry in transaction_entries:
                    os.replace(entry["staged"], entry["target"])
                receipt_root.mkdir(parents=True, exist_ok=True)
                receipt_temp = staging / "receipt.json"
                receipt_temp.write_text(
                    json.dumps(
                        {
                            "run_id": generation_id,
                            "validation_run_id": validation_run_id,
                            "status": "complete",
                            "completed_at": completed_at,
                            "table_hashes": staged_hashes,
                            "activate_run": activate_run,
                            "current_pointer": current_pointer,
                        },
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                os.replace(receipt_temp, receipt_path)
                receipt_written = True
                if activate_run:
                    _promote_validation_pointer(ads_root, current_pointer)
            except BaseException:
                for entry in transaction_entries:
                    target = Path(entry["target"])
                    backup = Path(entry["backup"])
                    if backup.exists():
                        shutil.copy2(backup, target)
                    elif not entry["had_original"]:
                        target.unlink(missing_ok=True)
                if receipt_written:
                    receipt_path.unlink(missing_ok=True)
                if activate_run:
                    if pointer_backup.exists():
                        shutil.copy2(pointer_backup, pointer_path)
                    elif not had_pointer:
                        pointer_path.unlink(missing_ok=True)
                raise
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        finally:
            if _lock_handle is None:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    return paths


def _commit_crypto_validation_outputs(
    data_root: str | Path,
    *,
    data_assurance: dict[str, Any],
    validation: dict[str, Any],
    reconciliation: pd.DataFrame,
    dry_run: bool,
    enforce_data_lineage: bool = False,
) -> tuple[dict[str, Any], dict[str, pd.DataFrame], dict[str, str]]:
    if dry_run:
        store = BtcRunStore(data_root)
        lineage_context = store.shared_lock() if enforce_data_lineage else nullcontext()
        with lineage_context:
            activation_allowed, activation_reason = (
                _data_lineage_activation_check(data_root, data_assurance, _lock=False)
                if enforce_data_lineage
                else (True, "LINEAGE_CHECK_NOT_REQUESTED")
            )
            enriched = _apply_signal_lifecycle(
                data_root,
                validation,
                activation_allowed=activation_allowed,
                activation_reason=activation_reason,
            )
            outputs = build_crypto_validation_outputs(
                data_assurance=data_assurance,
                validation=enriched,
                reconciliation=reconciliation,
            )
            paths = persist_crypto_validation_outputs(data_root, outputs, dry_run=True)
        return enriched, outputs, paths

    layout = WarehouseLayout.from_data_root(data_root)
    ads_root = layout.layer_dir("ads")
    ads_root.mkdir(parents=True, exist_ok=True)
    lock_path = ads_root / ".crypto-validation.lock"
    with lock_path.open("a+b") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            _recover_crypto_validation_transactions(ads_root)
            store = BtcRunStore(data_root)
            lineage_context = store.shared_lock() if enforce_data_lineage else nullcontext()
            with lineage_context:
                activation_allowed, activation_reason = (
                    _data_lineage_activation_check(data_root, data_assurance, _lock=False)
                    if enforce_data_lineage
                    else (True, "LINEAGE_CHECK_NOT_REQUESTED")
                )
                enriched = _apply_signal_lifecycle(
                    data_root,
                    validation,
                    activation_allowed=activation_allowed,
                    activation_reason=activation_reason,
                )
                outputs = build_crypto_validation_outputs(
                    data_assurance=data_assurance,
                    validation=enriched,
                    reconciliation=reconciliation,
                )
                paths = persist_crypto_validation_outputs(
                    data_root,
                    outputs,
                    dry_run=False,
                    _lock_handle=lock_handle,
                )
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    return enriched, outputs, paths


def read_crypto_validation_outputs(data_root: str | Path) -> dict[str, Any]:
    """Read one cross-table ADS generation selected by the atomic pointer."""

    layout = WarehouseLayout.from_data_root(data_root)
    ads_root = layout.layer_dir("ads")
    pointer_path = _validation_pointer_path(ads_root)
    lock_path = ads_root / ".crypto-validation.lock"
    lock_context = lock_path.open("rb") if lock_path.exists() else nullcontext(None)
    with lock_context as lock_handle:
        if lock_handle is not None:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_SH)
        try:
            if not pointer_path.exists():
                raise FileNotFoundError("Crypto validation current pointer is missing")
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            run_id = str(pointer.get("run_id") or "")
            generation_id = str(pointer.get("generation_id") or "")
            tables = list(pointer.get("tables") or [])
            if not run_id or not generation_id or set(tables) != CRYPTO_VALIDATION_TABLES:
                raise ValueError("Crypto validation current pointer is invalid")
            receipt_path = Path(str(pointer.get("receipt_path") or ""))
            if not receipt_path.is_file():
                raise ValueError("Crypto validation completion receipt is missing")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (
                receipt.get("status") != "complete"
                or str(receipt.get("run_id") or "") != generation_id
                or str(receipt.get("validation_run_id") or "") != run_id
            ):
                raise ValueError("Crypto validation completion receipt is invalid")
            frames: dict[str, pd.DataFrame] = {}
            for table in tables:
                path = layout.table_path("ads", str(table))
                frame = pd.read_parquet(path)
                if "run_id" not in frame.columns or "generation_id" not in frame.columns:
                    raise ValueError(f"Crypto ADS table has no run/generation id: {table}")
                selected = frame.loc[
                    frame["generation_id"].astype(str) == generation_id
                ].reset_index(drop=True)
                if selected.empty:
                    raise ValueError(f"Crypto ADS current run is missing from {table}")
                if not selected["run_id"].astype(str).eq(run_id).all():
                    raise ValueError(f"Crypto ADS validation run mismatch in {table}")
                if table == "ads_crypto_volatility_validation" and "is_active" in selected:
                    selected["is_active"] = True
                frames[str(table)] = selected
            data_run_ids: set[str] = set()
            for table, frame in frames.items():
                if "data_run_id" not in frame.columns:
                    raise ValueError(f"Crypto ADS table has no data_run_id: {table}")
                values = set(frame["data_run_id"].fillna("").astype(str))
                if len(values) != 1:
                    raise ValueError(f"Crypto ADS table mixes data runs: {table}")
                data_run_ids.update(values)
            if len(data_run_ids) != 1:
                raise ValueError("Crypto ADS current generation mixes data lineage")
            data_run_id = next(iter(data_run_ids))
            validation_frame = frames["ads_crypto_volatility_validation"]
            readiness_frame = frames["ads_crypto_data_readiness_report"]
            pointer_readiness = str(pointer.get("data_readiness") or "invalid")
            if not validation_frame["data_readiness"].astype(str).eq(pointer_readiness).all():
                raise ValueError("Crypto ADS validation readiness disagrees with its pointer")
            if not readiness_frame["data_readiness"].astype(str).eq(pointer_readiness).all():
                raise ValueError("Crypto ADS data readiness disagrees with its pointer")
            if pointer_readiness == "ready":
                store = BtcRunStore(data_root)
                with store.shared_lock():
                    current = store.current()
                    if current is None or str(current.get("run_id") or "") != data_run_id:
                        raise ValueError("Crypto ADS data run is no longer the current BTC run")
            elif not validation_frame["suppressed_by_data_gate"].fillna(False).astype(bool).all():
                raise ValueError("non-ready Crypto ADS generation is not suppression evidence")
            return {"current": pointer, "tables": frames}
        finally:
            if lock_handle is not None:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _assurance_order_key(data_assurance: dict[str, Any]) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    manifest = data_assurance.get("manifest") or {}
    acquisition = data_assurance.get("acquisition") or manifest.get("acquisition_evidence") or {}
    primary = pd.to_datetime(
        acquisition.get("as_of") or data_assurance.get("observed_at"),
        errors="coerce",
        utc=True,
    )
    secondary = pd.to_datetime(
        manifest.get("created_at") or data_assurance.get("observed_at"),
        errors="coerce",
        utc=True,
    )
    if pd.isna(primary):
        return None
    if pd.isna(secondary):
        secondary = primary
    return pd.Timestamp(primary), pd.Timestamp(secondary)


def _data_lineage_activation_check(
    data_root: str | Path,
    data_assurance: dict[str, Any],
    *,
    _lock: bool = True,
) -> tuple[bool, str]:
    store = BtcRunStore(data_root)
    if _lock:
        with store.shared_lock():
            return _data_lineage_activation_check(
                data_root,
                data_assurance,
                _lock=False,
            )
    else:
        try:
            current = store.current()
        except ValueError:
            if str(data_assurance.get("data_readiness") or "invalid") != "ready":
                return True, "CURRENT_POINTER_INVALID_SUPPRESSION"
            return False, "CURRENT_POINTER_INVALID"
        incoming_run_id = str(data_assurance.get("run_id") or "")
        if current is None:
            if str(data_assurance.get("data_readiness") or "invalid") != "ready":
                return True, "NO_CURRENT_SUPPRESSION"
            return False, "DATA_RUN_NOT_CURRENT"
        current_run_id = str(current.get("run_id") or "")
        if incoming_run_id and incoming_run_id == current_run_id:
            return True, "DATA_RUN_CURRENT"

        is_unpublished_attempt = (
            data_assurance.get("mode") == "sync"
            and data_assurance.get("published") is False
        )
        if not is_unpublished_attempt:
            return False, "DATA_RUN_SUPERSEDED"
        manifest_path = Path(str(current.get("manifest_path") or ""))
        try:
            current_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return True, "CURRENT_MANIFEST_INVALID_SUPPRESSION"
        incoming_key = _assurance_order_key(data_assurance)
        current_key = _assurance_order_key({"manifest": current_manifest})
        if incoming_key is None or current_key is None:
            return False, "ACQUISITION_ORDER_UNKNOWN"
        if incoming_key < current_key:
            return False, "ACQUISITION_ATTEMPT_SUPERSEDED"
        return True, "LATEST_ACQUISITION_FAILED_SUPPRESSION"
