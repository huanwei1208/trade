from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from trade_py.db.event_db import EventType
from trade_py.db.settings_db import SettingsDB
from trade_py.app.pipelines.event_pipeline import (
    _extract_events,
    _read_silver_for_date,
    run_event_backfill,
    run_event_backfill_range,
    run_event_pipeline_batch,
)


logger = logging.getLogger(__name__)


@dataclass
class EventSyncSummary:
    scanned_dates: int = 0
    dates_with_silver: int = 0
    empty_dates: int = 0
    legacy_dates: int = 0
    candidate_events: int = 0
    synced_events: int = 0
    propagated_rows: int = 0
    affected_symbols: int = 0

    def merge(self, other: "EventSyncSummary") -> None:
        self.scanned_dates += other.scanned_dates
        self.dates_with_silver += other.dates_with_silver
        self.empty_dates += other.empty_dates
        self.legacy_dates += other.legacy_dates
        self.candidate_events += other.candidate_events
        self.synced_events += other.synced_events
        self.propagated_rows += other.propagated_rows
        self.affected_symbols += other.affected_symbols

    def format(self) -> str:
        return (
            f"事件补齐: 扫描{self.scanned_dates}天, "
            f"Silver有数据{self.dates_with_silver}天, "
            f"空事件日{self.empty_dates}天, "
            f"旧Silver口径{self.legacy_dates}天, "
            f"候选事件{self.candidate_events}个, "
            f"补齐事件{self.synced_events}个, "
            f"KG传导{self.propagated_rows}条, "
            f"影响{self.affected_symbols}只股票"
        )


_NUMERIC_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _parse_numeric_text(value: object) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if not text or text.lower() in {"none", "null", "nan", "nat"}:
        return None
    match = _NUMERIC_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _planned_base_magnitude(importance: str | None) -> float:
    level = str(importance or "medium").lower()
    return {"high": 0.45, "medium": 0.3, "low": 0.2}.get(level, 0.3)


def _planned_breadth(entity_id: str) -> str:
    entity = str(entity_id or "").strip().upper()
    if entity.endswith((".SH", ".SZ", ".BJ")):
        return "company"
    return "market"


def _infer_planned_event_type(row: dict) -> str | None:
    title = str(row.get("title") or "")
    title_upper = title.upper()
    actual = _parse_numeric_text(row.get("actual_value"))
    expected = _parse_numeric_text(row.get("expected_value"))
    previous = _parse_numeric_text(row.get("previous_value"))
    baseline = expected if expected is not None else previous

    if "利率" in title or "RATE" in title_upper or "FOMC" in title_upper:
        if actual is None or baseline is None:
            return None
        if actual < baseline:
            return "rate_cut"
        if actual > baseline:
            return "rate_hike"
        return "other"

    if actual is None or baseline is None:
        if str(row.get("source") or "") == "tushare_disclosure_date" and str(row.get("actual_value") or "").strip():
            return "other"
        return None

    higher_is_better = any(
        key in title_upper
        for key in (
            "GDP", "PMI", "零售", "工业增加值", "出口", "服务业", "景气", "投资",
            "外商直接投资", "新屋开工", "TRADE", "EMPLOYMENT",
        )
    )
    lower_is_better = any(
        key in title_upper
        for key in ("CPI", "PPI", "失业", "通胀", "UNEMPLOYMENT", "INFLATION")
    )

    if higher_is_better:
        return "macro_recovery" if actual >= baseline else "macro_slowdown"
    if lower_is_better:
        return "macro_recovery" if actual <= baseline else "macro_slowdown"
    return "other"


def _build_planned_event_summary(row: dict) -> str:
    title = str(row.get("title") or "").strip()
    parts = []
    if row.get("actual_value"):
        parts.append(f"actual={row.get('actual_value')}")
    if row.get("expected_value"):
        parts.append(f"expected={row.get('expected_value')}")
    if row.get("previous_value"):
        parts.append(f"previous={row.get('previous_value')}")
    suffix = (" | " + ", ".join(parts)) if parts else ""
    return f"[planned-realized] {title}{suffix}"[:500]


