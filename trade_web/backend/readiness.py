from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DatasetMeta:
    key: str
    label: str
    critical: bool
    impacts: tuple[str, ...]
    job_name: str | None = None


DATASET_CATALOG: tuple[DatasetMeta, ...] = (
    DatasetMeta("kline", "Kline", True, ("today", "candidates", "symbol_chart", "signals", "belief", "recommendations"), "kline_update"),
    DatasetMeta("fund_flow", "Fund Flow", True, ("today", "candidates", "signals", "belief", "recommendations"), "fund_flow_update"),
    DatasetMeta("fundamental", "Fundamental", True, ("today", "candidates", "signals", "belief", "recommendations"), "fundamental"),
    DatasetMeta("sentiment_silver", "Sentiment Silver", False, ("trust", "events", "signals"), "sentiment_silver"),
    DatasetMeta("sentiment_gold", "Sentiment Gold", True, ("today", "candidates", "events", "belief", "recommendations"), "sentiment_gold"),
    DatasetMeta("events", "Market Events", True, ("today", "candidates", "symbol_chart", "belief", "recommendations"), "event_extract"),
    DatasetMeta("planned_events", "Planned Events", False, ("today", "ops", "events"), "planned_event_sync"),
    DatasetMeta("signals", "Signals", True, ("today", "candidates"), "window_score"),
    DatasetMeta("belief_state", "Belief State", True, ("today", "candidates", "symbol", "belief"), "belief_update"),
    DatasetMeta("recommendation", "Recommendation", True, ("today", "candidates", "symbol", "recommendations"), "recommend"),
    DatasetMeta("models", "Models", False, ("signals", "belief", "recommendations", "trust"), "model_train"),
    DatasetMeta("sector_map", "Sector Map", False, ("events", "signals", "belief"), "sector_refresh"),
)


READINESS_READY = {"READY", "LATE_READY", "REPLAYED"}
READINESS_WARN = {"PARTIAL", "CHANGED", "REPLAYING"}
READINESS_BAD = {"MISSING"}


def _safe_json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def _to_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _to_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _daterange(end_day: date, days: int) -> list[date]:
    start_day = end_day - timedelta(days=max(0, days - 1))
    return [start_day + timedelta(days=offset) for offset in range(days)]


def _coverage_status(coverage_pct: float | None, *, lag_days: int | None = None, exists: bool | None = None) -> str:
    if exists is False:
      return "MISSING"
    if coverage_pct is None:
      if exists:
        return "READY"
      return "UNKNOWN"
    if coverage_pct >= 0.95:
      return "LATE_READY" if lag_days and lag_days > 0 else "READY"
    if coverage_pct >= 0.65:
      return "PARTIAL"
    if coverage_pct > 0:
      return "MISSING"
    return "MISSING"


def _quality_to_readiness(raw: str | None) -> str:
    status = str(raw or "").strip().lower()
    if status in {"ok", "healthy", "ready"}:
        return "READY"
    if status in {"degraded"}:
        return "LATE_READY"
    if status in {"partial"}:
        return "PARTIAL"
    if status in {"missing", "blocked", "error"}:
        return "MISSING"
    return "UNKNOWN"


def _collect_count_by_date(db, sql: str, params: tuple[Any, ...] = ()) -> dict[str, int]:
    with db._conn_lock:
        rows = db._conn.execute(sql, params).fetchall()
    counts: dict[str, int] = {}
    for row in rows:
        values = dict(row)
        key = str(values.get("date_key") or "")
        if key:
            counts[key] = int(values.get("row_count") or 0)
    return counts


def _collect_snapshot_by_date(db, date_from: str, date_to: str) -> dict[str, dict[str, Any]]:
    with db._conn_lock:
        rows = db._conn.execute(
            """
            SELECT eval_date, source_count, market_event_count, propagation_count,
                   feature_rows, labeled_rows_5d, labeled_rows_20d, signal_dates, metadata_json
            FROM dataset_snapshots
            WHERE eval_date BETWEEN ? AND ?
            ORDER BY eval_date
            """,
            (date_from, date_to),
        ).fetchall()
    payload: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        item["metadata"] = _safe_json(item.get("metadata_json"), {})
        payload[str(item.get("eval_date"))] = item
    return payload


