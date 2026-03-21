from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trade_py.analysis.knowledge_graph import SW
from trade_py.db.trade_db import TradeDB
from trade_py.utils.data_inspector import _resolve_kline_glob


EDGE_FEATURE_COLS = [
    "sample_count",
    "price_link_score",
    "stability_score",
    "event_support_score",
    "source_vol",
    "target_vol",
    "source_event_days",
    "source_event_abs_mean",
    "sign_success",
]

EVENT_MAP_FEATURE_COLS = [
    "sample_count",
    "mean_signal_abs",
    "consistency",
    "mean_confidence",
    "news_scale",
    "signal_std",
    "signal_abs_p90",
]


@dataclass
class EdgeModelStats:
    backend: str
    train_rows: int
    metric_name: str
    metric_value: float | None
    artifact_path: str | None = None


@dataclass
class LearnKGSummary:
    start: str
    end: str
    backend: str
    event_candidates: int
    sector_candidates: int
    total_candidates: int
    event_model_metric: float | None = None
    sector_model_metric: float | None = None
    event_model_rows: int = 0
    sector_model_rows: int = 0

    def format(self) -> str:
        details = [
            f"KG学习候选边: [{self.start}, {self.end}] backend={self.backend}",
            f"event_map={self.event_candidates}",
            f"sector_link={self.sector_candidates}",
            f"total={self.total_candidates}",
        ]
        if self.event_model_metric is not None:
            details.append(
                f"event_model_metric={self.event_model_metric:.4f} rows={self.event_model_rows}"
            )
        if self.sector_model_metric is not None:
            details.append(
                f"sector_model_metric={self.sector_model_metric:.4f} rows={self.sector_model_rows}"
            )
        return ", ".join(details)


def _sector_entity(industry_code: int) -> str:
    return f"SW_{SW(int(industry_code)).name}"


def _sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _clip01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def _squash_weight(raw_score: float, confidence: float) -> float:
    return round(math.tanh(max(raw_score, 0.0) * max(confidence, 0.0) * 2.4), 4)


def _resolve_date_range(data_root: str, start: str | None, end: str | None) -> tuple[str, str]:
    db = TradeDB(data_root)
    resolved_start = start or str(db.get("kline.start", "2024-01-01"))
    resolved_end = end or date.today().isoformat()
    if resolved_start > resolved_end:
        raise ValueError(f"start ({resolved_start}) > end ({resolved_end})")
    return resolved_start, resolved_end


def _catboost_train_dir(data_root: str | Path, model_name: str) -> str:
    path = Path(data_root) / "catboost_info" / "kg_learned" / model_name
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _resolve_backend(backend: str) -> str:
    norm = str(backend or "auto").strip().lower().replace("-", "_")
    if norm in {"xgboost", "catboost", "lgbm"}:
        return norm
    for name in ("xgboost", "lgbm", "catboost"):
        try:
            if name == "xgboost":
                import xgboost  # noqa: F401
            elif name == "lgbm":
                import lightgbm  # noqa: F401
            else:
                import catboost  # noqa: F401
            return name
        except Exception:
            continue
    raise RuntimeError("No supported edge-learning backend available")


def _kg_model_dir(data_root: str) -> Path:
    return Path(data_root) / "models" / "kg_edges"


def _load_sector_members(db: TradeDB) -> pd.DataFrame:
    rows = db._conn.execute(
        """
        SELECT DISTINCT symbol, industry_code
        FROM sector_members
        WHERE industry_code >= 0 AND industry_code < 31
        """
    ).fetchall()
    if not rows:
        return pd.DataFrame(columns=["symbol", "industry_code", "sector"])
    frame = pd.DataFrame(rows, columns=["symbol", "industry_code"])
    frame["sector"] = frame["industry_code"].apply(_sector_entity)
    return frame


