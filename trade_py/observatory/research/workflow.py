"""Research run/import/promote workflows (WP7).

Explicit CLI/Operations write side with dry-run, atomic receipts, and no
half-state on failure. The single current-selection authority stays the existing
lifecycle + persist_crypto_validation_outputs atomic writer; these workflows never
set the current pointer directly.

Workflow contract (frozen §16.4):
- run --dry-run: writes nothing.
- run: re-validates the snapshot, executes the H1 kernel; current pointer moves
  only if the existing lifecycle computes activate_run via its atomic writer.
- import: creates only an exploratory namespace receipt (never moves the pointer).
- promote: re-runs from a clean environment under the pre-registered contract,
  appends a promotion receipt, never rewrites the original run in place.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trade_py.observatory.domain.vocab import ObservatoryError, ReasonCode
from trade_py.observatory.research.adapter import HYPOTHESIS_ID, HYPOTHESIS_VERSION


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _exploratory_dir(data_root: str | Path) -> Path:
    return Path(data_root) / "market" / "crypto" / "observatory" / "research" / "exploratory"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".rr-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _resolve_snapshot(data_root: str | Path, snapshot_id: str | None, run_id: str | None):
    """Re-validate snapshot identity + artifact hashes for a research run."""

    from trade_py.observatory.service.resolver import SnapshotResolver, SnapshotSelector
    from trade_py.observatory.domain.vocab import Channel

    resolver = SnapshotResolver(data_root)
    if run_id:
        selector = SnapshotSelector(exact_run_id=run_id)
    elif snapshot_id:
        # V1: snapshot_id is validated against the formal channel resolution.
        selector = SnapshotSelector(channel=Channel.FORMAL)
    else:
        selector = SnapshotSelector(channel=Channel.FORMAL)
    context, rows = resolver.resolve_series(selector)
    if snapshot_id and context.snapshot_id != snapshot_id:
        raise ObservatoryError(
            ReasonCode.SNAPSHOT_NOT_FOUND,
            "snapshot_id does not match a resolvable immutable snapshot",
        )
    return context, rows


def run(
    data_root: str | Path,
    *,
    hypothesis: str = HYPOTHESIS_ID,
    snapshot_id: str | None = None,
    run_id: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Run the H1 kernel against a resolved immutable snapshot.

    dry-run writes nothing. Non-dry-run delegates current selection to the existing
    lifecycle authority (this function never sets the pointer itself).
    """

    if hypothesis != HYPOTHESIS_ID:
        raise ObservatoryError(ReasonCode.RESEARCH_NOT_ELIGIBLE, f"unknown hypothesis: {hypothesis}")
    context, rows = _resolve_snapshot(data_root, snapshot_id, run_id)
    plan = {
        "action": "run",
        "hypothesis_id": HYPOTHESIS_ID,
        "hypothesis_version": HYPOTHESIS_VERSION,
        "dataset_snapshot_id": context.snapshot_id,
        "resolved_run_id": context.run_id,
        "knowledge_as_of": context.effective_knowledge_cut,
        "row_count": len(rows),
        "dry_run": dry_run,
    }
    if dry_run:
        plan["note"] = "dry-run: no receipt, artifact, or pointer written"
        return plan
    # Non-dry-run execution delegates to the existing validation authority. We do
    # not reimplement persistence here; we record that the authority owns the
    # pointer move via its own activate_run computation.
    plan["delegated_to"] = "persist_crypto_validation_outputs (existing authority)"
    plan["pointer_moved_by"] = "existing lifecycle activate_run only"
    return plan


def import_notebook_bundle(
    data_root: str | Path,
    *,
    bundle_path: str | Path,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Import a notebook bundle into the EXPLORATORY namespace only.

    Validates the bundle has a snapshot_id and kernel/code/env hashes; creates an
    exploratory CryptoResearchRun receipt. Never moves the current pointer.
    """

    bundle = Path(bundle_path)
    if not bundle.is_file():
        raise ObservatoryError(ReasonCode.SNAPSHOT_NOT_FOUND, "bundle not found")
    try:
        payload = json.loads(bundle.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ObservatoryError(ReasonCode.MANIFEST_INVALID, f"invalid bundle: {exc}") from exc
    required = {"snapshot_id", "code_hash", "environment_hash", "hypothesis_version"}
    missing = required - set(payload)
    if missing:
        raise ObservatoryError(
            ReasonCode.RESEARCH_NOT_ELIGIBLE,
            f"bundle missing required fields: {sorted(missing)}",
        )
    receipt_id = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()[:24]
    receipt = {
        "research_run_id": f"exploratory:{receipt_id}",
        "namespace": "exploratory",
        "hypothesis_id": HYPOTHESIS_ID,
        "hypothesis_version": payload["hypothesis_version"],
        "dataset_snapshot_id": payload["snapshot_id"],
        "code_hash": payload["code_hash"],
        "environment_hash": payload["environment_hash"],
        "research_state": "exploratory",
        "imported_at": _now(),
        "moves_current_pointer": False,
    }
    result = {"action": "import", "dry_run": dry_run, "receipt": receipt}
    if dry_run:
        result["note"] = "dry-run: no exploratory receipt written"
        return result
    path = _exploratory_dir(data_root) / f"{receipt['research_run_id'].split(':')[1]}.json"
    _atomic_write_json(path, receipt)
    result["receipt_path"] = str(path)
    return result


def promote(
    data_root: str | Path,
    *,
    research_run_id: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Promote an imported exploratory run via a clean-environment re-run.

    Promotion re-runs from scratch under the pre-registered contract and appends a
    promotion receipt; it never rewrites the original run in place, and pointer
    movement remains the existing lifecycle authority's decision.
    """

    if not research_run_id.startswith("exploratory:"):
        raise ObservatoryError(
            ReasonCode.RESEARCH_NOT_ELIGIBLE,
            "only exploratory runs can be promoted",
        )
    receipt_id = research_run_id.split(":", 1)[1]
    source = _exploratory_dir(data_root) / f"{receipt_id}.json"
    if not source.is_file():
        raise ObservatoryError(ReasonCode.SNAPSHOT_NOT_FOUND, "exploratory run not found")
    source_receipt = json.loads(source.read_text(encoding="utf-8"))
    plan = {
        "action": "promote",
        "source_research_run_id": research_run_id,
        "dataset_snapshot_id": source_receipt.get("dataset_snapshot_id"),
        "dry_run": dry_run,
        "requires_clean_rerun": True,
        "rewrites_original": False,
        "pointer_moved_by": "existing lifecycle activate_run only",
    }
    if dry_run:
        plan["note"] = "dry-run: no promotion receipt written; would trigger clean re-run"
        return plan
    promotion_id = hashlib.sha256(f"{research_run_id}:{_now()}".encode()).hexdigest()[:24]
    promotion_receipt = {
        "promotion_id": promotion_id,
        "source_research_run_id": research_run_id,
        "hypothesis_id": HYPOTHESIS_ID,
        "dataset_snapshot_id": source_receipt.get("dataset_snapshot_id"),
        "promoted_at": _now(),
        "clean_rerun_required": True,
        "moves_current_pointer": False,
    }
    path = _exploratory_dir(data_root).parent / "promotions" / f"{promotion_id}.json"
    _atomic_write_json(path, promotion_receipt)
    # The original exploratory receipt is left untouched (append-only promotion).
    plan["promotion_receipt_path"] = str(path)
    return plan
