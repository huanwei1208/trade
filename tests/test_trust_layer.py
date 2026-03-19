"""Tests for the trust layer (Phase A of EBRT_04 refactoring).

Verifies:
- TrustBreakdown dataclass and to_dict()
- compute_prediction_trust() formula and threshold logic
- compute_portfolio_trust() aggregation
- FreshnessReport / DataSnapshot contracts (Phase C)
- Factor group column coverage (Phase B)
"""
from __future__ import annotations

import pytest

from trade_py.trust import TrustBreakdown, compute_prediction_trust, compute_portfolio_trust
from trade_py.data.contracts import (
    DataSnapshot,
    FreshnessReport,
    build_freshness_report,
    snapshot_from_sync_state,
    STALE_THRESHOLD_DAYS,
)
from trade_py.factors.definitions import FEATURE_COLS, FEATURE_SCHEMA_VERSION
from trade_py.factors.groups import (
    FactorGroupResult,
    EVENT_FEATURE_COLS,
    SENTIMENT_FEATURE_COLS,
    TECHNICAL_FEATURE_COLS,
    INSTRUMENT_FEATURE_COLS,
)


# ── Phase A: TrustBreakdown ────────────────────────────────────────────────────

class TestTrustBreakdown:
    def test_to_dict_keys(self):
        b = TrustBreakdown(
            trust_score=0.75,
            trust_level="HIGH",
            feature_coverage=0.90,
            missing_features=["bf_novelty"],
            used_defaults=["window_score"],
            data_freshness_score=0.9,
            model_version="test_model_v1",
        )
        d = b.to_dict()
        for key in [
            "trust_score", "trust_level", "feature_coverage",
            "missing_features", "used_defaults", "data_freshness_score",
            "model_version", "feature_schema_version", "trace_id",
            "generation_method", "warnings",
        ]:
            assert key in d, f"Missing key: {key}"

    def test_unavailable_sentinel(self):
        b = TrustBreakdown.unavailable("test_reason")
        assert b.trust_score == 0.0
        assert b.trust_level == "LOW"
        assert "inference_unavailable:test_reason" in b.warnings

    def test_to_dict_values_rounded(self):
        b = TrustBreakdown(trust_score=0.123456789, trust_level="MEDIUM", feature_coverage=0.987654321)
        d = b.to_dict()
        assert d["trust_score"] == 0.1235
        assert d["feature_coverage"] == 0.9877


class TestComputePredictionTrust:
    """Verify trust score formula is deterministic and monotone."""

    _COLS = ["hop", "kg_score", "window_score", "net_sentiment", "tech_rsi_14"]

    def test_perfect_data_high_trust(self):
        # All features present and non-default, fresh data
        values = {col: 99.9 for col in self._COLS}
        t = compute_prediction_trust(
            factor_values=values,
            expected_cols=self._COLS,
            data_lag_days=0,
        )
        assert t.trust_level == "HIGH"
        assert t.trust_score > 0.70
        assert t.feature_coverage == 1.0
        assert not t.missing_features

    def test_missing_features_lower_trust(self):
        # Half features missing
        values = {col: 1.0 for col in self._COLS[:2]}
        t = compute_prediction_trust(
            factor_values=values,
            expected_cols=self._COLS,
            data_lag_days=0,
        )
        t_full = compute_prediction_trust(
            factor_values={col: 1.0 for col in self._COLS},
            expected_cols=self._COLS,
            data_lag_days=0,
        )
        assert t.trust_score < t_full.trust_score
        assert len(t.missing_features) == 3

    def test_stale_data_lower_trust(self):
        values = {col: 1.0 for col in self._COLS}
        t_fresh = compute_prediction_trust(values, self._COLS, data_lag_days=0)
        t_stale = compute_prediction_trust(values, self._COLS, data_lag_days=10)
        assert t_stale.trust_score < t_fresh.trust_score
        assert any("stale_data" in w for w in t_stale.warnings)

    def test_default_sentinels_detected(self):
        sentinels = {"window_score": 50.0, "net_sentiment": 0.0}
        values = {"window_score": 50.0, "net_sentiment": 0.0, "hop": 0.0}
        t = compute_prediction_trust(
            factor_values=values,
            expected_cols=list(sentinels.keys()),
            data_lag_days=0,
            default_value_sentinels=sentinels,
        )
        assert "window_score" in t.used_defaults
        assert "net_sentiment" in t.used_defaults
        assert any("used_defaults" in w for w in t.warnings)

    def test_low_coverage_warning(self):
        # Only 1 out of 10 features present — should trigger low_coverage warning
        cols = [f"f{i}" for i in range(10)]
        t = compute_prediction_trust(
            factor_values={"f0": 1.0},
            expected_cols=cols,
            data_lag_days=0,
        )
        assert any("low_feature_coverage" in w for w in t.warnings)
        # 10% coverage + 0% freshness penalty → trust is LOW or MEDIUM (not HIGH)
        assert t.trust_level in ("LOW", "MEDIUM")
        assert t.trust_score < 0.70

    def test_trust_score_in_unit_interval(self):
        for n_present in [0, 1, 5, 10, 10]:
            cols = [f"f{i}" for i in range(10)]
            vals = {f"f{i}": 1.0 for i in range(n_present)}
            t = compute_prediction_trust(vals, cols, data_lag_days=0)
            assert 0.0 <= t.trust_score <= 1.0

    def test_trust_level_thresholds(self):
        cols = ["f0"]
        high = compute_prediction_trust({"f0": 1.0}, cols, data_lag_days=0)
        low = compute_prediction_trust({}, cols, data_lag_days=10)
        assert high.trust_level == "HIGH"
        assert low.trust_level in ("LOW", "MEDIUM")

    def test_deterministic(self):
        """Same input → same output every time."""
        values = {"hop": 1.0, "kg_score": 0.5, "window_score": 60.0}
        cols = ["hop", "kg_score", "window_score"]
        t1 = compute_prediction_trust(values, cols, data_lag_days=2, trace_id="fixed")
        t2 = compute_prediction_trust(values, cols, data_lag_days=2, trace_id="fixed")
        assert t1.trust_score == t2.trust_score
        assert t1.trust_level == t2.trust_level


