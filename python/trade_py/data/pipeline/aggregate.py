"""Gold aggregation: Silver → Gold Parquet (daily sentiment factors per symbol)."""

from __future__ import annotations

import logging
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
                   event_magnitude, confidence
            FROM read_parquet('{silver_glob}', union_by_name=true)
            WHERE date = '{target_date.isoformat()}'
        """).df()

        if target_df.empty:
            con.close()
            return {"gold_rows": 0}

        from_date = (pd.Timestamp(target_date) - pd.Timedelta(days=lookback_days)).date()
        history_df = con.execute(f"""
            SELECT symbol, date, sentiment_score, sentiment_label
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

        neg_frac_today = float(neg / total) if total > 0 else 0.0
        hist_labels = sym_hist["sentiment_label"].values
        hist_neg_frac = (
            float((hist_labels == "negative").sum() / len(hist_labels))
            if len(hist_labels) > 0 else 0.0
        )
        neg_shock = neg_frac_today - hist_neg_frac

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
        })

    if gold_rows:
        gold_df = pd.DataFrame(gold_rows)
        path = _gold_path(data_root, target_date)
        _upsert_parquet(path, gold_df, key_cols=["date", "symbol"])
        logger.info("Gold %s: wrote %d rows to %s", target_date, len(gold_rows), path)

    return {"gold_rows": len(gold_rows)}
