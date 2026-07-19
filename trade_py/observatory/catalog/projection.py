"""Snapshot Catalog projection (WP1).

The Catalog is a rebuildable projection of immutable manifests, the current pointer,
and publish/rollback audits. It is NOT a second source of truth: every field is
derived from immutable facts and a full rebuild is deterministic.

Read paths only verify the Catalog `source_fingerprint`; they never build, migrate,
or write the projection (that is the CLI/Operations write side). Filesystem mtime is
never used as business time.
"""
from __future__ import annotations

import glob
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trade_py.observatory.catalog import legacy_time
from trade_py.observatory.domain.models import (
    ArtifactRef,
    AssetContract,
    ObservationRun,
    QualityFinding,
    Release,
)
from trade_py.observatory.domain.state_mapping import (
    acquisition_state_for,
    lifecycle_state_for,
    quality_state_for,
)
from trade_py.observatory.domain.vocab import (
    ASSET_ID,
    CATALOG_SCHEMA_VERSION,
    DISPLAY_SYMBOL,
    PRIMARY_INSTRUMENT,
    PRIMARY_INTERVAL,
    PRIMARY_PROVIDER,
    QUOTE,
    SHADOW_INSTRUMENT,
    SHADOW_INTERVAL,
    SHADOW_PROVIDER,
    LifecycleState,
    ObservatoryError,
    ReasonCode,
)

# Standard artifact files inside a run directory.
_ARTIFACT_NAMES = ("primary", "shadow", "canonical", "reconciliation", "revisions")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def default_contract(contract_version: str | None) -> AssetContract:
    return AssetContract(
        asset_id=ASSET_ID,
        display_symbol=DISPLAY_SYMBOL,
        contract_version=contract_version or "btc-data-v1",
        primary_provider=PRIMARY_PROVIDER,
        primary_instrument=PRIMARY_INSTRUMENT,
        shadow_provider=SHADOW_PROVIDER,
        shadow_instrument=SHADOW_INSTRUMENT,
        quote=QUOTE,
        primary_interval=PRIMARY_INTERVAL,
        shadow_interval=SHADOW_INTERVAL,
    )


def _findings_from_gates(run_id: str, gates: list[dict[str, Any]]) -> tuple[QualityFinding, ...]:
    findings: list[QualityFinding] = []
    for gate in gates or []:
        status = str(gate.get("status") or "")
        if status == "pass":
            continue
        gate_id = str(gate.get("gate") or "")
        reason = str(gate.get("reason_code") or "")
        findings.append(
            QualityFinding(
                finding_id=f"{run_id}:{gate_id}:{reason}",
                run_id=run_id,
                gate=gate_id,
                severity="block" if status == "fail" else status,
                reason_code=reason,
                detail=str(gate.get("detail") or ""),
                affected_dates=tuple(str(d) for d in (gate.get("affected_dates") or [])),
                metrics=dict(gate.get("metrics") or {}),
                evidence_refs=(f"runs/btc/{run_id}/manifest.json",),
            )
        )
    return tuple(findings)


def _artifact_refs(run_id: str, manifest: dict[str, Any]) -> tuple[ArtifactRef, ...]:
    hashes = manifest.get("artifact_hashes") or {}
    refs: list[ArtifactRef] = []
    for name, sha in sorted(hashes.items()):
        rel = f"{name}.json" if str(name).startswith("raw/") else f"{name}.parquet"
        refs.append(ArtifactRef(run_id=run_id, name=str(name), sha256=str(sha), relative_path=rel))
    return tuple(refs)


