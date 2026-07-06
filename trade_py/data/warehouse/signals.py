from __future__ import annotations

from typing import Any

import pandas as pd


def _date_key(value: Any) -> str:
    text = str(value or "")[:10]
    return text if len(text) == 10 else ""


def _safe_zscore(value: float, mean: float, std: float) -> float:
    if std <= 1e-9:
        return 0.0
    return round((value - mean) / std, 4)


def build_dws_sector_topic_daily(
    dwd_articles: pd.DataFrame,
    relevance: pd.DataFrame,
    *,
    lookback_days: int = 20,
) -> pd.DataFrame:
    """Build date × sector × topic daily statistics for EDA and signal discovery."""
    if dwd_articles.empty or relevance.empty:
        return pd.DataFrame(
            columns=[
                "date", "sector", "topic", "article_count", "valid_article_count",
                "article_count_baseline", "article_count_ratio", "article_count_zscore",
                "avg_quality_score", "source_count",
            ]
        )
    articles = dwd_articles.copy()
    articles["date"] = articles["published_at"].map(_date_key)
    articles = articles[articles["date"] != ""]
    joined = articles.merge(relevance[relevance["is_relevant"] == True], on="article_id", how="inner")
    if joined.empty:
        return pd.DataFrame()
    joined["topic"] = joined["sector"]
    grouped = (
        joined.groupby(["date", "sector", "topic"], as_index=False)
        .agg(
            article_count=("article_id", "count"),
            valid_article_count=("is_usable", "sum"),
            avg_quality_score=("quality_score", "mean"),
            source_count=("source_id", "nunique"),
        )
        .sort_values(["sector", "topic", "date"])
        .reset_index(drop=True)
    )
    rows: list[dict[str, Any]] = []
    for _, group in grouped.groupby(["sector", "topic"], sort=False):
        counts = group["article_count"].astype(float).tolist()
        for idx, row in group.reset_index(drop=True).iterrows():
            history = counts[max(0, idx - lookback_days):idx]
            baseline = float(pd.Series(history).mean()) if history else float(row["article_count"])
            std = float(pd.Series(history).std(ddof=0)) if len(history) > 1 else 0.0
            ratio = float(row["article_count"]) / max(baseline, 1.0)
            item = dict(row)
            item["article_count_baseline"] = round(baseline, 4)
            item["article_count_ratio"] = round(ratio, 4)
            item["article_count_zscore"] = _safe_zscore(float(row["article_count"]), baseline, std)
            item["avg_quality_score"] = round(float(row["avg_quality_score"] or 0.0), 4)
            rows.append(item)
    return pd.DataFrame(rows)


def _strength_from_stats(ratio: float, zscore: float) -> str:
    if ratio >= 2.0 or zscore >= 2.0:
        return "high"
    if ratio >= 1.3 or zscore >= 1.0:
        return "medium"
    return "low"


def build_ads_data_signal_report(dws_sector_topic_daily: pd.DataFrame) -> pd.DataFrame:
    """Convert DWS statistical structures into explainable ADS data signals."""
    if dws_sector_topic_daily.empty:
        return pd.DataFrame(
            columns=[
                "date", "sector", "signal_type", "target_type", "target_id",
                "metric_name", "metric_value", "baseline_value", "ratio_value",
                "zscore_value", "signal_strength", "value_reason", "validation_status",
            ]
        )
    rows: list[dict[str, Any]] = []
    for _, row in dws_sector_topic_daily.iterrows():
        ratio = float(row.get("article_count_ratio") or 0.0)
        zscore = float(row.get("article_count_zscore") or 0.0)
        if ratio < 1.2 and zscore < 0.8:
            continue
        strength = _strength_from_stats(ratio, zscore)
        sector = str(row.get("sector") or "")
        topic = str(row.get("topic") or sector)
        rows.append(
            {
                "date": row.get("date"),
                "sector": sector,
                "signal_type": "topic_burst",
                "target_type": "topic",
                "target_id": topic,
                "metric_name": "article_count",
                "metric_value": int(row.get("article_count") or 0),
                "baseline_value": float(row.get("article_count_baseline") or 0.0),
                "ratio_value": ratio,
                "zscore_value": zscore,
                "signal_strength": strength,
                "value_reason": (
                    f"{sector}/{topic} article volume is {ratio:.2f}x its baseline "
                    f"(z={zscore:.2f}); this may be useful as an awareness or warning signal "
                    "if it later aligns with price, volatility, or thesis changes."
                ),
                "validation_status": "candidate",
            }
        )
    return pd.DataFrame(rows)


def build_ads_source_value_report(
    dwd_articles: pd.DataFrame,
    relevance: pd.DataFrame,
) -> pd.DataFrame:
    """Score whether sources deserve continued analysis investment by sector."""
    if dwd_articles.empty:
        return pd.DataFrame(
            columns=[
                "source_id", "sector", "coverage_score", "parse_quality_score",
                "relevance_score", "uniqueness_score", "overall_value_score",
                "verdict", "value_reason",
            ]
        )
    relevant = relevance[relevance["is_relevant"] == True]
    joined = dwd_articles.merge(relevant, on="article_id", how="left")
    rows: list[dict[str, Any]] = []
    for (source_id, sector), group in joined.dropna(subset=["sector"]).groupby(["source_id", "sector"]):
        total = len(dwd_articles[dwd_articles["source_id"] == source_id])
        rel_count = len(group)
        usable = int(group["is_usable"].sum())
        unique_hashes = group["content_hash"].nunique()
        coverage_score = min(1.0, rel_count / 5.0)
        parse_quality_score = float(group["quality_score"].mean() or 0.0)
        relevance_score = float(group["relevance_score"].mean() or 0.0)
        uniqueness_score = unique_hashes / max(rel_count, 1)
        overall = round(
            coverage_score * 0.20
            + parse_quality_score * 0.25
            + relevance_score * 0.30
            + uniqueness_score * 0.15
            + (usable / max(rel_count, 1)) * 0.10,
            4,
        )
        verdict = "promote" if overall >= 0.72 else "monitor" if overall >= 0.45 else "low_value"
        rows.append(
            {
                "source_id": source_id,
                "sector": sector,
                "coverage_score": round(coverage_score, 4),
                "parse_quality_score": round(parse_quality_score, 4),
                "relevance_score": round(relevance_score, 4),
                "uniqueness_score": round(uniqueness_score, 4),
                "overall_value_score": overall,
                "verdict": verdict,
                "value_reason": (
                    f"{source_id} produced {rel_count}/{total} {sector}-relevant articles; "
                    f"quality={parse_quality_score:.2f}, relevance={relevance_score:.2f}, "
                    f"uniqueness={uniqueness_score:.2f}. Verdict: {verdict}."
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(["sector", "overall_value_score"], ascending=[True, False]).reset_index(drop=True)