def _planned_to_market_event(row: dict) -> dict | None:
    planned_event_id = str(row.get("planned_event_id") or "").strip()
    if not planned_event_id:
        return None
    event_type = _infer_planned_event_type(row)
    if event_type is None:
        return None

    title = str(row.get("title") or "")
    actual = _parse_numeric_text(row.get("actual_value"))
    expected = _parse_numeric_text(row.get("expected_value"))
    previous = _parse_numeric_text(row.get("previous_value"))
    baseline = expected if expected is not None else previous
    base_magnitude = _planned_base_magnitude(str(row.get("importance") or "medium"))
    if actual is not None and baseline not in (None, 0):
        surprise = min(1.0, abs(actual - baseline) / max(abs(baseline), 1e-6))
        magnitude = min(0.9, base_magnitude + 0.35 * surprise)
    else:
        magnitude = 0.15 if event_type == "other" else base_magnitude

    entity_id = str(row.get("entity_id") or "market").strip() or "market"
    breadth = _planned_breadth(entity_id)
    sentiment_score = 0.0
    if event_type in {"macro_recovery", "rate_cut", "earnings_beat"}:
        sentiment_score = 0.2
    elif event_type in {"macro_slowdown", "rate_hike", "earnings_miss"}:
        sentiment_score = -0.2

    raw = f"planned|{planned_event_id}|{row.get('scheduled_at')}|{event_type}"
    event_id = hashlib.sha1(raw.encode()).hexdigest()[:12]
    return {
        "event_id": event_id,
        "event_date": str(row.get("event_date") or date.today().isoformat()),
        "event_type": event_type,
        "magnitude": round(float(magnitude), 4),
        "entity_id": entity_id,
        "breadth": breadth,
        "confidence": 0.7 if actual is not None else 0.35,
        "sentiment_score": sentiment_score,
        "news_volume": 1,
        "summary": _build_planned_event_summary(row),
        "source_hash": f"planned:{planned_event_id}",
    }


def _date_range(start: date, end: date) -> Iterable[date]:
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _month_windows(start: date, end: date) -> Iterable[tuple[date, date]]:
    cur = start
    while cur <= end:
        next_month = date(cur.year + (1 if cur.month == 12 else 0), 1 if cur.month == 12 else cur.month + 1, 1)
        month_end = next_month - timedelta(days=1)
        window_end = min(month_end, end)
        yield cur, window_end
        cur = window_end + timedelta(days=1)


def _existing_event_ids(db: SettingsDB, target_date: str) -> set[str]:
    rows = db._conn.execute(
        "SELECT event_id FROM market_events WHERE event_date = ?",
        (target_date,),
    ).fetchall()
    return {str(r[0]) for r in rows}


def _propagated_event_ids(db: SettingsDB, target_date: str) -> set[str]:
    rows = db._conn.execute(
        """SELECT DISTINCT ep.event_id FROM event_propagations ep
           JOIN market_events me ON me.event_id = ep.event_id
           WHERE me.event_date = ?""",
        (target_date,),
    ).fetchall()
    return {str(r[0]) for r in rows}


def _default_sync_range(data_root: str) -> tuple[date, date]:
    db = SettingsDB(data_root)
    window_days = int(db.get("event.sync_window_days", 7) or 7)
    end = date.today()
    start = end - timedelta(days=max(0, window_days - 1))
    return start, end


def sync_events(
    data_root: str,
    start: str | None = None,
    end: str | None = None,
    failed_only: bool = False,
    force: bool = False,
) -> EventSyncSummary:
    db = SettingsDB(data_root)
    min_magnitude = float(db.get("event.min_magnitude", 0.4))
    range_start, range_end = _default_sync_range(data_root)
    if start:
        range_start = date.fromisoformat(start)
    if end:
        range_end = date.fromisoformat(end)
    if range_start > range_end:
        raise ValueError(f"start ({range_start}) > end ({range_end})")

    from trade_py.analysis.knowledge_graph import SectorGraph

    summary = EventSyncSummary()
    available_events = set(SectorGraph.from_db(data_root, merge_defaults=True).available_events())
    valid_event_types = {e.value for e in EventType}

    for target_date in _date_range(range_start, range_end):
        summary.scanned_dates += 1
        silver = _read_silver_for_date(Path(data_root), target_date)
        if silver.empty:
            continue
        summary.dates_with_silver += 1
        candidate_events = _extract_events(silver, min_magnitude=min_magnitude)
        if not candidate_events:
            summary.empty_dates += 1
            legacy_types = {
                str(v) for v in silver.get("event_type", [])
                if str(v) and str(v) not in valid_event_types
            }
            if legacy_types:
                summary.legacy_dates += 1
            continue

        summary.candidate_events += len(candidate_events)
        existing_ids = _existing_event_ids(db, target_date.isoformat())
        propagated_ids = _propagated_event_ids(db, target_date.isoformat())
        pending: list[dict] = []
        for ev in candidate_events:
            event_id = str(ev["event_id"])
            needs_event = force or event_id not in existing_ids
            needs_prop = (
                force
                or (
                    ev["event_type"] in available_events
                    and event_id not in propagated_ids
                )
            )
            if failed_only:
                if needs_prop:
                    pending.append(ev)
            elif needs_event or needs_prop:
                pending.append(ev)

        if not pending:
            continue

        n_events, n_prop, n_sym = run_event_pipeline_batch(data_root, pending)
        summary.synced_events += n_events
        summary.propagated_rows += n_prop
        summary.affected_symbols += n_sym

    return summary