def _collect_quality_by_date(db, date_from: str, date_to: str) -> dict[str, dict[str, Any]]:
    with db._conn_lock:
        rows = db._conn.execute(
            """
            SELECT eval_date, operational_status, research_status, brier_score, drift_mmd, metrics_json
            FROM QualityReport
            WHERE eval_date BETWEEN ? AND ?
            ORDER BY eval_date
            """,
            (date_from, date_to),
        ).fetchall()
    payload: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        item["metrics"] = _safe_json(item.get("metrics_json"), {})
        payload[str(item.get("eval_date"))] = item
    return payload


def _collect_gate_by_date(db, date_from: str, date_to: str) -> dict[str, dict[str, Any]]:
    with db._conn_lock:
        rows = db._conn.execute(
            """
            SELECT eval_date, status, reason_summary, reasons_json, metrics_json
            FROM daily_quality_gate
            WHERE eval_date BETWEEN ? AND ?
            ORDER BY eval_date
            """,
            (date_from, date_to),
        ).fetchall()
    payload: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        item["reasons"] = _safe_json(item.get("reasons_json"), [])
        item["metrics"] = _safe_json(item.get("metrics_json"), {})
        payload[str(item.get("eval_date"))] = item
    return payload


def _collect_freshness_by_date(db, date_from: str, date_to: str) -> dict[str, dict[str, dict[str, Any]]]:
    with db._conn_lock:
        rows = db._conn.execute(
            """
            SELECT as_of_date, dataset, freshness_date, lag_days, coverage_pct, status, details_json
            FROM FreshnessStatus
            WHERE as_of_date BETWEEN ? AND ?
            ORDER BY as_of_date, dataset
            """,
            (date_from, date_to),
        ).fetchall()
    payload: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        item = dict(row)
        item["details"] = _safe_json(item.get("details_json"), {})
        payload[str(item.get("as_of_date"))][str(item.get("dataset"))] = item
    return payload


def _collect_last_date_distribution(db, source: str, dataset: str) -> tuple[list[tuple[str, int]], str | None]:
    with db._conn_lock:
        rows = db._conn.execute(
            """
            SELECT last_date, COUNT(*) AS row_count
            FROM sync_state
            WHERE source = ? AND dataset = ? AND COALESCE(last_date, '') != ''
            GROUP BY last_date
            ORDER BY last_date
            """,
            (source, dataset),
        ).fetchall()
    grouped: list[tuple[str, int]] = []
    latest: str | None = None
    for row in rows:
        last_date = str(row["last_date"] or "")
        if not last_date:
            continue
        grouped.append((last_date, int(row["row_count"] or 0)))
        latest = last_date
    return grouped, latest


def _coverage_for_day(grouped_last_dates: list[tuple[str, int]], day_iso: str) -> int:
    return sum(count for last_date, count in grouped_last_dates if last_date >= day_iso)


def _list_daily_files(root: Path) -> set[str]:
    dates: set[str] = set()
    if not root.exists():
        return dates
    for path in root.rglob("*.parquet"):
        stem = path.stem
        if len(stem) == 10 and stem[4] == "-" and stem[7] == "-":
            dates.add(stem)
    return dates


def _latest_path_date(dates: set[str]) -> str | None:
    return max(dates) if dates else None


def _parse_range(value: Any) -> tuple[date | None, date | None]:
    text = str(value or "").strip()
    if not text:
        return None, None
    if ".." in text:
        start_text, end_text = text.split("..", 1)
        return _to_date(start_text), _to_date(end_text)
    parsed = _to_date(text)
    return parsed, parsed


def _range_contains_day(start_day: date | None, end_day: date | None, target_day: date) -> bool:
    if start_day and end_day:
        return start_day <= target_day <= end_day
    if start_day:
        return start_day <= target_day
    if end_day:
        return target_day <= end_day
    return False


