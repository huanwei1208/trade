"""Snapshot identity and view fingerprint (WP2.3 / frozen_contracts.md).

snapshot_id = sha256(normalized_serialization(asset contract id/version, resolved
run/release ids, artifact SHA-256s in stable order, effective knowledge cut,
knowledge_mode, revision_policy, quarantine/inclusion policy, resolver policy
version)).

Excluded from snapshot_id: requested_at, rendered_at, page ranges, chart metrics,
sort order. view_fingerprint additionally folds in the participating fact
fingerprints, date range, metric versions, lens, pagination/sort, and serialization
version.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from trade_py.observatory.domain.vocab import (
    RESOLVER_POLICY_VERSION,
    SERIALIZATION_VERSION,
)


def compute_snapshot_id(
    *,
    contract_id: str,
    contract_version: str,
    run_id: str | None,
    release_id: str | None,
    artifact_sha256s: list[str],
    effective_knowledge_cut: str | None,
    knowledge_mode: str,
    revision_policy: str,
    include_quarantined: bool,
) -> str:
    payload = {
        "contract_id": contract_id,
        "contract_version": contract_version,
        "run_id": run_id,
        "release_id": release_id,
        # Artifact hashes in stable (sorted) order.
        "artifact_sha256s": sorted(artifact_sha256s),
        "effective_knowledge_cut": effective_knowledge_cut,
        "knowledge_mode": knowledge_mode,
        "revision_policy": revision_policy,
        "include_quarantined": bool(include_quarantined),
        "resolver_policy_version": RESOLVER_POLICY_VERSION,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def compute_view_fingerprint(
    *,
    snapshot_id: str,
    fact_fingerprints: list[str],
    date_from: str | None,
    date_to: str | None,
    metric_versions: dict[str, Any],
    lens: str,
    page_cursor: str | None,
    sort_key: str | None,
) -> str:
    payload = {
        "snapshot_id": snapshot_id,
        "fact_fingerprints": sorted(fact_fingerprints),
        "date_from": date_from,
        "date_to": date_to,
        "metric_versions": metric_versions,
        "lens": lens,
        "page_cursor": page_cursor,
        "sort_key": sort_key,
        "serialization_version": SERIALIZATION_VERSION,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def etag_for(view_fingerprint: str) -> str:
    """Strong ETag from the view fingerprint."""

    return f'"{view_fingerprint[:32]}"'
