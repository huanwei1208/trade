from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_SETTINGS: list[tuple[str, str, str, str, str]] = [
    # (key, value, value_type, category, label)
    # 风险参数
    ("risk.target_annual_vol",   "0.11",    "float",  "risk",      "目标年化波动率"),
    ("risk.max_single_weight",   "0.10",    "float",  "risk",      "单股最大仓位"),
    ("risk.max_industry_weight", "0.35",    "float",  "risk",      "行业最大仓位"),
    ("risk.base_cash_pct",       "0.10",    "float",  "risk",      "基础现金比例"),
    # 交易成本
    ("cost.stamp_tax_rate",      "0.0005",  "float",  "risk",      "印花税率"),
    ("cost.commission_rate",     "0.00025", "float",  "risk",      "佣金率"),
    ("cost.commission_min_yuan", "5.0",     "float",  "risk",      "最低佣金（元）"),
    # 回测参数
    ("backtest.initial_capital", "1000000", "float",  "backtest",  "初始资金（元）"),
    ("backtest.max_positions",   "25",      "int",    "backtest",  "最大持仓数"),
    ("backtest.min_positions",   "15",      "int",    "backtest",  "最小持仓数"),
    # 信号参数
    ("signal.window_act_threshold",   "80", "int",    "signal",    "出手窗口质量分 cutoff"),
    ("signal.window_watch_threshold", "60", "int",    "signal",    "观察窗口质量分 cutoff"),
    # 调度参数
    ("scheduler.brief_time",     "09:10",   "string", "scheduler", "晨报生成时间"),
    ("scheduler.scan_interval",  "5",       "int",    "scheduler", "盘中扫描间隔（分钟）"),
]


class SettingsDB:
    """Read/write user settings stored in the shared SQLite metadata database.

    Settings are key-value pairs with a type hint (string | int | float | bool | json).
    All user-tunable parameters (risk limits, backtest params, signal thresholds)
    live here so they can be edited from the Web UI without touching YAML files.
    """

    def __init__(self, data_root: str = "data") -> None:
        db_path = Path(data_root) / ".metadata" / "trade.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                value_type  TEXT NOT NULL DEFAULT 'string',
                category    TEXT NOT NULL DEFAULT 'general',
                label       TEXT,
                description TEXT,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS watchlist (
                symbol    TEXT PRIMARY KEY,
                added_at  DATE NOT NULL DEFAULT (date('now')),
                note      TEXT,
                active    INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS signal_cache (
                date               DATE NOT NULL,
                symbol             TEXT NOT NULL,
                window_score       INTEGER,
                smart_money_signal INTEGER,
                large_order_trend  TEXT,
                net_sentiment      REAL,
                updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (date, symbol)
            );

            CREATE TABLE IF NOT EXISTS macro_events (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                event_date       DATE NOT NULL,
                event_type       TEXT NOT NULL,
                source           TEXT,
                intensity        REAL,
                affected_assets  TEXT,
                notes            TEXT
            );
        """)
        self._conn.commit()
        self._migrate()
        self._seed_defaults()

    def _migrate(self) -> None:
        """Add columns introduced after initial schema creation."""
        cur = self._conn.cursor()
        existing = {
            row[1]
            for row in cur.execute("PRAGMA table_info(signal_cache)").fetchall()
        }
        if "net_sentiment" not in existing:
            cur.execute("ALTER TABLE signal_cache ADD COLUMN net_sentiment REAL")
            self._conn.commit()

    def _seed_defaults(self) -> None:
        cur = self._conn.cursor()
        for key, value, vtype, category, label in _DEFAULT_SETTINGS:
            cur.execute(
                "INSERT OR IGNORE INTO settings (key, value, value_type, category, label) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, value, vtype, category, label),
            )
        self._conn.commit()

    # ── Settings CRUD ─────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute(
            "SELECT value, value_type FROM settings WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        return self._cast(row["value"], row["value_type"])

    def set(self, key: str, value: Any) -> None:
        self._conn.execute(
            "UPDATE settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?",
            (str(value), key),
        )
        self._conn.commit()

    def get_category(self, category: str) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT key, value, value_type, label FROM settings WHERE category = ? ORDER BY key",
            (category,),
        ).fetchall()
        return {
            row["key"]: {
                "value": self._cast(row["value"], row["value_type"]),
                "label": row["label"],
                "value_type": row["value_type"],
            }
            for row in rows
        }

    def all_categories(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT category FROM settings ORDER BY category"
        ).fetchall()
        return [r["category"] for r in rows]

    # ── Watchlist ─────────────────────────────────────────────────────────────

    def watchlist_add(self, symbol: str, note: str = "") -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO watchlist (symbol, added_at, note, active) "
            "VALUES (?, date('now'), ?, 1)",
            (symbol, note),
        )
        self._conn.commit()

    def watchlist_remove(self, symbol: str) -> None:
        self._conn.execute(
            "UPDATE watchlist SET active = 0 WHERE symbol = ?", (symbol,)
        )
        self._conn.commit()

    def watchlist_get(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT symbol FROM watchlist WHERE active = 1 ORDER BY added_at"
        ).fetchall()
        return [r["symbol"] for r in rows]

    # ── Signal cache ──────────────────────────────────────────────────────────

    def signal_cache_upsert(self, date: str, symbol: str, **fields: Any) -> None:
        cols = ["date", "symbol"] + list(fields.keys())
        placeholders = ", ".join(["?"] * len(cols))
        updates = ", ".join(f"{k} = excluded.{k}" for k in fields)
        values = [date, symbol] + [str(v) for v in fields.values()]
        self._conn.execute(
            f"INSERT INTO signal_cache ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(date, symbol) DO UPDATE SET {updates}, "
            f"updated_at = CURRENT_TIMESTAMP",
            values,
        )
        self._conn.commit()

    def signal_cache_get(self, date: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM signal_cache WHERE date = ? ORDER BY window_score DESC",
            (date,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _cast(value: str, vtype: str) -> Any:
        if vtype == "int":
            return int(value)
        if vtype == "float":
            return float(value)
        if vtype == "bool":
            return value.lower() in ("1", "true", "yes")
        return value
