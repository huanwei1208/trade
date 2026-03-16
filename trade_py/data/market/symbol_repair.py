from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from trade_py.db.trade_db import TradeDB, _BOARD_BSE, _MARKET_BJ, _market_name
from trade_py.utils.a_share_symbols import ensure_a_share_symbol

logger = logging.getLogger(__name__)

_SIGNALS_COLS = [
    "date", "symbol", "window_score", "net_sentiment", "event_kg_score",
    "event_affected", "event_type", "event_typical_days", "model_score",
    "model_risk", "model_version", "updated_at",
]
_FACTORS_COLS = [
    "date", "symbol", "factor_name", "factor_type", "value", "updated_at",
]


def _rename_map(db: TradeDB) -> dict[str, str]:
    rows = db._conn.execute(
        "SELECT symbol FROM instruments WHERE symbol GLOB '920*.SH' ORDER BY symbol"
    ).fetchall()
    mapping: dict[str, str] = {}
    for row in rows:
        old = str(row["symbol"])
        new = ensure_a_share_symbol(old)
        if new != old:
            mapping[old] = new
    return mapping


def _merge_symbol_table(db: TradeDB, table: str, old: str, new: str) -> int:
    count_row = db._conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE symbol = ?",
        (old,),
    ).fetchone()
    count = int(count_row[0]) if count_row else 0
    if count <= 0:
        return 0
    exists = db._conn.execute(
        f"SELECT 1 FROM {table} WHERE symbol = ?",
        (new,),
    ).fetchone()
    if exists:
        db._conn.execute(f"DELETE FROM {table} WHERE symbol = ?", (old,))
    else:
        db._conn.execute(f"UPDATE {table} SET symbol = ? WHERE symbol = ?", (new, old))
    return count


def _move_rows_by_symbol(db: TradeDB, table: str, cols: list[str], old: str, new: str) -> int:
    count_row = db._conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE symbol = ?",
        (old,),
    ).fetchone()
    count = int(count_row[0]) if count_row else 0
    if count <= 0:
        return 0
    select_cols = [("?" if col == "symbol" else col) for col in cols]
    db._conn.execute(
        f"""
        INSERT OR REPLACE INTO {table} ({", ".join(cols)})
        SELECT {", ".join(select_cols)} FROM {table} WHERE symbol = ?
        """,
        (new, old),
    )
    db._conn.execute(f"DELETE FROM {table} WHERE symbol = ?", (old,))
    return count


