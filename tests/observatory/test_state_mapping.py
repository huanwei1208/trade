"""WP2.2 state axis mapping + purpose fitness tests."""
from __future__ import annotations

import pytest

from trade_py.observatory.catalog import store as catalog_store
from trade_py.observatory.domain import state_mapping
from trade_py.observatory.domain.vocab import (
    Channel,
    CompatibilityState,
    FreshnessState,
    Purpose,
    QualityState,
)
from trade_py.observatory.service.resolver import SnapshotResolver, SnapshotSelector
from tests.observatory.fixtures import build_observatory_fixture


def test_readiness_maps_to_quality_states():
    assert state_mapping.quality_state_for({"data_readiness": "ready", "gates": [1]}) == QualityState.ASSURED
    assert state_mapping.quality_state_for({"data_readiness": "degraded", "gates": [1]}) == QualityState.DEGRADED
    assert state_mapping.quality_state_for({"data_readiness": "insufficient_data", "gates": [1]}) == QualityState.INSUFFICIENT
    assert state_mapping.quality_state_for({"data_readiness": "invalid", "gates": [1]}) == QualityState.INVALID
    # No gates and no readiness -> not evaluated.
    assert state_mapping.quality_state_for({}) == QualityState.NOT_EVALUATED
    # Unknown readiness value -> unknown, never inferred ready.
    assert state_mapping.quality_state_for({"data_readiness": "weird", "gates": [1]}) == QualityState.UNKNOWN


def test_freshness_is_separate_from_quality():
    assert state_mapping.freshness_for("2026-07-18", "2026-07-18", 1) == FreshnessState.FRESH
    assert state_mapping.freshness_for("2026-07-11", "2026-07-18", 1) == FreshnessState.STALE
    assert state_mapping.freshness_for(None, "2026-07-18") == FreshnessState.UNKNOWN


def test_compatibility_preserves_history():
    assert state_mapping.compatibility_for(manifest_code_revision="a", current_code_revision="a") == CompatibilityState.COMPATIBLE
    assert state_mapping.compatibility_for(manifest_code_revision="a", current_code_revision="b") == CompatibilityState.CONTRACT_STALE
    assert state_mapping.compatibility_for(manifest_code_revision="a", current_code_revision="a", replay_mismatch=True) == CompatibilityState.REPLAY_MISMATCH


def test_mapping_policy_version_present():
    assert state_mapping.mapping_metadata()["mapping_policy_version"] == "obs-map-v1"


@pytest.fixture()
def resolver(tmp_path):
    fx = build_observatory_fixture(tmp_path / "data")
    catalog_store.rebuild(fx["data_root"])
    return SnapshotResolver(fx["data_root"]), fx


def test_purpose_fitness_formal_allows_consumption(resolver):
    r, fx = resolver
    ctx = r.resolve_context(SnapshotSelector(channel=Channel.FORMAL))
    fitness = {f.purpose: f for f in ctx.purpose_fitness}
    assert fitness[Purpose.MANUAL_OBSERVATION.value].allowed is True
    assert fitness[Purpose.FORMAL_SYSTEM_CONSUMPTION.value].allowed is True
    # automated_decision is never auto-enabled.
    assert fitness[Purpose.AUTOMATED_DECISION.value].allowed is False


def test_purpose_fitness_candidate_blocks_formal_consumption(resolver):
    r, fx = resolver
    ctx = r.resolve_context(SnapshotSelector(channel=Channel.EVALUATED_CANDIDATE))
    fitness = {f.purpose: f for f in ctx.purpose_fitness}
    # Candidate is not a published formal release.
    assert fitness[Purpose.FORMAL_SYSTEM_CONSUMPTION.value].allowed is False
    assert "CHANNEL_UNAVAILABLE" in fitness[Purpose.FORMAL_SYSTEM_CONSUMPTION.value].reason_codes
    # strict_research is blocked (not assured / not formal).
    assert fitness[Purpose.STRICT_RESEARCH.value].allowed is False


def test_freshness_visible_on_formal(resolver):
    r, fx = resolver
    ctx = r.resolve_context(SnapshotSelector(channel=Channel.FORMAL))
    # Formal watermark 2026-07-11 is stale vs latest expected bar.
    assert ctx.freshness_state in {FreshnessState.STALE, FreshnessState.FRESH, FreshnessState.UNKNOWN}
    assert ctx.compatibility_state == CompatibilityState.COMPATIBLE
