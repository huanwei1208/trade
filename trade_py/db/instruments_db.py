"""SQLite wrapper for instrument metadata and watermarks.

Shares the same database file as the C++ MetadataStore
(data/.metadata/trade.db) so that watermarks written here are visible
to C++ and vice-versa.

Schema is kept strictly compatible with the C++ DDL defined in
src/storage/metadata_store.cpp.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Market enum values (must match C++ Market enum in types.h)
_MARKET_SH = 0  # Shanghai
_MARKET_SZ = 1  # Shenzhen
_MARKET_BJ = 2  # Beijing


def _infer_market(code: str) -> int:
    """Return market integer from 6-digit stock code."""
    if code.startswith(("6", "9")):
        return _MARKET_SH
    if code.startswith(("4", "8")):
        return _MARKET_BJ
    return _MARKET_SZ


def _market_name(market: int) -> str:
    names = {0: "Shanghai", 1: "Shenzhen", 2: "Beijing", 3: "Hong Kong", 4: "US", 5: "Crypto"}
    return names.get(market, "Unknown")


class InstrumentsDB:
    """Thin SQLite wrapper that mirrors the C++ MetadataStore interface.

    Args:
        data_root: Project data root directory (e.g. "data").
                   The database lives at data_root/.metadata/trade.db
    """

    def __init__(self, data_root: str | Path = "data") -> None:
        self._data_root = Path(data_root)
        db_dir = self._data_root / ".metadata"
        db_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = db_dir / "trade.db"
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_tables()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "InstrumentsDB":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ── Schema ─────────────────────────────────────────────────────────────

    def _ensure_tables(self) -> None:
        cur = self._conn.cursor()
        # instruments — must match C++ DDL exactly
        cur.execute("""
            CREATE TABLE IF NOT EXISTS instruments (
                symbol      TEXT PRIMARY KEY,
                name        TEXT,
                market      INTEGER,
                board       INTEGER,
                industry    INTEGER,
                list_date   TEXT,
                delist_date TEXT,
                status      INTEGER,
                total_shares  INTEGER DEFAULT 0,
                float_shares  INTEGER DEFAULT 0,
                market_name   TEXT NOT NULL DEFAULT ''
            )
        """)
        # Schema migration: add columns if missing (compatible with C++ side)
        for ddl in [
            "ALTER TABLE instruments ADD COLUMN total_shares INTEGER DEFAULT 0",
            "ALTER TABLE instruments ADD COLUMN float_shares INTEGER DEFAULT 0",
            "ALTER TABLE instruments ADD COLUMN market_name TEXT NOT NULL DEFAULT ''",
        ]:
            try:
                cur.execute(ddl)
            except sqlite3.OperationalError:
                pass  # column already exists

        # downloads
        cur.execute("""
            CREATE TABLE IF NOT EXISTS downloads (
                symbol          TEXT,
                start_date      TEXT,
                end_date        TEXT,
                row_count       INTEGER,
                downloaded_at   TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, end_date)
            )
        """)
        # watermarks
        cur.execute("""
            CREATE TABLE IF NOT EXISTS watermarks (
                source          TEXT NOT NULL,
                dataset         TEXT NOT NULL,
                symbol          TEXT NOT NULL,
                last_event_date TEXT NOT NULL,
                cursor_payload  TEXT NOT NULL DEFAULT '{}',
                updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (source, dataset, symbol)
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_downloads_symbol_end "
            "ON downloads(symbol, end_date)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_watermarks_lookup "
            "ON watermarks(source, dataset, symbol)"
        )
        self._conn.commit()

    # ── Instruments ────────────────────────────────────────────────────────

    def upsert_instrument(
        self,
        symbol: str,
        name: str,
        market: int | None = None,
        industry_idx: int = 0,
    ) -> None:
        """Insert or update an instrument record.

        Args:
            symbol:       Full symbol with suffix, e.g. "600000.SH"
            name:         Stock name
            market:       Market integer (0=SH, 1=SZ, 2=BJ). Inferred if None.
            industry_idx: SWIndustry enum integer (0 = Unknown)
        """
        code = symbol.split(".")[0]
        if market is None:
            market = _infer_market(code)
        mname = _market_name(market)
        self._conn.execute(
            """
            INSERT INTO instruments (symbol, name, market, board, industry,
                                     list_date, delist_date, status,
                                     total_shares, float_shares, market_name)
            VALUES (?, ?, ?, 0, ?, NULL, NULL, 1, 0, 0, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                name        = excluded.name,
                market      = excluded.market,
                industry    = excluded.industry,
                market_name = excluded.market_name
            """,
            (symbol, name, market, industry_idx, mname),
        )
        self._conn.commit()

    def get_all_symbols(self) -> list[str]:
        """Return all symbols currently in the instruments table."""
        cur = self._conn.execute("SELECT symbol FROM instruments ORDER BY symbol")
        return [row[0] for row in cur.fetchall()]

    # ── Watermarks ─────────────────────────────────────────────────────────

    def get_watermark(
        self, source: str, dataset: str, symbol: str
    ) -> Optional[date]:
        """Return the last recorded watermark date, or None if not set."""
        cur = self._conn.execute(
            "SELECT last_event_date FROM watermarks "
            "WHERE source=? AND dataset=? AND symbol=?",
            (source, dataset, symbol),
        )
        row = cur.fetchone()
        if row is None:
            return None
        try:
            return date.fromisoformat(row[0][:10])
        except (ValueError, TypeError):
            return None

    def set_watermark(
        self,
        source: str,
        dataset: str,
        symbol: str,
        last_date: date,
    ) -> None:
        """Upsert a watermark for the given (source, dataset, symbol) key."""
        self._conn.execute(
            """
            INSERT INTO watermarks (source, dataset, symbol, last_event_date, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(source, dataset, symbol) DO UPDATE SET
                last_event_date = excluded.last_event_date,
                updated_at      = CURRENT_TIMESTAMP
            """,
            (source, dataset, symbol, last_date.isoformat()),
        )
        self._conn.commit()

    # ── Downloads ──────────────────────────────────────────────────────────

    def record_download(
        self, symbol: str, start: date, end: date, row_count: int
    ) -> None:
        """Record a completed download event."""
        self._conn.execute(
            """
            INSERT INTO downloads (symbol, start_date, end_date, row_count)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(symbol, end_date) DO UPDATE SET
                start_date = excluded.start_date,
                row_count  = excluded.row_count,
                downloaded_at = CURRENT_TIMESTAMP
            """,
            (symbol, start.isoformat(), end.isoformat(), row_count),
        )
        self._conn.commit()

    def last_download_date(self, symbol: str) -> Optional[date]:
        """Return the most recent end_date recorded for a symbol."""
        cur = self._conn.execute(
            "SELECT MAX(end_date) FROM downloads WHERE symbol=?", (symbol,)
        )
        row = cur.fetchone()
        if row is None or row[0] is None:
            return None
        try:
            return date.fromisoformat(row[0][:10])
        except (ValueError, TypeError):
            return None