def rebuild_events(
    data_root: str,
    start: str | None = None,
    end: str | None = None,
    *,
    propagate: bool = False,
    incremental_by_month: bool = False,
) -> EventSyncSummary:
    db = SettingsDB(data_root)
    range_start, range_end = _default_sync_range(data_root)
    if start:
        range_start = date.fromisoformat(start)
    if end:
        range_end = date.fromisoformat(end)
    if range_start > range_end:
        raise ValueError(f"start ({range_start}) > end ({range_end})")

    if incremental_by_month:
        merged = EventSyncSummary()
        for window_start, window_end in _month_windows(range_start, range_end):
            partial = rebuild_events(
                data_root,
                start=window_start.isoformat(),
                end=window_end.isoformat(),
                propagate=propagate,
                incremental_by_month=False,
            )
            merged.merge(partial)
        return merged

    db.event_delete_range(range_start.isoformat(), range_end.isoformat())
    if propagate:
        return sync_events(
            data_root,
            start=range_start.isoformat(),
            end=range_end.isoformat(),
            failed_only=False,
            force=True,
        )

    min_magnitude = float(db.get("event.min_magnitude", 0.4))
    valid_event_types = {e.value for e in EventType}
    summary = EventSyncSummary()
    for target_date in _date_range(range_start, range_end):
        summary.scanned_dates += 1
        silver = _read_silver_for_date(Path(data_root), target_date)
        if silver.empty:
            continue
        summary.dates_with_silver += 1
        candidate_events = _extract_events(silver, min_magnitude=min_magnitude)
        if not candidate_events:
            summary.empty_dates += 1
            legacy_types = {
                str(v) for v in silver.get("event_type", [])
                if str(v) and str(v) not in valid_event_types
            }
            if legacy_types:
                summary.legacy_dates += 1
            continue

        summary.candidate_events += len(candidate_events)
        for ev in candidate_events:
            db.event_upsert(ev)
        summary.synced_events += len(candidate_events)
    return summary


def backfill_events(data_root: str, start: str | None = None, end: str | None = None) -> str:
    if start or end:
        if not start or not end:
            raise ValueError("backfill range requires both start and end")
        n5, n20 = run_event_backfill_range(data_root, start, end)
    else:
        n5, n20 = run_event_backfill(data_root)
    return f"回填超额收益: 5d={n5}条, 20d={n20}条"


def realize_planned_events(
    data_root: str,
    *,
    planned_event_ids: list[str] | None = None,
    refresh: bool = True,
    as_of: str | None = None,
) -> str:
    db = SettingsDB(data_root)
    as_of_dt = datetime.fromisoformat(as_of) if as_of else datetime.now()

    if planned_event_ids:
        rows = [
            db.planned_event_get(planned_event_id)
            for planned_event_id in planned_event_ids
        ]
        rows = [row for row in rows if row]
    else:
        rows = db.planned_events_due(as_of_dt, limit=200)

    if not rows:
        return "计划事件落地: 无到期 planned_events"

    if refresh:
        dates = [date.fromisoformat(str(row["event_date"])) for row in rows if row.get("event_date")]
        symbols = [
            str(row.get("entity_id") or "").strip().upper()
            for row in rows
            if str(row.get("entity_id") or "").strip().upper().endswith((".SH", ".SZ", ".BJ"))
        ]
        if dates:
            from trade_py.data.market.calendar import TradingCalendarService

            service = TradingCalendarService(data_root)
            try:
                try:
                    service.sync_planned_events(
                        start_date=min(dates) - timedelta(days=1),
                        end_date=max(dates) + timedelta(days=1),
                        symbols=symbols or None,
                        build_agenda=False,
                    )
                except Exception as exc:
                    logger.warning("planned event refresh skipped: %s", exc)
            finally:
                service.close()
            rows = [
                db.planned_event_get(str(row["planned_event_id"]))
                for row in rows
            ]
            rows = [row for row in rows if row]

    event_dicts: list[dict] = []
    released_ids: list[tuple[str, str]] = []
    live_count = 0
    expired_count = 0
    skipped_count = 0

    for row in rows:
        planned_event_id = str(row.get("planned_event_id") or "")
        if not planned_event_id:
            continue
        if row.get("realized_event_id"):
            continue
        event_dict = _planned_to_market_event(row)
        if event_dict is not None:
            event_dicts.append(event_dict)
            released_ids.append((planned_event_id, event_dict["event_id"]))
            continue
        event_day = date.fromisoformat(str(row.get("event_date") or as_of_dt.date().isoformat()))
        if event_day < as_of_dt.date():
            db.planned_event_update(planned_event_id, status="expired")
            expired_count += 1
        else:
            db.planned_event_update(planned_event_id, status="live")
            live_count += 1
        skipped_count += 1

    n_events = n_prop = n_symbols = 0
    if event_dicts:
        n_events, n_prop, n_symbols = run_event_pipeline_batch(data_root, event_dicts)
        for planned_event_id, event_id in released_ids:
            db.planned_event_update(
                planned_event_id,
                status="released",
                realized_event_id=event_id,
            )

    return (
        f"计划事件落地: scanned={len(rows)} released={len(released_ids)} "
        f"live={live_count} expired={expired_count} skipped={skipped_count} "
        f"events={n_events} propagations={n_prop} symbols={n_symbols}"
    )
