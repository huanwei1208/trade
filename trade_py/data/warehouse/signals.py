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


def build_ads_feature_value_report(dws_sector_topic_daily: pd.DataFrame) -> pd.DataFrame:
    """Create deterministic feature-value summaries from DWS statistics."""
    if dws_sector_topic_daily.empty:
        return pd.DataFrame(
            columns=[
                "feature_id", "sector", "feature_name", "coverage_days",
                "latest_ratio", "latest_zscore", "stability_score",
                "validation_status", "evidence", "reason",
            ]
        )
    rows: list[dict[str, Any]] = []
    for (sector, topic), group in dws_sector_topic_daily.groupby(["sector", "topic"]):
        group = group.sort_values("date")
        latest = group.iloc[-1]
        coverage_days = int(group["date"].nunique())
        latest_ratio = float(latest.get("article_count_ratio") or 0.0)
        latest_zscore = float(latest.get("article_count_zscore") or 0.0)
        active_days = int(
            (
                (group["article_count_ratio"].astype(float) >= 1.2)
                | (group["article_count_zscore"].astype(float) >= 0.8)
            ).sum()
        )
        stability_score = round(active_days / max(coverage_days, 1), 4)
        status = "candidate"
        if coverage_days >= 3 and latest_ratio >= 1.5:
            status = "monitoring"
        rows.append(
            {
                "feature_id": f"{sector}_{topic}_article_burst",
                "sector": sector,
                "feature_name": "article_burst",
                "coverage_days": coverage_days,
                "latest_ratio": round(latest_ratio, 4),
                "latest_zscore": round(latest_zscore, 4),
                "stability_score": stability_score,
                "validation_status": status,
                "evidence": f"dws_sector_topic_daily:{sector}:{topic}:{latest.get('date')}",
                "reason": (
                    f"{sector}/{topic} article-burst feature has {coverage_days} observed days; "
                    f"latest ratio={latest_ratio:.2f}, z={latest_zscore:.2f}, "
                    f"stability={stability_score:.2f}."
                ),
            }
        )
    return pd.DataFrame(rows)


def build_ads_association_result(dws_sector_topic_daily: pd.DataFrame) -> pd.DataFrame:
    """Create a first deterministic association table between topics and sectors."""
    if dws_sector_topic_daily.empty:
        return pd.DataFrame(
            columns=[
                "association_id", "driver_type", "driver_id", "target_type",
                "target_id", "lag_days", "association_score", "validation_status",
                "evidence", "reason",
            ]
        )
    rows: list[dict[str, Any]] = []
    for (sector, topic), group in dws_sector_topic_daily.groupby(["sector", "topic"]):
        ratio_mean = float(group["article_count_ratio"].astype(float).mean())
        zscore_max = float(group["article_count_zscore"].astype(float).max())
        score = round(min(1.0, max(0.0, (ratio_mean - 1.0) / 2.0 + max(0.0, zscore_max) / 5.0)), 4)
        status = "candidate" if score < 0.6 else "monitoring"
        rows.append(
            {
                "association_id": f"topic:{topic}->sector:{sector}:lag0",
                "driver_type": "topic",
                "driver_id": topic,
                "target_type": "sector",
                "target_id": sector,
                "lag_days": 0,
                "association_score": score,
                "validation_status": status,
                "evidence": f"dws_sector_topic_daily:{sector}:{topic}",
                "reason": (
                    f"{topic} is associated with {sector} attention with mean ratio={ratio_mean:.2f} "
                    f"and max z={zscore_max:.2f}; price/return validation is still required."
                ),
            }
        )
    return pd.DataFrame(rows)


def build_ads_hypothesis_validation_report(
    ads_data_signal_report: pd.DataFrame,
    ads_association_result: pd.DataFrame,
) -> pd.DataFrame:
    """Generate first-pass hypothesis validation rows from signals and associations."""
    columns = [
        "hypothesis_id", "sector", "hypothesis", "evidence_count",
        "support_score", "validation_status", "evidence", "reason",
    ]
    if ads_data_signal_report.empty and ads_association_result.empty:
        return pd.DataFrame(columns=columns)
    sectors = sorted(
        set(ads_data_signal_report.get("sector", pd.Series(dtype=str)).dropna().astype(str).tolist())
        | set(ads_association_result.get("target_id", pd.Series(dtype=str)).dropna().astype(str).tolist())
    )
    rows: list[dict[str, Any]] = []
    for sector in sectors:
        signals = ads_data_signal_report[ads_data_signal_report.get("sector") == sector] if not ads_data_signal_report.empty else pd.DataFrame()
        associations = (
            ads_association_result[ads_association_result.get("target_id") == sector]
            if not ads_association_result.empty
            else pd.DataFrame()
        )
        evidence_count = int(len(signals) + len(associations))
        strong_signals = int((signals.get("signal_strength", pd.Series(dtype=str)) == "high").sum()) if not signals.empty else 0
        assoc_score = float(associations.get("association_score", pd.Series([0.0])).astype(float).max()) if not associations.empty else 0.0
        support_score = round(min(1.0, strong_signals * 0.25 + evidence_count * 0.1 + assoc_score * 0.4), 4)
        status = "candidate" if support_score < 0.55 else "monitoring"
        rows.append(
            {
                "hypothesis_id": f"{sector}_attention_has_research_value",
                "sector": sector,
                "hypothesis": f"{sector} attention bursts may identify research-worthy changes before formal recommendation logic.",
                "evidence_count": evidence_count,
                "support_score": support_score,
                "validation_status": status,
                "evidence": f"signals={len(signals)};associations={len(associations)}",
                "reason": (
                    f"{sector} has {len(signals)} signal rows and {len(associations)} association rows; "
                    f"support_score={support_score:.2f}. This remains deterministic pre-price validation."
                ),
            }
        )
    return pd.DataFrame(rows, columns=columns)
