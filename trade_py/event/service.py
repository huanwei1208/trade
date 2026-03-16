from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from trade_py.db.event_db import EventType
from trade_py.db.settings_db import SettingsDB
from trade_py.report.event_pipeline import (
    _extract_events,
    _read_silver_for_date,
    run_event_backfill,
    run_event_backfill_range,
    run_event_pipeline_batch,
)


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