def _merge_sync_state(db: TradeDB, old: str, new: str) -> int:
    rows = db._conn.execute(
        """
        SELECT source, dataset, symbol, last_date, row_count, cursor
        FROM sync_state
        WHERE symbol = ?
        """,
        (old,),
    ).fetchall()
    updated = 0
    for row in rows:
        existing = db._conn.execute(
            """
            SELECT last_date, row_count, cursor
            FROM sync_state
            WHERE source = ? AND dataset = ? AND symbol = ?
            """,
            (row["source"], row["dataset"], new),
        ).fetchone()
        last_dates = [v for v in [row["last_date"], existing["last_date"] if existing else None] if v]
        row_counts = [v for v in [row["row_count"], existing["row_count"] if existing else None] if v is not None]
        cursor = row["cursor"] if row["cursor"] not in (None, "", "{}") else (
            existing["cursor"] if existing else "{}"
        )
        db._conn.execute(
            """
            INSERT INTO sync_state (source, dataset, symbol, last_date, row_count, cursor, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(source, dataset, symbol) DO UPDATE SET
                last_date = COALESCE(excluded.last_date, sync_state.last_date),
                row_count = COALESCE(excluded.row_count, sync_state.row_count),
                cursor = excluded.cursor,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                row["source"],
                row["dataset"],
                new,
                max(last_dates) if last_dates else None,
                max(row_counts) if row_counts else None,
                cursor,
            ),
        )
        db._conn.execute(
            "DELETE FROM sync_state WHERE source = ? AND dataset = ? AND symbol = ?",
            (row["source"], row["dataset"], old),
        )
        updated += 1
    return updated


def _repair_gap_tables(db: TradeDB, old: str, new: str) -> int:
    updated = 0

    rows = db._conn.execute(
        "SELECT dataset FROM data_gaps WHERE item_key = ?",
        (old,),
    ).fetchall()
    for row in rows:
        exists = db._conn.execute(
            "SELECT 1 FROM data_gaps WHERE dataset = ? AND item_key = ?",
            (row["dataset"], new),
        ).fetchone()
        if exists:
            db._conn.execute(
                "DELETE FROM data_gaps WHERE dataset = ? AND item_key = ?",
                (row["dataset"], old),
            )
        else:
            db._conn.execute(
                "UPDATE data_gaps SET item_key = ?, updated_at = CURRENT_TIMESTAMP WHERE dataset = ? AND item_key = ?",
                (new, row["dataset"], old),
            )
        updated += 1

    cur = db._conn.execute(
        "UPDATE data_repair_runs SET item_key = ? WHERE item_key = ?",
        (new, old),
    )
    updated += max(0, cur.rowcount)
    return updated


def _repair_instruments(db: TradeDB, old: str, new: str) -> int:
    row = db._conn.execute(
        "SELECT 1 FROM instruments WHERE symbol = ?",
        (old,),
    ).fetchone()
    if row is None:
        return 0
    exists = db._conn.execute(
        "SELECT 1 FROM instruments WHERE symbol = ?",
        (new,),
    ).fetchone()
    if exists:
        db._conn.execute("DELETE FROM instruments WHERE symbol = ?", (old,))
    else:
        db._conn.execute(
            """
            UPDATE instruments
            SET symbol = ?, market = ?, board = ?, market_name = ?
            WHERE symbol = ?
            """,
            (new, _MARKET_BJ, _BOARD_BSE, _market_name(_MARKET_BJ), old),
        )
    return 1


def _repair_kline_files(data_root: str | Path, mapping: dict[str, str]) -> dict[str, int]:
    root = Path(data_root) / "market" / "kline"
    if not root.exists():
        return {"files_rewritten": 0, "symbols_with_files": 0}

    files_rewritten = 0
    symbols_with_files = 0
    for old, new in mapping.items():
        old_name = f"{old.replace('.', '_')}.parquet"
        new_name = f"{new.replace('.', '_')}.parquet"
        matched = list(root.rglob(old_name))
        if not matched:
            continue
        symbols_with_files += 1
        for old_path in matched:
            target = old_path.with_name(new_name)
            source_df = pd.read_parquet(old_path)
            if "symbol" in source_df.columns:
                source_df["symbol"] = new
            source_df = source_df.sort_values("date").drop_duplicates(subset=["date"], keep="last")

            if target.exists() and target != old_path:
                target_df = pd.read_parquet(target)
                if "symbol" in target_df.columns:
                    target_df["symbol"] = new
                source_df = (
                    pd.concat([target_df, source_df], ignore_index=True)
                    .sort_values("date")
                    .drop_duplicates(subset=["date"], keep="last")
                    .reset_index(drop=True)
                )
            else:
                source_df = source_df.reset_index(drop=True)

            source_df.to_parquet(target, index=False)
            if target != old_path:
                old_path.unlink()
            files_rewritten += 1
    return {"files_rewritten": files_rewritten, "symbols_with_files": symbols_with_files}


def repair_bse_920_suffixes(data_root: str | Path = "data") -> dict[str, Any]:
    db = TradeDB(data_root)
    mapping = _rename_map(db)
    if not mapping:
        return {
            "renamed_symbols": 0,
            "db_rows_updated": 0,
            "sync_state_rows_updated": 0,
            "files_rewritten": 0,
            "symbols_with_files": 0,
            "mapping": {},
        }

    db_rows_updated = 0
    sync_state_rows_updated = 0

    for old, new in mapping.items():
        db_rows_updated += _repair_instruments(db, old, new)
        db_rows_updated += _merge_symbol_table(db, "watchlist", old, new)
        db_rows_updated += _merge_symbol_table(db, "sector_members", old, new)
        db_rows_updated += _move_rows_by_symbol(db, "signals", _SIGNALS_COLS, old, new)
        db_rows_updated += _move_rows_by_symbol(db, "factors", _FACTORS_COLS, old, new)
        cur = db._conn.execute(
            "UPDATE event_propagations SET symbol = ? WHERE symbol = ?",
            (new, old),
        )
        db_rows_updated += max(0, cur.rowcount)
        sync_state_rows_updated += _merge_sync_state(db, old, new)
        db_rows_updated += _repair_gap_tables(db, old, new)

    file_stats = _repair_kline_files(data_root, mapping)
    db._conn.commit()

    logger.info(
        "repair_bse_920_suffixes: renamed=%d db_rows=%d sync_rows=%d files=%d",
        len(mapping),
        db_rows_updated,
        sync_state_rows_updated,
        file_stats["files_rewritten"],
    )
    return {
        "renamed_symbols": len(mapping),
        "db_rows_updated": db_rows_updated,
        "sync_state_rows_updated": sync_state_rows_updated,
        "files_rewritten": file_stats["files_rewritten"],
        "symbols_with_files": file_stats["symbols_with_files"],
        "mapping": mapping,
    }