def run_from_manifest(manifest: dict[str, Any]) -> ObservationRun:
    """Project an immutable manifest into an ObservationRun (deterministic)."""

    run_id = _text(manifest.get("run_id"))
    if not run_id:
        raise ObservatoryError(ReasonCode.MANIFEST_INVALID, "manifest missing run_id")
    contract = default_contract(_text(manifest.get("contract_version")))
    gates = list(manifest.get("gates") or [])
    health = manifest.get("health") or {}
    rows = int(manifest.get("canonical_rows") or 0)
    has_d0_blocker = any(
        str(g.get("gate")) == "D0" and str(g.get("status")) == "fail" for g in gates
    )
    return ObservationRun(
        run_id=run_id,
        contract=contract,
        created_at=_text(manifest.get("created_at")),
        effective_as_of=legacy_time.derive_effective_as_of(manifest),
        market_watermark=_text(manifest.get("watermark")),
        input_watermarks=dict(manifest.get("input_watermarks") or {}),
        output_watermark=_text(manifest.get("output_watermark")),
        canonical_rows=rows,
        code_revision=_text(manifest.get("code_revision")),
        config_hash=_text(manifest.get("config_hash")),
        schema_hash=_text(manifest.get("schema_hash")),
        canonical_hash=_text(manifest.get("canonical_hash")),
        primary_hash=_text(manifest.get("primary_hash")),
        shadow_hash=_text(manifest.get("shadow_hash")),
        artifact_refs=_artifact_refs(run_id, manifest),
        gates=tuple(gates),
        data_readiness=_text(manifest.get("data_readiness")),
        acquisition_state=acquisition_state_for(manifest),
        quality_state=quality_state_for(manifest),
        lifecycle_state=LifecycleState.STAGED,
        blocking_gate=_text(health.get("blocking_gate")),
        blocking_reason_code=_text(health.get("blocking_reason_code")),
        findings=_findings_from_gates(run_id, gates),
        staged_at=legacy_time.derive_staged_at(manifest),
        assurance_completed_at=legacy_time.derive_assurance_completed_at(manifest),
        capture_completed_at=legacy_time.derive_capture_completed_at(manifest),
        first_proven_present_at=legacy_time.derive_first_proven_present_at(manifest),
        has_primary_canonical=bool(manifest.get("canonical_hash")) and rows > 0,
        has_final_bar=rows > 0,
        has_d0_blocker=has_d0_blocker,
    )


