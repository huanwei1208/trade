"""Gold aggregation: Silver → Gold Parquet (daily sentiment factors per symbol)."""

from __future__ import annotations

import logging
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _silver_glob(data_root: Path) -> str:
    return str(data_root / "sentiment" / "silver" / "**" / "*.parquet")


def _gold_path(data_root: Path, d: date) -> Path:
    y, m, day = d.year, d.month, d.day
    return (data_root / "sentiment" / "gold"
            / f"{y:04d}" / f"{m:02d}" / f"{y:04d}-{m:02d}-{day:02d}.parquet")


def _upsert_parquet(path: Path, new_df: pd.DataFrame,
                    key_cols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = pd.read_parquet(path)
        combined = pd.concat([existing, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=key_cols, keep="last")
    else:
        combined = new_df
    combined.to_parquet(path, index=False)


def _compute_signal_strength(sym_df: pd.DataFrame) -> float:
    """Compute Gold row credibility score (0~1).

    Combines article volume, source diversity, directional consensus,
    and mean LLM confidence into a single quality score.
    """
    n = len(sym_df)
    if n == 0:
        return 0.0

    # 1. Volume score: 5+ articles → full score (log scale)
    vol_score = min(1.0, math.log1p(n) / math.log1p(5))

    # 2. Source diversity: 2+ distinct sources → full score
    n_sources = sym_df["source"].nunique() if "source" in sym_df.columns else 1
    diversity_score = min(1.0, n_sources / 2.0)

    # 3. Directional consensus: what fraction share the majority label
    labels = sym_df["sentiment_label"].values
    pos = (labels == "positive").sum()
    neg = (labels == "negative").sum()
    total = len(labels)
    majority = max(int(pos), int(neg), int(total - pos - neg))
    consensus_score = majority / total if total > 0 else 0.5

    # 4. Mean LLM confidence (minor corrective term)
    conf_mean = (float(sym_df["confidence"].mean())
                 if "confidence" in sym_df.columns else 0.5)
    noise_penalty = (
        1.0 - float(sym_df["base_noise_score"].mean())
        if "base_noise_score" in sym_df.columns and len(sym_df) > 0
        else 1.0
    )

    strength = (
        vol_score      * 0.40
        + diversity_score * 0.25
        + consensus_score * 0.25
        + conf_mean       * 0.05
        + noise_penalty   * 0.05
    )
    return round(strength, 4)


def aggregate(data_root: Path, target_date: date,
              lookback_days: int = 5) -> dict:
    """Compute Gold sentiment factors from Silver layer and write to Parquet.

    Factors:
      net_sentiment   — (pos−neg)/total  [-1, 1]
      sentiment_score — mean LLM score   [-1, 1]
      sent_velocity   — score vs 5d mean
      neg_shock       — neg fraction vs 5d mean
      article_count   — number of articles
      event_magnitude — max event magnitude
      confidence      — mean confidence

    Returns:
        Stats dict: gold_rows.
    """
    import duckdb

    silver_glob = _silver_glob(data_root)
    try:
        con = duckdb.connect()
        target_df = con.execute(f"""
            SELECT symbol, date, sentiment_score, sentiment_label,
                   event_magnitude, confidence,
                   COALESCE(base_sentiment_score, sentiment_score, 0.0) AS base_sentiment_score,
                   COALESCE(base_event_magnitude, event_magnitude, 0.0) AS base_event_magnitude,
                   COALESCE(base_policy_signal, FALSE) AS base_policy_signal,
                   COALESCE(base_entity_density, 0.0) AS base_entity_density,
                   COALESCE(base_novelty_score, 1.0) AS base_novelty_score,
                   COALESCE(base_noise_score, 0.0) AS base_noise_score,
                   COALESCE(source, 'unknown') AS source
            FROM read_parquet('{silver_glob}', union_by_name=true)
            WHERE date = '{target_date.isoformat()}'
        """).df()

        if target_df.empty:
            con.close()
            return {"gold_rows": 0}

        from_date = (pd.Timestamp(target_date) - pd.Timedelta(days=lookback_days)).date()
        history_df = con.execute(f"""
            SELECT symbol, date, sentiment_score, sentiment_label,
                   COALESCE(base_sentiment_score, sentiment_score, 0.0) AS base_sentiment_score
            FROM read_parquet('{silver_glob}', union_by_name=true)
            WHERE date >= '{from_date.isoformat()}'
              AND date <= '{target_date.isoformat()}'
        """).df()
        con.close()
    except Exception as e:
        logger.warning("DuckDB query failed: %s", e)
        return {"gold_rows": 0, "error": str(e)}

    symbols = list(target_df["symbol"].unique())
    only_market_level = bool(symbols) and all(s == "_MARKET_" for s in symbols)

    gold_rows = []
    for symbol in symbols:
        if symbol == "_MARKET_" and not only_market_level:
            continue
        sym_today = target_df[target_df["symbol"] == symbol]
        sym_hist = history_df[history_df["symbol"] == symbol]

        scores = sym_today["sentiment_score"].values
        labels = sym_today["sentiment_label"].values
        pos = (labels == "positive").sum()
        neg = (labels == "negative").sum()
        total = len(labels)

        net_sentiment = float((pos - neg) / total) if total > 0 else 0.0
        mean_score = float(np.mean(scores)) if len(scores) > 0 else 0.0

        hist_scores = sym_hist["sentiment_score"].values
        hist_mean = float(np.mean(hist_scores)) if len(hist_scores) > 0 else 0.0
        sent_velocity = mean_score - hist_mean
        hist_base_scores = sym_hist["base_sentiment_score"].values if "base_sentiment_score" in sym_hist.columns else hist_scores
        hist_base_mean = float(np.mean(hist_base_scores)) if len(hist_base_scores) > 0 else 0.0

        neg_frac_today = float(neg / total) if total > 0 else 0.0
        hist_labels = sym_hist["sentiment_label"].values
        hist_neg_frac = (
            float((hist_labels == "negative").sum() / len(hist_labels))
            if len(hist_labels) > 0 else 0.0
        )
        neg_shock = neg_frac_today - hist_neg_frac
        hist_daily_counts = sym_hist.groupby("date").size()
        hist_avg_count = float(hist_daily_counts.mean()) if not hist_daily_counts.empty else float(total)
        n_sources = sym_today["source"].nunique() if "source" in sym_today.columns else 1
        base_scores = sym_today["base_sentiment_score"].to_numpy(dtype=float) if "base_sentiment_score" in sym_today.columns else scores
        volume_burst = float(total / max(hist_avg_count, 1.0))
        cross_source_confirmation = float(min(1.0, n_sources / max(1.0, min(float(total), 3.0))))

        gold_rows.append({
            "date": target_date.isoformat(),
            "symbol": symbol,
            "net_sentiment": net_sentiment,
            "sentiment_score": mean_score,
            "sent_velocity": sent_velocity,
            "neg_shock": neg_shock,
            "article_count": total,
            "event_magnitude": float(sym_today["event_magnitude"].max()),
            "confidence": float(sym_today["confidence"].mean()),
            "signal_strength": _compute_signal_strength(sym_today),
            "bf_net_sentiment": float(np.mean(base_scores)) if len(base_scores) > 0 else 0.0,
            "bf_sent_velocity": float((np.mean(base_scores) if len(base_scores) > 0 else 0.0) - hist_base_mean),
            "bf_event_strength": float(sym_today["base_event_magnitude"].max()) if "base_event_magnitude" in sym_today.columns else float(sym_today["event_magnitude"].max()),
            "bf_policy_intensity": float(pd.to_numeric(sym_today.get("base_policy_signal", pd.Series([0] * len(sym_today))), errors="coerce").fillna(0.0).mean()),
            "bf_entity_density": float(pd.to_numeric(sym_today.get("base_entity_density", pd.Series([0.0] * len(sym_today))), errors="coerce").fillna(0.0).mean()),
            "bf_novelty": float(pd.to_numeric(sym_today.get("base_novelty_score", pd.Series([1.0] * len(sym_today))), errors="coerce").fillna(1.0).mean()),
            "bf_volume_burst": volume_burst,
            "bf_cross_source_confirmation": cross_source_confirmation,
            "bf_noise_penalty": 1.0 - float(pd.to_numeric(sym_today.get("base_noise_score", pd.Series([0.0] * len(sym_today))), errors="coerce").fillna(0.0).mean()),
        })

    if gold_rows:
        gold_df = pd.DataFrame(gold_rows)
        path = _gold_path(data_root, target_date)
        _upsert_parquet(path, gold_df, key_cols=["date", "symbol"])
        logger.info("Gold %s: wrote %d rows to %s", target_date, len(gold_rows), path)

    return {"gold_rows": len(gold_rows)}
