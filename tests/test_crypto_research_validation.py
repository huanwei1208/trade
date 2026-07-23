from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from trade_py.analysis.crypto_validation import (
    CryptoValidationConfig,
    benjamini_hochberg,
    build_btc_volatility_frame,
    build_purged_walk_forward_folds,
    select_non_overlapping_events,
    validate_btc_volatility,
)


def _frame_from_returns(returns: np.ndarray, *, start: str = "2020-01-01") -> pd.DataFrame:
    dates = pd.date_range(start, periods=len(returns), freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "close": 30_000.0 * np.exp(np.cumsum(returns)),
            "available_at": dates.tz_localize("UTC") + pd.Timedelta(days=1),
        }
    )


def _positive_persistence_frame(row_count: int = 1_800) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    returns: list[float] = []
    high_regime = False
    for _ in range(row_count):
        if high_regime:
            if rng.random() < 0.035:
                high_regime = False
        elif rng.random() < 0.035:
            high_regime = True
        returns.append(rng.normal(0.0, 0.055 if high_regime else 0.002))
    return _frame_from_returns(np.asarray(returns))


def _anti_persistence_frame(row_count: int = 1_600) -> pd.DataFrame:
    rng = np.random.default_rng(44)
    returns = rng.normal(0.0, 0.010, row_count)
    position = 100
    event_number = 0
    while position < row_count - 30:
        returns[position] = rng.choice([-1.0, 1.0]) * (0.14 + 0.001 * event_number)
        returns[position + 1 : position + 22] = rng.normal(0.0, 0.0007, 21)
        position += int(rng.integers(45, 75))
        event_number += 1
    return _frame_from_returns(returns)


def _fast_default_config() -> CryptoValidationConfig:
    return CryptoValidationConfig(bootstrap_iterations=200)


def _fast_relaxed_config() -> CryptoValidationConfig:
    return CryptoValidationConfig(
        threshold_min_history=60,
        minimum_events=8,
        minimum_events_per_fold=1,
        minimum_valid_folds=3,
        bootstrap_iterations=200,
    )


def test_features_are_past_only_and_latest_horizons_remain_pending() -> None:
    rng = np.random.default_rng(9)
    returns = rng.normal(0.0002, 0.012, 360)
    base = _frame_from_returns(returns[:320])
    extended = _frame_from_returns(returns)

    base_features = build_btc_volatility_frame(base)
    extended_features = build_btc_volatility_frame(extended)

    for column in ("rv20", "rv20_threshold", "high_vol"):
        pd.testing.assert_series_equal(
            base_features[column],
            extended_features.loc[: len(base) - 1, column],
            check_names=False,
        )

    anchor = 250
    expected_future_rv = float(
        extended_features.loc[anchor + 1 : anchor + 7, "log_return"].std(ddof=1)
        * math.sqrt(365.0)
    )
    expected_abs_return = abs(
        float(extended_features.loc[anchor + 7, "close"])
        / float(extended_features.loc[anchor, "close"])
        - 1.0
    )
    assert extended_features.loc[anchor, "future_rv7"] == pytest.approx(expected_future_rv)
    assert extended_features.loc[anchor, "abs_ret7"] == pytest.approx(expected_abs_return)

    pending = base_features.tail(7)
    assert pending["label_status"].eq("pending_horizon").all()
    assert pending["future_rv7"].isna().all()
    assert pending["abs_ret7"].isna().all()
    matured = extended_features.loc[
        len(base) - 7 : len(base) - 1,
        "label_status",
    ]
    assert matured.eq("ready").all()


def test_feature_is_unavailable_when_a_past_input_arrives_after_the_anchor() -> None:
    frame = _frame_from_returns(np.full(260, 0.001))
    frame.loc[220, "available_at"] = pd.Timestamp("2030-01-01T00:00:00Z")

    features = build_btc_volatility_frame(
        frame,
        CryptoValidationConfig(threshold_min_history=20),
    )

    assert features.loc[220:240, "feature_status"].eq("unavailable_input").all()
    assert features.loc[220:240, "rv20"].isna().all()
    assert features.loc[220:240, "high_vol"].eq(False).all()


