"""A-share daily K-line fetcher using akshare.

Replaces the C++ EastMoney provider for OHLCV data collection.
Writes consolidated per-symbol Parquet files compatible with the C++ ParquetReader.

Storage layout:  data/market/kline/{symbol}.parquet

Column order (must match C++ ParquetReader):
    symbol, date, open, high, low, close, volume, amount,
    turnover_rate, prev_close, vwap

Units:
    volume      : 手 (lots = 100 shares)  — akshare native unit, kept as-is
    amount      : 元 (CNY)                — akshare native unit, kept as-is
    vwap        : 元/股                    — computed as amount / (volume * 100)

Usage:
    fetcher = KlineFetcher("data")
    fetcher.fetch_instruments()
    fetcher.update("600000.SH")
    fetcher.update_all()
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

import pandas as pd

from trade_py.db.instruments_db import InstrumentsDB
from trade_py.data.market.kline.providers import _finalize_frame
from trade_py.data.paths import KLINE_MANIFEST
from trade_py.utils.a_share_symbols import ensure_a_share_symbol, infer_a_share_suffix
from trade_py.utils.retry import retry

logger = logging.getLogger(__name__)

# Watermark key constants (must be consistent across fetch calls)
_SOURCE = "akshare"
_DATASET = "kline"

# Parquet column order expected by C++ ParquetReader
_COLUMN_ORDER = [
    "symbol", "date", "open", "high", "low", "close",
    "volume", "amount", "turnover_rate", "prev_close", "vwap",
]

_FETCH_RETRY_DELAYS_SEC = (1.0, 3.0, 8.0)


def _classify_fetch_error(exc: Exception) -> str:
    text = str(exc).lower()
    name = type(exc).__name__.lower()
    if "timeout" in text or "timedout" in text or "timeout" in name:
        return "timeout"
    if "remote end closed connection" in text or "connection aborted" in text:
        return "upstream_disconnect"
    if "name or service not known" in text or "temporary failure in name resolution" in text:
        return "dns_failure"
    if "refused" in text:
        return "connection_refused"
    return "unknown"


def _to_akshare_code(symbol: str) -> str:
    """Convert 'NNNNNN.SH' → '600000', stripping exchange suffix."""
    return symbol.split(".")[0]


def _infer_suffix(code: str) -> str:
    return infer_a_share_suffix(code)


def _ensure_symbol(code_or_symbol: str) -> str:
    """Return a canonical symbol with suffix (e.g. '600000.SH')."""
    return ensure_a_share_symbol(code_or_symbol)


class KlineFetcher:
    """Fetch and persist A-share daily K-line data via akshare.

    Args:
        data_root: Project data root directory (e.g. "data").
    """

    def __init__(self, data_root: str | Path = "data") -> None:
        self._data_root = Path(data_root)
        self._kline_root = self._data_root / "market" / "kline"
        self._kline_root.mkdir(parents=True, exist_ok=True)
        self._db = InstrumentsDB(data_root)

    @staticmethod
    @retry(delays=_FETCH_RETRY_DELAYS_SEC, on=(Exception,))
    def _fetch_raw_hist(ak, code: str, start_ymd: str, end_ymd: str, adjust: str):
        return ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_ymd,
            end_date=end_ymd,
            adjust=adjust,
        )

    # ── Fetch ──────────────────────────────────────────────────────────────

    def fetch(
        self,
        symbol: str,
        start: str,
        end: Optional[str] = None,
        adjust: str = "none",
    ) -> pd.DataFrame:
        """Fetch daily OHLCV bars for one symbol via akshare.

        Args:
            symbol:  Stock symbol with or without suffix, e.g. "600000.SH" or "600000"
            start:   Start date string "YYYY-MM-DD"
            end:     End date string "YYYY-MM-DD" (defaults to today)
            adjust:  Price adjustment type: "hfq" (back-adjusted), "qfq" (forward), "" (none)

        Returns:
            DataFrame with columns matching _COLUMN_ORDER, sorted ascending by date.
        """
        import akshare as ak  # lazy import to avoid mandatory dependency at module load

        symbol = _ensure_symbol(symbol)
        code = _to_akshare_code(symbol)
        end_str = end or date.today().isoformat()

        # akshare expects dates without hyphens for some APIs; use YYYYMMDD.
        start_ymd = start.replace("-", "")
        end_ymd = end_str.replace("-", "")
        ak_adjust = "" if adjust == "none" else adjust
        try:
            raw = self._fetch_raw_hist(ak, code, start_ymd, end_ymd, ak_adjust)
        except Exception as exc:
            error_kind = _classify_fetch_error(exc)
            logger.warning(
                (
                    "akshare fetch failed "
                    "symbol=%s code=%s start=%s end=%s adjust=%s "
                    "kind=%s error_type=%s error=%r"
                ),
                symbol, code, start, end_str, adjust,
                error_kind, type(exc).__name__, exc,
            )
            return pd.DataFrame()

        if raw is None or raw.empty:
            return pd.DataFrame()

        # Rename columns from Chinese to English
        col_map = {
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",       # 手 (lots)
            "成交额": "amount",       # 元
            "换手率": "turnover_rate",
            "涨跌幅": "pct_chg",
        }
        df = raw.rename(columns=col_map)

        # Keep only the columns we care about (ignore akshare extras like 振幅/涨跌幅...)
        keep = [c for c in col_map.values() if c in df.columns]
        return _finalize_frame(symbol, df[keep].copy())

    # ── Parquet I/O ────────────────────────────────────────────────────────

    def _flat_path(self, symbol: str) -> Path:
        return self._kline_root / f"{symbol.replace('.', '_')}.parquet"

    def _legacy_month_paths(self, symbol: str) -> list[Path]:
        safe_sym = symbol.replace('.', '_')
        return sorted(self._kline_root.glob(f"20??-??/{safe_sym}.parquet"))

    def _normalize_frame(self, symbol: str, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=_COLUMN_ORDER)
        combined = df.copy()
        combined["symbol"] = symbol
        combined["date"] = combined["date"].astype(str).str[:10]
        combined = combined.dropna(subset=["date"])
        combined = combined.drop_duplicates(subset=["date"], keep="last")
        combined = combined.sort_values("date").reset_index(drop=True)
        for col in _COLUMN_ORDER:
            if col not in combined.columns:
                combined[col] = 0.0 if col != "symbol" else symbol
        combined["symbol"] = combined["symbol"].fillna(symbol)
        return combined[_COLUMN_ORDER]

    def _load_existing_symbol(self, symbol: str) -> pd.DataFrame:
        flat_path = self._flat_path(symbol)
        if flat_path.exists():
            try:
                return self._normalize_frame(symbol, pd.read_parquet(flat_path))
            except Exception as exc:
                logger.warning("Ignoring unreadable flat parquet %s during repair: %s", flat_path, exc)

        frames: list[pd.DataFrame] = []
        for legacy_path in self._legacy_month_paths(symbol):
            try:
                frames.append(pd.read_parquet(legacy_path))
            except Exception as exc:
                logger.warning("Ignoring unreadable legacy parquet %s during repair: %s", legacy_path, exc)
        if not frames:
            return pd.DataFrame(columns=_COLUMN_ORDER)
        return self._normalize_frame(symbol, pd.concat(frames, ignore_index=True))

    def _write_symbol_frame(self, symbol: str, df: pd.DataFrame, *, merge_existing: bool) -> Path | None:
        if df.empty:
            return None
        incoming = self._normalize_frame(symbol, df)
        if merge_existing:
            existing = self._load_existing_symbol(symbol)
            if not existing.empty:
                incoming = self._normalize_frame(symbol, pd.concat([existing, incoming], ignore_index=True))

        out_path = self._flat_path(symbol)
        tmp_path = out_path.with_name(f".{out_path.name}.{uuid4().hex}.tmp")
        incoming.to_parquet(tmp_path, index=False, compression=None)
        tmp_path.replace(out_path)
        self._update_manifest(symbol, incoming, out_path)
        return out_path

    def _update_manifest(self, symbol: str, df: pd.DataFrame, path: Path) -> None:
        manifest_path = KLINE_MANIFEST(self._data_root)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        manifest: dict[str, object]
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            except Exception as exc:
                logger.warning("Ignoring unreadable manifest %s during rewrite: %s", manifest_path, exc)
                manifest = {}
        else:
            manifest = {}

        entries = manifest.setdefault('entries', {})
        assert isinstance(entries, dict)
        safe_sym = symbol.replace('.', '_')
        bytes_size = path.stat().st_size if path.exists() else 0
        entries[safe_sym] = {
            'rows': int(len(df)),
            'date_min': str(df['date'].min()) if not df.empty else None,
            'date_max': str(df['date'].max()) if not df.empty else None,
            'bytes': int(bytes_size),
            'updated_at': now,
        }
        manifest.update({
            'dataset': 'kline',
            'layout': 'per_symbol',
            'schema_version': 2,
            'columns': list(_COLUMN_ORDER),
            'primary_key': ['symbol', 'date'],
            'last_compaction': now,
        })
        tmp_path = manifest_path.with_name(f".{manifest_path.name}.{uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
        tmp_path.replace(manifest_path)

    def save_parquet(self, symbol: str, df: pd.DataFrame) -> None:
        """Persist a DataFrame to a per-symbol Parquet file.

        The writer keeps backward compatibility during migration by merging any
        existing monthly shards the first time a symbol is touched, then writing
        a single authoritative file at ``market/kline/{symbol}.parquet``.
        """
        out_path = self._write_symbol_frame(symbol, df, merge_existing=True)
        if out_path is not None:
            logger.debug("Saved %d rows for %s -> %s", len(df), symbol, out_path)

    def replace_month_parquet(self, symbol: str, df: pd.DataFrame) -> None:
        """Rewrite the authoritative per-symbol file without reading old rows first."""
        out_path = self._write_symbol_frame(symbol, df, merge_existing=False)
        if out_path is not None:
            logger.debug("Replaced %d rows for %s -> %s", len(df), symbol, out_path)

    # ── Incremental update ─────────────────────────────────────────────────

    def update(
        self,
        symbol: str,
        start_fallback: str | None = None,
        adjust: str = "none",
    ) -> int:
        """Incrementally fetch new bars for one symbol and persist to Parquet.

        Uses the watermark table to determine the fetch start date.

        Args:
            symbol:         Stock symbol e.g. "600000.SH"
            start_fallback: Date to use when no watermark exists. None => read settings.kline.start
            adjust:         akshare price adjustment mode

        Returns:
            Number of rows fetched and saved (0 if nothing new)
        """
        symbol = _ensure_symbol(symbol)
        wm = self._db.get_watermark(_SOURCE, _DATASET, symbol)
        if wm is not None:
            # Start from the day after the last watermark
            fetch_start = (wm + timedelta(days=1)).isoformat()
        else:
            fetch_start = str(self._db.get("kline.start", None) or start_fallback or "2024-01-01")

        today = date.today().isoformat()
        if fetch_start > today:
            logger.debug("%s is already up to date (watermark=%s)", symbol, wm)
            return 0

        df = self.fetch(symbol, start=fetch_start, end=today, adjust=adjust)
        if df.empty:
            logger.info("No new data for %s since %s", symbol, fetch_start)
            return 0

        self.save_parquet(symbol, df)

        # Update watermark to the latest date in the fetched data
        latest_date = date.fromisoformat(df["date"].max())
        self._db.set_watermark(_SOURCE, _DATASET, symbol, latest_date)
        self._db.record_download(
            symbol,
            start=date.fromisoformat(df["date"].min()),
            end=latest_date,
            row_count=len(df),
        )
        logger.info("Updated %s: %d rows (%s → %s)", symbol, len(df), fetch_start, latest_date)
        return len(df)

    def update_all(
        self,
        symbols: Optional[list[str]] = None,
        start_fallback: str | None = None,
        delay_ms: int = 200,
    ) -> dict[str, int]:
        """Incrementally update all (or specified) symbols.

        Args:
            symbols:        List of symbols to update (defaults to all in DB)
            start_fallback: Fallback start date for symbols with no watermark. None => read settings.kline.start
            delay_ms:       Delay in milliseconds between requests (rate limiting)

        Returns:
            Dict mapping symbol → rows fetched
        """
        if symbols is None:
            symbols = self._db.get_all_symbols()

        if not symbols:
            logger.warning("No symbols in database. Run fetch_instruments() first.")
            return {}

        results: dict[str, int] = {}
        for i, sym in enumerate(symbols, 1):
            try:
                n = self.update(sym, start_fallback=start_fallback)
                results[sym] = n
            except Exception as exc:
                logger.error("Failed to update %s: %s", sym, exc)
                results[sym] = -1
            if i < len(symbols) and delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

        total = sum(v for v in results.values() if v > 0)
        logger.info(
            "update_all done: %d/%d symbols, %d total new rows",
            len(results), len(symbols), total,
        )
        return results

    # ── Instrument list ────────────────────────────────────────────────────

    def fetch_instruments(self) -> list[tuple[str, str]]:
        """Fetch the full A-share instrument list from akshare and upsert to DB.

        Returns:
            List of (symbol, name) tuples for all A-share stocks
        """
        import akshare as ak

        try:
            raw = ak.stock_info_a_code_name()
        except Exception as exc:
            logger.error("akshare fetch_instruments failed: %s", exc)
            return []

        if raw is None or raw.empty:
            return []

        result: list[tuple[str, str]] = []
        for _, row in raw.iterrows():
            code = str(row.get("code", row.get("股票代码", ""))).strip()
            name = str(row.get("name", row.get("股票名称", ""))).strip()
            if not code or not name:
                continue
            symbol = code + _infer_suffix(code)
            self._db.upsert_instrument(symbol, name)
            result.append((symbol, name))

        logger.info("fetch_instruments: upserted %d instruments", len(result))
        return result
