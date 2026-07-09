from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from trade_py.data.warehouse.profiles import RESEARCH_SECTOR_PROFILES, SectorProfile


NULL_REASON_MISSING = "missing"
NULL_REASON_EMPTY = "empty_string"
NULL_REASON_INVALID_TYPE = "invalid_type"
NULL_REASON_INVALID_RANGE = "invalid_range"
NULL_REASON_INVALID_ENUM = "invalid_enum"
NULL_REASON_SEMANTIC_INVALID = "semantic_invalid"
NULL_REASON_PARSE_FAILED = "parse_failed"

_NEGATIVE_LABELS = {"差评", "负面", "negative", "bad", "bearish"}
_POSITIVE_LABELS = {"好评", "正面", "positive", "good", "bullish"}
_NEUTRAL_LABELS = {"中性", "neutral", "mixed"}
_MISSING_TEXT = {"", "none", "null", "nan", "n/a", "--", "-"}


DEFAULT_SECTOR_PROFILES = RESEARCH_SECTOR_PROFILES


def _stable_hash(*parts: Any) -> str:
    text = "|".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _MISSING_TEXT:
        return None
    text = re.sub(r"\s+", " ", text)
    return text or None


def _parse_datetime(value: Any) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def normalize_semantic_value(raw_value: Any, target_field: str) -> tuple[Any, str | None]:
    """Normalize field values with explicit semantic NULL reasons.

    Examples:
    - raw "差评" for a numeric score becomes (None, "invalid_type")
    - raw "差评" for sentiment_label becomes ("negative", None)
    """
    text = _clean_text(raw_value)
    if text is None:
        return None, NULL_REASON_EMPTY if raw_value is not None else NULL_REASON_MISSING

    field = target_field.lower()
    if field.endswith("_score") or field in {"metric_value", "ratio_value", "rating_score"}:
        try:
            value = float(text)
        except ValueError:
            if text in _NEGATIVE_LABELS | _POSITIVE_LABELS | _NEUTRAL_LABELS:
                return None, NULL_REASON_INVALID_TYPE
            return None, NULL_REASON_SEMANTIC_INVALID
        if math.isnan(value) or math.isinf(value):
            return None, NULL_REASON_INVALID_RANGE
        return value, None

    if field in {"sentiment_label", "rating_label", "comment_label"}:
        lowered = text.lower()
        if text in _NEGATIVE_LABELS or lowered in _NEGATIVE_LABELS:
            return "negative", None
        if text in _POSITIVE_LABELS or lowered in _POSITIVE_LABELS:
            return "positive", None
        if text in _NEUTRAL_LABELS or lowered in _NEUTRAL_LABELS:
            return "neutral", None
        return None, NULL_REASON_INVALID_ENUM

    return text, None