class TestComputePortfolioTrust:
    def test_empty_input(self):
        result = compute_portfolio_trust({})
        assert result["n_symbols"] == 0
        assert result["mean_trust_score"] == 0.0

    def test_aggregation(self):
        b1 = TrustBreakdown(trust_score=0.8, trust_level="HIGH", feature_coverage=1.0)
        b2 = TrustBreakdown(trust_score=0.3, trust_level="LOW", feature_coverage=0.5)
        result = compute_portfolio_trust({"SYM1": b1, "SYM2": b2})
        assert result["n_symbols"] == 2
        assert abs(result["mean_trust_score"] - 0.55) < 0.01
        assert "SYM2" in result["low_trust_symbols"]
        assert "SYM1" not in result["low_trust_symbols"]


# ── Phase C: Data Contracts ─────────────────────────────────────────────────────

class TestDataSnapshot:
    def test_to_dict_keys(self):
        snap = DataSnapshot(
            dataset="kline", symbol="000001.SZ", as_of_date="2026-03-19",
            latest_available_date="2026-03-18", freshness_days=1,
        )
        d = snap.to_dict()
        for key in ["dataset", "symbol", "as_of_date", "latest_available_date",
                    "freshness_days", "row_count", "missing_columns",
                    "schema_version", "quality_flags"]:
            assert key in d


class TestFreshnessReport:
    def test_fresh_data(self):
        from datetime import date
        snap = snapshot_from_sync_state("kline", "2026-03-19", date(2026, 3, 19))
        report = build_freshness_report([snap])
        assert report.overall_freshness_score == 1.0
        assert report.overall_lag_days == 0
        assert not report.stale_datasets

    def test_stale_data_flagged(self):
        from datetime import date
        snap = snapshot_from_sync_state("kline", "2026-03-19", date(2026, 3, 14))
        assert snap.freshness_days == 5
        assert "stale" in snap.quality_flags

    def test_missing_data(self):
        snap = snapshot_from_sync_state("signals", "2026-03-19", None)
        assert snap.freshness_days is None
        assert "no_data" in snap.quality_flags

    def test_overall_score_weighted(self):
        from datetime import date
        snaps = [
            snapshot_from_sync_state("kline", "2026-03-19", date(2026, 3, 19)),    # lag 0
            snapshot_from_sync_state("signals", "2026-03-19", date(2026, 3, 14)),  # lag 5
        ]
        report = build_freshness_report(snaps)
        # kline weight=0.30, signals weight=0.25 → weighted avg < 1.0
        assert report.overall_freshness_score < 1.0
        assert "signals" in report.stale_datasets

    def test_to_dict_structure(self):
        from datetime import date
        snaps = [snapshot_from_sync_state("kline", "2026-03-19", date(2026, 3, 19))]
        report = build_freshness_report(snaps)
        d = report.to_dict()
        for key in ["overall_freshness_score", "overall_lag_days",
                    "stale_datasets", "missing_datasets", "as_of_date", "snapshots"]:
            assert key in d


# ── Phase B: Factor Group Column Coverage ──────────────────────────────────────

class TestFactorGroupColumns:
    def test_total_columns_matches_feature_cols(self):
        all_group_cols = (
            EVENT_FEATURE_COLS
            + SENTIMENT_FEATURE_COLS
            + TECHNICAL_FEATURE_COLS
            + INSTRUMENT_FEATURE_COLS
        )
        assert len(all_group_cols) == len(FEATURE_COLS), (
            f"Group cols ({len(all_group_cols)}) != FEATURE_COLS ({len(FEATURE_COLS)})"
        )

    def test_group_cols_are_subset_of_feature_cols(self):
        all_group_cols = set(
            EVENT_FEATURE_COLS
            + SENTIMENT_FEATURE_COLS
            + TECHNICAL_FEATURE_COLS
            + INSTRUMENT_FEATURE_COLS
        )
        missing = all_group_cols - set(FEATURE_COLS)
        extra = set(FEATURE_COLS) - all_group_cols
        assert not missing, f"Group cols not in FEATURE_COLS: {missing}"
        assert not extra, f"FEATURE_COLS not covered by any group: {extra}"

    def test_feature_schema_version_exists(self):
        assert FEATURE_SCHEMA_VERSION, "FEATURE_SCHEMA_VERSION must be non-empty"
        assert FEATURE_SCHEMA_VERSION == "v1"

    def test_factor_group_result_empty(self):
        cols = ["f1", "f2"]
        result = FactorGroupResult.empty("test_group", cols)
        assert result.coverage == 0.0
        assert result.missing == ["f1", "f2"]
        assert result.values.empty or set(result.values.columns) >= {"date", "symbol", "f1", "f2"}
