from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
from io import BytesIO
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from trade_py.data.market.cross_asset.assurance import (
    BtcAssuranceConfig,
    BtcAssuranceResult,
    _frame_hash,
    _json_hash,
    _watermark,
    assure_btc,
    summarize_btc_health,
)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def btc_operational_freshness(
    manifest: dict[str, Any],
    *,
    as_of: Any | None = None,
) -> dict[str, Any]:
    timestamp = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp.now(tz="UTC")
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    expected = timestamp.normalize() - pd.Timedelta(days=1)
    watermark = pd.to_datetime(manifest.get("watermark"), errors="coerce", utc=True)
    maximum = int((manifest.get("config") or {}).get("maximum_staleness_days", 1))
    staleness = (
        max(int((expected - pd.Timestamp(watermark).normalize()).days), 0)
        if not pd.isna(watermark)
        else None
    )
    return {
        "as_of": timestamp.isoformat(),
        "expected_latest_open": expected.date().isoformat(),
        "watermark": pd.Timestamp(watermark).date().isoformat() if not pd.isna(watermark) else None,
        "staleness_days": staleness,
        "maximum_staleness_days": maximum,
        "fresh": staleness is not None and staleness <= maximum,
    }


def _pilot_item(
    name: str,
    status: str,
    detail: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "evidence": evidence or {},
    }


def _count_qualified_days(manifest: dict[str, Any]) -> int:
    evidence = manifest.get("acquisition_evidence") or {}
    dates = {
        str(attempt.get("date"))
        for attempt in (evidence.get("daily_attempts") or [])
        if attempt.get("qualified") and attempt.get("date")
    }
    return len(dates)


def _has_provider_revision_overlap(manifest: dict[str, Any]) -> bool:
    revision = (manifest.get("gates") or [])
    d4 = next((gate for gate in revision if gate.get("gate") == "D4"), {})
    metrics = d4.get("metrics") or {}
    required = int(metrics.get("minimum_revision_overlap_days") or 0)
    observed = int(metrics.get("revision_rows") or 0)
    return required > 0 and observed >= required


def btc_live_pilot_checklist(data_root: str | Path, status_payload: dict[str, Any]) -> dict[str, Any]:
    """Summarize live-pilot evidence without performing network or data mutations."""

    store = BtcRunStore(data_root)
    current = status_payload.get("current") or {}
    manifest = status_payload.get("manifest") or {}
    readiness = str(status_payload.get("data_readiness") or "invalid")
    acquisition = manifest.get("acquisition_evidence") or {}
    providers = acquisition.get("providers") or {}
    qualified_days = _count_qualified_days(manifest)
    required_days = int((manifest.get("config") or {}).get("minimum_successful_acquisition_days") or 29)
    has_revision_overlap = _has_provider_revision_overlap(manifest)
    publish_audits = list((store.cross_asset_root / "audit" / "publish").glob("*.json"))
    rollback_audits = list((store.cross_asset_root / "audit" / "rollback").glob("*.json"))
    ads_pointer = store.data_root / "warehouse" / "ads" / "_crypto_validation_current.json"
    latest_provider_status = {
        name: {
            "status": report.get("status"),
            "rows": report.get("rows"),
            "error_kind": report.get("error_kind"),
            "raw_payload_count": len(report.get("raw_payload_hashes") or []),
        }
        for name, report in sorted(providers.items())
    }
    okx_ready = (providers.get("okx") or {}).get("status") == "succeeded"
    binance_ready = (providers.get("binance") or {}).get("status") == "succeeded"

    items = [
        _pilot_item(
            "free_api_mode",
            "pass",
            "Using free public APIs (OKX primary + Binance shadow), no API key required",
            {"primary": "okx", "shadow": "binance"},
        ),
        _pilot_item(
            "provider_contracts",
            "pass" if okx_ready and binance_ready else "pending",
            "latest OKX and Binance captures succeeded" if okx_ready and binance_ready else "latest provider success is not yet proven",
            latest_provider_status,
        ),
        _pilot_item(
            "published_current",
            "pass" if current and readiness == "ready" else ("fail" if readiness == "invalid" else "pending"),
            "BTC current pointer is ready" if current and readiness == "ready" else "BTC current pointer is not ready",
            {"run_id": current.get("run_id"), "readiness": readiness},
        ),
        _pilot_item(
            "ads_current_pointer",
            "pass" if ads_pointer.exists() else "pending",
            "crypto ADS current pointer exists" if ads_pointer.exists() else "crypto ADS current pointer is not present",
            {"path": str(ads_pointer)},
        ),
        _pilot_item(
            "qualified_acquisition_days",
            "pass" if qualified_days >= required_days else "pending",
            f"{qualified_days}/{required_days} qualified acquisition days observed",
            {"qualified_days": qualified_days, "required_days": required_days},
        ),
        _pilot_item(
            "revision_overlap",
            "pass" if has_revision_overlap else "pending",
            "provider-native revision overlap requirement is satisfied" if has_revision_overlap else "provider-native revision overlap is not yet proven",
            {"minimum_revision_overlap_days": (manifest.get("config") or {}).get("minimum_revision_overlap_days")},
        ),
        _pilot_item(
            "first_pointer_switch",
            "pass" if publish_audits else "pending",
            "publish audit exists" if publish_audits else "no publish audit has been recorded",
            {"audit_count": len(publish_audits)},
        ),
        _pilot_item(
            "rollback_rehearsal",
            "pass" if rollback_audits else "pending",
            "rollback audit exists" if rollback_audits else "no rollback rehearsal audit has been recorded",
            {"audit_count": len(rollback_audits)},
        ),
    ]
    return {
        "status": (
            "pass"
            if all(item["status"] == "pass" for item in items)
            else ("fail" if any(item["status"] == "fail" for item in items) else "pending")
        ),
        "items": items,
    }