def _collect_repair_runs(db, date_from: str, date_to: str) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    with db._conn_lock:
        rows = db._conn.execute(
            """
            SELECT id, ts, dataset, item_key, action, degraded, reason_code, local_range,
                   missing_range, api_endpoint, api_calls_actual, duration_ms, error, meta_json
            FROM data_repair_runs
            WHERE substr(ts, 1, 10) BETWEEN ? AND ?
            ORDER BY ts DESC
            LIMIT 2000
            """,
            (date_from, date_to),
        ).fetchall()
    by_cell: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_dataset: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        item = dict(row)
        item["meta"] = _safe_json(item.get("meta_json"), {})
        dataset = str(item.get("dataset") or "")
        if not dataset:
            continue
        by_dataset[dataset].append(item)
        item_day = _to_date(item.get("item_key"))
        dates: set[str] = set()
        if item_day:
            dates.add(item_day.isoformat())
        for field_name in ("local_range", "missing_range"):
            start_day, end_day = _parse_range(item.get(field_name))
            if start_day or end_day:
                if start_day and end_day:
                    cursor = start_day
                    while cursor <= end_day and len(dates) < 31:
                        dates.add(cursor.isoformat())
                        cursor += timedelta(days=1)
                else:
                    parsed = start_day or end_day
                    if parsed:
                        dates.add(parsed.isoformat())
        for day_iso in dates:
            bucket = by_cell[(dataset, day_iso)]
            if len(bucket) < 6:
                bucket.append(item)
    return by_cell, by_dataset


def _collect_gap_ranges(db) -> dict[str, list[tuple[date | None, date | None, str]]]:
    with db._conn_lock:
        rows = db._conn.execute(
            """
            SELECT dataset, missing_range, status
            FROM data_gaps
            ORDER BY updated_at DESC
            LIMIT 4000
            """
        ).fetchall()
    payload: dict[str, list[tuple[date | None, date | None, str]]] = defaultdict(list)
    for row in rows:
        dataset = str(row["dataset"] or "")
        if not dataset:
            continue
        payload[dataset].append((*_parse_range(row["missing_range"]), str(row["status"] or "")))
    return payload