def _load_sector_returns(data_root: str, start: str, end: str, members: pd.DataFrame) -> pd.DataFrame:
    if members.empty:
        return pd.DataFrame()

    import duckdb

    con = duckdb.connect()
    con.register("members", members[["symbol", "industry_code"]])
    kline_glob = _resolve_kline_glob(data_root)
    query = f"""
        WITH joined AS (
            SELECT
                k.symbol,
                CAST(k.date AS DATE) AS trade_date,
                CAST(k.close AS DOUBLE) AS close,
                m.industry_code
            FROM read_parquet('{kline_glob}', union_by_name=true) k
            JOIN members m ON k.symbol = m.symbol
            WHERE CAST(k.date AS DATE) >= CAST(? AS DATE)
              AND CAST(k.date AS DATE) <= CAST(? AS DATE)
        ),
        returns AS (
            SELECT
                symbol,
                industry_code,
                trade_date,
                close / LAG(close) OVER (PARTITION BY symbol ORDER BY trade_date) - 1.0 AS ret
            FROM joined
        )
        SELECT
            trade_date AS date,
            industry_code,
            AVG(ret) AS sector_ret
        FROM returns
        WHERE ret IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    frame = con.execute(query, [start, end]).df()
    con.close()
    if frame.empty:
        return pd.DataFrame()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["sector"] = frame["industry_code"].astype(int).apply(_sector_entity)
    return frame.pivot(index="date", columns="sector", values="sector_ret").sort_index()


def _load_event_rows(db: TradeDB, start: str, end: str) -> pd.DataFrame:
    rows = db._conn.execute(
        """
        SELECT event_type, entity_id, event_date, magnitude,
               COALESCE(confidence, 1.0) AS confidence,
               COALESCE(sentiment_score, 0.0) AS sentiment_score,
               COALESCE(news_volume, 0) AS news_volume
        FROM market_events
        WHERE event_date >= ? AND event_date <= ?
          AND entity_id LIKE 'SW_%'
        ORDER BY event_date, event_type, entity_id
        """,
        (start, end),
    ).fetchall()
    if not rows:
        return pd.DataFrame(
            columns=[
                "event_type",
                "entity_id",
                "event_date",
                "magnitude",
                "confidence",
                "sentiment_score",
                "news_volume",
                "signal",
            ]
        )
    frame = pd.DataFrame(
        rows,
        columns=[
            "event_type",
            "entity_id",
            "event_date",
            "magnitude",
            "confidence",
            "sentiment_score",
            "news_volume",
        ],
    )
    frame["event_date"] = pd.to_datetime(frame["event_date"])
    frame["signal"] = frame["sentiment_score"].where(
        frame["sentiment_score"].abs() >= 0.05,
        frame["magnitude"],
    )
    return frame


def _load_event_signal_matrix(db: TradeDB, start: str, end: str) -> pd.DataFrame:
    frame = _load_event_rows(db, start, end)
    if frame.empty:
        return pd.DataFrame()
    agg = (
        frame.groupby(["event_date", "entity_id"], as_index=False)["signal"]
        .mean()
        .rename(columns={"signal": "event_signal"})
    )
    return agg.pivot(index="event_date", columns="entity_id", values="event_signal").sort_index()


def _split_indexed_frame(frame: pd.DataFrame, ratio: float = 0.7) -> tuple[pd.DataFrame, pd.DataFrame]:
    if frame.empty or len(frame.index) < 24:
        return frame.copy(), frame.iloc[0:0].copy()
    cut = max(8, int(len(frame.index) * ratio))
    cut = min(cut, len(frame.index) - 4)
    train = frame.iloc[:cut].copy()
    holdout = frame.iloc[cut:].copy()
    if holdout.empty:
        return train, frame.iloc[0:0].copy()
    return train, holdout


def _forward_mean_return(series: pd.Series, horizon: int = 5) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=np.float64)
    out = np.full(len(values), np.nan, dtype=np.float64)
    min_periods = max(2, min(horizon, 3))
    for idx in range(len(values)):
        window = values[idx + 1 : idx + 1 + horizon]
        if len(window) < min_periods:
            continue
        if np.all(np.isnan(window)):
            continue
        out[idx] = float(np.nanmean(window))
    return pd.Series(out, index=series.index)


def _chunk_stability(aligned: pd.DataFrame, expected_sign: int) -> float:
    if aligned.empty or expected_sign == 0:
        return 0.0
    index_chunks = np.array_split(aligned.index.to_numpy(), min(3, len(aligned)))
    chunks = [aligned.loc[idx] for idx in index_chunks if len(idx) >= 8]
    if not chunks:
        return 0.0
    votes = []
    for chunk in chunks:
        corr = float(chunk.iloc[:, 0].corr(chunk.iloc[:, 1]))
        if math.isnan(corr):
            continue
        votes.append(1.0 if _sign(corr) == expected_sign else 0.0)
    return round(sum(votes) / len(votes), 4) if votes else 0.0


def _best_lag_correlation(
    source: pd.Series,
    target: pd.Series,
    max_lag: int,
    min_samples: int,
) -> tuple[float, int, int, pd.DataFrame]:
    best_corr = 0.0
    best_lag = 0
    best_samples = 0
    best_aligned = pd.DataFrame()
    for lag in range(1, max_lag + 1):
        aligned = pd.concat(
            [source.rename("src"), target.shift(-lag).rename("tgt")],
            axis=1,
        ).dropna()
        if len(aligned) < min_samples:
            continue
        corr = float(aligned["src"].corr(aligned["tgt"]))
        if math.isnan(corr):
            continue
        if abs(corr) > abs(best_corr):
            best_corr = corr
            best_lag = lag
            best_samples = len(aligned)
            best_aligned = aligned
    return best_corr, best_lag, best_samples, best_aligned


def _event_support_score(event_signal: pd.Series | None, target: pd.Series, lag: int) -> tuple[float, int]:
    if event_signal is None:
        return 0.0, 0
    aligned = pd.concat(
        [event_signal.rename("evt"), target.shift(-lag).rename("tgt")],
        axis=1,
    ).dropna()
    if len(aligned) < 5:
        return 0.0, len(aligned)
    corr = float(aligned["evt"].corr(aligned["tgt"]))
    if math.isnan(corr):
        return 0.0, len(aligned)
    return corr, len(aligned)


def _sign_success_rate(values_a: np.ndarray, values_b: np.ndarray, direction: int) -> float:
    prod = np.sign(values_a * values_b)
    valid = prod != 0
    if not np.any(valid):
        return 0.5
    return float(np.mean(prod[valid] == direction))


def _response_scale(value: float) -> float:
    return _clip01(abs(float(value)) / 0.01)


def _sector_feature_frame(
    sector_returns: pd.DataFrame,
    event_signals: pd.DataFrame,
    *,
    max_lag: int,
    min_samples: int,
) -> pd.DataFrame:
    if sector_returns.empty:
        return pd.DataFrame(
            columns=[
                "from_entity",
                "to_entity",
                "lag_days",
                "direction",
                "sample_count",
                "price_link_score",
                "stability_score",
                "event_support_score",
                "source_vol",
                "target_vol",
                "source_event_days",
                "source_event_abs_mean",
                "sign_success",
                "raw_corr",
                "event_support_raw",
                "event_obs",
            ]
        )
    rows: list[dict[str, Any]] = []
    sectors = list(sector_returns.columns)
    for from_sector in sectors:
        source_series = sector_returns[from_sector]
        if source_series.dropna().shape[0] < min_samples:
            continue
        event_series = event_signals[from_sector] if from_sector in event_signals.columns else None
        source_event_days = int(event_series.dropna().shape[0]) if event_series is not None else 0
        source_event_abs_mean = float(event_series.abs().mean()) if event_series is not None and source_event_days else 0.0
        source_vol = float(source_series.dropna().std() or 0.0)
        for to_sector in sectors:
            if from_sector == to_sector:
                continue
            target_series = sector_returns[to_sector]
            corr, lag_days, sample_count, aligned = _best_lag_correlation(
                source_series,
                target_series,
                max_lag=max_lag,
                min_samples=min_samples,
            )
            if lag_days == 0 or sample_count < min_samples:
                continue
            event_support_raw, event_obs = _event_support_score(event_series, target_series, lag_days)
            direction_signal = corr if abs(corr) >= max(0.03, abs(event_support_raw)) else event_support_raw
            direction = _sign(direction_signal)
            if direction == 0:
                continue
            price_link_score = round(abs(corr), 4)
            stability = _chunk_stability(aligned, direction)
            event_support_score = round(abs(event_support_raw), 4)
            sign_success = _sign_success_rate(
                aligned["src"].to_numpy(dtype=np.float64),
                aligned["tgt"].to_numpy(dtype=np.float64),
                direction,
            )
            rows.append(
                {
                    "from_entity": from_sector,
                    "to_entity": to_sector,
                    "lag_days": lag_days,
                    "direction": direction,
                    "sample_count": int(sample_count),
                    "price_link_score": price_link_score,
                    "stability_score": round(stability, 4),
                    "event_support_score": event_support_score,
                    "source_vol": round(source_vol, 6),
                    "target_vol": round(float(target_series.dropna().std() or 0.0), 6),
                    "source_event_days": source_event_days,
                    "source_event_abs_mean": round(source_event_abs_mean, 6),
                    "sign_success": round(sign_success, 4),
                    "raw_corr": round(float(corr), 6),
                    "event_support_raw": round(float(event_support_raw), 6),
                    "event_obs": int(event_obs),
                }
            )
    return pd.DataFrame(rows)


def _sector_label_frame(
    feature_frame: pd.DataFrame,
    sector_returns_holdout: pd.DataFrame,
    event_signals_holdout: pd.DataFrame,
) -> pd.DataFrame:
    if feature_frame.empty or sector_returns_holdout.empty:
        return pd.DataFrame(columns=["from_entity", "to_entity", "label_strength"])
    labels: list[dict[str, Any]] = []
    for row in feature_frame.to_dict(orient="records"):
        src = sector_returns_holdout.get(row["from_entity"])
        tgt = sector_returns_holdout.get(row["to_entity"])
        if src is None or tgt is None:
            continue
        lag_days = int(row["lag_days"])
        aligned = pd.concat(
            [src.rename("src"), tgt.shift(-lag_days).rename("tgt")],
            axis=1,
        ).dropna()
        if len(aligned) < 8:
            continue
        holdout_corr = float(aligned["src"].corr(aligned["tgt"]))
        if math.isnan(holdout_corr):
            continue
        direction = int(row["direction"])
        success_rate = _sign_success_rate(
            aligned["src"].to_numpy(dtype=np.float64),
            aligned["tgt"].to_numpy(dtype=np.float64),
            direction,
        )
        mean_signed_move = float(
            np.nanmean(direction * np.sign(aligned["src"].to_numpy(dtype=np.float64)) * aligned["tgt"].to_numpy(dtype=np.float64))
        )
        event_success = 0.5
        evt = event_signals_holdout.get(row["from_entity"])
        if evt is not None:
            evt_aligned = pd.concat(
                [evt.rename("evt"), tgt.shift(-lag_days).rename("tgt")],
                axis=1,
            ).dropna()
            if len(evt_aligned) >= 5:
                event_success = _sign_success_rate(
                    evt_aligned["evt"].to_numpy(dtype=np.float64),
                    evt_aligned["tgt"].to_numpy(dtype=np.float64),
                    direction,
                )
        sign_match = 1.0 if _sign(holdout_corr) == direction else 0.0
        label_strength = _clip01(
            abs(holdout_corr) * 0.35
            + success_rate * 0.35
            + event_success * 0.15
            + _response_scale(mean_signed_move) * 0.15
        )
        label_valid = 1.0 if sign_match > 0 and label_strength >= 0.55 else 0.0
        labels.append(
            {
                "from_entity": row["from_entity"],
                "to_entity": row["to_entity"],
                "label_strength": round(label_strength, 6),
                "label_valid": label_valid,
                "holdout_corr": round(holdout_corr, 6),
                "holdout_success": round(success_rate, 4),
                "holdout_event_success": round(event_success, 4),
            }
        )
    return pd.DataFrame(labels)


def _event_map_feature_frame(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(
            columns=[
                "from_entity",
                "to_entity",
                "direction",
                "sample_count",
                "mean_signal_abs",
                "consistency",
                "mean_confidence",
                "news_scale",
                "signal_std",
                "signal_abs_p90",
            ]
        )
    rows: list[dict[str, Any]] = []
    for (event_type, entity_id), group in events.groupby(["event_type", "entity_id"]):
        sample_count = int(len(group))
        if sample_count <= 0:
            continue
        mean_signal = float(group["signal"].mean())
        direction = _sign(mean_signal)
        if direction == 0:
            continue
        abs_signal = group["signal"].abs()
        rows.append(
            {
                "from_entity": str(event_type),
                "to_entity": str(entity_id),
                "direction": direction,
                "sample_count": sample_count,
                "mean_signal_abs": round(abs(mean_signal), 6),
                "consistency": round(float((group["signal"] * direction > 0).mean()), 4),
                "mean_confidence": round(float(group["confidence"].mean()), 4),
                "news_scale": round(min(1.0, math.log1p(float(group["news_volume"].sum() or sample_count)) / 3.5), 4),
                "signal_std": round(float(group["signal"].std() or 0.0), 6),
                "signal_abs_p90": round(float(abs_signal.quantile(0.9) if len(abs_signal) >= 2 else abs_signal.mean()), 6),
            }
        )
    return pd.DataFrame(rows)


def _event_map_label_frame(train_features: pd.DataFrame, holdout_events: pd.DataFrame, sector_returns_holdout: pd.DataFrame) -> pd.DataFrame:
    if train_features.empty or holdout_events.empty or sector_returns_holdout.empty:
        return pd.DataFrame(columns=["from_entity", "to_entity", "label_strength"])
    labels: list[dict[str, Any]] = []
    grouped = holdout_events.groupby(["event_type", "entity_id"])
    for row in train_features.to_dict(orient="records"):
        key = (row["from_entity"], row["to_entity"])
        if key not in grouped.groups:
            continue
        target = sector_returns_holdout.get(row["to_entity"])
        if target is None:
            continue
        group = grouped.get_group(key).copy()
        future = _forward_mean_return(target, horizon=5).rename("future_ret")
        date_col = future.index.name or "index"
        merged = group.merge(
            future.reset_index().rename(columns={date_col: "event_date"}),
            on="event_date",
            how="left",
        ).dropna(subset=["future_ret"])
        if len(merged) < 2:
            continue
        direction = int(row["direction"])
        success_rate = _sign_success_rate(
            merged["signal"].to_numpy(dtype=np.float64),
            merged["future_ret"].to_numpy(dtype=np.float64),
            direction,
        )
        mean_signed_ret = float(
            np.nanmean(direction * np.sign(merged["signal"].to_numpy(dtype=np.float64)) * merged["future_ret"].to_numpy(dtype=np.float64))
        )
        consistency = float((merged["signal"] * direction > 0).mean())
        label_strength = _clip01(
            success_rate * 0.45
            + _response_scale(mean_signed_ret) * 0.30
            + consistency * 0.25
        )
        label_valid = 1.0 if label_strength >= 0.55 and success_rate >= 0.5 else 0.0
        labels.append(
            {
                "from_entity": row["from_entity"],
                "to_entity": row["to_entity"],
                "label_strength": round(label_strength, 6),
                "label_valid": label_valid,
                "holdout_success": round(success_rate, 4),
                "holdout_mean_signed_ret": round(mean_signed_ret, 6),
            }
        )
    return pd.DataFrame(labels)


def _fit_edge_regressor(
    frame: pd.DataFrame,
    feature_cols: list[str],
    label_col: str,
    *,
    backend: str,
    data_root: str,
    model_name: str,
) -> tuple[dict[str, Any] | None, EdgeModelStats | None]:
    if frame.empty or len(frame) < 12:
        return None, None

    import joblib
    from sklearn.model_selection import train_test_split

    X = frame[feature_cols].fillna(0.0).to_numpy(dtype=np.float32)
    y = pd.to_numeric(frame[label_col], errors="coerce").fillna(0.0).to_numpy(dtype=np.float32)
    X_tr, X_val, y_tr, y_val = train_test_split(
        X,
        y,
        test_size=min(0.25, max(0.15, 8 / max(len(frame), 32))),
        random_state=42,
    )

    if backend == "xgboost":
        import xgboost as xgb

        model = xgb.XGBRegressor(
            n_estimators=200,
            learning_rate=0.05,
            max_depth=4,
            subsample=0.9,
            colsample_bytree=0.9,
            reg_lambda=1.0,
            random_state=42,
            tree_method="hist",
            n_jobs=min(8, max(1, (os.cpu_count() or 4))),
            objective="reg:squarederror",
            eval_metric="mae",
            verbosity=0,
        )
    elif backend == "catboost":
        from catboost import CatBoostRegressor

        model = CatBoostRegressor(
            iterations=250,
            learning_rate=0.05,
            depth=5,
            loss_function="RMSE",
            eval_metric="MAE",
            random_seed=42,
            train_dir=_catboost_train_dir(data_root, model_name),
            verbose=False,
        )
    else:
        import lightgbm as lgb

        model = lgb.LGBMRegressor(
            n_estimators=220,
            learning_rate=0.05,
            num_leaves=31,
            subsample=0.9,
            colsample_bytree=0.9,
            reg_lambda=1.0,
            random_state=42,
            verbose=-1,
        )

    if backend == "catboost":
        model.fit(X_tr, y_tr, eval_set=(X_val, y_val), use_best_model=True, verbose=False)
    else:
        model.fit(X_tr, y_tr)
    pred = np.asarray(model.predict(X_val), dtype=np.float32)
    metric = None
    if len(pred) >= 3 and not np.allclose(pred, pred[0]) and not np.allclose(y_val, y_val[0]):
        metric = float(np.corrcoef(pred, y_val)[0, 1])

    model.fit(X, y)
    artifact_dir = _kg_model_dir(data_root)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{model_name}__{backend}.pkl"
    joblib.dump(
        {
            "backend": backend,
            "feature_cols": feature_cols,
            "label_col": label_col,
            "model": model,
        },
        artifact_path,
    )
    return (
        {
            "backend": backend,
            "feature_cols": feature_cols,
            "label_col": label_col,
            "model": model,
        },
        EdgeModelStats(
            backend=backend,
            train_rows=int(len(frame)),
            metric_name="corr",
            metric_value=round(metric, 4) if metric is not None else None,
            artifact_path=str(artifact_path),
        ),
    )


def _predict_edge_scores(model_bundle: dict[str, Any] | None, frame: pd.DataFrame, feature_cols: list[str]) -> np.ndarray:
    if frame.empty:
        return np.array([], dtype=np.float32)
    if model_bundle is None:
        return np.full(len(frame), np.nan, dtype=np.float32)
    model = model_bundle["model"]
    cols = [col for col in feature_cols if col in frame.columns]
    X = frame[cols].fillna(0.0).to_numpy(dtype=np.float32)
    pred = np.asarray(model.predict(X), dtype=np.float32)
    return np.clip(pred, 0.0, 1.0)


def _rank_sector_candidates(
    rows: list[dict[str, Any]],
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for source in sorted({row["from_entity"] for row in rows}):
        subset = [row for row in rows if row["from_entity"] == source]
        for direction in (-1, 1):
            picked = [row for row in subset if int(row["direction"]) == direction]
            picked.sort(
                key=lambda row: (
                    float(row["confidence"]),
                    float(row["weight"]),
                    float(row["raw_score"]),
                ),
                reverse=True,
            )
            ranked.extend(picked[:top_k])
    return ranked


def _build_sector_candidates(
    full_features: pd.DataFrame,
    *,
    backend: str,
    model_bundle: dict[str, Any] | None,
    model_stats: EdgeModelStats | None,
    top_k: int,
    min_confidence: float,
    min_weight: float,
) -> list[dict[str, Any]]:
    if full_features.empty:
        return []
    pred = _predict_edge_scores(model_bundle, full_features, EDGE_FEATURE_COLS)
    if pred.size == 0:
        pred = np.full(len(full_features), np.nan, dtype=np.float32)
    rows: list[dict[str, Any]] = []
    for idx, record in enumerate(full_features.to_dict(orient="records")):
        learned_score = float(pred[idx]) if idx < len(pred) and not math.isnan(float(pred[idx])) else 0.0
        sample_scale = min(1.0, float(record["sample_count"]) / 80.0)
        confidence = _clip01(
            learned_score * 0.45
            + float(record["stability_score"]) * 0.20
            + sample_scale * 0.20
            + min(1.0, float(record["event_support_score"]) * 4.0) * 0.15
        )
        raw_score = _clip01(
            learned_score * 0.60
            + float(record["price_link_score"]) * 0.25
            + float(record["event_support_score"]) * 0.15
        )
        weight = _squash_weight(raw_score, confidence)
        if confidence < min_confidence or weight < min_weight:
            continue
        rows.append(
            {
                "from_entity": record["from_entity"],
                "to_entity": record["to_entity"],
                "rel_type": "sector_link",
                "weight": weight,
                "direction": int(record["direction"]),
                "lag_days": int(record["lag_days"]),
                "confidence": round(confidence, 4),
                "sample_count": int(record["sample_count"]),
                "price_link_score": round(float(record["price_link_score"]), 4),
                "stability_score": round(float(record["stability_score"]), 4),
                "event_support_score": round(float(record["event_support_score"]), 4),
                "raw_score": round(raw_score, 4),
                "source": f"learned_sector_link_v2_{backend}",
                "evidence_json": {
                    "learned_score": round(learned_score, 4),
                    "raw_corr": round(float(record.get("raw_corr", 0.0)), 4),
                    "event_support_raw": round(float(record.get("event_support_raw", 0.0)), 4),
                    "model_metric": None if model_stats is None else model_stats.metric_value,
                    "artifact_path": None if model_stats is None else model_stats.artifact_path,
                },
                "status": "pending",
            }
        )
    return _rank_sector_candidates(rows, top_k=top_k)


def _build_event_candidates(
    full_features: pd.DataFrame,
    *,
    backend: str,
    model_bundle: dict[str, Any] | None,
    model_stats: EdgeModelStats | None,
    min_event_count: int,
    min_weight: float,
) -> list[dict[str, Any]]:
    if full_features.empty:
        return []
    pred = _predict_edge_scores(model_bundle, full_features, EVENT_MAP_FEATURE_COLS)
    if pred.size == 0:
        pred = np.full(len(full_features), np.nan, dtype=np.float32)
    rows: list[dict[str, Any]] = []
    for idx, record in enumerate(full_features.to_dict(orient="records")):
        if int(record["sample_count"]) < min_event_count:
            continue
        learned_score = float(pred[idx]) if idx < len(pred) and not math.isnan(float(pred[idx])) else 0.0
        confidence = _clip01(
            learned_score * 0.40
            + float(record["mean_confidence"]) * 0.35
            + float(record["consistency"]) * 0.15
            + float(record["news_scale"]) * 0.10
        )
        raw_score = _clip01(
            learned_score * 0.55
            + float(record["mean_signal_abs"]) * 0.25
            + float(record["consistency"]) * 0.20
        )
        weight = _squash_weight(raw_score, confidence)
        if weight < min_weight:
            continue
        rows.append(
            {
                "from_entity": record["from_entity"],
                "to_entity": record["to_entity"],
                "rel_type": "event_map",
                "weight": weight,
                "direction": int(record["direction"]),
                "lag_days": 0,
                "confidence": round(confidence, 4),
                "sample_count": int(record["sample_count"]),
                "price_link_score": 0.0,
                "stability_score": round(float(record["consistency"]), 4),
                "event_support_score": round(float(record["mean_signal_abs"]), 4),
                "raw_score": round(raw_score, 4),
                "source": f"learned_event_map_v2_{backend}",
                "evidence_json": {
                    "learned_score": round(learned_score, 4),
                    "mean_signal_abs": round(float(record["mean_signal_abs"]), 4),
                    "mean_confidence": round(float(record["mean_confidence"]), 4),
                    "news_scale": round(float(record["news_scale"]), 4),
                    "model_metric": None if model_stats is None else model_stats.metric_value,
                    "artifact_path": None if model_stats is None else model_stats.artifact_path,
                },
                "status": "pending",
            }
        )
    return rows


def learn_kg_candidates(
    data_root: str = "data",
    *,
    start: str | None = None,
    end: str | None = None,
    top_k: int = 4,
    max_lag: int = 3,
    min_event_count: int = 2,
    min_samples: int = 20,
    min_confidence: float = 0.25,
    min_weight: float = 0.12,
    backend: str = "auto",
) -> LearnKGSummary:
    resolved_start, resolved_end = _resolve_date_range(data_root, start, end)
    backend_name = _resolve_backend(backend)
    db = TradeDB(data_root)

    members = _load_sector_members(db)
    sector_returns_full = _load_sector_returns(data_root, resolved_start, resolved_end, members)
    event_rows_full = _load_event_rows(db, resolved_start, resolved_end)
    event_signals_full = _load_event_signal_matrix(db, resolved_start, resolved_end)

    sector_train, sector_holdout = _split_indexed_frame(sector_returns_full)
    evt_train, evt_holdout = _split_indexed_frame(event_signals_full)

    sector_feature_train = _sector_feature_frame(
        sector_train,
        evt_train,
        max_lag=max_lag,
        min_samples=min_samples,
    )
    sector_label_train = _sector_label_frame(
        sector_feature_train,
        sector_holdout,
        evt_holdout,
    )
    sector_train_rows = sector_feature_train.merge(
        sector_label_train,
        on=["from_entity", "to_entity"],
        how="inner",
    )

    event_train_rows = event_rows_full[event_rows_full["event_date"] <= (sector_train.index.max() if not sector_train.empty else pd.Timestamp.max)].copy()
    event_holdout_rows = event_rows_full[event_rows_full["event_date"] > (sector_train.index.max() if not sector_train.empty else pd.Timestamp.max)].copy()
    event_feature_train = _event_map_feature_frame(event_train_rows)
    event_label_train = _event_map_label_frame(event_feature_train, event_holdout_rows, sector_holdout)
    event_train_rows = event_feature_train.merge(
        event_label_train,
        on=["from_entity", "to_entity"],
        how="inner",
    )

    sector_model, sector_stats = _fit_edge_regressor(
        sector_train_rows,
        EDGE_FEATURE_COLS,
        "label_strength",
        backend=backend_name,
        data_root=data_root,
        model_name=f"sector_link_edge_model__{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
    )
    event_model, event_stats = _fit_edge_regressor(
        event_train_rows,
        EVENT_MAP_FEATURE_COLS,
        "label_strength",
        backend=backend_name,
        data_root=data_root,
        model_name=f"event_map_edge_model__{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
    )

    full_sector_features = _sector_feature_frame(
        sector_returns_full,
        event_signals_full,
        max_lag=max_lag,
        min_samples=min_samples,
    )
    full_event_features = _event_map_feature_frame(event_rows_full)

    sector_candidates = _build_sector_candidates(
        full_sector_features,
        backend=backend_name,
        model_bundle=sector_model,
        model_stats=sector_stats,
        top_k=top_k,
        min_confidence=min_confidence,
        min_weight=min_weight,
    )
    event_candidates = _build_event_candidates(
        full_event_features,
        backend=backend_name,
        model_bundle=event_model,
        model_stats=event_stats,
        min_event_count=min_event_count,
        min_weight=min_weight,
    )

    db.kg_candidate_upsert_batch(event_candidates + sector_candidates)
    return LearnKGSummary(
        start=resolved_start,
        end=resolved_end,
        backend=backend_name,
        event_candidates=len(event_candidates),
        sector_candidates=len(sector_candidates),
        total_candidates=len(event_candidates) + len(sector_candidates),
        event_model_metric=None if event_stats is None else event_stats.metric_value,
        sector_model_metric=None if sector_stats is None else sector_stats.metric_value,
        event_model_rows=0 if event_stats is None else event_stats.train_rows,
        sector_model_rows=0 if sector_stats is None else sector_stats.train_rows,
    )