class BtcRunStore:
    def __init__(self, data_root: str | Path) -> None:
        self.data_root = Path(data_root)
        self.cross_asset_root = self.data_root / "market" / "cross_asset"
        self.runs_root = self.cross_asset_root / "runs" / "btc"
        self.current_path = self.cross_asset_root / "btc_current.json"
        self.compatibility_path = self.cross_asset_root / "btc.parquet"

    @contextmanager
    def _exclusive_lock(self):
        self.cross_asset_root.mkdir(parents=True, exist_ok=True)
        lock_path = self.cross_asset_root / ".btc-assurance.lock"
        with lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def shared_lock(self):
        lock_path = self.cross_asset_root / ".btc-assurance.lock"
        if not lock_path.exists():
            yield
            return
        with lock_path.open("rb") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def run_dir(self, run_id: str) -> Path:
        return self.runs_root / run_id

    def _assert_predecessor_unchanged(self, result: BtcAssuranceResult) -> None:
        predecessor = (result.manifest.get("acquisition_evidence") or {}).get("predecessor") or {}
        expected_status = str(predecessor.get("status") or "missing")
        current = self.current()
        if expected_status == "missing":
            if current is not None or self.compatibility_path.exists():
                raise RuntimeError("BTC publish predecessor changed; rerun assurance")
            return
        if expected_status != "readable":
            raise RuntimeError(f"BTC publish predecessor is not safe: {expected_status}")
        expected_hash = str(predecessor.get("sha256") or "")
        if not self.compatibility_path.exists() or file_sha256(self.compatibility_path) != expected_hash:
            raise RuntimeError("BTC publish predecessor hash changed; rerun assurance")
        expected_run_id = str(predecessor.get("run_id") or "")
        if expected_run_id and (current is None or str(current.get("run_id")) != expected_run_id):
            raise RuntimeError("BTC publish current run changed; rerun assurance")

    def _was_published(self, run_id: str, current: dict[str, Any] | None) -> bool:
        if current and run_id in {
            str(current.get("run_id") or ""),
            str(current.get("previous_run_id") or ""),
        }:
            return True
        audit_root = self.cross_asset_root / "audit" / "publish"
        for path in audit_root.glob("*.json") if audit_root.exists() else ():
            try:
                event = json.loads(path.read_text(encoding="utf-8"))
                if str(event.get("to_run_id") or "") == run_id:
                    return True
            except (OSError, json.JSONDecodeError):
                continue
        return False

    def _snapshot_compatibility_predecessor(self) -> tuple[Path | None, str | None]:
        if not self.compatibility_path.exists():
            return None, None
        predecessor_hash = file_sha256(self.compatibility_path)
        backup_root = self.runs_root / "_predecessors"
        backup_root.mkdir(parents=True, exist_ok=True)
        backup_path = backup_root / f"{predecessor_hash}.parquet"
        if backup_path.exists() and file_sha256(backup_path) == predecessor_hash:
            return backup_path, predecessor_hash
        temp = backup_root / f".{predecessor_hash}.parquet.tmp"
        try:
            shutil.copy2(self.compatibility_path, temp)
            if file_sha256(temp) != predecessor_hash:
                raise ValueError("BTC predecessor snapshot copy hash mismatch")
            os.replace(temp, backup_path)
        finally:
            temp.unlink(missing_ok=True)
        return backup_path, predecessor_hash

    def current(self) -> dict[str, Any] | None:
        if not self.current_path.exists():
            return None
        try:
            value = json.loads(self.current_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid BTC current pointer: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("invalid BTC current pointer: expected object")
        run_id = str(value.get("run_id") or "")
        canonical_hash = str(value.get("canonical_sha256") or "")
        if not run_id or len(canonical_hash) != 64:
            raise ValueError("invalid BTC current pointer: missing run_id or canonical hash")
        return value

    @staticmethod
    def _artifact_path(run_dir: Path, name: str) -> Path:
        return run_dir / (f"{name}.json" if name.startswith("raw/") else f"{name}.parquet")

    def _verify_staged_artifacts(
        self,
        run_dir: Path,
        manifest: dict[str, Any],
        *,
        require_raw: bool = False,
    ) -> list[str]:
        hashes = manifest.get("artifact_hashes") or {}
        required = {"primary", "shadow", "canonical", "reconciliation", "revisions"}
        errors = [f"{name}:missing_hash" for name in sorted(required - set(hashes))]
        snapshots: dict[str, bytes] = {}
        for name, expected in hashes.items():
            path = self._artifact_path(run_dir, str(name))
            if not path.exists():
                errors.append(f"{name}:sha256")
                continue
            snapshot = path.read_bytes()
            snapshots[str(name)] = snapshot
            if hashlib.sha256(snapshot).hexdigest() != str(expected):
                errors.append(f"{name}:sha256")
        canonical_path = run_dir / "canonical.parquet"
        if canonical_path.exists():
            try:
                canonical = pd.read_parquet(BytesIO(snapshots.get("canonical", b"")))
                if _frame_hash(canonical) != str(manifest.get("canonical_hash") or ""):
                    errors.append("canonical:logical_hash")
            except Exception:
                errors.append("canonical:read")
        if require_raw:
            raw_providers = {
                str(name).split("/", 2)[1]
                for name in hashes
                if str(name).startswith("raw/") and len(str(name).split("/", 2)) == 3
            }
            for provider in ("okx", "binance"):
                if provider not in raw_providers:
                    errors.append(f"raw/{provider}:missing")
        return sorted(set(errors))

    def _verify_staged_result(
        self,
        run_dir: Path,
        manifest: dict[str, Any],
        result: BtcAssuranceResult,
        *,
        require_publishable: bool,
    ) -> list[str]:
        errors: list[str] = []
        for key in (
            "run_id",
            "data_readiness",
            "config_hash",
            "code_revision",
            "schema_hash",
            "primary_hash",
            "shadow_hash",
            "canonical_hash",
        ):
            expected = result.run_id if key == "run_id" else result.manifest.get(key)
            if manifest.get(key) != expected:
                errors.append(f"manifest:{key}")
        if _json_hash(manifest.get("gates") or []) != _json_hash(result.manifest.get("gates") or []):
            errors.append("manifest:gates")
        gate_status = {
            str(gate.get("gate") or ""): str(gate.get("status") or "")
            for gate in (manifest.get("gates") or [])
        }
        if require_publishable and (
            manifest.get("data_readiness") != "ready"
            or any(gate_status.get(gate) != "pass" for gate in ("D0", "D1", "D2", "D3", "D4"))
        ):
            errors.append("manifest:not_publishable")

        frames = {
            "primary": result.primary,
            "shadow": result.shadow,
            "canonical": result.canonical,
            "reconciliation": result.reconciliation,
            "revisions": result.revisions,
        }
        for name, expected_frame in frames.items():
            try:
                actual = pd.read_parquet(run_dir / f"{name}.parquet")
                if _frame_hash(actual) != _frame_hash(expected_frame):
                    errors.append(f"{name}:logical_hash")
            except Exception:
                errors.append(f"{name}:read")

        expected_raw = {
            f"raw/{provider}/{index:04d}": hashlib.sha256(payload).hexdigest()
            for provider, payloads in sorted(result.raw_payloads.items())
            for index, payload in enumerate(payloads)
        }
        actual_raw = {
            str(name): str(value)
            for name, value in (manifest.get("artifact_hashes") or {}).items()
            if str(name).startswith("raw/")
        }
        if actual_raw != expected_raw:
            errors.append("raw:result_mismatch")
        return sorted(set(errors))

    def stage(
        self,
        result: BtcAssuranceResult,
        *,
        dry_run: bool = False,
        _lock: bool = True,
    ) -> dict[str, Any]:
        if dry_run:
            return result.summary()
        if _lock:
            with self._exclusive_lock():
                return self.stage(result, dry_run=False, _lock=False)
        target = self.run_dir(result.run_id)
        manifest_path = target / "manifest.json"
        if target.exists():
            if not manifest_path.exists():
                raise FileExistsError(f"immutable BTC run is incomplete: {target}")
            existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                existing_manifest.get("run_id") != result.run_id
                or existing_manifest.get("canonical_hash") != result.manifest.get("canonical_hash")
            ):
                raise ValueError(f"immutable BTC run hash mismatch: {result.run_id}")
            integrity_errors = self._verify_staged_artifacts(target, existing_manifest)
            integrity_errors.extend(
                self._verify_staged_result(
                    target,
                    existing_manifest,
                    result,
                    require_publishable=False,
                )
            )
            if integrity_errors:
                raise ValueError(
                    f"immutable BTC run artifacts are invalid: {integrity_errors}"
                )
            return {
                **result.summary(),
                "run_dir": str(target),
                "artifact_hashes": dict(existing_manifest.get("artifact_hashes") or {}),
                "already_staged": True,
            }

        self.runs_root.mkdir(parents=True, exist_ok=True)
        staging = self.runs_root / f".{result.run_id}.stage.tmp"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        artifacts = {
            "primary": (result.primary, staging / "primary.parquet"),
            "shadow": (result.shadow, staging / "shadow.parquet"),
            "canonical": (result.canonical, staging / "canonical.parquet"),
            "reconciliation": (result.reconciliation, staging / "reconciliation.parquet"),
            "revisions": (result.revisions, staging / "revisions.parquet"),
        }
        hashes: dict[str, str] = {}
        try:
            for name, (frame, path) in artifacts.items():
                frame.to_parquet(path, index=False)
                hashes[name] = file_sha256(path)
            for provider, payloads in sorted(result.raw_payloads.items()):
                raw_root = staging / "raw" / provider
                raw_root.mkdir(parents=True, exist_ok=True)
                for index, payload in enumerate(payloads):
                    raw_path = raw_root / f"{index:04d}.json"
                    raw_path.write_bytes(payload)
                    hashes[f"raw/{provider}/{index:04d}"] = file_sha256(raw_path)
            manifest = dict(result.manifest)
            manifest["artifact_hashes"] = hashes
            manifest["health"] = summarize_btc_health(
                run_id=result.run_id,
                data_readiness=result.data_readiness,
                publishable=result.publishable,
                gates=[gate.to_dict() for gate in result.gates],
                canonical=result.canonical,
                reconciliation=result.reconciliation,
                revisions=result.revisions,
                acquisition_evidence=manifest.get("acquisition_evidence") or {},
                manifest=manifest,
            )
            (staging / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(staging, target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return {**result.summary(), "run_dir": str(target), "artifact_hashes": hashes}

    def publish(
        self,
        result: BtcAssuranceResult,
        *,
        dry_run: bool = False,
        _lock: bool = True,
    ) -> dict[str, Any]:
        if not result.publishable:
            raise ValueError(f"BTC run is not publishable: {result.data_readiness}")
        if dry_run:
            return self.stage(result, dry_run=True)
        if _lock:
            with self._exclusive_lock():
                return self.publish(result, dry_run=False, _lock=False)
        self._assert_predecessor_unchanged(result)
        summary = self.stage(result, dry_run=False, _lock=False)
        run_dir = self.run_dir(result.run_id)
        source = run_dir / "canonical.parquet"
        if not source.exists():
            raise FileNotFoundError(source)
        staged_manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        integrity_errors = self._verify_staged_artifacts(
            run_dir,
            staged_manifest,
            require_raw=True,
        )
        integrity_errors.extend(
            self._verify_staged_result(
                run_dir,
                staged_manifest,
                result,
                require_publishable=True,
            )
        )
        if integrity_errors:
            raise ValueError(f"publish staged artifacts are invalid: {integrity_errors}")
        self.cross_asset_root.mkdir(parents=True, exist_ok=True)
        previous = self.current()
        backup_path, previous_hash = self._snapshot_compatibility_predecessor()

        temp_compat = self.cross_asset_root / f".btc.{result.run_id}.tmp"
        temp_current = self.cross_asset_root / f".btc_current.{result.run_id}.tmp"
        current_restore = self.cross_asset_root / f".btc_current.restore.{result.run_id}.tmp"
        had_current = self.current_path.exists()
        if had_current:
            shutil.copy2(self.current_path, current_restore)
        payload = {
            "run_id": result.run_id,
            "run_dir": str(run_dir),
            "manifest_path": str(run_dir / "manifest.json"),
            "canonical_path": str(self.compatibility_path),
            "canonical_sha256": file_sha256(source),
            "previous_run_id": previous.get("run_id") if previous else None,
            "predecessor_path": str(backup_path) if backup_path else None,
            "predecessor_sha256": previous_hash,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        publish_event_id = _json_hash(payload)[:24]
        publish_audit_root = self.cross_asset_root / "audit" / "publish"
        publish_audit_root.mkdir(parents=True, exist_ok=True)
        publish_audit_path = publish_audit_root / (
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')}-{publish_event_id}.json"
        )
        publish_audit_temp = self.cross_asset_root / f".btc_publish_audit.{publish_event_id}.tmp"
        payload["publish_audit_path"] = str(publish_audit_path)
        try:
            publish_audit_temp.write_text(
                json.dumps(
                    {
                        "event_id": publish_event_id,
                        "event_type": "btc_canonical_publish",
                        "from_run_id": payload["previous_run_id"],
                        "to_run_id": result.run_id,
                        "canonical_sha256": payload["canonical_sha256"],
                        "occurred_at": payload["published_at"],
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            shutil.copy2(source, temp_compat)
            temp_current.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(temp_compat, self.compatibility_path)
            os.replace(temp_current, self.current_path)
            os.replace(publish_audit_temp, publish_audit_path)
        except Exception:
            temp_compat.unlink(missing_ok=True)
            temp_current.unlink(missing_ok=True)
            publish_audit_temp.unlink(missing_ok=True)
            if backup_path and backup_path.exists():
                restore = self.cross_asset_root / ".btc.restore.tmp"
                shutil.copy2(backup_path, restore)
                os.replace(restore, self.compatibility_path)
            else:
                self.compatibility_path.unlink(missing_ok=True)
            if had_current and current_restore.exists():
                os.replace(current_restore, self.current_path)
            elif not had_current:
                self.current_path.unlink(missing_ok=True)
            raise
        finally:
            current_restore.unlink(missing_ok=True)
        return {**summary, "current": payload}

    def rollback_predecessor(self, *, _lock: bool = True) -> dict[str, Any]:
        """Restore the current pointer's predecessor, including a legacy seed.

        A legacy predecessor has no provider-native manifest and therefore
        returns to the explicit lineage-missing state instead of pretending the
        restored bytes passed D0-D4.
        """

        if _lock:
            with self._exclusive_lock():
                return self.rollback_predecessor(_lock=False)
        current = self.current()
        if current is None:
            raise ValueError("BTC current pointer has no predecessor")
        previous_run_id = str(current.get("previous_run_id") or "")
        if previous_run_id:
            return self.rollback(previous_run_id, _lock=False)
        predecessor_path = Path(str(current.get("predecessor_path") or ""))
        expected = str(current.get("predecessor_sha256") or "")
        if (
            not predecessor_path.is_file()
            or len(expected) != 64
            or file_sha256(predecessor_path) != expected
        ):
            raise ValueError("legacy BTC predecessor snapshot hash mismatch")

        event_time = datetime.now(timezone.utc)
        event_id = _json_hash({
            "from": current.get("run_id"),
            "to": "legacy",
            "at": event_time.isoformat(),
            "hash": expected,
        })[:24]
        audit_root = self.cross_asset_root / "audit" / "rollback"
        audit_root.mkdir(parents=True, exist_ok=True)
        audit_path = audit_root / f"{event_time.strftime('%Y%m%dT%H%M%S.%fZ')}-{event_id}.json"
        temp_compat = self.cross_asset_root / f".btc.rollback.legacy.{event_id}.tmp"
        restore_compat = self.cross_asset_root / f".btc.rollback.restore.{event_id}.tmp"
        restore_current = self.cross_asset_root / f".btc_current.rollback.restore.{event_id}.tmp"
        audit_temp = self.cross_asset_root / f".btc_rollback_audit.{event_id}.tmp"
        shutil.copy2(self.compatibility_path, restore_compat)
        shutil.copy2(self.current_path, restore_current)
        shutil.copy2(predecessor_path, temp_compat)
        audit = {
            "event_id": event_id,
            "event_type": "btc_legacy_predecessor_rollback",
            "from_run_id": current.get("run_id"),
            "to_run_id": None,
            "canonical_sha256": expected,
            "data_readiness": "insufficient_data",
            "reason_code": "LEGACY_LINEAGE_MISSING",
            "occurred_at": event_time.isoformat(),
        }
        try:
            audit_temp.write_text(
                json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temp_compat, self.compatibility_path)
            self.current_path.unlink()
            os.replace(audit_temp, audit_path)
        except Exception:
            temp_compat.unlink(missing_ok=True)
            audit_temp.unlink(missing_ok=True)
            if restore_compat.exists():
                os.replace(restore_compat, self.compatibility_path)
            if restore_current.exists():
                os.replace(restore_current, self.current_path)
            raise
        finally:
            restore_compat.unlink(missing_ok=True)
            restore_current.unlink(missing_ok=True)
        return {
            **audit,
            "rollback": True,
            "rollback_audit_path": str(audit_path),
            "canonical_path": str(self.compatibility_path),
        }

    def rollback(self, run_id: str, *, _lock: bool = True) -> dict[str, Any]:
        if _lock:
            with self._exclusive_lock():
                return self.rollback(run_id, _lock=False)
        current = self.current()
        if current is not None and str(current.get("run_id") or "") == run_id:
            raise ValueError("rollback target is already the current BTC run")
        run_dir = self.run_dir(run_id)
        canonical = run_dir / "canonical.parquet"
        manifest_path = run_dir / "manifest.json"
        if not canonical.exists() or not manifest_path.exists():
            raise FileNotFoundError(f"run not found or incomplete: {run_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        original_gates = {
            str(gate.get("gate") or ""): str(gate.get("status") or "")
            for gate in (manifest.get("gates") or [])
        }
        if (
            manifest.get("data_readiness") != "ready"
            or any(original_gates.get(gate) != "pass" for gate in ("D0", "D1", "D2", "D3", "D4"))
        ):
            raise ValueError("rollback target was not an originally ready run")
        if not self._was_published(run_id, current):
            raise ValueError("rollback target has no publication evidence")
        expected = str((manifest.get("artifact_hashes") or {}).get("canonical") or "")
        actual = file_sha256(canonical)
        if not expected or expected != actual:
            raise ValueError("rollback canonical hash mismatch")
        for name, artifact_hash in (manifest.get("artifact_hashes") or {}).items():
            if name == "canonical":
                continue
            artifact_path = (
                run_dir / f"{name}.json"
                if str(name).startswith("raw/")
                else run_dir / f"{name}.parquet"
            )
            if not artifact_path.exists() or file_sha256(artifact_path) != str(artifact_hash):
                raise ValueError(f"rollback artifact hash mismatch: {name}")
        primary_path = run_dir / "primary.parquet"
        shadow_path = run_dir / "shadow.parquet"
        if not primary_path.exists() or not shadow_path.exists():
            raise FileNotFoundError("rollback provider evidence is incomplete")
        config_payload = manifest.get("config") or {}
        config = BtcAssuranceConfig(**config_payload)
        predecessor_frame: pd.DataFrame | None = None
        revision = (manifest.get("acquisition_evidence") or {}).get("revision_predecessor") or {}
        revision_kind = str(revision.get("kind") or "missing")
        revision_hash = str(revision.get("artifact_sha256") or "")
        if revision_kind == "staged_run":
            predecessor_path = self.run_dir(str(revision.get("run_id") or "")) / "canonical.parquet"
        elif revision_kind == "published_or_legacy":
            predecessor_path = self.runs_root / "_predecessors" / f"{revision_hash}.parquet"
        elif revision_kind == "missing":
            predecessor_path = None
        else:
            raise ValueError("rollback revision predecessor kind is invalid")
        if predecessor_path is not None:
            if not predecessor_path.exists() or file_sha256(predecessor_path) != revision_hash:
                raise ValueError("rollback predecessor snapshot hash mismatch")
            predecessor_frame = pd.read_parquet(predecessor_path)
        replay = assure_btc(
            pd.read_parquet(primary_path),
            pd.read_parquet(shadow_path),
            existing=predecessor_frame,
            config=config,
            acquisition_evidence=manifest.get("acquisition_evidence") or {},
        )
        replay_gates = {gate.gate: gate.status for gate in replay.gates}
        if any(replay_gates.get(gate) != "pass" for gate in ("D0", "D1", "D2", "D3", "D4")):
            raise ValueError(f"rollback assurance replay failed: {replay_gates}")
        if replay.manifest.get("canonical_hash") != manifest.get("canonical_hash"):
            raise ValueError("rollback deterministic replay hash mismatch")
        if replay.manifest.get("code_revision") != manifest.get("code_revision"):
            raise ValueError("rollback implementation revision mismatch")
        if replay.manifest.get("schema_hash") != manifest.get("schema_hash"):
            raise ValueError("rollback schema revision mismatch")
        previous = current
        temp_compat = self.cross_asset_root / f".btc.rollback.{run_id}.tmp"
        temp_current = self.cross_asset_root / f".btc_current.rollback.{run_id}.tmp"
        restore_backup = self.cross_asset_root / ".btc.rollback.restore.tmp"
        current_restore = self.cross_asset_root / ".btc_current.rollback.restore.tmp"
        had_compatibility = self.compatibility_path.exists()
        had_current = self.current_path.exists()
        operational_predecessor_path, operational_predecessor_hash = (
            self._snapshot_compatibility_predecessor()
        )
        if had_compatibility:
            shutil.copy2(self.compatibility_path, restore_backup)
        if had_current:
            shutil.copy2(self.current_path, current_restore)
        shutil.copy2(canonical, temp_compat)
        event_time = datetime.now(timezone.utc)
        event_id = _json_hash({
            "from": previous.get("run_id") if previous else None,
            "to": run_id,
            "at": event_time.isoformat(),
            "hash": actual,
        })[:24]
        audit_root = self.cross_asset_root / "audit" / "rollback"
        audit_root.mkdir(parents=True, exist_ok=True)
        audit_path = audit_root / f"{event_time.strftime('%Y%m%dT%H%M%S.%fZ')}-{event_id}.json"
        audit_temp = self.cross_asset_root / f".btc_rollback_audit.{event_id}.tmp"
        payload = {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "manifest_path": str(manifest_path),
            "canonical_path": str(self.compatibility_path),
            "canonical_sha256": actual,
            "previous_run_id": previous.get("run_id") if previous else None,
            "predecessor_path": (
                str(operational_predecessor_path)
                if operational_predecessor_path is not None
                else None
            ),
            "predecessor_sha256": operational_predecessor_hash,
            "rollback": True,
            "published_at": event_time.isoformat(),
            "rollback_audit_path": str(audit_path),
        }
        try:
            temp_current.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            audit_temp.write_text(
                json.dumps(
                    {
                        "event_id": event_id,
                        "event_type": "btc_canonical_rollback",
                        "from_run_id": previous.get("run_id") if previous else None,
                        "to_run_id": run_id,
                        "canonical_sha256": actual,
                        "replay_gates": replay_gates,
                        "occurred_at": event_time.isoformat(),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            os.replace(temp_compat, self.compatibility_path)
            os.replace(temp_current, self.current_path)
            os.replace(audit_temp, audit_path)
        except Exception:
            temp_compat.unlink(missing_ok=True)
            temp_current.unlink(missing_ok=True)
            audit_temp.unlink(missing_ok=True)
            if had_compatibility and restore_backup.exists():
                os.replace(restore_backup, self.compatibility_path)
            elif not had_compatibility:
                self.compatibility_path.unlink(missing_ok=True)
            if had_current and current_restore.exists():
                os.replace(current_restore, self.current_path)
            elif not had_current:
                self.current_path.unlink(missing_ok=True)
            raise
        finally:
            restore_backup.unlink(missing_ok=True)
            current_restore.unlink(missing_ok=True)
        return payload


def inspect_btc_status(data_root: str | Path, *, as_of: Any | None = None) -> dict[str, Any]:
    store = BtcRunStore(data_root)
    try:
        current = store.current()
    except ValueError as exc:
        reason_codes = ["CURRENT_POINTER_INVALID"]
        payload = {
            "data_readiness": "invalid",
            "reason_code": "CURRENT_POINTER_INVALID",
            "reason_codes": reason_codes,
            "error": str(exc),
            "path": str(store.current_path),
            "health": summarize_btc_health(
                run_id=None,
                data_readiness="invalid",
                publishable=False,
                gates=[],
                reason_codes=reason_codes,
                evidence_refs={"current_pointer": str(store.current_path)},
            ),
        }
        payload["live_pilot"] = btc_live_pilot_checklist(data_root, payload)
        return payload
    if current:
        manifest_path = Path(str(current.get("manifest_path") or ""))
        manifest: dict[str, Any] = {}
        manifest_error = None
        if manifest_path.exists():
            try:
                value = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest = value if isinstance(value, dict) else {}
            except (OSError, json.JSONDecodeError) as exc:
                manifest = {}
                manifest_error = f"{type(exc).__name__}: {exc}"
        freshness = btc_operational_freshness(manifest, as_of=as_of)
        readiness = manifest.get("data_readiness", "degraded")
        reason_codes = []
        if manifest_error:
            readiness = "invalid"
            reason_codes.append("CURRENT_MANIFEST_INVALID")
        if readiness == "ready" and not freshness["fresh"]:
            readiness = "degraded"
            reason_codes.append("CANONICAL_STALE")
        health = summarize_btc_health(
            run_id=str(current.get("run_id") or ""),
            data_readiness=str(readiness),
            publishable=readiness == "ready",
            gates=manifest.get("gates") or [],
            manifest=manifest,
            current=current,
            operational_freshness=freshness,
            reason_codes=reason_codes,
            integrity_errors=["manifest"] if manifest_error else [],
            evidence_refs={
                "manifest_path": str(manifest_path),
                "canonical_path": str(store.compatibility_path),
            },
        )
        payload = {
            "data_readiness": readiness,
            "reason_code": reason_codes[0] if reason_codes else None,
            "reason_codes": reason_codes,
            "current": current,
            "manifest": manifest,
            "operational_freshness": freshness,
            "health": health,
        }
        payload["live_pilot"] = btc_live_pilot_checklist(data_root, payload)
        return payload
    path = store.compatibility_path
    if not path.exists():
        reason_codes = ["NO_CANONICAL_DATA"]
        payload = {
            "data_readiness": "invalid",
            "reason_code": "NO_CANONICAL_DATA",
            "reason_codes": reason_codes,
            "path": str(path),
            "health": summarize_btc_health(
                run_id=None,
                data_readiness="invalid",
                publishable=False,
                gates=[],
                reason_codes=reason_codes,
                evidence_refs={"canonical_path": str(path)},
            ),
        }
        payload["live_pilot"] = btc_live_pilot_checklist(data_root, payload)
        return payload
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        reason_codes = ["CANONICAL_READ_ERROR"]
        payload = {
            "data_readiness": "invalid",
            "reason_code": "CANONICAL_READ_ERROR",
            "reason_codes": reason_codes,
            "error": str(exc),
            "path": str(path),
            "health": summarize_btc_health(
                run_id=None,
                data_readiness="invalid",
                publishable=False,
                gates=[],
                reason_codes=reason_codes,
                integrity_errors=["canonical_read"],
                evidence_refs={"canonical_path": str(path)},
            ),
        }
        payload["live_pilot"] = btc_live_pilot_checklist(data_root, payload)
        return payload
    reason_codes = ["LEGACY_LINEAGE_MISSING"]
    payload = {
        "data_readiness": "insufficient_data",
        "reason_code": "LEGACY_LINEAGE_MISSING",
        "reason_codes": reason_codes,
        "path": str(path),
        "row_count": int(len(frame)),
        "watermark": _watermark(frame),
        "health": summarize_btc_health(
            run_id=None,
            data_readiness="insufficient_data",
            publishable=False,
            gates=[],
            canonical=frame,
            reason_codes=reason_codes,
            evidence_refs={"canonical_path": str(path)},
        ),
    }
    payload["live_pilot"] = btc_live_pilot_checklist(data_root, payload)
    return payload