def _history_summary(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in history[:5]:
        items.append({
            "ts": row.get("ts"),
            "action": row.get("action"),
            "reason_code": row.get("reason_code"),
            "duration_ms": row.get("duration_ms"),
            "api_calls_actual": row.get("api_calls_actual"),
            "error": row.get("error"),
        })
    return items


def _snapshot_coverage(snapshot: dict[str, Any] | None, key: str) -> float | None:
    if not snapshot:
        return None
    metadata = snapshot.get("metadata") or {}
    value = metadata.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _signal_expected_count(signal_counts: dict[str, int], total_symbols: int) -> int:
    max_signal = max(signal_counts.values()) if signal_counts else 0
    return max(max_signal, total_symbols, 1)


def _build_cell(
    dataset: DatasetMeta,
    day_iso: str,
    *,
    status: str,
    row_count: int | None = None,
    expected_count: int | None = None,
    coverage_pct: float | None = None,
    lag_days: int | None = None,
    source_last_date: str | None = None,
    last_backfill_at: str | None = None,
    history: list[dict[str, Any]] | None = None,
    reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "id": f"{dataset.key}:{day_iso}",
        "dataset": dataset.key,
        "date": day_iso,
        "status": status,
        "row_count": row_count,
        "expected_count": expected_count,
        "coverage_pct": coverage_pct,
        "lag_days": lag_days,
        "source_last_date": source_last_date,
        "last_backfill_at": last_backfill_at,
        "affected_outputs": list(dataset.impacts),
        "history": history or [],
        "reason_codes": reason_codes or [],
        "changed_since_last_ready": False,
        "fingerprint": None,
    }
    return payload


def build_readiness_grid(
    data_root: str | Path,
    db,
    *,
    days: int = 30,
    end_date: str | None = None,
    datasets: list[str] | None = None,
) -> dict[str, Any]:
    end_day = _to_date(end_date) or date.today()
    day_list = _daterange(end_day, max(1, min(days, 90)))
    day_strings = [item.isoformat() for item in day_list]
    date_from = day_strings[0]
    date_to = day_strings[-1]

    catalog = [item for item in DATASET_CATALOG if not datasets or item.key in set(datasets)]
    dataset_order = [item.key for item in catalog]

    with db._conn_lock:
        total_symbols_row = db._conn.execute("SELECT COUNT(*) AS count FROM instruments").fetchone()
        total_symbols = int(total_symbols_row["count"] or 0)
        active_models_row = db._conn.execute(
            "SELECT COUNT(*) AS count, MIN(substr(trained_at, 1, 10)) AS first_day, MAX(substr(trained_at, 1, 10)) AS last_day "
            "FROM model_registry WHERE COALESCE(is_active, 0) = 1 OR promotion_state = 'active'"
        ).fetchone()
        sector_row = db._conn.execute(
            "SELECT COUNT(*) AS count, MAX(substr(updated_at, 1, 10)) AS last_day FROM sector_members"
        ).fetchone()

    snapshots = _collect_snapshot_by_date(db, date_from, date_to)
    gates = _collect_gate_by_date(db, date_from, date_to)
    quality = _collect_quality_by_date(db, date_from, date_to)
    freshness = _collect_freshness_by_date(db, date_from, date_to)
    signal_counts = _collect_count_by_date(db, "SELECT date AS date_key, COUNT(*) AS row_count FROM signals WHERE date BETWEEN ? AND ? GROUP BY date", (date_from, date_to))
    belief_counts = _collect_count_by_date(db, "SELECT as_of_date AS date_key, COUNT(*) AS row_count FROM BeliefState WHERE as_of_date BETWEEN ? AND ? GROUP BY as_of_date", (date_from, date_to))
    recommendation_counts = _collect_count_by_date(db, "SELECT as_of_date AS date_key, COUNT(*) AS row_count FROM Recommendation WHERE as_of_date BETWEEN ? AND ? GROUP BY as_of_date", (date_from, date_to))
    event_counts = _collect_count_by_date(db, "SELECT event_date AS date_key, COUNT(*) AS row_count FROM market_events WHERE event_date BETWEEN ? AND ? GROUP BY event_date", (date_from, date_to))
    planned_counts = _collect_count_by_date(db, "SELECT event_date AS date_key, COUNT(*) AS row_count FROM planned_events WHERE event_date BETWEEN ? AND ? GROUP BY event_date", (date_from, date_to))
    calendar_counts = _collect_count_by_date(db, "SELECT trade_date AS date_key, COUNT(*) AS row_count FROM trading_calendar WHERE trade_date BETWEEN ? AND ? GROUP BY trade_date", (date_from, date_to))
    kline_dist, kline_latest = _collect_last_date_distribution(db, "tushare_kline", "daily")
    repair_by_cell, repair_by_dataset = _collect_repair_runs(db, date_from, date_to)
    gap_ranges = _collect_gap_ranges(db)

    sentiment_gold_dates = _list_daily_files(Path(data_root) / "sentiment" / "gold")
    sentiment_silver_dates = _list_daily_files(Path(data_root) / "sentiment" / "silver")
    latest_gold = _latest_path_date(sentiment_gold_dates)
    latest_silver = _latest_path_date(sentiment_silver_dates)

    signal_expected = _signal_expected_count(signal_counts, total_symbols)
    belief_expected = max(max(belief_counts.values()) if belief_counts else 0, 1)
    recommendation_expected = max(max(recommendation_counts.values()) if recommendation_counts else 0, 1)

    rows: list[dict[str, Any]] = []
    unstable: list[tuple[int, str]] = []
    today_impacts: set[str] = set()
    blocked_days: set[str] = set()
    readiness_score_total = 0
    readiness_score_ready = 0

    for dataset in catalog:
        row_cells: list[dict[str, Any]] = []
        issue_count = 0
        last_known_snapshot: dict[str, Any] | None = None
        for day in day_list:
            day_iso = day.isoformat()
            gate = gates.get(day_iso)
            snapshot = snapshots.get(day_iso) or last_known_snapshot
            if snapshots.get(day_iso):
                last_known_snapshot = snapshots[day_iso]
            quality_row = quality.get(day_iso)
            day_freshness = freshness.get(day_iso, {}).get(dataset.key)
            cell_history = repair_by_cell.get((dataset.key, day_iso), [])
            last_backfill_at = cell_history[0].get("ts") if cell_history else None
            gap_match = any(
                status != "resolved" and _range_contains_day(start_day, end_day, day)
                for start_day, end_day, status in gap_ranges.get(dataset.key, [])
            )

            if dataset.key == "kline":
                row_count = _coverage_for_day(kline_dist, day_iso)
                coverage_pct = (row_count / total_symbols) if total_symbols else None
                lag_days = max(0, (day - _to_date(kline_latest)).days) if _to_date(kline_latest) else None
                status = "MISSING" if gap_match else _coverage_status(coverage_pct, lag_days=lag_days, exists=row_count > 0)
                cell = _build_cell(
                    dataset,
                    day_iso,
                    status=status,
                    row_count=row_count,
                    expected_count=total_symbols or None,
                    coverage_pct=coverage_pct,
                    lag_days=lag_days,
                    source_last_date=kline_latest,
                    last_backfill_at=last_backfill_at,
                    history=_history_summary(cell_history),
                    reason_codes=["gap"] if gap_match else [],
                )
            elif dataset.key in {"fund_flow", "fundamental"}:
                coverage_key = f"{dataset.key}_coverage"
                coverage_pct = _snapshot_coverage(snapshot, coverage_key)
                snapshot_day = str(snapshot.get("eval_date")) if snapshot else None
                lag_days = max(0, (day - _to_date(snapshot_day)).days) if _to_date(snapshot_day) else None
                row_count = int(round((coverage_pct or 0.0) * total_symbols)) if coverage_pct is not None and total_symbols else None
                status = "MISSING" if gap_match and not coverage_pct else _coverage_status(coverage_pct, lag_days=lag_days)
                cell = _build_cell(
                    dataset,
                    day_iso,
                    status=status,
                    row_count=row_count,
                    expected_count=total_symbols or None,
                    coverage_pct=coverage_pct,
                    lag_days=lag_days,
                    source_last_date=snapshot_day,
                    last_backfill_at=last_backfill_at,
                    history=_history_summary(cell_history),
                    reason_codes=["snapshot_gap"] if gap_match else [],
                )
            elif dataset.key == "sentiment_silver":
                exists = day_iso in sentiment_silver_dates
                lag_days = max(0, (day - _to_date(latest_silver)).days) if _to_date(latest_silver) else None
                cell = _build_cell(
                    dataset,
                    day_iso,
                    status="READY" if exists else ("MISSING" if day <= end_day else "UNKNOWN"),
                    row_count=1 if exists else 0,
                    expected_count=1,
                    coverage_pct=1.0 if exists else 0.0,
                    lag_days=lag_days,
                    source_last_date=latest_silver,
                    last_backfill_at=last_backfill_at,
                    history=_history_summary(cell_history),
                    reason_codes=[],
                )
            elif dataset.key == "sentiment_gold":
                exists = day_iso in sentiment_gold_dates
                lag_days = max(0, (day - _to_date(latest_gold)).days) if _to_date(latest_gold) else None
                cell = _build_cell(
                    dataset,
                    day_iso,
                    status="READY" if exists else ("MISSING" if day <= end_day else "UNKNOWN"),
                    row_count=1 if exists else 0,
                    expected_count=1,
                    coverage_pct=1.0 if exists else 0.0,
                    lag_days=lag_days,
                    source_last_date=latest_gold,
                    last_backfill_at=last_backfill_at,
                    history=_history_summary(cell_history),
                    reason_codes=[],
                )
            elif dataset.key == "events":
                sentiment_exists = day_iso in sentiment_gold_dates
                row_count = int(event_counts.get(day_iso, 0))
                cell = _build_cell(
                    dataset,
                    day_iso,
                    status="READY" if sentiment_exists else "MISSING",
                    row_count=row_count,
                    expected_count=1,
                    coverage_pct=1.0 if sentiment_exists else 0.0,
                    lag_days=max(0, (day - _to_date(latest_gold)).days) if _to_date(latest_gold) else None,
                    source_last_date=max(filter(None, [max(event_counts) if event_counts else None, latest_gold]), default=None),
                    last_backfill_at=last_backfill_at,
                    history=_history_summary(cell_history),
                    reason_codes=[] if sentiment_exists else ["missing_sentiment_gold"],
                )
            elif dataset.key == "planned_events":
                calendar_ready = calendar_counts.get(day_iso, 0) > 0
                row_count = int(planned_counts.get(day_iso, 0))
                cell = _build_cell(
                    dataset,
                    day_iso,
                    status="READY" if calendar_ready else "UNKNOWN",
                    row_count=row_count,
                    expected_count=1 if calendar_ready else None,
                    coverage_pct=1.0 if calendar_ready else None,
                    lag_days=0 if calendar_ready else None,
                    source_last_date=day_iso if calendar_ready else None,
                    last_backfill_at=last_backfill_at,
                    history=_history_summary(cell_history),
                    reason_codes=[],
                )
            elif dataset.key == "signals":
                row_count = int(signal_counts.get(day_iso, 0))
                coverage_pct = row_count / signal_expected if signal_expected else None
                status = _coverage_status(coverage_pct, exists=row_count > 0)
                if gate and status == "READY":
                    status = _quality_to_readiness(gate.get("status"))
                cell = _build_cell(
                    dataset,
                    day_iso,
                    status=status,
                    row_count=row_count,
                    expected_count=signal_expected,
                    coverage_pct=coverage_pct,
                    lag_days=0 if row_count else None,
                    source_last_date=max(signal_counts) if signal_counts else None,
                    last_backfill_at=last_backfill_at,
                    history=_history_summary(cell_history),
                    reason_codes=list(gate.get("reasons") or [])[:2] if gate else [],
                )
            elif dataset.key == "belief_state":
                row_count = int(belief_counts.get(day_iso, 0))
                coverage_pct = row_count / belief_expected if belief_expected else None
                cell = _build_cell(
                    dataset,
                    day_iso,
                    status=_coverage_status(coverage_pct, exists=row_count > 0),
                    row_count=row_count,
                    expected_count=belief_expected,
                    coverage_pct=coverage_pct,
                    lag_days=0 if row_count else None,
                    source_last_date=max(belief_counts) if belief_counts else None,
                    last_backfill_at=last_backfill_at,
                    history=_history_summary(cell_history),
                    reason_codes=[],
                )
            elif dataset.key == "recommendation":
                row_count = int(recommendation_counts.get(day_iso, 0))
                coverage_pct = row_count / recommendation_expected if recommendation_expected else None
                status = _coverage_status(coverage_pct, exists=row_count > 0)
                if quality_row and quality_row.get("research_status") == "partial" and status == "READY":
                    status = "PARTIAL"
                cell = _build_cell(
                    dataset,
                    day_iso,
                    status=status,
                    row_count=row_count,
                    expected_count=recommendation_expected,
                    coverage_pct=coverage_pct,
                    lag_days=0 if row_count else None,
                    source_last_date=max(recommendation_counts) if recommendation_counts else None,
                    last_backfill_at=last_backfill_at,
                    history=_history_summary(cell_history),
                    reason_codes=[],
                )
            elif dataset.key == "models":
                active_count = int(active_models_row["count"] or 0)
                first_day = str(active_models_row["first_day"] or "") or None
                last_day = str(active_models_row["last_day"] or "") or None
                ready = bool(active_count and first_day and first_day <= day_iso)
                cell = _build_cell(
                    dataset,
                    day_iso,
                    status="READY" if ready else "UNKNOWN",
                    row_count=active_count or None,
                    expected_count=active_count or None,
                    coverage_pct=1.0 if ready else None,
                    lag_days=max(0, (day - _to_date(last_day)).days) if ready and _to_date(last_day) else None,
                    source_last_date=last_day,
                    last_backfill_at=last_backfill_at,
                    history=_history_summary(cell_history),
                    reason_codes=[],
                )
            elif dataset.key == "sector_map":
                member_count = int(sector_row["count"] or 0)
                last_day = str(sector_row["last_day"] or "") or None
                cell = _build_cell(
                    dataset,
                    day_iso,
                    status="READY" if member_count > 0 else "UNKNOWN",
                    row_count=member_count or None,
                    expected_count=member_count or None,
                    coverage_pct=1.0 if member_count > 0 else None,
                    lag_days=max(0, (day - _to_date(last_day)).days) if member_count > 0 and _to_date(last_day) else None,
                    source_last_date=last_day,
                    last_backfill_at=last_backfill_at,
                    history=_history_summary(cell_history),
                    reason_codes=[],
                )
            else:
                cell = _build_cell(dataset, day_iso, status="UNKNOWN")

            if day_freshness and day_iso == end_day.isoformat():
                cell["coverage_pct"] = day_freshness.get("coverage_pct", cell.get("coverage_pct"))
                cell["lag_days"] = day_freshness.get("lag_days", cell.get("lag_days"))
                cell["source_last_date"] = day_freshness.get("freshness_date", cell.get("source_last_date"))
                cell["status"] = _quality_to_readiness(day_freshness.get("status"))

            snapshot_meta = snapshot.get("metadata", {}) if snapshot else {}
            fingerprint = (
                (((snapshot_meta.get("cache_fingerprint") or {}).get("hash")) if snapshot_meta else None)
                if dataset.key in {"fund_flow", "fundamental", "sentiment_gold", "signals", "recommendation"}
                else None
            )
            cell["fingerprint"] = fingerprint

            row_cells.append(cell)
            readiness_score_total += 1
            if cell["status"] in READINESS_READY:
                readiness_score_ready += 1
            elif dataset.critical and cell["status"] in READINESS_BAD | READINESS_WARN | {"UNKNOWN"}:
                blocked_days.add(day_iso)
            if cell["status"] not in READINESS_READY:
                issue_count += 1
                if day_iso == end_day.isoformat():
                    today_impacts.update(dataset.impacts)

        unstable.append((issue_count, dataset.key))
        rows.append({
            "dataset": dataset.key,
            "label": dataset.label,
            "critical": dataset.critical,
            "job_name": dataset.job_name,
            "impacts": list(dataset.impacts),
            "cells": row_cells,
        })

    unstable.sort(key=lambda item: (-item[0], item[1]))
    unstable_datasets = [
        {
            "dataset": key,
            "label": next(item.label for item in catalog if item.key == key),
            "issue_count": count,
        }
        for count, key in unstable[:4]
    ]

    today_datasets = []
    today_iso = end_day.isoformat()
    for row in rows:
        today_cell = next((cell for cell in row["cells"] if cell["date"] == today_iso), None)
        if today_cell and today_cell["status"] not in READINESS_READY:
            today_datasets.append({
                "dataset": row["dataset"],
                "label": row["label"],
                "status": today_cell["status"],
                "affected_outputs": today_cell["affected_outputs"],
            })

    summary = {
        "overall_readiness_pct": round((readiness_score_ready / readiness_score_total), 4) if readiness_score_total else None,
        "blocked_days": len(blocked_days),
        "unstable_datasets": unstable_datasets,
        "today_impact": {
            "date": today_iso,
            "affected_outputs": sorted(today_impacts),
            "datasets": today_datasets,
            "constrained": bool(today_datasets),
        },
    }

    return {
        "as_of": date.today().isoformat(),
        "range": {
            "days": len(day_strings),
            "end_date": day_strings[-1],
            "dates": day_strings,
        },
        "summary": summary,
        "datasets": [
            {
                "key": item.key,
                "label": item.label,
                "critical": item.critical,
                "job_name": item.job_name,
                "affected_outputs": list(item.impacts),
            }
            for item in catalog
        ],
        "rows": rows,
        "recovery_history": {
            dataset: _history_summary(items)
            for dataset, items in repair_by_dataset.items()
            if dataset in dataset_order
        },
    }