def test_backfilled_future_availability_cannot_retroactively_validate_history() -> None:
    frame = _frame_from_returns(np.full(260, 0.001))
    frame["available_at"] = pd.Timestamp("2030-01-01T00:00:00Z")

    features = build_btc_volatility_frame(
        frame,
        CryptoValidationConfig(threshold_min_history=20),
    )

    assert features["feature_status"].ne("ready").all()
    assert features["rv20"].isna().all()
    assert features["rv20_threshold"].isna().all()


def test_small_historical_gap_marks_local_windows_unavailable_not_global_invalid() -> None:
    frame = _frame_from_returns(np.full(420, 0.001)).drop(index=210).reset_index(drop=True)

    features = build_btc_volatility_frame(frame)
    result = validate_btc_volatility(frame, "ready", _fast_default_config())

    missing_row = features.index[features["date"].eq(pd.Timestamp("2020-07-29"))][0]
    assert pd.isna(features.loc[missing_row, "close"])
    assert features.loc[missing_row, "feature_status"] == "missing_input"
    assert features.loc[missing_row, "label_status"] == "missing_horizon"
    assert result["status"] != "invalid"


def test_events_are_deoverlapped_and_walk_forward_folds_are_label_safe() -> None:
    config = _fast_default_config()
    features = build_btc_volatility_frame(_positive_persistence_frame(), config)

    events = select_non_overlapping_events(features, config.event_gap_days)
    event_gaps = events["date"].diff().dropna() / pd.Timedelta(days=1)
    assert not events.empty
    assert event_gaps.ge(7).all()

    folds = build_purged_walk_forward_folds(features, config)
    assert folds
    first = folds[0]
    assert first["train_rows"] == 180
    assert first["test_rows"] == 60
    assert first["purge_embargo_days"] == 7
    first_gap = pd.Timestamp(first["test_start"]) - pd.Timestamp(first["train_end"])
    assert first_gap.days == 8

    # The next expanding training set excludes the final seven anchors of the
    # previous test, whose forward labels would cross the new test boundary.
    second = folds[1]
    embargo = pd.Timestamp(first["test_end"]) - pd.Timestamp(second["train_end"])
    assert embargo.days == 7
    assert sum(fold["valid"] for fold in folds) >= 3


def test_benjamini_hochberg_preserves_input_order_and_monotonic_adjustment() -> None:
    adjusted = benjamini_hochberg([0.01, 0.04, 0.03, 0.002])
    assert adjusted == [0.02, 0.04, 0.04, 0.008]
    assert benjamini_hochberg([]) == []


def test_fold_effect_uses_same_test_window_normals_not_lower_level_training() -> None:
    config = CryptoValidationConfig(
        threshold_min_history=2,
        minimum_history_days=20,
        initial_train_days=10,
        test_days=10,
        step_days=10,
        purge_embargo_days=7,
        minimum_valid_folds=1,
        minimum_events=1,
        minimum_events_per_fold=1,
        bootstrap_iterations=20,
    )
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=27, freq="D"),
            "high_vol": False,
            "label_status": "ready",
            "future_rv7": [1.0] * 17 + [2.0] * 10,
            "rv20_threshold": 1.0,
        }
    )
    frame.loc[[17, 24], "high_vol"] = True

    fold = build_purged_walk_forward_folds(frame, config)[0]

    assert fold["training_normal_count"] == 10
    assert fold["test_normal_count"] == 8
    assert fold["future_rv7_median_ratio"] == pytest.approx(1.0)
    assert fold["positive_effect"] is False


def test_readiness_and_sample_gates_return_explicit_non_validated_states() -> None:
    small = _frame_from_returns(np.full(240, 0.001))

    insufficient = validate_btc_volatility(small, "ready", _fast_default_config())
    assert insufficient["status"] == "insufficient_data"
    assert "MINIMUM_HISTORY_DAYS_NOT_MET" in insufficient["reasons"]
    assert insufficient["causal"] is False
    assert insufficient["recommendation"] is None

    degraded = validate_btc_volatility(small, "degraded", _fast_default_config())
    assert degraded["status"] == "candidate"
    assert degraded["metrics"] is None

    blocked = validate_btc_volatility(small, "insufficient_data", _fast_default_config())
    assert blocked["status"] == "insufficient_data"
    assert blocked["metrics"] is None
    assert insufficient["run_id"] != degraded["run_id"]

    malformed = small.copy()
    malformed.loc[10, "date"] = malformed.loc[9, "date"]
    invalid = validate_btc_volatility(malformed, "ready", _fast_default_config())
    assert invalid["status"] == "invalid"
    assert invalid["reasons"] == ["INVALID_CANONICAL_INPUT"]