@dataclass
class Catalog:
    """In-memory Catalog projection with a deterministic content hash."""

    catalog_schema_version: str
    source_fingerprint: str
    generation_id: str
    runs: dict[str, ObservationRun] = field(default_factory=dict)
    releases: list[Release] = field(default_factory=list)
    current_run_id: str | None = None
    current_pointer: dict[str, Any] | None = None

    def content_hash(self) -> str:
        payload = {
            "schema": self.catalog_schema_version,
            "runs": sorted(self.runs.keys()),
            "run_hashes": {
                rid: hashlib.sha256(
                    json.dumps(
                        {
                            "watermark": r.market_watermark,
                            "created_at": r.created_at,
                            "canonical_hash": r.canonical_hash,
                            "readiness": r.data_readiness,
                            "rows": r.canonical_rows,
                        },
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                for rid, r in sorted(self.runs.items())
            },
            "releases": [
                (rel.release_id, rel.run_id, rel.published_at, rel.lifecycle_state.value)
                for rel in self.releases
            ],
            "current_run_id": self.current_run_id,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _iter_manifest_paths(runs_dir: Path) -> list[Path]:
    return sorted(Path(p) for p in glob.glob(str(runs_dir / "*" / "manifest.json")))


def compute_source_fingerprint(runs_dir: Path, audit_dir: Path, current_path: Path) -> str:
    """Deterministic fingerprint of the immutable fact set (no mtime)."""

    parts: list[str] = []
    for path in _iter_manifest_paths(runs_dir):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        parts.append(f"m:{path.parent.name}:{hashlib.sha256(data).hexdigest()}")
    for kind in ("publish", "rollback"):
        for path in sorted(glob.glob(str(audit_dir / kind / "*.json"))):
            try:
                data = Path(path).read_bytes()
            except OSError:
                continue
            parts.append(f"a:{kind}:{Path(path).name}:{hashlib.sha256(data).hexdigest()}")
    if current_path.exists():
        parts.append(f"c:{hashlib.sha256(current_path.read_bytes()).hexdigest()}")
    return hashlib.sha256("\n".join(sorted(parts)).encode()).hexdigest()


def _load_releases(audit_dir: Path, current_pointer: dict[str, Any] | None) -> list[Release]:
    """Project the publication/rollback ledger into ordered Release records."""

    events: list[dict[str, Any]] = []
    for kind in ("publish", "rollback"):
        for path in sorted(glob.glob(str(audit_dir / kind / "*.json"))):
            try:
                event = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            event["_kind"] = kind
            event["_audit_ref"] = f"audit/{kind}/{Path(path).name}"
            events.append(event)
    events.sort(key=lambda e: str(e.get("occurred_at") or ""))

    releases: list[Release] = []
    previous_release_id: str | None = None
    for event in events:
        event_id = _text(event.get("event_id")) or _text(event.get("_audit_ref"))
        to_run = _text(event.get("to_run_id"))
        if not to_run:
            continue
        rollback = event.get("_kind") == "rollback"
        release = Release(
            release_id=str(event_id),
            channel="formal",
            run_id=to_run,
            previous_release_id=previous_release_id,
            published_at=_text(event.get("occurred_at")),
            policy_version=_text(event.get("policy_version")),
            audit_ref=_text(event.get("_audit_ref")),
            canonical_sha256=_text(event.get("canonical_sha256")),
            lifecycle_state=LifecycleState.ROLLED_BACK if rollback else LifecycleState.PUBLISHED,
        )
        releases.append(release)
        previous_release_id = release.release_id
    # Mark superseded: only the last release stays active.
    if releases:
        for rel in releases[:-1]:
            object.__setattr__(rel, "lifecycle_state", LifecycleState.SUPERSEDED)
    return releases


def build_catalog(data_root: str | Path) -> Catalog:
    """Full deterministic rebuild from immutable facts."""

    root = Path(data_root)
    crypto_root = root / "market" / "crypto"
    runs_dir = crypto_root / "runs" / "btc"
    audit_dir = crypto_root / "audit"
    current_path = crypto_root / "btc_current.json"

    fingerprint = compute_source_fingerprint(runs_dir, audit_dir, current_path)
    generation_id = hashlib.sha256(fingerprint.encode()).hexdigest()[:24]

    runs: dict[str, ObservationRun] = {}
    for path in _iter_manifest_paths(runs_dir):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        try:
            run = run_from_manifest(manifest)
        except ObservatoryError:
            continue
        runs[run.run_id] = run

    current_pointer: dict[str, Any] | None = None
    current_run_id: str | None = None
    if current_path.exists():
        try:
            current_pointer = json.loads(current_path.read_text(encoding="utf-8"))
            current_run_id = _text(current_pointer.get("run_id"))
        except (OSError, ValueError):
            current_pointer = None

    releases = _load_releases(audit_dir, current_pointer)

    # Reconcile lifecycle on runs referenced by releases.
    active_release = releases[-1] if releases else None
    for rel in releases:
        run = runs.get(rel.run_id)
        if run is None:
            continue
        if active_release is not None and rel.run_id == active_release.run_id and rel.lifecycle_state == LifecycleState.PUBLISHED:
            object.__setattr__(run, "lifecycle_state", LifecycleState.PUBLISHED)
        elif run.lifecycle_state == LifecycleState.STAGED:
            object.__setattr__(run, "lifecycle_state", LifecycleState.SUPERSEDED)

    return Catalog(
        catalog_schema_version=CATALOG_SCHEMA_VERSION,
        source_fingerprint=fingerprint,
        generation_id=generation_id,
        runs=runs,
        releases=releases,
        current_run_id=current_run_id,
        current_pointer=current_pointer,
    )
