"""Trading calendar and planned-event sync via Tushare."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

from trade_py.data.market.tushare_client import TushareAuthError, get_pro_api
from trade_py.db.trade_db import TradeDB

logger = logging.getLogger(__name__)

_DEFAULT_EXCHANGES = ("SSE", "SZSE")
_DEFAULT_TIMEZONE = "Asia/Shanghai"
_DEFAULT_DATE_TIME = "09:00:00"


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan", "nat"}:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _date_text(value: Any) -> str | None:
    dt = _to_date(value)
    return dt.isoformat() if dt is not None else None


def _tushare_date(value: Any) -> str | None:
    dt = _to_date(value)
    return dt.strftime("%Y%m%d") if dt is not None else None


def _normalize_time_text(value: Any, default: str | None = None) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "null", "nan", "nat"}:
        return default
    digits = "".join(ch for ch in text if ch.isdigit())
    if ":" in text:
        parts = text.split(":")
        if len(parts) >= 2:
            hh = parts[0].zfill(2)
            mm = parts[1].zfill(2)
            ss = parts[2].zfill(2) if len(parts) >= 3 else "00"
            return f"{hh}:{mm}:{ss}"
    if len(digits) >= 4:
        hh = digits[:2]
        mm = digits[2:4]
        ss = digits[4:6] if len(digits) >= 6 else "00"
        return f"{hh}:{mm}:{ss}"
    return default


def _scheduled_at(event_date: str, event_time: str | None, default_time: str = _DEFAULT_DATE_TIME) -> str:
    return f"{event_date} {event_time or default_time}"


def _month_ranges(start: date, end: date) -> Iterable[tuple[date, date]]:
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        if cursor.month == 12:
            nxt = date(cursor.year + 1, 1, 1)
        else:
            nxt = date(cursor.year, cursor.month + 1, 1)
        chunk_start = max(start, cursor)
        chunk_end = min(end, nxt - timedelta(days=1))
        yield chunk_start, chunk_end
        cursor = nxt


def _date_range(start: date, end: date) -> Iterable[date]:
    cursor = start
    while cursor <= end:
        yield cursor
        cursor += timedelta(days=1)


def _stable_planned_event_id(source: str, vendor_event_id: str) -> str:
    digest = hashlib.sha1(f"{source}|{vendor_event_id}".encode("utf-8")).hexdigest()[:24]
    return f"pe_{digest}"


def _importance_from_text(title: str) -> str:
    text = title.upper()
    high = ("利率", "RATE", "CPI", "PPI", "PMI", "GDP", "非农", "NFP", "FOMC", "议息", "财报")
    medium = ("出口", "进口", "M2", "融资", "零售", "失业", "社融", "贸易")
    if any(key in text for key in high):
        return "high"
    if any(key in text for key in medium):
        return "medium"
    return "low"


def _event_type_from_title(title: str, source: str) -> str:
    text = title.upper()
    if source == "tushare_disclosure_date":
        return "earnings_disclosure"
    if "利率" in text or "RATE" in text or "FOMC" in text:
        return "macro_rate_decision"
    if "CPI" in text:
        return "macro_cpi"
    if "PPI" in text:
        return "macro_ppi"
    if "PMI" in text:
        return "macro_pmi"
    if "GDP" in text:
        return "macro_gdp"
    if "就业" in text or "NFP" in text or "非农" in text:
        return "macro_employment"
    if "贸易" in text or "出口" in text or "进口" in text:
        return "macro_trade"
    return "macro_calendar"


def _priority_from_importance(importance: str, phase: str) -> int:
    base = {"high": 20, "medium": 40, "low": 60}.get(str(importance or "medium").lower(), 40)
    phase_adj = {"pre": -5, "live": -10, "post": 0}.get(phase, 0)
    return max(1, base + phase_adj)


@dataclass(frozen=True)
class CalendarSyncSummary:
    exchange_count: int
    row_count: int
    start_date: str
    end_date: str
    fallback_used: bool = False
    fallback_reason: str = ""


@dataclass(frozen=True)
class PlannedEventSyncSummary:
    eco_rows: int
    disclosure_rows: int
    agenda_rows: int
    start_date: str
    end_date: str
    fallback_used: bool = False
    fallback_reason: str = ""
    cached_rows: int = 0


class TradingCalendarService:
    """Sync trading-calendar facts and future planned events into TradeDB."""

    def __init__(self, data_root: str | Path = "data") -> None:
        self.data_root = str(data_root)
        self._db = TradeDB(data_root)
        self._pro = None

    def close(self) -> None:
        self._db.close()

    def _pro_api(self):
        if self._pro is not None:
            return self._pro
        try:
            self._pro = get_pro_api(self.data_root)
        except RuntimeError as exc:
            raise TushareAuthError(str(exc)) from exc
        return self._pro

    def _default_calendar_range(self) -> tuple[date, date]:
        today = date.today()
        return date(today.year, 1, 1), date(today.year + 1, 12, 31)

    def _cached_calendar_rows(self, start: date, end: date, exchange: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for current in _date_range(start, end):
            row = self._db.trading_calendar_get(current.isoformat(), exchange=exchange)
            if row:
                rows.append(row)
        return rows

    def _weekday_fallback_calendar_rows(self, start: date, end: date, exchange: str) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        previous_open: str | None = None
        for current in _date_range(start, end):
            is_open = 1 if current.weekday() < 5 else 0
            trade_date = current.isoformat()
            payload.append({
                "exchange": exchange,
                "trade_date": trade_date,
                "is_open": is_open,
                "pretrade_date": previous_open or trade_date,
                "session_am_open": "09:30:00",
                "session_am_close": "11:30:00",
                "session_pm_open": "13:00:00",
                "session_pm_close": "15:00:00",
                "source": "fallback_weekday",
            })
            if is_open:
                previous_open = trade_date
        return payload

    def _cached_planned_event_count(self, start: date, end: date) -> int:
        return len(
            self._db.planned_events_list(
                start_date=start,
                end_date=end,
                limit=10000,
            )
        )

    def sync_calendar(
        self,
        *,
        start_date: str | date | datetime | None = None,
        end_date: str | date | datetime | None = None,
        exchanges: Sequence[str] = _DEFAULT_EXCHANGES,
    ) -> CalendarSyncSummary:
        start = _to_date(start_date)
        end = _to_date(end_date)
        if start is None or end is None:
            default_start, default_end = self._default_calendar_range()
            start = start or default_start
            end = end or default_end
        start_ts = _tushare_date(start)
        end_ts = _tushare_date(end)
        total_rows = 0
        exchange_count = 0
        fallback_used = False
        fallback_reasons: list[str] = []
        for exchange in exchanges:
            try:
                raw = self._pro_api().call("trade_cal", exchange=str(exchange).upper(), start_date=start_ts, end_date=end_ts)
            except TushareAuthError as exc:
                fallback_used = True
                fallback_reasons.append(f"{exchange}: auth fallback")
                cached_rows = self._cached_calendar_rows(start, end, str(exchange).upper())
                if cached_rows:
                    total_rows += len(cached_rows)
                    exchange_count += 1
                    logger.warning(
                        "TradingCalendarService: using cached trading calendar for %s range=%s..%s because auth failed: %s",
                        exchange, _date_text(start), _date_text(end), exc,
                    )
                    continue
                payload = self._weekday_fallback_calendar_rows(start, end, str(exchange).upper())
                self._db.trading_calendar_upsert_batch(payload)
                self._db.sync_state_set(
                    "fallback", "trade_cal", str(exchange).upper(),
                    last_date=_date_text(end), row_count=len(payload),
                )
                total_rows += len(payload)
                exchange_count += 1
                logger.warning(
                    "TradingCalendarService: using weekday fallback for %s range=%s..%s because auth failed: %s",
                    exchange, _date_text(start), _date_text(end), exc,
                )
                continue
            if raw is None or raw.empty:
                continue
            payload: list[dict[str, Any]] = []
            for _, item in raw.iterrows():
                payload.append({
                    "exchange": exchange,
                    "trade_date": item.get("cal_date"),
                    "is_open": int(item.get("is_open") or 0),
                    "pretrade_date": item.get("pretrade_date"),
                    "session_am_open": "09:30:00",
                    "session_am_close": "11:30:00",
                    "session_pm_open": "13:00:00",
                    "session_pm_close": "15:00:00",
                    "source": "tushare_trade_cal",
                })
            self._db.trading_calendar_upsert_batch(payload)
            self._db.sync_state_set(
                "tushare", "trade_cal", str(exchange).upper(),
                last_date=_date_text(end), row_count=len(payload),
            )
            total_rows += len(payload)
            exchange_count += 1
        summary = CalendarSyncSummary(
            exchange_count=exchange_count,
            row_count=total_rows,
            start_date=_date_text(start) or "",
            end_date=_date_text(end) or "",
            fallback_used=fallback_used,
            fallback_reason="; ".join(fallback_reasons[:3]),
        )
        logger.info(
            "TradingCalendarService: synced calendar exchanges=%d rows=%d range=%s..%s fallback=%s",
            summary.exchange_count, summary.row_count, summary.start_date, summary.end_date,
            summary.fallback_reason or "-",
        )
        return summary

    def _default_planned_event_range(self) -> tuple[date, date]:
        today = date.today()
        return today - timedelta(days=7), today + timedelta(days=90)

    def sync_planned_events(
        self,
        *,
        start_date: str | date | datetime | None = None,
        end_date: str | date | datetime | None = None,
        symbols: Sequence[str] | None = None,
        include_eco: bool = True,
        include_disclosure: bool = True,
        build_agenda: bool = True,
    ) -> PlannedEventSyncSummary:
        start = _to_date(start_date)
        end = _to_date(end_date)
        if start is None or end is None:
            default_start, default_end = self._default_planned_event_range()
            start = start or default_start
            end = end or default_end
        eco_rows = 0
        disclosure_rows = 0
        fallback_used = False
        fallback_reasons: list[str] = []
        if include_eco:
            try:
                eco_rows = self._sync_eco_cal(start, end)
            except TushareAuthError as exc:
                fallback_used = True
                fallback_reasons.append("eco_cal auth fallback")
                logger.warning(
                    "TradingCalendarService: using cached planned eco events range=%s..%s because auth failed: %s",
                    _date_text(start), _date_text(end), exc,
                )
        if include_disclosure:
            try:
                disclosure_rows = self._sync_disclosure_dates(start, end, symbols=symbols)
            except TushareAuthError as exc:
                fallback_used = True
                fallback_reasons.append("disclosure auth fallback")
                logger.warning(
                    "TradingCalendarService: using cached disclosure events range=%s..%s because auth failed: %s",
                    _date_text(start), _date_text(end), exc,
                )
        agenda_rows = 0
        if build_agenda:
            agenda_start = max(start, date.today())
            agenda_rows = self.build_agenda(start_date=agenda_start, end_date=end)
        summary = PlannedEventSyncSummary(
            eco_rows=eco_rows,
            disclosure_rows=disclosure_rows,
            agenda_rows=agenda_rows,
            start_date=_date_text(start) or "",
            end_date=_date_text(end) or "",
            fallback_used=fallback_used,
            fallback_reason="; ".join(fallback_reasons[:3]),
            cached_rows=self._cached_planned_event_count(start, end) if fallback_used else 0,
        )
        logger.info(
            "TradingCalendarService: synced planned events eco=%d disclosure=%d agenda=%d cached=%d range=%s..%s fallback=%s",
            summary.eco_rows, summary.disclosure_rows, summary.agenda_rows,
            summary.cached_rows, summary.start_date, summary.end_date,
            summary.fallback_reason or "-",
        )
        return summary

    def _sync_eco_cal(self, start: date, end: date) -> int:
        total_rows = 0
        payload: list[dict[str, Any]] = []
        for chunk_start, chunk_end in _month_ranges(start, end):
            raw = self._pro_api().call(
                "eco_cal",
                start_date=_tushare_date(chunk_start),
                end_date=_tushare_date(chunk_end),
            )
            if raw is None or raw.empty:
                continue
            total_rows += len(raw)
            for _, item in raw.iterrows():
                event_date = _date_text(item.get("date"))
                if not event_date:
                    continue
                event_time = _normalize_time_text(item.get("time"))
                title = str(item.get("event") or "").strip()
                source = "tushare_eco_cal"
                vendor_event_id = "|".join([
                    event_date,
                    event_time or "",
                    str(item.get("country") or "").strip(),
                    str(item.get("currency") or "").strip(),
                    title,
                ])
                payload.append({
                    "planned_event_id": _stable_planned_event_id(source, vendor_event_id),
                    "source": source,
                    "vendor_event_id": vendor_event_id,
                    "event_type": _event_type_from_title(title, source),
                    "entity_id": str(item.get("currency") or item.get("country") or "").strip(),
                    "event_date": event_date,
                    "event_time": event_time or "",
                    "scheduled_at": _scheduled_at(event_date, event_time),
                    "timezone": _DEFAULT_TIMEZONE,
                    "title": title or "宏观日历事件",
                    "country": str(item.get("country") or "").strip(),
                    "currency": str(item.get("currency") or "").strip(),
                    "importance": _importance_from_text(title),
                    "status": "scheduled",
                    "expected_value": item.get("fore_value"),
                    "previous_value": item.get("pre_value"),
                    "actual_value": item.get("value"),
                    "realized_event_id": None,
                    "payload_json": json.dumps(item.to_dict(), ensure_ascii=False, default=str),
                })
        self._db.planned_events_upsert_batch(payload)
        self._db.sync_state_set(
            "tushare", "eco_cal", "",
            last_date=_date_text(end), row_count=total_rows,
        )
        return len(payload)

    def _default_disclosure_symbols(self) -> list[str]:
        watchlist = self._db.watchlist_get()
        if watchlist:
            return watchlist
        return []

    def _sync_disclosure_dates(
        self,
        start: date,
        end: date,
        *,
        symbols: Sequence[str] | None = None,
    ) -> int:
        symbol_list = [str(symbol).strip().upper() for symbol in (symbols or self._default_disclosure_symbols()) if str(symbol).strip()]
        if not symbol_list:
            return 0
        payload: list[dict[str, Any]] = []
        total_rows = 0
        for symbol in symbol_list:
            raw = self._pro_api().call(
                "disclosure_date",
                ts_code=symbol,
                start_date=_tushare_date(start),
                end_date=_tushare_date(end),
            )
            if raw is None or raw.empty:
                continue
            total_rows += len(raw)
            for _, item in raw.iterrows():
                event_date = _date_text(item.get("pre_date") or item.get("actual_date") or item.get("ann_date"))
                if not event_date:
                    continue
                source = "tushare_disclosure_date"
                vendor_event_id = "|".join([
                    symbol,
                    str(item.get("end_date") or "").strip(),
                    event_date,
                ])
                title = f"{symbol} 定期报告披露计划"
                payload.append({
                    "planned_event_id": _stable_planned_event_id(source, vendor_event_id),
                    "source": source,
                    "vendor_event_id": vendor_event_id,
                    "event_type": _event_type_from_title(title, source),
                    "entity_id": symbol,
                    "event_date": event_date,
                    "event_time": "",
                    "scheduled_at": _scheduled_at(event_date, None),
                    "timezone": _DEFAULT_TIMEZONE,
                    "title": title,
                    "country": "CN",
                    "currency": "CNY",
                    "importance": "high",
                    "status": "scheduled",
                    "expected_value": None,
                    "previous_value": str(item.get("end_date") or ""),
                    "actual_value": str(item.get("actual_date") or ""),
                    "realized_event_id": None,
                    "payload_json": json.dumps(item.to_dict(), ensure_ascii=False, default=str),
                })
        self._db.planned_events_upsert_batch(payload)
        self._db.sync_state_set(
            "tushare", "disclosure_date", "",
            last_date=_date_text(end), row_count=total_rows,
        )
        return len(payload)

    def build_agenda(
        self,
        *,
        start_date: str | date | datetime | None = None,
        end_date: str | date | datetime | None = None,
    ) -> int:
        start = _to_date(start_date) or date.today()
        end = _to_date(end_date) or (start + timedelta(days=30))
        rows = self._db.planned_events_list(
            start_date=start,
            end_date=end,
            status="scheduled",
            limit=5000,
        )
        payload: list[dict[str, Any]] = []
        for row in rows:
            try:
                scheduled_at = datetime.fromisoformat(str(row.get("scheduled_at")))
            except ValueError:
                event_date = _date_text(row.get("event_date")) or start.isoformat()
                event_time = _normalize_time_text(row.get("event_time"), default=_DEFAULT_DATE_TIME) or _DEFAULT_DATE_TIME
                scheduled_at = datetime.fromisoformat(f"{event_date} {event_time}")
            importance = str(row.get("importance") or "medium").lower()
            planned_event_id = str(row.get("planned_event_id") or "")
            title = str(row.get("title") or "")
            if not planned_event_id:
                continue
            lead_minutes = 60 if importance == "high" else 30 if importance == "medium" else 15
            phases = [
                ("pre", scheduled_at - timedelta(minutes=lead_minutes), "realtime_quote_sync"),
                ("live", scheduled_at, "realtime_compute"),
                ("post", scheduled_at + timedelta(minutes=15), "planned_event_realize"),
            ]
            for phase, run_at, job_name in phases:
                payload.append({
                    "planned_event_id": planned_event_id,
                    "phase": phase,
                    "run_at": run_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "trigger_topic": "",
                    "job_name": job_name,
                    "payload_json": json.dumps({
                        "planned_event_id": planned_event_id,
                        "phase": phase,
                        "event_type": row.get("event_type"),
                        "entity_id": row.get("entity_id"),
                        "title": title,
                        "scheduled_at": row.get("scheduled_at"),
                    }, ensure_ascii=False),
                    "priority": _priority_from_importance(importance, phase),
                    "status": "pending",
                })
        self._db.agenda_queue_upsert_batch(payload)
        return len(payload)
