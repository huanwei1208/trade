"""WP6 point-in-time resolver tests."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from trade_py.observatory.catalog import store as catalog_store
from trade_py.observatory.domain.vocab import (
    Channel,
    KnowledgeMode,
    ObservatoryError,
    ReasonCode,
    RevisionPolicy,
)
from trade_py.observatory.pit.resolver import PointInTimeResolver
from trade_py.observatory.service.resolver import SnapshotSelector
from tests.observatory.fixtures import build_observatory_fixture


@pytest.fixture()
def pit(tmp_path):
    fx = build_observatory_fixture(tmp_path / "data")
    catalog_store.rebuild(fx["data_root"])
    return PointInTimeResolver(fx["data_root"]), fx


def test_evidence_report_has_earliest_proven(pit):
    r, fx = pit
    report = r.evidence_report()
    assert report["earliest_proven_knowledge_time"] is not None
    assert report["has_precise_stage_times"] is False
    assert ReasonCode.LEGACY_TIME_UNPROVEN.value in report["gap_reason_codes"]


def test_installation_observed_before_earliest_is_not_proven(pit):
    r, fx = pit
    # Earliest proven ~2026-07-12; ask before that in installation_observed mode.
    with pytest.raises(ObservatoryError) as exc:
        r.resolve(
            SnapshotSelector(
                channel=Channel.FORMAL,
                knowledge_as_of="2020-01-01T00:00:00+00:00",
                knowledge_mode=KnowledgeMode.INSTALLATION_OBSERVED,
            )
        )
    assert exc.value.reason_code == ReasonCode.PIT_NOT_PROVEN
    assert "coverage_interval" in exc.value.extra


def test_market_available_allows_historical(pit):
    r, fx = pit
    # market_available mode does not require installation proof.
    result = r.resolve(
        SnapshotSelector(
            channel=Channel.FORMAL,
            knowledge_as_of="2020-01-01T00:00:00+00:00",
            knowledge_mode=KnowledgeMode.MARKET_AVAILABLE,
        )
    )
    assert result.knowledge_mode == "market_available"


def test_latest_installation_observed_is_proven(pit):
    r, fx = pit
    result = r.resolve(SnapshotSelector(channel=Channel.FORMAL, knowledge_as_of=None))
    assert result.pit_valid is True


def test_future_rows_not_visible_at_cut(pit):
    r, fx = pit
    # Cut at 2024-08-01: formal run bars after that (by available_at proxy fetched)
    # Formal rows available_at is bar_close (historical), so a mid-history cut keeps
    # only rows whose available_at <= cut.
    result = r.resolve(
        SnapshotSelector(
            channel=Channel.FORMAL,
            knowledge_as_of="2024-08-01T00:00:00+00:00",
            knowledge_mode=KnowledgeMode.MARKET_AVAILABLE,
            date_from="2024-07-19",
            date_to="2026-07-11",
        )
    )
    # All visible rows have available_at <= cut.
    assert all(row.available_at is None or row.available_at <= "2024-08-01T00:00:00+00:00" for row in result.rows)
    # And there is at least one row (early history) visible.
    assert result.rows


def test_latest_restated_is_flagged_not_pit(pit):
    r, fx = pit
    result = r.resolve(
        SnapshotSelector(channel=Channel.FORMAL, revision_policy=RevisionPolicy.LATEST_RESTATED)
    )
    assert result.pit_valid is False
    assert ReasonCode.RESTATED_NOT_PIT.value in result.reason_codes


def test_deterministic_replay_same_hash(pit):
    r, fx = pit
    a = r.resolve(SnapshotSelector(channel=Channel.FORMAL, knowledge_as_of="2026-07-15T00:00:00+00:00", knowledge_mode=KnowledgeMode.MARKET_AVAILABLE))
    b = r.resolve(SnapshotSelector(channel=Channel.FORMAL, knowledge_as_of="2026-07-15T00:00:00+00:00", knowledge_mode=KnowledgeMode.MARKET_AVAILABLE))
    assert a.context.snapshot_id == b.context.snapshot_id
    assert [row.date for row in a.rows] == [row.date for row in b.rows]


def test_installation_observed_cut_filters_by_fetched_at(tmp_path):
    # Two PIT runs: an early run (created + fetched early) establishes the proven
    # window; a later run fetches a fresh tail. An as-of within the proven window
    # but before the later fetch must not show the later run's freshly-fetched tail.
    from tests.observatory.fixtures import build_pit_run

    data_root = tmp_path / "data"
    # Early run: created 2026-07-05, fetched 2026-07-05 -> establishes proven window.
    build_pit_run(
        data_root, "pitrun_early00000000000001",
        created_at="2026-07-05T00:00:00+00:00", days=60,
        fetched_at=datetime(2026, 7, 5, tzinfo=timezone.utc),
    )
    # Later run: created 2026-07-20, fetched 2026-07-20 -> fresh tail.
    build_pit_run(
        data_root, "pitrun_late000000000000001",
        created_at="2026-07-20T00:00:00+00:00", days=100,
        fetched_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    catalog_store.rebuild(data_root)
    r = PointInTimeResolver(data_root)
    # installation_observed at 2026-07-06 is inside the proven window (>= 2026-07-05)
    # but before the late fetch. Rows fetched at 2026-07-20 must be filtered out.
    result = r.resolve(
        SnapshotSelector(
            channel=Channel.OBSERVED,
            knowledge_as_of="2026-07-06T00:00:00+00:00",
            knowledge_mode=KnowledgeMode.INSTALLATION_OBSERVED,
        )
    )
    assert all(
        row.fetched_at is None or row.fetched_at <= "2026-07-06T00:00:00+00:00"
        for row in result.rows
    )
