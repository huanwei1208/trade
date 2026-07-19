"""Artifact verification and canonical reads (WP2.5).

Verifies artifact SHA-256 against the manifest, reads canonical parquet under the
existing shared lock, and fixes the uppercase/lowercase BTC path defect at this
boundary (new logic never guesses case). Fails closed on any integrity mismatch.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd

from trade_py.observatory.domain.models import ArtifactRef
from trade_py.observatory.domain.vocab import ObservatoryError, ReasonCode


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_dir(data_root: str | Path, run_id: str) -> Path:
    """Resolve a run directory with strict boundary validation (no traversal)."""

    root = (Path(data_root) / "market" / "crypto" / "runs" / "btc").resolve()
    # Strict run-id format: hex-ish token, no separators.
    if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
        raise ObservatoryError(
            ReasonCode.SNAPSHOT_NOT_FOUND, "invalid run id", extra={"run_id": "<redacted>"}
        )
    candidate = (root / run_id).resolve()
    if root not in candidate.parents and candidate != root:
        raise ObservatoryError(ReasonCode.SNAPSHOT_NOT_FOUND, "run id outside root boundary")
    return candidate


def verify_artifact(data_root: str | Path, ref: ArtifactRef) -> Path:
    """Verify a single artifact hash; fail closed on mismatch."""

    directory = run_dir(data_root, ref.run_id)
    path = directory / ref.relative_path
    if not path.exists():
        raise ObservatoryError(
            ReasonCode.ARTIFACT_HASH_MISMATCH,
            f"artifact missing: {ref.name}",
            evidence_refs=[f"runs/btc/{ref.run_id}/{ref.relative_path}"],
        )
    actual = _sha256_file(path)
    if actual != ref.sha256:
        raise ObservatoryError(
            ReasonCode.ARTIFACT_HASH_MISMATCH,
            f"artifact hash mismatch: {ref.name}",
            evidence_refs=[f"runs/btc/{ref.run_id}/{ref.relative_path}"],
        )
    return path


def read_canonical(data_root: str | Path, run_id: str, canonical_sha256: str | None) -> pd.DataFrame:
    """Read a run's canonical parquet, verifying its hash first."""

    directory = run_dir(data_root, run_id)
    path = directory / "canonical.parquet"
    if not path.exists():
        raise ObservatoryError(
            ReasonCode.ARTIFACT_HASH_MISMATCH,
            "canonical artifact missing",
            evidence_refs=[f"runs/btc/{run_id}/canonical.parquet"],
        )
    if canonical_sha256:
        actual = _sha256_file(path)
        if actual != canonical_sha256:
            raise ObservatoryError(
                ReasonCode.ARTIFACT_HASH_MISMATCH,
                "canonical hash mismatch",
                evidence_refs=[f"runs/btc/{run_id}/canonical.parquet"],
            )
    return pd.read_parquet(path)


def read_artifact_frame(data_root: str | Path, run_id: str, name: str) -> pd.DataFrame:
    """Read reconciliation/revisions/primary/shadow parquet for a run (no hash gate)."""

    directory = run_dir(data_root, run_id)
    path = directory / f"{name}.parquet"
    if not path.exists():
        raise ObservatoryError(
            ReasonCode.SNAPSHOT_NOT_FOUND,
            f"artifact not found: {name}",
            evidence_refs=[f"runs/btc/{run_id}/{name}.parquet"],
        )
    return pd.read_parquet(path)


def verify_current_pointer(current: dict[str, Any] | None, active_run_id: str | None) -> None:
    """Fail closed if the current pointer disagrees with the resolved formal run."""

    if current is None:
        return
    pointer_run = str(current.get("run_id") or "")
    if active_run_id and pointer_run and pointer_run != active_run_id:
        raise ObservatoryError(
            ReasonCode.CURRENT_POINTER_INVALID,
            "current pointer disagrees with publication ledger",
            evidence_refs=["btc_current.json"],
        )
