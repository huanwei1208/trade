"""Point-in-time-safe validation for the BTC volatility-persistence study.

The module is deliberately independent of providers, storage, the warehouse,
and CLI concerns.  Its only market-data input is a canonical daily BTC frame;
the caller must also provide the separately computed data-readiness state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd


CONTRACT_VERSION = "crypto-btc-volatility-v1"
HYPOTHESIS_ID = "btc-volatility-persistence-h1"
_READINESS_STATES = {"invalid", "insufficient_data", "ready", "degraded"}


@dataclass(frozen=True)
class CryptoValidationConfig:
    """Frozen defaults for the pre-registered BTC H1 validation."""

    contract_version: str = CONTRACT_VERSION
    rv_window_days: int = 20
    future_window_days: int = 7
    annualization_days: int = 365
    threshold_quantile: float = 0.80
    threshold_min_history: int = 180
    minimum_history_days: int = 365
    event_gap_days: int = 7
    initial_train_days: int = 180
    test_days: int = 60
    step_days: int = 60
    purge_embargo_days: int = 7
    minimum_valid_folds: int = 3
    minimum_events: int = 30
    minimum_events_per_fold: int = 3
    minimum_normals_per_fold: int = 8
    maximum_evaluation_folds: int = 5
    practical_effect_ratio: float = 1.10
    confidence_level: float = 0.95
    maximum_q_value: float = 0.10
    positive_fold_fraction: float = 2.0 / 3.0
    bootstrap_iterations: int = 1_000
    bootstrap_block_days: int = 7
    placebo_shift_days: int = 60
    random_seed: int = 20_260_710

    def __post_init__(self) -> None:
        positive_integer_fields = (
            "rv_window_days",
            "future_window_days",
            "annualization_days",
            "threshold_min_history",
            "minimum_history_days",
            "event_gap_days",
            "initial_train_days",
            "test_days",
            "step_days",
            "purge_embargo_days",
            "minimum_valid_folds",
            "minimum_events",
            "minimum_events_per_fold",
            "minimum_normals_per_fold",
            "maximum_evaluation_folds",
            "bootstrap_iterations",
            "bootstrap_block_days",
            "placebo_shift_days",
        )
        for field_name in positive_integer_fields:
            if int(getattr(self, field_name)) <= 0:
                raise ValueError(f"{field_name} must be positive")
        if not 0.0 < self.threshold_quantile < 1.0:
            raise ValueError("threshold_quantile must be between zero and one")
        if not 0.0 < self.confidence_level < 1.0:
            raise ValueError("confidence_level must be between zero and one")
        if not 0.0 < self.maximum_q_value <= 1.0:
            raise ValueError("maximum_q_value must be in (0, 1]")
        if not 0.0 < self.positive_fold_fraction <= 1.0:
            raise ValueError("positive_fold_fraction must be in (0, 1]")
        if self.purge_embargo_days < self.future_window_days:
            raise ValueError("purge_embargo_days must cover the forward horizon")


def _stable_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (str, int, bool)):
        return value
    return str(value)


def _stable_json(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def _implementation_revision() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _hash_frame(frame: pd.DataFrame) -> str:
    columns = sorted(str(column) for column in frame.columns)
    work = frame.reindex(columns=columns)
    records = [
        {column: _stable_value(value) for column, value in row.items()}
        for row in work.to_dict(orient="records")
    ]
    return _sha256_payload({"columns": columns, "records": records})


def _normalize_canonical_frame(canonical_btc: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(canonical_btc, pd.DataFrame):
        raise ValueError("canonical BTC input must be a pandas DataFrame")
    missing = {"date", "close", "available_at"} - set(canonical_btc.columns)
    if missing:
        raise ValueError(f"canonical BTC input missing columns: {sorted(missing)}")

    frame = canonical_btc.copy()
    parsed_dates = pd.to_datetime(frame["date"], errors="coerce", utc=True)
    if parsed_dates.isna().any():
        raise ValueError("canonical BTC input contains an invalid date")
    frame["date"] = parsed_dates.dt.tz_convert(None).dt.normalize()
    available_at = pd.to_datetime(frame["available_at"], errors="coerce", utc=True)
    if available_at.isna().any():
        raise ValueError("canonical BTC input contains an invalid available_at")
    frame["available_at"] = available_at
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    close_values = frame["close"].to_numpy(dtype=float)
    if not np.isfinite(close_values).all() or (close_values <= 0.0).any():
        raise ValueError("canonical BTC close values must be finite and positive")

    frame = frame.sort_values("date", kind="mergesort").reset_index(drop=True)
    if frame["date"].duplicated().any():
        raise ValueError("canonical BTC input contains duplicate UTC dates")
    return frame


def build_btc_volatility_frame(
    canonical_btc: pd.DataFrame,
    config: CryptoValidationConfig | None = None,
) -> pd.DataFrame:
    """Build past-only features and explicit seven-day forward labels.

    ``rv20_threshold`` at date *t* is based on ``rv20`` observations strictly
    before *t*.  The latest seven anchors retain missing numeric labels and are
    marked ``pending_horizon`` rather than being filled with zero.
    """

    config = config or CryptoValidationConfig()
    frame = _normalize_canonical_frame(canonical_btc)
    if not frame.empty:
        calendar = pd.date_range(frame["date"].min(), frame["date"].max(), freq="D")
        frame = (
            frame.set_index("date")
            .reindex(calendar)
            .rename_axis("date")
            .reset_index()
        )
    frame["log_return"] = np.log(frame["close"] / frame["close"].shift(1))
    annualizer = math.sqrt(float(config.annualization_days))
    raw_rv20 = (
        frame["log_return"]
        .rolling(config.rv_window_days, min_periods=config.rv_window_days)
        .std(ddof=1)
        * annualizer
    )
    availability_present = frame["available_at"].notna()
    availability_ns = frame["available_at"].astype("datetime64[ns, UTC]").astype("int64")
    latest_input_availability_ns = availability_ns.rolling(
        config.rv_window_days + 1,
        min_periods=config.rv_window_days + 1,
    ).max()
    complete_input_window = (
        frame["close"].notna().rolling(config.rv_window_days + 1).sum()
        == config.rv_window_days + 1
    ) & (
        availability_present.rolling(config.rv_window_days + 1).sum()
        == config.rv_window_days + 1
    )
    anchor_close_ns = (
        frame["date"].dt.tz_localize("UTC") + pd.Timedelta(days=1)
    ).astype("datetime64[ns, UTC]").astype("int64")
    point_in_time_ready = (
        complete_input_window
        & latest_input_availability_ns.le(anchor_close_ns)
    )
    positions = np.arange(len(frame))
    frame["feature_status"] = np.select(
        [
            positions < config.rv_window_days,
            ~complete_input_window.to_numpy(dtype=bool),
            ~point_in_time_ready.to_numpy(dtype=bool),
        ],
        ["insufficient_history", "missing_input", "unavailable_input"],
        default="ready",
    )
    frame["rv20"] = raw_rv20.where(point_in_time_ready)
    frame["rv20_threshold"] = (
        frame["rv20"]
        .shift(1)
        .expanding(min_periods=config.threshold_min_history)
        .quantile(config.threshold_quantile)
    )
    frame["high_vol"] = (
        frame["rv20"].notna()
        & frame["rv20_threshold"].notna()
        & frame["rv20"].ge(frame["rv20_threshold"])
    )

    frame["future_rv7"] = (
        frame["log_return"]
        .rolling(config.future_window_days, min_periods=config.future_window_days)
        .std(ddof=1)
        .shift(-config.future_window_days)
        * annualizer
    )
    frame["abs_ret7"] = (
        frame["close"].shift(-config.future_window_days) / frame["close"] - 1.0
    ).abs()
    horizon_ready = frame["future_rv7"].notna() & frame["abs_ret7"].notna()
    pending_horizon = positions >= max(len(frame) - config.future_window_days, 0)
    frame["label_status"] = np.select(
        [horizon_ready.to_numpy(dtype=bool), pending_horizon],
        ["ready", "pending_horizon"],
        default="missing_horizon",
    )
    return frame


def select_non_overlapping_events(
    frame: pd.DataFrame,
    min_gap_days: int = 7,
) -> pd.DataFrame:
    """Select high-volatility events greedily in time, at least ``gap`` apart."""

    if min_gap_days <= 0:
        raise ValueError("min_gap_days must be positive")
    required = {"date", "high_vol", "label_status"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"feature frame missing columns: {sorted(missing)}")
    candidates = frame.loc[
        frame["high_vol"].eq(True) & frame["label_status"].eq("ready")  # noqa: E712
    ].sort_values("date", kind="mergesort")
    selected_indexes: list[Any] = []
    previous_date: pd.Timestamp | None = None
    for index, row in candidates.iterrows():
        event_date = pd.Timestamp(row["date"])
        if previous_date is None or (event_date - previous_date).days >= min_gap_days:
            selected_indexes.append(index)
            previous_date = event_date
    selected = frame.loc[selected_indexes].copy()
    if not selected.empty:
        selected["event_id"] = selected["date"].map(
            lambda value: f"btc-vol-{pd.Timestamp(value).strftime('%Y-%m-%d')}"
        )
    else:
        selected["event_id"] = pd.Series(dtype="object")
    return selected.reset_index(drop=False).rename(columns={"index": "source_index"})


def _median_ratio(
    event_values: Iterable[float],
    normal_values: Iterable[float],
) -> float | None:
    events = np.asarray(list(event_values), dtype=float)
    normals = np.asarray(list(normal_values), dtype=float)
    events = events[np.isfinite(events)]
    normals = normals[np.isfinite(normals)]
    if len(events) == 0 or len(normals) == 0:
        return None
    normal_median = float(np.median(normals))
    if normal_median <= 0.0:
        return None
    return float(np.median(events) / normal_median)


def build_purged_walk_forward_folds(
    frame: pd.DataFrame,
    config: CryptoValidationConfig | None = None,
) -> list[dict[str, Any]]:
    """Return expanding 180/60/60 folds with a seven-day label-safe gap.

    Fold effects compare events and normal observations inside the same test
    window so a secular volatility-level trend cannot masquerade as a positive
    event effect. Training anchors still stop seven days before the test; on
    subsequent folds the final seven anchors of the preceding test are likewise
    embargoed from the expanded training sample.
    """

    config = config or CryptoValidationConfig()
    required = {
        "date",
        "high_vol",
        "label_status",
        "future_rv7",
        "rv20_threshold",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"feature frame missing columns: {sorted(missing)}")

    work = frame.sort_values("date", kind="mergesort").reset_index(drop=True).copy()
    selected = select_non_overlapping_events(work, config.event_gap_days)
    work["event_selected"] = False
    if not selected.empty:
        work.loc[selected["source_index"].astype(int), "event_selected"] = True

    folds: list[dict[str, Any]] = []
    first_test_start = config.initial_train_days + config.purge_embargo_days
    fold_id = 0
    for test_start in range(first_test_start, len(work), config.step_days):
        test_stop = test_start + config.test_days
        if test_stop > len(work):
            break
        train_stop = test_start - config.purge_embargo_days
        train = work.iloc[:train_stop]
        test = work.iloc[test_start:test_stop]
        train_normal = train.loc[
            train["label_status"].eq("ready")
            & train["rv20_threshold"].notna()
            & ~train["high_vol"].eq(True),  # noqa: E712
            "future_rv7",
        ].dropna()
        test_events = test.loc[
            test["label_status"].eq("ready") & test["event_selected"],
            "future_rv7",
        ].dropna()
        test_normal = test.loc[
            test["label_status"].eq("ready")
            & test["rv20_threshold"].notna()
            & ~test["high_vol"].eq(True),  # noqa: E712
            "future_rv7",
        ].dropna()
        ratio = _median_ratio(test_events, test_normal)
        valid = (
            len(test_events) >= config.minimum_events_per_fold
            and len(test_normal) >= config.minimum_normals_per_fold
            and ratio is not None
        )
        if len(test_events) < config.minimum_events_per_fold:
            reason = "minimum_events_per_fold_not_met"
        elif len(test_normal) < config.minimum_normals_per_fold:
            reason = "minimum_normals_per_fold_not_met"
        elif ratio is None:
            reason = "fold_ratio_not_estimable"
        else:
            reason = None
        folds.append(
            {
                "fold_id": fold_id,
                "train_start": work.iloc[0]["date"].strftime("%Y-%m-%d"),
                "train_end": work.iloc[train_stop - 1]["date"].strftime("%Y-%m-%d"),
                "test_start": work.iloc[test_start]["date"].strftime("%Y-%m-%d"),
                "test_end": work.iloc[test_stop - 1]["date"].strftime("%Y-%m-%d"),
                "train_rows": int(train_stop),
                "test_rows": int(config.test_days),
                "purge_embargo_days": int(config.purge_embargo_days),
                "event_count": int(len(test_events)),
                "training_normal_count": int(len(train_normal)),
                "test_normal_count": int(len(test_normal)),
                "future_rv7_median_ratio": ratio,
                "positive_effect": bool(ratio is not None and ratio > 1.0),
                "valid": bool(valid),
                "reason": reason,
            }
        )
        fold_id += 1
    return folds


def benjamini_hochberg(p_values: Sequence[float]) -> list[float]:
    """Return Benjamini-Hochberg adjusted p-values in original order."""

    values = np.asarray(list(p_values), dtype=float)
    if values.ndim != 1:
        raise ValueError("p_values must be one-dimensional")
    if not np.isfinite(values).all() or ((values < 0.0) | (values > 1.0)).any():
        raise ValueError("p_values must be finite values between zero and one")
    if len(values) == 0:
        return []
    order = np.argsort(values, kind="mergesort")
    ranked = values[order]
    adjusted = ranked * len(values) / np.arange(1, len(values) + 1, dtype=float)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    adjusted = np.clip(adjusted, 0.0, 1.0)
    restored = np.empty_like(adjusted)
    restored[order] = adjusted
    return [float(value) for value in restored]


def _moving_block_indexes(
    row_count: int,
    block_days: int,
    rng: np.random.Generator,
) -> np.ndarray:
    block_size = min(block_days, row_count)
    required_blocks = int(math.ceil(row_count / block_size))
    maximum_start = row_count - block_size
    starts = rng.integers(0, maximum_start + 1, size=required_blocks)
    indexes = np.concatenate(
        [np.arange(start, start + block_size, dtype=int) for start in starts]
    )
    return indexes[:row_count]


def _block_bootstrap_evidence(
    evaluation: pd.DataFrame,
    *,
    config: CryptoValidationConfig,
    seed: int,
) -> dict[str, float | int] | None:
    work = evaluation[["future_rv7", "group"]].copy()
    work["future_rv7"] = pd.to_numeric(work["future_rv7"], errors="coerce")
    work = work.replace([np.inf, -np.inf], np.nan).dropna(subset=["future_rv7"])
    observed = _median_ratio(
        work.loc[work["group"].eq(1), "future_rv7"],
        work.loc[work["group"].eq(0), "future_rv7"],
    )
    if observed is None or len(work) < config.bootstrap_block_days:
        return None

    groups = work["group"].to_numpy(dtype=int)
    values = work["future_rv7"].to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    samples: list[float] = []
    for _ in range(config.bootstrap_iterations):
        indexes = _moving_block_indexes(len(work), config.bootstrap_block_days, rng)
        ratio = _median_ratio(
            values[indexes][groups[indexes] == 1],
            values[indexes][groups[indexes] == 0],
        )
        if ratio is not None:
            samples.append(ratio)
    if len(samples) < max(20, config.bootstrap_iterations // 2):
        return None

    distribution = np.asarray(samples, dtype=float)
    tail = (1.0 - config.confidence_level) / 2.0
    lower, upper = np.quantile(distribution, [tail, 1.0 - tail])
    positive_p = (float(np.count_nonzero(distribution <= 1.0)) + 1.0) / (
        len(distribution) + 1.0
    )
    opposite_p = (float(np.count_nonzero(distribution >= 1.0)) + 1.0) / (
        len(distribution) + 1.0
    )
    return {
        "observed_ratio": float(observed),
        "ci_lower": float(lower),
        "ci_upper": float(upper),
        "positive_p_value": float(positive_p),
        "opposite_p_value": float(opposite_p),
        "bootstrap_samples": int(len(distribution)),
        "block_days": int(config.bootstrap_block_days),
        "seed": int(seed),
    }


def _past_only_invariance(
    canonical_btc: pd.DataFrame,
    full_features: pd.DataFrame,
    config: CryptoValidationConfig,
) -> dict[str, Any]:
    cutoff = len(canonical_btc) - max(
        config.future_window_days + 1,
        len(canonical_btc) // 5,
    )
    if cutoff <= config.rv_window_days:
        return {"passed": True, "compared_rows": 0, "maximum_absolute_difference": 0.0}
    prefix = canonical_btc.iloc[:cutoff].copy()
    prefix_features = build_btc_volatility_frame(prefix, config)
    cutoff_date = prefix_features.iloc[-1]["date"]
    comparable_full = full_features.loc[full_features["date"] <= cutoff_date].reset_index(drop=True)
    if len(prefix_features) != len(comparable_full):
        return {
            "passed": False,
            "compared_rows": int(len(prefix_features)),
            "maximum_absolute_difference": float("inf"),
        }
    columns = ["rv20", "rv20_threshold"]
    maximum_difference = 0.0
    for column in columns:
        left = prefix_features[column].to_numpy(dtype=float)
        right = comparable_full[column].to_numpy(dtype=float)
        finite = np.isfinite(left) & np.isfinite(right)
        if finite.any():
            maximum_difference = max(
                maximum_difference,
                float(np.max(np.abs(left[finite] - right[finite]))),
            )
        if not np.array_equal(np.isnan(left), np.isnan(right)):
            return {
                "passed": False,
                "compared_rows": int(cutoff),
                "maximum_absolute_difference": maximum_difference,
            }
    regimes_equal = bool(
        prefix_features["high_vol"].to_numpy(dtype=bool).tolist()
        == comparable_full["high_vol"].to_numpy(dtype=bool).tolist()
    )
    passed = regimes_equal and maximum_difference <= 1e-12
    return {
        "passed": bool(passed),
        "compared_rows": int(len(prefix_features)),
        "maximum_absolute_difference": float(maximum_difference),
    }


def _placebo_checks(
    evaluation: pd.DataFrame,
    config: CryptoValidationConfig,
) -> dict[str, Any]:
    shift = min(config.placebo_shift_days, max(1, len(evaluation) // 2))
    shifted = evaluation.copy()
    shifted["future_rv7"] = shifted["future_rv7"].shift(shift)
    shifted_evidence = _block_bootstrap_evidence(
        shifted,
        config=config,
        seed=config.random_seed + 101,
    )

    randomized = evaluation.copy()
    rng = np.random.default_rng(config.random_seed + 202)
    randomized["future_rv7"] = rng.permutation(randomized["future_rv7"].to_numpy())
    randomized_evidence = _block_bootstrap_evidence(
        randomized,
        config=config,
        seed=config.random_seed + 303,
    )

    def summarize(evidence: dict[str, float | int] | None) -> dict[str, Any]:
        if evidence is None:
            return {"passed_registered_gate": False, "evidence": None}
        passed = (
            float(evidence["observed_ratio"]) >= config.practical_effect_ratio
            and float(evidence["ci_lower"]) > 1.0
            and float(evidence["positive_p_value"]) <= config.maximum_q_value
        )
        return {"passed_registered_gate": bool(passed), "evidence": evidence}

    return {
        "time_shifted_labels": {"shift_days": int(shift), **summarize(shifted_evidence)},
        "randomized_labels": summarize(randomized_evidence),
    }


def _base_result(
    *,
    config: CryptoValidationConfig,
    data_readiness: str,
    input_hash: str,
    row_count: int,
    start: str | None,
    end: str | None,
    assurance_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config_payload = asdict(config)
    config_hash = _sha256_payload(config_payload)
    code_revision = _implementation_revision()
    data_assurance_hash = _sha256_payload(assurance_evidence or {})
    run_id = _sha256_payload(
        {
            "contract_version": config.contract_version,
            "code_revision": code_revision,
            "config_hash": config_hash,
            "input_hash": input_hash,
            "effective_as_of": end,
            "data_readiness": data_readiness,
            "data_assurance_hash": data_assurance_hash,
        }
    )[:24]
    return {
        "contract_version": config.contract_version,
        "code_revision": code_revision,
        "hypothesis_id": HYPOTHESIS_ID,
        "run_id": run_id,
        "status": "candidate",
        "data_readiness": data_readiness,
        "causal": False,
        "recommendation": None,
        "watermark": end,
        "configuration": config_payload,
        "input_evidence": {
            "input_hash": input_hash,
            "config_hash": config_hash,
            "code_revision": code_revision,
            "row_count": int(row_count),
            "start": start,
            "end": end,
            "feature_hash": None,
            "data_assurance_hash": data_assurance_hash,
            "data_assurance": dict(assurance_evidence or {}),
        },
        "sample": {
            "eligible_observations": 0,
            "event_count": 0,
            "normal_count": 0,
            "valid_fold_count": 0,
        },
        "metrics": None,
        "confidence_interval": None,
        "p_value": None,
        "q_value": None,
        "opposite_p_value": None,
        "opposite_q_value": None,
        "folds": [],
        "placebos": {},
        "reasons": [],
    }


def _finalize_result(result: dict[str, Any]) -> dict[str, Any]:
    payload = dict(result)
    payload.pop("evidence_hash", None)
    result["evidence_hash"] = _sha256_payload(payload)
    return result


def validate_btc_volatility(
    canonical_btc: pd.DataFrame,
    data_readiness: str,
    config: CryptoValidationConfig | None = None,
    *,
    assurance_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the pre-registered BTC volatility-persistence hypothesis.

    ``insufficient_data`` is a normal, auditable result.  A statistical status
    cannot become ``validated`` unless the separate data-assurance state is
    exactly ``ready``.
    """

    config = config or CryptoValidationConfig()
    raw_hash = (
        _hash_frame(canonical_btc)
        if isinstance(canonical_btc, pd.DataFrame)
        else _sha256_payload(str(canonical_btc))
    )
    try:
        frame = _normalize_canonical_frame(canonical_btc)
    except (TypeError, ValueError) as exc:
        result = _base_result(
            config=config,
            data_readiness=data_readiness,
            input_hash=raw_hash,
            row_count=len(canonical_btc) if isinstance(canonical_btc, pd.DataFrame) else 0,
            start=None,
            end=None,
            assurance_evidence=assurance_evidence,
        )
        result["status"] = "invalid"
        result["reasons"] = ["INVALID_CANONICAL_INPUT"]
        result["input_error"] = str(exc)
        return _finalize_result(result)

    start = frame.iloc[0]["date"].strftime("%Y-%m-%d") if len(frame) else None
    end = frame.iloc[-1]["date"].strftime("%Y-%m-%d") if len(frame) else None
    input_hash = _hash_frame(frame)
    result = _base_result(
        config=config,
        data_readiness=data_readiness,
        input_hash=input_hash,
        row_count=len(frame),
        start=start,
        end=end,
        assurance_evidence=assurance_evidence,
    )

    if data_readiness not in _READINESS_STATES:
        result["status"] = "invalid"
        result["reasons"] = ["INVALID_DATA_READINESS_STATE"]
        return _finalize_result(result)
    if data_readiness != "ready":
        result["status"] = {
            "invalid": "invalid",
            "insufficient_data": "insufficient_data",
            "degraded": "candidate",
        }[data_readiness]
        result["reasons"] = [f"DATA_READINESS_{data_readiness.upper()}"]
        return _finalize_result(result)

    features = build_btc_volatility_frame(frame, config)
    result["input_evidence"]["feature_hash"] = _hash_frame(
        features[
            [
                "date",
                "close",
                "available_at",
                "log_return",
                "rv20",
                "rv20_threshold",
                "high_vol",
                "feature_status",
                "future_rv7",
                "abs_ret7",
                "label_status",
            ]
        ]
    )
    invariance = _past_only_invariance(frame, features, config)
    result["placebos"]["past_only_invariance"] = invariance
    if not invariance["passed"]:
        result["status"] = "invalid"
        result["reasons"] = ["FUTURE_INFORMATION_LEAKAGE"]
        return _finalize_result(result)

    selected = select_non_overlapping_events(features, config.event_gap_days)
    features["event_selected"] = False
    if not selected.empty:
        features.loc[selected["source_index"].astype(int), "event_selected"] = True
    eligible = features.loc[
        features["label_status"].eq("ready") & features["rv20_threshold"].notna()
    ].copy()
    eligible["group"] = np.where(
        eligible["event_selected"],
        1,
        np.where(eligible["high_vol"].eq(False), 0, -1),  # noqa: E712
    )
    event_count = int(eligible["group"].eq(1).sum())
    normal_count = int(eligible["group"].eq(0).sum())
    folds = build_purged_walk_forward_folds(features, config)
    all_valid_folds = [fold for fold in folds if fold["valid"]]
    valid_folds = all_valid_folds[-config.maximum_evaluation_folds :]
    retained_fold_ids = {fold["fold_id"] for fold in valid_folds}
    for fold in folds:
        fold["retained_for_evaluation"] = fold["fold_id"] in retained_fold_ids
    result["folds"] = folds
    result["sample"] = {
        "eligible_observations": int(len(eligible)),
        "event_count": event_count,
        "normal_count": normal_count,
        "valid_fold_count": int(len(valid_folds)),
        "all_valid_fold_count": int(len(all_valid_folds)),
    }

    insufficient_reasons: list[str] = []
    if len(features) < config.minimum_history_days:
        insufficient_reasons.append("MINIMUM_HISTORY_DAYS_NOT_MET")
    if event_count < config.minimum_events:
        insufficient_reasons.append("MINIMUM_EVENT_COUNT_NOT_MET")
    if len(valid_folds) < config.minimum_valid_folds:
        insufficient_reasons.append("MINIMUM_VALID_FOLD_COUNT_NOT_MET")
    if normal_count == 0:
        insufficient_reasons.append("NO_NORMAL_COMPARATOR_OBSERVATIONS")
    if insufficient_reasons:
        result["status"] = "insufficient_data"
        result["reasons"] = insufficient_reasons
        return _finalize_result(result)

    aggregate = _block_bootstrap_evidence(
        eligible,
        config=config,
        seed=config.random_seed,
    )
    if aggregate is None:
        result["status"] = "insufficient_data"
        result["reasons"] = ["BOOTSTRAP_SAMPLE_NOT_ESTIMABLE"]
        return _finalize_result(result)

    positive_q = benjamini_hochberg([float(aggregate["positive_p_value"])])[0]
    opposite_q = benjamini_hochberg([float(aggregate["opposite_p_value"])])[0]
    positive_fold_count = sum(bool(fold["positive_effect"]) for fold in valid_folds)
    positive_fraction = positive_fold_count / len(valid_folds)
    result["metrics"] = {
        "future_rv7_median_ratio": float(aggregate["observed_ratio"]),
        "event_median_future_rv7": float(
            eligible.loc[eligible["group"].eq(1), "future_rv7"].median()
        ),
        "normal_median_future_rv7": float(
            eligible.loc[eligible["group"].eq(0), "future_rv7"].median()
        ),
        "positive_fold_count": int(positive_fold_count),
        "positive_fold_fraction": float(positive_fraction),
    }
    result["confidence_interval"] = {
        "level": float(config.confidence_level),
        "lower": float(aggregate["ci_lower"]),
        "upper": float(aggregate["ci_upper"]),
        "bootstrap_samples": int(aggregate["bootstrap_samples"]),
        "block_days": int(aggregate["block_days"]),
        "seed": int(aggregate["seed"]),
    }
    result["p_value"] = float(aggregate["positive_p_value"])
    result["q_value"] = float(positive_q)
    result["opposite_p_value"] = float(aggregate["opposite_p_value"])
    result["opposite_q_value"] = float(opposite_q)

    statistical_placebos = _placebo_checks(eligible, config)
    result["placebos"].update(statistical_placebos)
    passed_placebos = [
        name
        for name, evidence in statistical_placebos.items()
        if evidence["passed_registered_gate"]
    ]
    if passed_placebos:
        result["status"] = "invalid"
        result["reasons"] = [f"PLACEBO_{name.upper()}_PASSED" for name in passed_placebos]
        return _finalize_result(result)

    validation_gates = {
        "practical_effect": (
            float(aggregate["observed_ratio"]) >= config.practical_effect_ratio
        ),
        "confidence_interval": float(aggregate["ci_lower"]) > 1.0,
        "multiple_testing": positive_q <= config.maximum_q_value,
        "fold_stability": positive_fraction >= config.positive_fold_fraction,
    }
    if all(validation_gates.values()):
        result["status"] = "validated"
        result["reasons"] = ["ALL_PRE_REGISTERED_GATES_PASSED"]
    else:
        negative_fold_fraction = 1.0 - positive_fraction
        opposite_supported = (
            float(aggregate["ci_upper"]) < 1.0
            and opposite_q <= config.maximum_q_value
            and negative_fold_fraction >= config.positive_fold_fraction
        )
        if opposite_supported:
            result["status"] = "rejected"
            result["reasons"] = ["SIGNIFICANT_OPPOSITE_EFFECT"]
        else:
            result["status"] = "monitoring"
            result["reasons"] = [
                f"GATE_{name.upper()}_NOT_MET"
                for name, passed in validation_gates.items()
                if not passed
            ]
    result["validation_gates"] = validation_gates
    return _finalize_result(result)


__all__ = [
    "CONTRACT_VERSION",
    "HYPOTHESIS_ID",
    "CryptoValidationConfig",
    "benjamini_hochberg",
    "build_btc_volatility_frame",
    "build_purged_walk_forward_folds",
    "select_non_overlapping_events",
    "validate_btc_volatility",
]