def test_validation_run_id_includes_data_assurance_lineage() -> None:
    frame = _frame_from_returns(np.full(240, 0.001))

    first = validate_btc_volatility(
        frame,
        "ready",
        _fast_default_config(),
        assurance_evidence={"data_run_id": "assurance-a"},
    )
    second = validate_btc_volatility(
        frame,
        "ready",
        _fast_default_config(),
        assurance_evidence={"data_run_id": "assurance-b"},
    )

    assert first["run_id"] != second["run_id"]
    assert first["input_evidence"]["data_assurance_hash"] != second["input_evidence"][
        "data_assurance_hash"
    ]


def test_stable_positive_effect_is_validated_and_replay_is_deterministic() -> None:
    frame = _positive_persistence_frame()
    config = _fast_default_config()

    first = validate_btc_volatility(frame, "ready", config)
    replay = validate_btc_volatility(frame.copy(), "ready", config)

    assert first == replay
    assert first["status"] == "validated"
    assert first["causal"] is False
    assert first["recommendation"] is None
    assert first["metrics"]["future_rv7_median_ratio"] >= 1.10
    assert first["confidence_interval"]["lower"] > 1.0
    assert first["q_value"] <= 0.10
    assert first["metrics"]["positive_fold_fraction"] >= 2.0 / 3.0
    assert not first["placebos"]["time_shifted_labels"]["passed_registered_gate"]
    assert not first["placebos"]["randomized_labels"]["passed_registered_gate"]
    assert first["placebos"]["past_only_invariance"]["passed"]
    all_valid_ids = [fold["fold_id"] for fold in first["folds"] if fold["valid"]]
    retained_ids = [
        fold["fold_id"] for fold in first["folds"] if fold["retained_for_evaluation"]
    ]
    assert retained_ids == all_valid_ids[-config.maximum_evaluation_folds :]
    assert len(retained_ids) <= 5

    revised = frame.copy()
    revised.loc[len(revised) - 1, "close"] *= 1.001
    changed = validate_btc_volatility(revised, "ready", config)
    assert changed["run_id"] != first["run_id"]
    assert changed["input_evidence"]["input_hash"] != first["input_evidence"]["input_hash"]


def test_complete_but_unstable_evidence_stays_monitoring() -> None:
    rng = np.random.default_rng(17)
    frame = _frame_from_returns(rng.normal(0.0, 0.012, 800))

    result = validate_btc_volatility(frame, "ready", _fast_relaxed_config())

    assert result["status"] == "monitoring"
    assert result["sample"]["valid_fold_count"] >= 3
    assert result["confidence_interval"]["lower"] <= 1.0
    assert result["reasons"]


def test_significant_opposite_effect_is_rejected_without_directional_claims() -> None:
    result = validate_btc_volatility(
        _anti_persistence_frame(),
        "ready",
        _fast_relaxed_config(),
    )

    assert result["status"] == "rejected"
    assert result["confidence_interval"]["upper"] < 1.0
    assert result["opposite_q_value"] <= 0.10
    assert result["causal"] is False
    assert result["recommendation"] is None
    assert result["reasons"] == ["SIGNIFICANT_OPPOSITE_EFFECT"]


def test_a_registered_time_shift_placebo_blocks_statistical_status() -> None:
    row_count = 1_300
    returns = np.zeros(row_count)
    for position in range(row_count):
        phase = position % 42
        cycle = position // 42
        if phase == 14:
            returns[position] = 0.12 + cycle * 0.001
        elif 15 <= phase <= 34:
            returns[position] = 0.0008 * math.sin(position)
        else:
            returns[position] = 0.012 * math.sin(2.0 * math.pi * position / 5.0)

    result = validate_btc_volatility(
        _frame_from_returns(returns),
        "ready",
        _fast_relaxed_config(),
    )

    assert result["status"] == "invalid"
    assert result["placebos"]["time_shifted_labels"]["passed_registered_gate"]
    assert result["reasons"] == ["PLACEBO_TIME_SHIFTED_LABELS_PASSED"]
