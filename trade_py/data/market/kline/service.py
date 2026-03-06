from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

import pandas as pd

from trade_py.data.market.kline.akshare import KlineFetcher
from trade_py.data.market.kline.providers import build_provider_chain, ensure_symbol
from trade_py.db.instruments_db import InstrumentsDB

logger = logging.getLogger(__name__)

KlineMode = Literal["incremental", "range", "full"]
KlineAdjust = Literal["hfq", "qfq", "none"]


@dataclass
class KlineSyncOptions:
    mode: KlineMode = "incremental"
    symbols: list[str] | None = None
    start: str | None = None
    end: str | None = None
    adjust: KlineAdjust = "hfq"
    provider: str = "auto"
    delay_ms: int = 300
    fail_fast: bool = False


@dataclass
class SymbolSyncResult:
    symbol: str
    ok: bool
    rows: int
    provider: str
    start: str | None
    end: str | None
    error_kind: str | None = None
    error_message: str | None = None


@dataclass
class SyncSummary:
    total_symbols: int
    succeeded: int
    failed: int
    empty: int
    total_rows: int
    results: dict[str, SymbolSyncResult]


class KlineSyncService:
    def __init__(self, data_root: str | Path) -> None:
        self._data_root = Path(data_root)
        self._db = InstrumentsDB(self._data_root)
        self._fetcher = KlineFetcher(self._data_root)
        self._failure_log = self._data_root / ".metadata" / "kline_failures.jsonl"
        self._failure_log.parent.mkdir(parents=True, exist_ok=True)

    def refresh_instruments(self) -> list[tuple[str, str]]:
        return self._fetcher.fetch_instruments()

    def _resolve_symbols(self, symbols: list[str] | None) -> list[str]:
        if symbols:
            resolved = [ensure_symbol(s.strip()) for s in symbols if s.strip()]
            return sorted(set(resolved))
        return self._db.get_all_symbols()

    @staticmethod
    def _parse_date(v: str) -> date:
        return date.fromisoformat(v[:10])

    @staticmethod
    def _month_chunks(start_date: date, end_date: date) -> list[tuple[date, date]]:
        chunks: list[tuple[date, date]] = []
        cur = start_date
        while cur <= end_date:
            if cur.month == 12:
                month_end = date(cur.year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(cur.year, cur.month + 1, 1) - timedelta(days=1)
            to_d = min(month_end, end_date)
            chunks.append((cur, to_d))
            cur = to_d + timedelta(days=1)
        return chunks

    def _last_watermark(self, symbol: str) -> date | None:
        values = [
            self._db.get_watermark("akshare", "kline", symbol),
            self._db.get_watermark("baostock", "kline", symbol),
        ]
        values = [v for v in values if v is not None]
        return max(values) if values else None

    def _resolve_range(self, symbol: str, opts: KlineSyncOptions) -> tuple[date, date] | None:
        today = date.today()
        if opts.mode == "incremental":
            wm = self._last_watermark(symbol)
            start_d = (wm + timedelta(days=1)) if wm else self._parse_date(opts.start or "2020-01-01")
            end_d = self._parse_date(opts.end) if opts.end else today
        elif opts.mode == "range":
            if not opts.start:
                raise ValueError("range mode requires --start")
            start_d = self._parse_date(opts.start)
            end_d = self._parse_date(opts.end) if opts.end else today
        else:  # full
            start_d = self._parse_date(opts.start) if opts.start else date(2000, 1, 1)
            end_d = self._parse_date(opts.end) if opts.end else today
        if start_d > end_d:
            return None
        return start_d, end_d

    def _record_failure(
        self,
        symbol: str,
        provider: str,
        start: str,
        end: str,
        error_kind: str,
        error_message: str,
    ) -> None:
        payload = {
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "symbol": symbol,
            "provider": provider,
            "start": start,
            "end": end,
            "error_kind": error_kind,
            "error_message": error_message,
        }
        with self._failure_log.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def sync(self, opts: KlineSyncOptions) -> SyncSummary:
        symbols = self._resolve_symbols(opts.symbols)
        if not symbols:
            logger.warning("No symbols available. Run: trade data kline instruments")
            return SyncSummary(0, 0, 0, 0, 0, {})

        chain = build_provider_chain(opts.provider)
        results: dict[str, SymbolSyncResult] = {}
        succeeded = 0
        failed = 0
        empty = 0
        total_rows = 0

        for i, symbol in enumerate(symbols, 1):
            target = self._resolve_range(symbol, opts)
            if target is None:
                results[symbol] = SymbolSyncResult(
                    symbol=symbol, ok=True, rows=0, provider="none",
                    start=None, end=None,
                )
                empty += 1
                continue
            start_d, end_d = target
            chunks = self._month_chunks(start_d, end_d)
            provider_name = "none"
            parts: list[pd.DataFrame] = []
            symbol_failed = False
            err_kind: str | None = None
            err_msg: str | None = None

            for chunk_start, chunk_end in chunks:
                f = chain.fetch(
                    symbol=symbol,
                    start=chunk_start.isoformat(),
                    end=chunk_end.isoformat(),
                    adjust=opts.adjust,
                )
                provider_name = f.provider
                if f.error_kind is not None:
                    symbol_failed = True
                    err_kind = f.error_kind
                    err_msg = f.error_message
                    self._record_failure(
                        symbol=symbol,
                        provider=f.provider,
                        start=chunk_start.isoformat(),
                        end=chunk_end.isoformat(),
                        error_kind=f.error_kind,
                        error_message=f.error_message or "",
                    )
                    break
                if not f.df.empty:
                    parts.append(f.df)

            if symbol_failed:
                failed += 1
                results[symbol] = SymbolSyncResult(
                    symbol=symbol,
                    ok=False,
                    rows=0,
                    provider=provider_name,
                    start=start_d.isoformat(),
                    end=end_d.isoformat(),
                    error_kind=err_kind,
                    error_message=err_msg,
                )
                logger.error(
                    "kline sync failed symbol=%s provider=%s kind=%s error=%s",
                    symbol, provider_name, err_kind, err_msg,
                )
                if opts.fail_fast:
                    break
            else:
                if parts:
                    merged = pd.concat(parts, ignore_index=True)
                    merged = merged.drop_duplicates(subset=["date"], keep="last")
                    merged = merged.sort_values("date").reset_index(drop=True)
                    self._fetcher.save_parquet(symbol, merged)
                    min_d = self._parse_date(str(merged["date"].min()))
                    max_d = self._parse_date(str(merged["date"].max()))
                    for src in ("akshare", "baostock"):
                        self._db.set_watermark(src, "kline", symbol, max_d)
                    self._db.record_download(symbol, min_d, max_d, len(merged))
                    rows = len(merged)
                    total_rows += rows
                else:
                    rows = 0

                ok = True
                succeeded += 1
                if rows == 0:
                    empty += 1
                results[symbol] = SymbolSyncResult(
                    symbol=symbol,
                    ok=ok,
                    rows=rows,
                    provider=provider_name,
                    start=start_d.isoformat(),
                    end=end_d.isoformat(),
                )
                logger.info(
                    "kline sync ok symbol=%s rows=%d provider=%s range=%s..%s (%d/%d)",
                    symbol, rows, provider_name, start_d, end_d, i, len(symbols),
                )

            if i < len(symbols) and opts.delay_ms > 0:
                time.sleep(opts.delay_ms / 1000.0)

        return SyncSummary(
            total_symbols=len(symbols),
            succeeded=succeeded,
            failed=failed,
            empty=empty,
            total_rows=total_rows,
            results=results,
        )

    def status(self, stale_days: int | None = None, limit: int | None = None) -> list[dict[str, str]]:
        symbols = self._db.get_all_symbols()
        if not symbols:
            return []

        latest_failure: dict[str, str] = {}
        if self._failure_log.exists():
            for line in self._failure_log.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                    latest_failure[str(payload.get("symbol", ""))] = str(payload.get("error_kind", ""))
                except json.JSONDecodeError:
                    continue

        today = date.today()
        rows: list[dict[str, str]] = []
        for sym in symbols:
            wm = self._last_watermark(sym)
            dl = self._db.last_download_date(sym)
            ref = wm or dl
            stale = (today - ref).days if ref else -1
            if stale_days is not None and ref is not None and stale < stale_days:
                continue
            rows.append({
                "symbol": sym,
                "watermark": wm.isoformat() if wm else "-",
                "last_download": dl.isoformat() if dl else "-",
                "stale_days": str(stale if ref else -1),
                "last_error_kind": latest_failure.get(sym, "-"),
            })

        rows.sort(
            key=lambda r: (
                -1 if r["stale_days"] == "-1" else int(r["stale_days"]),
                r["symbol"],
            ),
            reverse=True,
        )
        if limit is not None and limit > 0:
            rows = rows[:limit]
        return rows

