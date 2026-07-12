from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from trade_py.data.market.cross_asset.assurance import (
    BtcAssuranceConfig,
    assure_btc,
    summarize_btc_health,
)
from trade_py.data.market.cross_asset.store import (
    BtcRunStore,
    btc_live_pilot_checklist,
    btc_operational_freshness,
    file_sha256,
    inspect_btc_status,
)
from trade_py.data.market.cross_asset.providers import (
    CRYPTO_PROVIDER_COLUMNS as BTC_PROVIDER_COLUMNS,
    BinanceDailyProvider,
    CryptoProviderCapture as BtcProviderCapture,
    OkxDailyProvider as OkxBtcDailyProvider,
    okx_canonical_candidate,
)


def _stable_id(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


class BtcMarketDataService:
    """Explicit BTC acquisition, assurance, staging, and publication use case."""

    def __init__(
        self,
        data_root: str | Path,
        *,
        primary_provider: OkxBtcDailyProvider | None = None,
        shadow_provider: BinanceDailyProvider | None = None,
        config: BtcAssuranceConfig | None = None,
        days: int = 730,
        shadow_days: int | None = None,
        max_attempts: int = 3,
        retry_base_seconds: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], Any] | None = None,
    ) -> None:
        if days < 1:
            raise ValueError("days must be positive")
        if max_attempts < 1 or max_attempts > 3:
            raise ValueError("max_attempts must be in [1, 3]")
        self.data_root = Path(data_root)
        self.primary_provider = primary_provider or OkxBtcDailyProvider(base_asset="BTC")
        # Shadow provider uses Binance: 100% free, no API key required, full OHLCV data
        # This replaces the paid CoinGecko API key requirement entirely
        self.shadow_provider = shadow_provider or BinanceDailyProvider(base_asset="BTC")
        self.config = config or BtcAssuranceConfig()
        self.days = days
        self.shadow_days = shadow_days or self.config.shadow_days
        if self.shadow_days < 1:
            raise ValueError("shadow_days must be positive")
        self.max_attempts = max_attempts
        self.retry_base_seconds = retry_base_seconds
        self.sleep = sleep
        self.now = now or (lambda: pd.Timestamp.now(tz="UTC"))
        self.store = BtcRunStore(self.data_root)

    @staticmethod
    def _empty_capture_frame() -> pd.DataFrame:
        return pd.DataFrame(columns=BTC_PROVIDER_COLUMNS)

    def _capture(
        self,
        name: str,
        provider: Any,
        *,
        as_of: pd.Timestamp,
        days: int,
    ) -> tuple[BtcProviderCapture | None, dict[str, Any]]:
        started = time.monotonic()
        errors: list[dict[str, str]] = []
        capture_seed = _stable_id({
            "provider": name,
            "contract": asdict(provider.contract),
            "as_of": as_of.isoformat(),
            "days": days,
        })
        for attempt in range(1, self.max_attempts + 1):
            try:
                capture = provider.capture(
                    days=days,
                    fetched_at=as_of,
                    run_id=capture_seed,
                )
                capture_id = _stable_id({
                    "contract": asdict(capture.contract),
                    "payload_hashes": capture.raw_payload_hashes,
                })
                capture = capture.with_run_id(capture_id)
                status = "empty" if capture.frame.empty else "succeeded"
                return capture, {
                    "provider": name,
                    "status": status,
                    "attempts": attempt,
                    "retry_count": attempt - 1,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "rows": int(len(capture.frame)),
                    "raw_payload_hashes": list(capture.raw_payload_hashes),
                    "error_kind": None,
                    "error": None,
                }
            except Exception as exc:
                errors.append({"kind": type(exc).__name__, "message": str(exc)})
                if attempt < self.max_attempts:
                    self.sleep(self.retry_base_seconds * (2 ** (attempt - 1)))
        last = errors[-1]
        return None, {
            "provider": name,
            "status": "failed",
            "attempts": self.max_attempts,
            "retry_count": self.max_attempts - 1,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "rows": 0,
            "raw_payload_hashes": [],
            "error_kind": last["kind"],
            "error": last["message"],
            "errors": errors,
        }

    @staticmethod
    def _acquisition_evidence(provider_reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
        statuses = [report["status"] for report in provider_reports.values()]
        return {
            "expected": len(provider_reports),
            "attempted": len(provider_reports),
            "succeeded": statuses.count("succeeded"),
            "empty": statuses.count("empty"),
            "failed": statuses.count("failed"),
            "providers": provider_reports,
        }

    def _historical_daily_attempts(self) -> list[dict[str, Any]]:
        attempts: list[dict[str, Any]] = []
        if not self.store.runs_root.exists():
            return attempts
        for manifest_path in sorted(self.store.runs_root.glob("*/manifest.json")):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                evidence = manifest.get("acquisition_evidence") or {}
                as_of = pd.to_datetime(evidence.get("as_of"), errors="coerce", utc=True)
                if pd.isna(as_of):
                    continue
                providers = evidence.get("providers") or {}
                artifacts = manifest.get("artifact_hashes") or {}
                run_dir = manifest_path.parent
                normalized_ok = all(
                    name in artifacts
                    and (run_dir / f"{name}.parquet").exists()
                    and file_sha256(run_dir / f"{name}.parquet") == str(artifacts[name])
                    for name in ("primary", "shadow")
                )
                raw_ok = True
                for provider in ("okx", "binance"):
                    raw_entries = [
                        (str(name), str(value))
                        for name, value in artifacts.items()
                        if str(name).startswith(f"raw/{provider}/")
                    ]
                    if not raw_entries:
                        raw_ok = False
                        break
                    for name, expected in raw_entries:
                        raw_path = run_dir / f"{name}.json"
                        if not raw_path.exists() or file_sha256(raw_path) != expected:
                            raw_ok = False
                            break
                provider_ok = all(
                    (providers.get(provider) or {}).get("status") == "succeeded"
                    for provider in ("okx", "binance")
                )
                gates = {
                    gate.get("gate"): gate
                    for gate in (manifest.get("gates") or [])
                }
                d1 = gates.get("D1") or {}
                gate_ok = (
                    (gates.get("D0") or {}).get("status") == "pass"
                    and (gates.get("D2") or {}).get("status") == "pass"
                    and (
                        d1.get("status") == "pass"
                        or d1.get("reason_code") == "ACQUISITION_STABILITY_INSUFFICIENT"
                    )
                )
                attempts.append({
                    "date": pd.Timestamp(as_of).date().isoformat(),
                    "qualified": bool(normalized_ok and raw_ok and provider_ok and gate_ok),
                    "run_id": manifest.get("run_id"),
                })
            except Exception:
                continue
        return attempts

    def _latest_staged_revision_baseline(
        self,
        *,
        before: pd.Timestamp,
    ) -> tuple[pd.DataFrame, dict[str, Any]] | None:
        candidates: list[tuple[pd.Timestamp, Path, dict[str, Any]]] = []
        if not self.store.runs_root.exists():
            return None
        for manifest_path in self.store.runs_root.glob("*/manifest.json"):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                as_of = pd.to_datetime(
                    (manifest.get("acquisition_evidence") or {}).get("as_of"),
                    errors="coerce",
                    utc=True,
                )
                gates = {
                    gate.get("gate"): gate.get("status")
                    for gate in (manifest.get("gates") or [])
                }
                if (
                    pd.isna(as_of)
                    or pd.Timestamp(as_of) > before
                    or any(gates.get(name) != "pass" for name in ("D0", "D2", "D3"))
                ):
                    continue
                canonical_path = manifest_path.parent / "canonical.parquet"
                expected = str((manifest.get("artifact_hashes") or {}).get("canonical") or "")
                if not canonical_path.exists() or not expected or file_sha256(canonical_path) != expected:
                    continue
                candidates.append((pd.Timestamp(as_of), canonical_path, manifest))
            except Exception:
                continue
        if not candidates:
            return None
        as_of, path, manifest = max(candidates, key=lambda item: item[0])
        return pd.read_parquet(path), {
            "kind": "staged_run",
            "run_id": manifest.get("run_id"),
            "as_of": as_of.isoformat(),
            "artifact_sha256": file_sha256(path),
            "canonical_hash": manifest.get("canonical_hash"),
        }

    def _load_revision_baseline(
        self,
        manifest: dict[str, Any],
        current: dict[str, Any],
    ) -> tuple[pd.DataFrame | None, list[str]]:
        evidence = manifest.get("acquisition_evidence") or {}
        revision = evidence.get("revision_predecessor") or {}
        kind = str(revision.get("kind") or "missing")
        expected = str(revision.get("artifact_sha256") or "")
        if kind == "missing":
            return None, []
        if kind == "staged_run":
            path = self.store.run_dir(str(revision.get("run_id") or "")) / "canonical.parquet"
        elif kind == "published_or_legacy":
            pointer_path = str(current.get("predecessor_path") or "")
            path = (
                Path(pointer_path)
                if pointer_path
                else self.store.runs_root / "_predecessors" / f"{expected}.parquet"
            )
        else:
            return None, ["revision_predecessor_kind"]
        if not path.exists() or not expected or file_sha256(path) != expected:
            return None, ["revision_predecessor_snapshot"]
        return pd.read_parquet(path), []

    def sync(
        self,
        *,
        dry_run: bool = False,
        as_of: Any | None = None,
    ) -> dict[str, Any]:
        effective_as_of = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp(self.now())
        if effective_as_of.tzinfo is None:
            effective_as_of = effective_as_of.tz_localize("UTC")
        else:
            effective_as_of = effective_as_of.tz_convert("UTC")

        previous_current = self.store.current()
        if previous_current and not self.store.compatibility_path.exists():
            raise FileNotFoundError("BTC current pointer exists but canonical artifact is missing")
        if previous_current:
            expected_current_hash = str(previous_current.get("canonical_sha256") or "")
            if file_sha256(self.store.compatibility_path) != expected_current_hash:
                raise ValueError("BTC current canonical hash does not match its pointer")
            previous_run_dir = self.store.run_dir(str(previous_current.get("run_id") or ""))
            previous_manifest_path = previous_run_dir / "manifest.json"
            if not previous_manifest_path.exists():
                raise FileNotFoundError("BTC current run manifest is missing")
            previous_manifest = json.loads(previous_manifest_path.read_text(encoding="utf-8"))
            previous_errors = self._verify_artifacts(previous_run_dir, previous_manifest)
            if previous_errors:
                raise ValueError(f"BTC current run artifacts are invalid: {previous_errors}")

        primary_capture, primary_report = self._capture(
            "okx", self.primary_provider, as_of=effective_as_of, days=self.days
        )
        shadow_capture, shadow_report = self._capture(
            "binance",
            self.shadow_provider,
            as_of=effective_as_of,
            days=self.shadow_days,
        )
        provider_reports = {"okx": primary_report, "binance": shadow_report}
        acquisition = self._acquisition_evidence(provider_reports)
        current_qualified = (
            primary_capture is not None
            and shadow_capture is not None
            and not primary_capture.final_rows.empty
            and not shadow_capture.final_rows.empty
            and bool(primary_capture.raw_payloads)
            and bool(shadow_capture.raw_payloads)
            and all(primary_capture.raw_payload_hashes)
            and all(shadow_capture.raw_payload_hashes)
            and all(
                report.get("status") == "succeeded"
                for report in provider_reports.values()
            )
        )
        acquisition["as_of"] = effective_as_of.isoformat()
        acquisition["daily_attempts"] = [
            *self._historical_daily_attempts(),
            {
                "date": effective_as_of.date().isoformat(),
                "qualified": current_qualified,
                "run_id": None,
            },
        ]

        if primary_capture is None:
            primary = self._empty_capture_frame()
            primary_raw: tuple[bytes, ...] = ()
        else:
            primary = okx_canonical_candidate(primary_capture)
            primary_raw = primary_capture.raw_payloads
        if shadow_capture is None:
            shadow = self._empty_capture_frame()
            shadow_raw: tuple[bytes, ...] = ()
        else:
            shadow = shadow_capture.final_rows
            shadow_raw = shadow_capture.raw_payloads

        existing: pd.DataFrame | None = None
        predecessor: dict[str, Any] = {"status": "missing", "sha256": None}
        if self.store.compatibility_path.exists():
            try:
                predecessor = {
                    "status": "readable",
                    "sha256": file_sha256(self.store.compatibility_path),
                    "run_id": previous_current.get("run_id") if previous_current else None,
                }
                existing = pd.read_parquet(self.store.compatibility_path)
            except Exception as exc:
                predecessor = {
                    "status": "read_error",
                    "sha256": (
                        file_sha256(self.store.compatibility_path)
                        if self.store.compatibility_path.is_file()
                        else None
                    ),
                    "error_kind": type(exc).__name__,
                }
                existing = None
        acquisition["predecessor"] = predecessor
        revision_predecessor: dict[str, Any] = {
            "kind": "missing",
            "run_id": None,
            "artifact_sha256": None,
        }
        staged_baseline = self._latest_staged_revision_baseline(before=effective_as_of)
        if staged_baseline is not None:
            existing, revision_predecessor = staged_baseline
        elif existing is not None:
            revision_predecessor = {
                "kind": "published_or_legacy",
                "run_id": predecessor.get("run_id"),
                "artifact_sha256": predecessor.get("sha256"),
            }
        acquisition["revision_predecessor"] = revision_predecessor
        result = assure_btc(
            primary,
            shadow,
            existing=existing,
            config=self.config,
            acquisition_evidence=acquisition,
            raw_payloads={"okx": primary_raw, "binance": shadow_raw},
        )
        summary: dict[str, Any] = {
            **result.summary(),
            "mode": "sync",
            "dry_run": dry_run,
            "acquisition": acquisition,
            "staged": None,
            "published": False,
        }
        if dry_run:
            return summary
        staged = self.store.stage(result)
        summary["staged"] = staged
        if result.publishable:
            published = self.store.publish(result)
            summary["published"] = True
            summary["current"] = published.get("current")
        return summary

    def validate_current(self, *, _lock: bool = True) -> dict[str, Any]:
        if _lock:
            with self.store.shared_lock():
                return self.validate_current(_lock=False)
        try:
            current = self.store.current()
        except ValueError as exc:
            reason_codes = ["CURRENT_POINTER_INVALID"]
            payload = {
                "mode": "validate",
                "validated": False,
                "data_readiness": "invalid",
                "reason_code": "CURRENT_POINTER_INVALID",
                "reason_codes": reason_codes,
                "error": str(exc),
                "health": summarize_btc_health(
                    run_id=None,
                    data_readiness="invalid",
                    publishable=False,
                    gates=[],
                    reason_codes=reason_codes,
                    evidence_refs={"current_pointer": str(self.store.current_path)},
                ),
            }
            payload["live_pilot"] = btc_live_pilot_checklist(self.data_root, payload)
            return payload
        if not current:
            payload = {**inspect_btc_status(self.data_root), "mode": "validate", "validated": False}
            if "health" not in payload:
                payload["health"] = summarize_btc_health(
                    run_id=payload.get("run_id"),
                    data_readiness=str(payload.get("data_readiness") or "invalid"),
                    publishable=False,
                    gates=[],
                    reason_codes=[str(payload.get("reason_code") or "")],
                    evidence_refs={"canonical_path": str(self.store.compatibility_path)},
                )
            return payload
        run_id = str(current.get("run_id") or "")
        run_dir = self.store.run_dir(run_id)
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            reason_codes = ["CURRENT_MANIFEST_MISSING"]
            payload = {
                "mode": "validate",
                "validated": False,
                "data_readiness": "invalid",
                "reason_code": "CURRENT_MANIFEST_MISSING",
                "reason_codes": reason_codes,
                "run_id": run_id,
                "current": current,
                "health": summarize_btc_health(
                    run_id=run_id,
                    data_readiness="invalid",
                    publishable=False,
                    gates=[],
                    current=current,
                    reason_codes=reason_codes,
                    evidence_refs={"manifest_path": str(manifest_path)},
                ),
            }
            payload["live_pilot"] = btc_live_pilot_checklist(self.data_root, payload)
            return payload
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            integrity_errors = self._verify_artifacts(run_dir, manifest)
            if str(manifest.get("run_id") or "") != run_id:
                integrity_errors.append("manifest_run_id")
            if str(current.get("manifest_path") or "") != str(manifest_path):
                integrity_errors.append("pointer_manifest_path")
            if str(current.get("run_dir") or "") != str(run_dir):
                integrity_errors.append("pointer_run_dir")
            if str(current.get("canonical_path") or "") != str(self.store.compatibility_path):
                integrity_errors.append("pointer_canonical_path")
            primary = pd.read_parquet(run_dir / "primary.parquet")
            shadow = pd.read_parquet(run_dir / "shadow.parquet")
            predecessor_frame, predecessor_errors = self._load_revision_baseline(
                manifest,
                current,
            )
            integrity_errors.extend(predecessor_errors)
            replay = assure_btc(
                primary,
                shadow,
                existing=predecessor_frame,
                config=BtcAssuranceConfig(**(manifest.get("config") or {})),
                acquisition_evidence=manifest.get("acquisition_evidence") or {},
            )
        except Exception as exc:
            reason_codes = ["CURRENT_REPLAY_ERROR"]
            payload = {
                "mode": "validate",
                "validated": False,
                "data_readiness": "invalid",
                "reason_code": "CURRENT_REPLAY_ERROR",
                "reason_codes": reason_codes,
                "run_id": run_id,
                "error": f"{type(exc).__name__}: {exc}",
                "current": current,
                "health": summarize_btc_health(
                    run_id=run_id,
                    data_readiness="invalid",
                    publishable=False,
                    gates=(manifest.get("gates") or []) if "manifest" in locals() else [],
                    manifest=manifest if "manifest" in locals() else None,
                    current=current,
                    reason_codes=reason_codes,
                    evidence_refs={"manifest_path": str(manifest_path)},
                ),
            }
            payload["live_pilot"] = btc_live_pilot_checklist(self.data_root, payload)
            return payload
        replay_errors = []
        if replay.manifest.get("canonical_hash") != manifest.get("canonical_hash"):
            replay_errors.append("canonical_hash")
        if replay.manifest.get("code_revision") != manifest.get("code_revision"):
            replay_errors.append("code_revision")
        if replay.manifest.get("schema_hash") != manifest.get("schema_hash"):
            replay_errors.append("schema_hash")
        if self.store.compatibility_path.exists():
            expected = str(current.get("canonical_sha256") or "")
            if not expected or file_sha256(self.store.compatibility_path) != expected:
                integrity_errors.append("current_canonical_sha256")
        else:
            integrity_errors.append("current_canonical_missing")
        readiness = replay.data_readiness
        reason_codes: list[str] = []
        operational_freshness = btc_operational_freshness(
            manifest,
            as_of=self.now(),
        )
        if integrity_errors or replay_errors:
            readiness = "invalid"
            reason_codes.append("CURRENT_INTEGRITY_INVALID")
        elif readiness == "ready" and not operational_freshness["fresh"]:
            readiness = "degraded"
            reason_codes.append("CANONICAL_STALE")
        health = summarize_btc_health(
            run_id=run_id,
            data_readiness=readiness,
            publishable=readiness == "ready",
            gates=[gate.to_dict() for gate in replay.gates],
            canonical=replay.canonical,
            reconciliation=replay.reconciliation,
            revisions=replay.revisions,
            acquisition_evidence=manifest.get("acquisition_evidence") or {},
            manifest=manifest,
            current=current,
            operational_freshness=operational_freshness,
            reason_codes=reason_codes,
            integrity_errors=integrity_errors,
            replay_errors=replay_errors,
            evidence_refs={
                "manifest_path": str(manifest_path),
                "run_dir": str(run_dir),
                "canonical_path": str(self.store.compatibility_path),
            },
        )
        payload = {
            "mode": "validate",
            "validated": readiness == "ready",
            "data_readiness": readiness,
            "reason_code": reason_codes[0] if reason_codes else None,
            "reason_codes": reason_codes,
            "run_id": run_id,
            "current": current,
            "integrity_errors": integrity_errors,
            "replay_errors": replay_errors,
            "operational_freshness": operational_freshness,
            "gates": [gate.to_dict() for gate in replay.gates],
            "manifest": manifest,
            "health": health,
        }
        payload["live_pilot"] = btc_live_pilot_checklist(self.data_root, payload)
        return payload

    @staticmethod
    def _verify_artifacts(run_dir: Path, manifest: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        hashes = manifest.get("artifact_hashes") or {}
        required = {"primary", "shadow", "canonical", "reconciliation", "revisions"}
        errors.extend(f"{name}:missing_hash" for name in sorted(required - set(hashes)))
        for name, expected in hashes.items():
            if name.startswith("raw/"):
                path = run_dir / f"{name}.json"
            else:
                path = run_dir / f"{name}.parquet"
            if not path.exists() or file_sha256(path) != str(expected):
                errors.append(name)
        return errors

    def status(self) -> dict[str, Any]:
        try:
            current = self.store.current()
        except ValueError:
            current = None
        if current:
            return {**self.validate_current(), "mode": "status"}
        return {**inspect_btc_status(self.data_root, as_of=self.now()), "mode": "status"}


__all__ = ["BtcMarketDataService"]