def normalize_ods_rss_entries(rows: list[dict[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    """Create ODS RSS entry rows without dropping malformed source records."""
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "entry_id", "fetch_id", "source_id", "url", "title_raw",
                "summary_raw", "body_raw", "published_at_raw",
                "raw_content_hash", "ingest_time", "parse_status",
            ]
        )

    now = datetime.now(timezone.utc).isoformat()
    out: list[dict[str, Any]] = []
    for idx, row in frame.iterrows():
        source_id = str(row.get("source_id") or row.get("source") or "unknown").strip() or "unknown"
        url = str(row.get("url") or row.get("link") or "").strip()
        title = row.get("title")
        summary = row.get("summary") if "summary" in row else row.get("text")
        body = row.get("body") if "body" in row else row.get("body_text")
        published_at = row.get("published_at")
        core_keys = {
            "source_id", "source", "url", "link", "title", "summary", "text",
            "body", "body_text", "published_at", "fetch_id", "ingest_time",
            "parse_status",
        }
        raw_extra = {str(key): row.get(key) for key in row.index if str(key) not in core_keys}
        raw_hash = _stable_hash(source_id, url, title, summary, body, published_at)
        fetch_id = str(row.get("fetch_id") or _stable_hash(source_id, "fetch", idx, published_at))
        item = {
            "entry_id": _stable_hash(source_id, url, title, published_at, raw_hash),
            "fetch_id": fetch_id,
            "source_id": source_id,
            "url": url or None,
            "title_raw": title,
            "summary_raw": summary,
            "body_raw": body,
            "published_at_raw": published_at,
            "raw_content_hash": raw_hash,
            "ingest_time": str(row.get("ingest_time") or now),
            "parse_status": str(row.get("parse_status") or "raw"),
            "raw_extra_json": json.dumps(raw_extra, ensure_ascii=False, sort_keys=True, default=str),
        }
        for semantic_key in ("rating", "sentiment_label", "rating_score", "metric_value", "ratio_value"):
            if semantic_key in row.index:
                item[semantic_key] = row.get(semantic_key)
        out.append(item)
    return pd.DataFrame(out)


def _quality_flags(title: str | None, summary: str | None, body: str | None, published_at: str | None) -> list[str]:
    flags: list[str] = []
    if not title:
        flags.append("empty_title")
    if not summary and not body:
        flags.append("empty_content")
    text = " ".join(part for part in (title, summary, body) if part)
    if "\ufffd" in text:
        flags.append("encoding_suspect")
    lowered = text.lower()
    if any(token in lowered for token in ("enable cookies", "sign in", "404 not found", "access denied")):
        flags.append("boilerplate_or_error_page")
    if not published_at:
        flags.append("missing_published_at")
    return flags


def _language_for_text(text: str) -> str:
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return "zh"
    return "en"


def _sector_scores(text: str, profiles: tuple[SectorProfile, ...]) -> dict[str, float]:
    lowered = text.lower()
    scores: dict[str, float] = {}
    for profile in profiles:
        hits = sum(1 for keyword in profile.keywords if keyword.lower() in lowered)
        scores[profile.sector] = round(min(1.0, hits / 3.0), 4)
    return scores


def build_dwd_articles(
    ods_entries: pd.DataFrame,
    *,
    profiles: tuple[SectorProfile, ...] = DEFAULT_SECTOR_PROFILES,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Transform ODS RSS entries into DWD article, quality, semantic, relevance rows."""
    article_rows: list[dict[str, Any]] = []
    quality_rows: list[dict[str, Any]] = []
    semantic_rows: list[dict[str, Any]] = []
    relevance_rows: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    for _, row in ods_entries.iterrows():
        article_id = str(row.get("entry_id") or _stable_hash(row.get("source_id"), row.get("url"), row.get("title_raw")))
        title = _clean_text(row.get("title_raw"))
        summary = _clean_text(row.get("summary_raw"))
        body = _clean_text(row.get("body_raw"))
        published_at = _parse_datetime(row.get("published_at_raw"))
        content_hash = str(row.get("raw_content_hash") or _stable_hash(title, summary, body))
        is_duplicate = content_hash in seen_hashes
        seen_hashes.add(content_hash)
        flags = _quality_flags(title, summary, body, published_at)
        if is_duplicate:
            flags.append("duplicate")
        quality_score = max(0.0, 1.0 - 0.18 * len(flags))
        quality_status = "accepted" if quality_score >= 0.7 and not is_duplicate else "flagged"
        if "empty_content" in flags or "boilerplate_or_error_page" in flags:
            quality_status = "quarantined"
        if is_duplicate:
            quality_status = "rejected"
        text = " ".join(part for part in (title, summary, body) if part)
        language = _language_for_text(text) if text else "unknown"
        article_rows.append(
            {
                "article_id": article_id,
                "source_id": row.get("source_id"),
                "url": row.get("url"),
                "title": title,
                "summary": summary,
                "body_text": body,
                "published_at": published_at,
                "language": language,
                "content_hash": content_hash,
                "quality_score": round(quality_score, 4),
                "quality_status": quality_status,
                "is_duplicate": bool(is_duplicate),
                "is_usable": quality_status in {"accepted", "flagged"},
            }
        )
        for flag in flags or ["ok"]:
            quality_rows.append(
                {
                    "article_id": article_id,
                    "check_name": flag,
                    "status": "pass" if flag == "ok" else "fail",
                    "score": 1.0 if flag == "ok" else 0.0,
                }
            )

        sentiment_raw = row.get("sentiment_label") if "sentiment_label" in row else row.get("rating")
        sentiment_value, sentiment_null_reason = normalize_semantic_value(sentiment_raw, "sentiment_label")
        semantic_rows.append(
            {
                "article_id": article_id,
                "field_name": "sentiment_label",
                "raw_value": sentiment_raw,
                "normalized_value": sentiment_value,
                "null_reason": sentiment_null_reason,
                "semantic_rule_version": "v1",
            }
        )
        rating_raw = row.get("rating_score") if "rating_score" in row else row.get("rating")
        rating_value, rating_null_reason = normalize_semantic_value(rating_raw, "rating_score")
        semantic_rows.append(
            {
                "article_id": article_id,
                "field_name": "rating_score",
                "raw_value": rating_raw,
                "normalized_value": rating_value,
                "null_reason": rating_null_reason,
                "semantic_rule_version": "v1",
            }
        )

        scores = _sector_scores(text, profiles)
        for sector, score in scores.items():
            if score <= 0:
                continue
            relevance_rows.append(
                {
                    "article_id": article_id,
                    "sector": sector,
                    "relevance_score": score,
                    "is_relevant": score >= 0.34,
                }
            )

    return (
        pd.DataFrame(article_rows),
        pd.DataFrame(quality_rows),
        pd.DataFrame(semantic_rows),
        pd.DataFrame(relevance_rows),
    )
