"""Data inspection utilities extracted from notebooks.

Provides functions to query data layer status, replaces inline notebook cells.

Usage (notebook):
    from trade_py.utils.data_inspector import get_data_status, display_status_table
    status = get_data_status("data")
    display_status_table(status)
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter, deque
from importlib.util import find_spec
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from trade_py.data.paths import (
    CROSS_ASSET_DIR,
    FUND_FLOW_DIR,
    FUNDAMENTAL_DIR,
    INDEX_DIR,
    KLINE_DIR,
    KLINE_MANIFEST,
    MACRO_DIR,
    NORTHBOUND_DIR,
)

logger = logging.getLogger(__name__)


_REQUIRED_PARQUET_COLUMNS: dict[str, tuple[str, ...]] = {
    "kline": (
        "symbol",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "turnover_rate",
        "prev_close",
        "vwap",
    ),
    "fund_flow": ("symbol", "date", "large_order_net_ratio"),
    "fundamental": ("symbol", "report_date", "roe"),
    "cross_asset.gold": ("date", "close"),
    "cross_asset.fx_cnh": ("date", "close"),
    "cross_asset.btc": ("date", "close"),
    "index": ("date", "close"),
    "northbound": ("date", "total_net", "net_5d"),
    "macro.gdp": ("date", "q_gdp"),
    "macro.cpi": ("date", "nt_yoy"),
    "macro.ppi": ("date", "ppi_yoy"),
    "macro.pmi": ("date", "mfg_pmi"),
    "sentiment.silver": ("date", "symbol", "sentiment_score", "sentiment_label"),
    "sentiment.gold": ("date", "symbol", "net_sentiment"),
}


_PARQUET_COLUMN_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "macro.gdp": {"q_gdp": ("gdp",)},
    "macro.pmi": {"mfg_pmi": ("PMI010000",)},
}


_DATA_SOURCE_JOB_POLICIES: dict[str, float] = {
    "kline_update": 6.0,
    "fundamental": 4.0,
    "fund_flow_update": 1.0,
    "northbound": 1.0,
    "market_index": 1.0,
    "market_index_sector": 2.0,
    "sector_refresh": 2.0,
    "macro": 2.0,
    "cross_asset_fetch": 1.0,
    "crypto_btc_fetch": 1.0,
    "crypto_research_validation": 1.0,
    "sentiment_fetch": 2.0,
    "sentiment_silver": 2.0,
    "sentiment_gold": 2.0,
    "sentiment_pipeline": 4.0,
    "event_pipeline": 2.0,
}


_VALUE_QUALITY_RECOVERY: dict[str, dict[str, Any]] = {
    "kline": {
        "command": ["trade", "data", "kline", "sync", "--mode", "full"],
        "mode": "refetch",
        "detail": "Re-fetch affected K-line symbols from the configured provider and re-run data status.",
    },
    "fund_flow": {
        "command": ["trade", "data", "fund-flow", "sync"],
        "mode": "refetch",
        "detail": "Re-fetch affected fund-flow symbols and verify large_order_net_ratio stays within [-1, 1].",
    },
    "fundamental": {
        "command": ["trade", "data", "fundamental", "sync"],
        "mode": "refetch",
        "detail": "Re-fetch affected fundamental symbols and inspect extreme ROE rows before trusting factor outputs.",
    },
    "index": {
        "command": ["trade", "data", "market-index", "sync"],
        "mode": "refetch",
        "detail": "Re-fetch market or sector index series whose OHLC relationships are inconsistent.",
    },
    "northbound": {
        "command": ["trade", "data", "northbound", "sync"],
        "mode": "refetch",
        "detail": "Re-fetch northbound flow data and verify rolling net_5d values are populated.",
    },
    "cross_asset": {
        "command": ["trade", "data", "cross-asset", "all"],
        "mode": "refetch",
        "detail": "Re-fetch cross-asset files and verify close/optional OHLC relationships.",
    },
    "macro": {
        "command": ["trade", "data", "macro", "sync"],
        "mode": "refetch",
        "detail": "Re-fetch macro datasets with missing required value columns and audit historical nulls.",
    },
    "sentiment": {
        "command": ["trade", "data", "sentiment"],
        "mode": "recompute",
        "detail": "Recompute Silver/Gold sentiment layers and verify score/confidence ranges.",
    },
}


_PYTHON_PROVIDER_MODULES: dict[str, tuple[str, ...]] = {
    "akshare": ("akshare",),
    "baostock": ("baostock",),
    "tencent": ("requests",),
    "okx": ("requests",),
    "coingecko": ("requests",),
    "tushare": ("tushare",),
}


_PROVIDER_RECOVERY: dict[str, dict[str, Any]] = {
    "tushare": {
        "command": ["trade", "account", "setting-set", "tushare_token", "YOUR_TOKEN"],
        "mode": "configure",
        "detail": "Configure Tushare token before running A-share market, fundamental, macro, and flow refresh jobs.",
    },
    "coingecko": {
        "command": ["export", "COINGECKO_API_KEY=YOUR_KEY"],
        "mode": "configure",
        "detail": "Set COINGECKO_API_KEY or COINGECKO_DEMO_API_KEY before BTC shadow reconciliation.",
    },
}


_TUSHARE_AUDIT_LOG_NAME = "tushare_requests.jsonl"
_TUSHARE_AUDIT_FAIL_STATUSES = {"auth", "permission", "invalid_request"}
_TUSHARE_AUDIT_WARN_STATUSES = {"rate_limit", "transient", "unknown"}
_REQUIRED_CROSS_SOURCE_DATASETS = ("kline", "cross_asset.btc")
_KLINE_RECONCILIATION_SCHEMA_VERSION = "kline-reconciliation-v1"
_KLINE_RECONCILIATION_COMMAND = [
    "trade",
    "data",
    "kline",
    "reconcile",
    "--symbols",
    "<symbols>",
    "--start",
    "<start>",
    "--end",
    "<end>",
    "--shadow-provider",
    "tencent",
    "--json",
]
_MACRO_VALUE_START_DATES = {
    "macro.ppi": "1996-10-01",
}
_OHLC_RELATIONSHIP_TOLERANCE = {
    "index": 0.010001,
}


# ── Status helpers ─────────────────────────────────────────────────────────────


def _resolve_kline_dir(data_root: str | Path = "data") -> Path:
    root = Path(data_root)
    candidates = (KLINE_DIR(root), root / "kline")
    for candidate in candidates:
        if candidate.exists() and any(candidate.glob("*.parquet")):
            return candidate
    for candidate in candidates:
        if candidate.exists() and any(candidate.rglob("*.parquet")):
            return candidate
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return KLINE_DIR(root)


def _load_kline_manifest(data_root: str | Path = "data") -> dict[str, Any]:
    manifest_path = KLINE_MANIFEST(data_root)
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        logger.debug("kline manifest read error: %s", exc)
        return {}


def _resolve_kline_glob(data_root: str | Path = "data") -> str:
    kline_dir = _resolve_kline_dir(data_root)
    if any(kline_dir.glob("*.parquet")):
        return str(kline_dir / "*.parquet")
    return str(kline_dir / "**" / "*.parquet")

def status_emoji(n: int, days_threshold: int = 3) -> str:
    """Return status emoji based on row count and recency check."""
    if n == 0:
        return "❌"
    if n < days_threshold:
        return "⚠️"
    return "✅"


def parquet_stats(files: list[str | Path]) -> dict[str, Any]:
    """Return row count, date range, and file count for a list of parquet files."""
    try:
        import duckdb
        if not files:
            return {"rows": 0, "files": 0, "min_date": None, "max_date": None}
        glob_pattern = str(files[0]) if len(files) == 1 else None
        if glob_pattern is None:
            # Multiple files — use first as proxy; caller should pass glob pattern instead
            glob_pattern = str(files[0])
        con = duckdb.connect()
        row = con.execute(f"""
            SELECT COUNT(*) AS rows,
                   MIN(date) AS min_date,
                   MAX(date) AS max_date
            FROM read_parquet({[str(f) for f in files]!r})
        """).fetchone()
        con.close()
        rows, min_date, max_date = row if row else (0, None, None)
        return {"rows": int(rows or 0), "files": len(files), "min_date": min_date, "max_date": max_date}
    except Exception as exc:
        logger.debug("parquet_stats error: %s", exc)
        return {"rows": 0, "files": len(files), "min_date": None, "max_date": None, "error": str(exc)}


def kline_stats(data_root: str | Path = "data") -> dict[str, Any]:
    """Return kline data statistics, preferring the manifest when present."""
    manifest = _load_kline_manifest(data_root)
    entries = manifest.get("entries") if isinstance(manifest, dict) else None
    if isinstance(entries, dict) and entries:
        mins = [str(v.get("date_min")) for v in entries.values() if v.get("date_min")]
        maxs = [str(v.get("date_max")) for v in entries.values() if v.get("date_max")]
        return {
            "symbols": len(entries),
            "rows": sum(int((v or {}).get("rows") or 0) for v in entries.values()),
            "bytes": sum(int((v or {}).get("bytes") or 0) for v in entries.values()),
            "min_date": min(mins) if mins else None,
            "max_date": max(maxs) if maxs else None,
            "layout": manifest.get("layout"),
            "manifest": True,
        }

    kline_dir = _resolve_kline_dir(data_root)
    if not kline_dir.exists():
        return {"symbols": 0, "rows": 0, "min_date": None, "max_date": None}
    try:
        import duckdb
        kline_glob = _resolve_kline_glob(data_root)
        con = duckdb.connect()
        row = con.execute(f"""
            SELECT COUNT(DISTINCT symbol) AS symbols,
                   COUNT(*) AS rows,
                   MIN(date) AS min_date,
                   MAX(date) AS max_date
            FROM read_parquet('{kline_glob}', union_by_name=true)
        """).fetchone()
        con.close()
        symbols, rows, min_date, max_date = row if row else (0, 0, None, None)
        return {
            "symbols": int(symbols or 0),
            "rows": int(rows or 0),
            "min_date": str(min_date) if min_date else None,
            "max_date": str(max_date) if max_date else None,
            "manifest": False,
        }
    except Exception as exc:
        logger.debug("kline_stats error: %s", exc)
        return {"symbols": 0, "rows": 0, "error": str(exc)}


def kline_coverage_stats(data_root: str | Path = "data", sample_limit: int = 10) -> dict[str, Any]:
    try:
        from trade_py.db.instruments_db import InstrumentsDB

        db = InstrumentsDB(data_root)
        db_symbols = set(db.get_all_symbols())
        manifest = _load_kline_manifest(data_root)
        entries = manifest.get("entries") if isinstance(manifest, dict) else None
        if isinstance(entries, dict) and entries:
            file_symbols = {key.replace("_", ".") for key in entries.keys()}
            source = "manifest"
        else:
            kline_dir = _resolve_kline_dir(data_root)
            file_symbols = {p.stem.replace("_", ".") for p in kline_dir.glob("*.parquet")}
            if not file_symbols:
                file_symbols = {p.stem.replace("_", ".") for p in kline_dir.glob("**/*.parquet")}
            source = "filesystem"
        missing = sorted(db_symbols - file_symbols)
        suspicious = sorted(s for s in db_symbols if s.startswith("920") and s.endswith(".SH"))
        present = len(db_symbols) - len(missing)
        coverage_pct = round((present / len(db_symbols)) * 100, 1) if db_symbols else 0.0
        return {
            "db_symbols": len(db_symbols),
            "file_symbols": len(file_symbols),
            "missing_symbols": len(missing),
            "coverage_pct": coverage_pct,
            "missing_sample": missing[:sample_limit],
            "suspicious_suffix_symbols": len(suspicious),
            "suspicious_sample": suspicious[:sample_limit],
            "source": source,
        }
    except Exception as exc:
        logger.debug("kline_coverage_stats error: %s", exc)
        return {"db_symbols": 0, "error": str(exc)}


def kline_freshness_stats(data_root: str | Path = "data", sample_limit: int = 10) -> dict[str, Any]:
    try:
        from trade_py.data.market.kline import KlineSyncService
        from trade_py.db.trade_db import TradeDB

        rows = KlineSyncService(data_root).status(limit=1000000)
        stale_values = [int(r["stale_days"]) for r in rows if r.get("stale_days") not in {None, "-"}]
        trading_reference = None
        trading_lag_values: list[int] = []
        try:
            db = TradeDB(data_root)
            trading_reference = db.get_latest_open_trade_date()
            if trading_reference:
                with db._conn_lock:
                    lag_rows = db._conn.execute(
                        """
                        SELECT s.symbol, COUNT(c.trade_date) AS missing_trade_days
                        FROM sync_state s
                        LEFT JOIN trading_calendar c
                          ON c.exchange = 'SSE'
                         AND c.is_open = 1
                         AND c.trade_date > COALESCE(s.last_date, '')
                         AND c.trade_date <= ?
                        WHERE s.source = 'tushare_kline'
                          AND s.dataset = 'daily'
                        GROUP BY s.symbol
                        """,
                        (trading_reference,),
                    ).fetchall()
                by_symbol = {
                    str(row["symbol"]): int(row["missing_trade_days"] or 0)
                    for row in lag_rows
                }
                for row in rows:
                    row["trading_day_stale_days"] = str(by_symbol.get(str(row.get("symbol") or ""), 0))
                trading_lag_values = list(by_symbol.values())
        except Exception as exc:
            logger.debug("kline trading-day freshness error: %s", exc)
        return {
            "stale_ge_1": sum(1 for v in stale_values if v >= 1),
            "stale_ge_5": sum(1 for v in stale_values if v >= 5),
            "stale_ge_30": sum(1 for v in stale_values if v >= 30),
            "max_stale_days": max(stale_values) if stale_values else 0,
            "expected_trade_date": trading_reference,
            "trading_day_stale_ge_1": sum(1 for v in trading_lag_values if v >= 1),
            "trading_day_stale_ge_5": sum(1 for v in trading_lag_values if v >= 5),
            "trading_day_stale_ge_30": sum(1 for v in trading_lag_values if v >= 30),
            "max_trading_day_stale_days": max(trading_lag_values) if trading_lag_values else 0,
            "stale_sample": rows[:sample_limit],
        }
    except Exception as exc:
        logger.debug("kline_freshness_stats error: %s", exc)
        return {"stale_ge_1": 0, "error": str(exc)}


def _instrument_symbols(data_root: str | Path) -> set[str]:
    try:
        from trade_py.db.instruments_db import InstrumentsDB

        return set(InstrumentsDB(data_root).get_all_symbols())
    except Exception as exc:
        logger.debug("instrument symbol lookup error: %s", exc)
        return set()


def _expected_data_date(data_root: str | Path, *, trading_day: bool = True) -> str:
    if trading_day:
        try:
            from trade_py.db.trade_db import TradeDB

            value = TradeDB(data_root).get_latest_open_trade_date()
            if value:
                return str(value)
        except Exception as exc:
            logger.debug("expected trading date lookup error: %s", exc)
    return date.today().isoformat()


def _lag_days(watermark: Any, expected: str | None) -> int | None:
    if not watermark or not expected:
        return None
    try:
        return max((date.fromisoformat(str(expected)[:10]) - date.fromisoformat(str(watermark)[:10])).days, 0)
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        return None


def _age_hours(value: Any, now: datetime | None = None) -> float | None:
    started = _parse_datetime(value)
    if started is None:
        return None
    return max(((now or datetime.now()) - started).total_seconds() / 3600.0, 0.0)


def _resolve_kline_files(data_root: str | Path = "data") -> list[Path]:
    kline_dir = _resolve_kline_dir(data_root)
    if not kline_dir.exists():
        return []
    files = sorted(kline_dir.glob("*.parquet"))
    if files:
        return files
    return sorted(kline_dir.glob("**/*.parquet"))


def _parquet_columns(path: Path) -> tuple[set[str], str | None]:
    try:
        import pyarrow.parquet as pq

        return {str(name) for name in pq.read_schema(path).names}, None
    except Exception as arrow_exc:
        try:
            import duckdb

            con = duckdb.connect()
            try:
                rows = con.execute(
                    f"DESCRIBE SELECT * FROM read_parquet({[str(path)]!r}, union_by_name=true)"
                ).fetchall()
            finally:
                con.close()
            return {str(row[0]) for row in rows if row and row[0]}, None
        except Exception as duck_exc:
            return set(), f"{arrow_exc}; duckdb fallback: {duck_exc}"


def _single_parquet_date_stats(path: Path, date_column: str = "date") -> dict[str, Any]:
    try:
        import duckdb

        con = duckdb.connect()
        try:
            row = con.execute(
                f"""
                SELECT COUNT(*) AS rows,
                       MIN({date_column}) AS min_date,
                       MAX({date_column}) AS max_date
                FROM read_parquet('{path}', union_by_name=true)
                """
            ).fetchone()
        finally:
            con.close()
        rows, min_date, max_date = row if row else (0, None, None)
        return {
            "rows": int(rows or 0),
            "min_date": str(min_date)[:10] if min_date else None,
            "max_date": str(max_date)[:10] if max_date else None,
        }
    except Exception as exc:
        return {"rows": 0, "min_date": None, "max_date": None, "error": str(exc)}


def _schema_contract(
    dataset: str,
    files: list[Path],
    required_columns: tuple[str, ...],
    *,
    sample_limit: int,
) -> dict[str, Any]:
    aliases = _PARQUET_COLUMN_ALIASES.get(dataset, {})
    missing_sample: list[dict[str, Any]] = []
    error_sample: list[dict[str, Any]] = []
    observed_columns: set[str] = set()
    missing_columns: set[str] = set()
    checked_files = 0

    for path in files:
        columns, error = _parquet_columns(path)
        if error:
            error_sample.append({"path": str(path), "error": error})
            continue
        checked_files += 1
        observed_columns.update(columns)
        missing = sorted(
            column
            for column in required_columns
            if column not in columns and not any(alias in columns for alias in aliases.get(column, ()))
        )
        if missing:
            missing_columns.update(missing)
            missing_sample.append({"path": str(path), "missing_columns": missing})

    return {
        "dataset": dataset,
        "status": "fail" if missing_sample or error_sample else "pass",
        "files": len(files),
        "checked_files": checked_files,
        "required_columns": list(required_columns),
        "column_aliases": {key: list(value) for key, value in aliases.items()},
        "observed_columns": sorted(observed_columns),
        "missing_columns": sorted(missing_columns),
        "missing_files": len(missing_sample),
        "missing_sample": missing_sample[:sample_limit],
        "error_files": len(error_sample),
        "error_sample": error_sample[:sample_limit],
    }


def schema_contract_stats(data_root: str | Path = "data", sample_limit: int = 10) -> dict[str, Any]:
    root = Path(data_root)
    specs: list[tuple[str, list[Path], tuple[str, ...]]] = [
        ("kline", _resolve_kline_files(root), _REQUIRED_PARQUET_COLUMNS["kline"]),
        ("fund_flow", sorted(FUND_FLOW_DIR(root).glob("*.parquet")), _REQUIRED_PARQUET_COLUMNS["fund_flow"]),
        ("fundamental", sorted(FUNDAMENTAL_DIR(root).glob("*.parquet")), _REQUIRED_PARQUET_COLUMNS["fundamental"]),
        ("index", sorted(INDEX_DIR(root).glob("*.parquet")), _REQUIRED_PARQUET_COLUMNS["index"]),
        (
            "northbound",
            [NORTHBOUND_DIR(root) / "daily.parquet"] if (NORTHBOUND_DIR(root) / "daily.parquet").exists() else [],
            _REQUIRED_PARQUET_COLUMNS["northbound"],
        ),
    ]
    specs.extend(
        (
            f"cross_asset.{name}",
            [path] if path.exists() else [],
            _REQUIRED_PARQUET_COLUMNS[f"cross_asset.{name}"],
        )
        for name in ("gold", "fx_cnh", "btc")
        for path, _layout in [_cross_asset_path(root, name)]
    )
    specs.extend(
        (
            f"macro.{name}",
            [MACRO_DIR(root) / f"{name}.parquet"] if (MACRO_DIR(root) / f"{name}.parquet").exists() else [],
            _REQUIRED_PARQUET_COLUMNS[f"macro.{name}"],
        )
        for name in ("gdp", "cpi", "ppi", "pmi")
    )
    specs.extend(
        (
            f"sentiment.{layer}",
            sorted((root / "sentiment" / layer).glob("**/*.parquet")),
            _REQUIRED_PARQUET_COLUMNS[f"sentiment.{layer}"],
        )
        for layer in ("silver", "gold")
    )

    datasets = {
        dataset: _schema_contract(dataset, files, required_columns, sample_limit=sample_limit)
        for dataset, files, required_columns in specs
    }
    failed_contracts = [
        dataset
        for dataset, contract in datasets.items()
        if contract.get("status") == "fail"
    ]
    checked_files = sum(int(contract.get("checked_files") or 0) for contract in datasets.values())
    return {
        "status": "fail" if failed_contracts else "pass",
        "checked_files": checked_files,
        "failed_contracts": failed_contracts,
        "datasets": datasets,
    }


def _parquet_table_sql(files: list[Path]) -> str:
    return f"read_parquet({[str(path) for path in files]!r}, union_by_name=true)"


def _metric_status(metrics: dict[str, int]) -> str:
    return "fail" if any(
        value > 0
        for key, value in metrics.items()
        if key != "checked_rows" and not key.startswith("waived_")
    ) else "pass"


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _present_value_column(dataset: str, observed_columns: set[str], required_column: str) -> str | None:
    if required_column in observed_columns:
        return required_column
    for alias in _PARQUET_COLUMN_ALIASES.get(dataset, {}).get(required_column, ()):
        if alias in observed_columns:
            return alias
    return None


def _value_quality_scan(
    dataset: str,
    files: list[Path],
    *,
    observed_columns: set[str],
    conditions: list[tuple[str, str]],
    duplicate_key: tuple[str, ...] = (),
    waivers: dict[str, str] | None = None,
    sample_limit: int = 10,
) -> dict[str, Any]:
    if not files:
        return {
            "dataset": dataset,
            "status": "pass",
            "files": 0,
            "checked_rows": 0,
            "metrics": {"checked_rows": 0},
            "failed_checks": [],
            "sample": [],
        }

    try:
        import duckdb

        table_sql = _parquet_table_sql(files)
        con = duckdb.connect()
        try:
            select_exprs = ["COUNT(*) AS checked_rows"]
            select_exprs.extend(
                f"COALESCE(SUM(CASE WHEN {condition} THEN 1 ELSE 0 END), 0) AS {name}"
                for name, condition in conditions
            )
            for name, condition in (waivers or {}).items():
                select_exprs.append(
                    f"COALESCE(SUM(CASE WHEN {condition} THEN 1 ELSE 0 END), 0) AS waived_{name}"
                )
            row = con.execute(f"SELECT {', '.join(select_exprs)} FROM {table_sql}").fetchone()
            metric_names = (
                ["checked_rows"]
                + [name for name, _condition in conditions]
                + [f"waived_{name}" for name in (waivers or {})]
            )
            metrics = {
                metric_name: int((row or [0] * len(metric_names))[idx] or 0)
                for idx, metric_name in enumerate(metric_names)
            }
            if duplicate_key:
                key_expr = ", ".join(duplicate_key)
                dup_row = con.execute(
                    f"""
                    SELECT COALESCE(SUM(cnt - 1), 0) AS duplicate_keys
                    FROM (
                        SELECT {key_expr}, COUNT(*) AS cnt
                        FROM {table_sql}
                        GROUP BY {key_expr}
                        HAVING COUNT(*) > 1
                    )
                    """
                ).fetchone()
                metrics["duplicate_keys"] = int((dup_row or [0])[0] or 0)

            sample: list[dict[str, Any]] = []
            if conditions and sample_limit > 0:
                sample_columns = [
                    col
                    for col in (
                        "symbol",
                        "date",
                        "report_date",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                        "amount",
                        "large_order_net_ratio",
                        "roe",
                        "total_net",
                        "net_5d",
                        "net_sentiment",
                        "sentiment_score",
                        "confidence",
                    )
                    if col in observed_columns
                ]
                if sample_columns:
                    invalid_where = " OR ".join(f"({condition})" for _name, condition in conditions)
                    sample_rows = con.execute(
                        f"""
                        SELECT {', '.join(sample_columns)}
                        FROM {table_sql}
                        WHERE {invalid_where}
                        LIMIT {int(sample_limit)}
                        """
                    ).fetchall()
                    sample = [
                        {sample_columns[idx]: _jsonable(row_value) for idx, row_value in enumerate(sample_row)}
                        for sample_row in sample_rows
                    ]
        finally:
            con.close()
        failed_checks = [
            f"{dataset}.{name}"
            for name, value in metrics.items()
            if name != "checked_rows" and not name.startswith("waived_") and value > 0
        ]
        return {
            "dataset": dataset,
            "status": _metric_status(metrics),
            "files": len(files),
            "checked_rows": metrics.get("checked_rows", 0),
            "metrics": metrics,
            "failed_checks": failed_checks,
            "sample": sample,
        }
    except Exception as exc:
        return {
            "dataset": dataset,
            "status": "fail",
            "files": len(files),
            "checked_rows": 0,
            "metrics": {"checked_rows": 0, "scan_errors": 1},
            "failed_checks": [f"{dataset}.scan_errors"],
            "sample": [],
            "error": str(exc),
        }


def _date_conditions(date_column: str) -> list[tuple[str, str]]:
    today = date.today().isoformat()
    return [
        ("invalid_dates", f"{date_column} IS NULL OR TRY_CAST({date_column} AS DATE) IS NULL"),
        ("future_dates", f"TRY_CAST({date_column} AS DATE) > DATE '{today}'"),
    ]


def _value_conditions_for(dataset: str, observed_columns: set[str]) -> tuple[list[tuple[str, str]], tuple[str, ...]]:
    if dataset == "kline":
        return (
            _date_conditions("date") + [
                ("null_ohlc", "open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL"),
                ("non_positive_ohlc", "open <= 0 OR high <= 0 OR low <= 0 OR close <= 0"),
                (
                    "invalid_ohlc_relationship",
                    "high < low OR high < open OR high < close OR low > open OR low > close",
                ),
                ("negative_volume", "volume < 0"),
                ("negative_amount", "amount < 0"),
                ("negative_prev_close", "prev_close < 0"),
                ("negative_vwap", "vwap < 0"),
            ],
            ("symbol", "date"),
        )
    if dataset == "fund_flow":
        return (
            _date_conditions("date") + [
                (
                    "invalid_large_order_net_ratio",
                    "large_order_net_ratio IS NULL OR large_order_net_ratio < -1 OR large_order_net_ratio > 1",
                ),
            ],
            ("symbol", "date"),
        )
    if dataset == "fundamental":
        return (
            _date_conditions("report_date") + [
                ("invalid_roe", "roe IS NULL OR ABS(roe) > 1.5"),
            ],
            ("symbol", "report_date"),
        )
    if dataset.startswith("cross_asset."):
        conditions = _date_conditions("date") + [
            ("non_positive_close", "close IS NULL OR close <= 0"),
        ]
        if {"open", "high", "low", "close"}.issubset(observed_columns):
            conditions.extend([
                ("non_positive_ohlc", "open <= 0 OR high <= 0 OR low <= 0 OR close <= 0"),
                (
                    "invalid_ohlc_relationship",
                    "high < low OR high < open OR high < close OR low > open OR low > close",
                ),
            ])
        return conditions, ("date",)
    if dataset == "index":
        tolerance = _OHLC_RELATIONSHIP_TOLERANCE.get(dataset, 0.0)
        conditions = _date_conditions("date") + [
            ("non_positive_close", "close IS NULL OR close <= 0"),
        ]
        if {"open", "high", "low", "close"}.issubset(observed_columns):
            conditions.extend([
                ("non_positive_ohlc", "open <= 0 OR high <= 0 OR low <= 0 OR close <= 0"),
                (
                    "invalid_ohlc_relationship",
                    (
                        f"high + {tolerance} < low "
                        f"OR high + {tolerance} < open "
                        f"OR high + {tolerance} < close "
                        f"OR low - {tolerance} > open "
                        f"OR low - {tolerance} > close"
                    ),
                ),
            ])
        return conditions, ()
    if dataset == "northbound":
        return (
            _date_conditions("date") + [
                ("null_flow_values", "total_net IS NULL OR net_5d IS NULL"),
            ],
            ("date",),
        )
    if dataset.startswith("macro."):
        required_value = {
            "macro.gdp": "q_gdp",
            "macro.cpi": "nt_yoy",
            "macro.ppi": "ppi_yoy",
            "macro.pmi": "mfg_pmi",
        }.get(dataset)
        conditions = _date_conditions("date")
        value_column = _present_value_column(dataset, observed_columns, required_value or "")
        if value_column:
            start_date = _MACRO_VALUE_START_DATES.get(dataset)
            condition = f"{value_column} IS NULL"
            if start_date:
                condition = f"{condition} AND TRY_CAST(date AS DATE) >= DATE '{start_date}'"
            conditions.append(("null_macro_value", condition))
        return conditions, ("date",)
    if dataset == "sentiment.silver":
        conditions = _date_conditions("date") + [
            ("sentiment_score_out_of_range", "sentiment_score IS NULL OR sentiment_score < -1 OR sentiment_score > 1"),
        ]
        if "confidence" in observed_columns:
            conditions.append(("confidence_out_of_range", "confidence < 0 OR confidence > 1"))
        return conditions, ()
    if dataset == "sentiment.gold":
        conditions = _date_conditions("date") + [
            ("net_sentiment_out_of_range", "net_sentiment IS NULL OR net_sentiment < -1 OR net_sentiment > 1"),
        ]
        if "sentiment_score" in observed_columns:
            conditions.append(("sentiment_score_out_of_range", "sentiment_score < -1 OR sentiment_score > 1"))
        if "confidence" in observed_columns:
            conditions.append(("confidence_out_of_range", "confidence < 0 OR confidence > 1"))
        return conditions, ("date", "symbol")
    return [], ()


def _value_waivers_for(dataset: str, observed_columns: set[str]) -> dict[str, str]:
    if dataset == "index" and {"open", "high", "low", "close"}.issubset(observed_columns):
        tolerance = _OHLC_RELATIONSHIP_TOLERANCE["index"]
        strict = "high < low OR high < open OR high < close OR low > open OR low > close"
        beyond_tolerance = (
            f"high + {tolerance} < low "
            f"OR high + {tolerance} < open "
            f"OR high + {tolerance} < close "
            f"OR low - {tolerance} > open "
            f"OR low - {tolerance} > close"
        )
        return {
            "invalid_ohlc_relationship": (
                f"({strict}) AND NOT ({beyond_tolerance})"
            )
        }
    if not dataset.startswith("macro."):
        return {}
    required_value = {
        "macro.gdp": "q_gdp",
        "macro.cpi": "nt_yoy",
        "macro.ppi": "ppi_yoy",
        "macro.pmi": "mfg_pmi",
    }.get(dataset)
    value_column = _present_value_column(dataset, observed_columns, required_value or "")
    start_date = _MACRO_VALUE_START_DATES.get(dataset)
    if not value_column or not start_date:
        return {}
    return {
        "null_macro_value": (
            f"{value_column} IS NULL "
            f"AND TRY_CAST(date AS DATE) IS NOT NULL "
            f"AND TRY_CAST(date AS DATE) < DATE '{start_date}'"
        )
    }


def _value_recovery_key(dataset: str) -> str:
    if dataset.startswith("cross_asset."):
        return "cross_asset"
    if dataset.startswith("macro."):
        return "macro"
    if dataset.startswith("sentiment."):
        return "sentiment"
    return dataset


def _sample_symbols_dates(item: dict[str, Any], sample_limit: int) -> dict[str, list[str]]:
    symbols: list[str] = []
    dates: list[str] = []
    for row in item.get("sample") or []:
        symbol = str(row.get("symbol") or "").strip()
        day = str(row.get("date") or row.get("report_date") or "").strip()[:10]
        if symbol and symbol not in symbols:
            symbols.append(symbol)
        if day and day not in dates:
            dates.append(day)
        if len(symbols) >= sample_limit and len(dates) >= sample_limit:
            break
    return {"symbols": symbols[:sample_limit], "dates": dates[:sample_limit]}


def _build_value_quality_recovery_plan(
    datasets: dict[str, dict[str, Any]],
    *,
    sample_limit: int,
) -> list[dict[str, Any]]:
    plan_by_key: dict[str, dict[str, Any]] = {}
    for dataset, item in datasets.items():
        failed_checks = list(item.get("failed_checks") or [])
        if not failed_checks:
            continue
        recovery_key = _value_recovery_key(dataset)
        spec = _VALUE_QUALITY_RECOVERY.get(recovery_key, {
            "command": ["trade", "data", "status", "--strict", "--json"],
            "mode": "audit",
            "detail": "Inspect value_quality failed checks before trusting this dataset.",
        })
        entry = plan_by_key.setdefault(
            recovery_key,
            {
                "component": recovery_key,
                "command": list(spec["command"]),
                "mode": spec["mode"],
                "detail": spec["detail"],
                "datasets": [],
                "failed_checks": [],
                "sample_symbols": [],
                "sample_dates": [],
            },
        )
        entry["datasets"].append(dataset)
        entry["failed_checks"].extend(failed_checks)
        sample = _sample_symbols_dates(item, sample_limit)
        for symbol in sample["symbols"]:
            if symbol not in entry["sample_symbols"]:
                entry["sample_symbols"].append(symbol)
        for day in sample["dates"]:
            if day not in entry["sample_dates"]:
                entry["sample_dates"].append(day)
    result: list[dict[str, Any]] = []
    for entry in plan_by_key.values():
        entry["datasets"] = sorted(set(entry["datasets"]))
        entry["failed_checks"] = sorted(set(entry["failed_checks"]))
        entry["sample_symbols"] = entry["sample_symbols"][:sample_limit]
        entry["sample_dates"] = entry["sample_dates"][:sample_limit]
        result.append(entry)
    return sorted(result, key=lambda item: str(item.get("component") or ""))


def value_quality_stats(
    data_root: str | Path = "data",
    sample_limit: int = 10,
    schema_contracts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(data_root)
    if schema_contracts is None:
        schema_contracts = schema_contract_stats(root, sample_limit=sample_limit)

    files_by_dataset: dict[str, list[Path]] = {
        "kline": _resolve_kline_files(root),
        "fund_flow": sorted(FUND_FLOW_DIR(root).glob("*.parquet")),
        "fundamental": sorted(FUNDAMENTAL_DIR(root).glob("*.parquet")),
        "index": sorted(INDEX_DIR(root).glob("*.parquet")),
        "northbound": [NORTHBOUND_DIR(root) / "daily.parquet"] if (NORTHBOUND_DIR(root) / "daily.parquet").exists() else [],
    }
    files_by_dataset.update({
        f"cross_asset.{name}": [path] if path.exists() else []
        for name in ("gold", "fx_cnh", "btc")
        for path, _layout in [_cross_asset_path(root, name)]
    })
    files_by_dataset.update({
        f"macro.{name}": [MACRO_DIR(root) / f"{name}.parquet"] if (MACRO_DIR(root) / f"{name}.parquet").exists() else []
        for name in ("gdp", "cpi", "ppi", "pmi")
    })
    files_by_dataset.update({
        f"sentiment.{layer}": sorted((root / "sentiment" / layer).glob("**/*.parquet"))
        for layer in ("silver", "gold")
    })

    schema_datasets = schema_contracts.get("datasets") if isinstance(schema_contracts, dict) else {}
    datasets: dict[str, dict[str, Any]] = {}
    for dataset, files in files_by_dataset.items():
        schema = (schema_datasets or {}).get(dataset) or {}
        if schema.get("status") == "fail":
            datasets[dataset] = {
                "dataset": dataset,
                "status": "blocked",
                "files": len(files),
                "checked_rows": 0,
                "metrics": {"checked_rows": 0},
                "failed_checks": [],
                "blocked_by_schema": True,
                "missing_columns": schema.get("missing_columns") or [],
            }
            continue
        observed_columns = set(schema.get("observed_columns") or [])
        if not observed_columns and files:
            for path in files:
                columns, _error = _parquet_columns(path)
                observed_columns.update(columns)
        conditions, duplicate_key = _value_conditions_for(dataset, observed_columns)
        waivers = _value_waivers_for(dataset, observed_columns)
        datasets[dataset] = _value_quality_scan(
            dataset,
            files,
            observed_columns=observed_columns,
            conditions=conditions,
            duplicate_key=duplicate_key,
            waivers=waivers,
            sample_limit=sample_limit,
        )

    failed_checks = [
        check
        for item in datasets.values()
        for check in item.get("failed_checks", [])
    ]
    checked_rows = sum(int(item.get("checked_rows") or 0) for item in datasets.values())
    blocked_contracts = [
        dataset
        for dataset, item in datasets.items()
        if item.get("status") == "blocked"
    ]
    return {
        "status": "fail" if failed_checks else "pass",
        "checked_rows": checked_rows,
        "failed_checks": failed_checks,
        "blocked_contracts": blocked_contracts,
        "recovery_plan": _build_value_quality_recovery_plan(datasets, sample_limit=sample_limit),
        "datasets": datasets,
    }


def _market_flat_stats(
    data_root: str | Path,
    *,
    dataset: str,
    root: Path,
    date_column: str,
    sample_limit: int = 10,
    trading_day_freshness: bool = False,
) -> dict[str, Any]:
    files = sorted(root.glob("*.parquet"))
    db_symbols = _instrument_symbols(data_root)
    if not files:
        return {
            "dataset": dataset,
            "files": 0,
            "symbols": 0,
            "rows": 0,
            "min_date": None,
            "max_date": None,
            "db_symbols": len(db_symbols),
            "coverage_pct": 0.0,
            "missing_symbols": len(db_symbols),
            "missing_sample": sorted(db_symbols)[:sample_limit],
            "stale_sample": [],
        }
    try:
        import duckdb

        file_list = [str(path) for path in files]
        con = duckdb.connect()
        try:
            summary = con.execute(
                f"""
                SELECT
                    COUNT(*) AS rows,
                    COUNT(DISTINCT symbol) AS symbols,
                    MIN({date_column}) AS min_date,
                    MAX({date_column}) AS max_date
                FROM read_parquet({file_list!r}, union_by_name=true)
                """
            ).fetchone()
            by_symbol = con.execute(
                f"""
                SELECT symbol, MAX({date_column}) AS max_date, COUNT(*) AS rows
                FROM read_parquet({file_list!r}, union_by_name=true)
                GROUP BY symbol
                ORDER BY max_date ASC, symbol
                """
            ).fetchall()
        finally:
            con.close()
        rows, symbols, min_date, max_date = summary if summary else (0, 0, None, None)
        present_symbols = {str(row[0]) for row in by_symbol if row[0]}
        missing = sorted(db_symbols - present_symbols)
        coverage_pct = round(len(present_symbols) / len(db_symbols) * 100.0, 1) if db_symbols else 0.0
        stale_sample: list[dict[str, Any]] = []
        expected_trade_date: str | None = None
        if trading_day_freshness:
            try:
                from trade_py.db.trade_db import TradeDB

                db = TradeDB(data_root)
                expected_trade_date = db.get_latest_open_trade_date()
                if expected_trade_date:
                    with db._conn_lock:
                        for symbol, symbol_max_date, row_count in by_symbol[:sample_limit]:
                            lag_row = db._conn.execute(
                                """
                                SELECT COUNT(*) AS missing_trade_days
                                FROM trading_calendar
                                WHERE exchange = 'SSE'
                                  AND is_open = 1
                                  AND trade_date > ?
                                  AND trade_date <= ?
                                """,
                                (str(symbol_max_date)[:10], expected_trade_date),
                            ).fetchone()
                            stale_sample.append({
                                "symbol": str(symbol),
                                "watermark": str(symbol_max_date)[:10] if symbol_max_date else None,
                                "rows": int(row_count or 0),
                                "trading_day_stale_days": int((lag_row or [0])[0] or 0),
                            })
            except Exception as exc:
                logger.debug("%s trading-day freshness error: %s", dataset, exc)
        return {
            "dataset": dataset,
            "files": len(files),
            "symbols": int(symbols or 0),
            "rows": int(rows or 0),
            "min_date": str(min_date)[:10] if min_date else None,
            "max_date": str(max_date)[:10] if max_date else None,
            "db_symbols": len(db_symbols),
            "coverage_pct": coverage_pct,
            "missing_symbols": len(missing),
            "missing_sample": missing[:sample_limit],
            "expected_trade_date": expected_trade_date,
            "stale_sample": stale_sample,
        }
    except Exception as exc:
        logger.debug("%s stats error: %s", dataset, exc)
        return {
            "dataset": dataset,
            "files": len(files),
            "symbols": 0,
            "rows": 0,
            "error": str(exc),
        }


def fund_flow_stats(data_root: str | Path = "data", sample_limit: int = 10) -> dict[str, Any]:
    return _market_flat_stats(
        data_root,
        dataset="fund_flow",
        root=FUND_FLOW_DIR(data_root),
        date_column="date",
        sample_limit=sample_limit,
        trading_day_freshness=True,
    )


def fundamental_stats(data_root: str | Path = "data", sample_limit: int = 10) -> dict[str, Any]:
    return _market_flat_stats(
        data_root,
        dataset="fundamental",
        root=FUNDAMENTAL_DIR(data_root),
        date_column="report_date",
        sample_limit=sample_limit,
        trading_day_freshness=False,
    )


def _cross_asset_path(data_root: str | Path, name: str) -> tuple[Path, str]:
    root = Path(data_root)
    canonical = CROSS_ASSET_DIR(root) / f"{name}.parquet"
    if canonical.exists():
        return canonical, "market/cross_asset"
    legacy = root / "cross_asset" / f"{name}.parquet"
    return legacy, "cross_asset"


def cross_asset_stats(data_root: str | Path = "data") -> dict[str, Any]:
    expected = _expected_data_date(data_root, trading_day=False)
    result: dict[str, Any] = {}
    for name in ("gold", "fx_cnh", "btc"):
        path, layout = _cross_asset_path(data_root, name)
        item: dict[str, Any] = {
            "path": str(path),
            "layout": layout,
            "exists": path.exists(),
            "rows": 0,
            "min_date": None,
            "max_date": None,
            "expected_date": expected,
            "lag_days": None,
        }
        if path.exists():
            try:
                import duckdb

                con = duckdb.connect()
                try:
                    row = con.execute(
                        f"""
                        SELECT COUNT(*) AS rows, MIN(date) AS min_date, MAX(date) AS max_date
                        FROM read_parquet('{path}', union_by_name=true)
                        """
                    ).fetchone()
                finally:
                    con.close()
                rows, min_date, max_date = row if row else (0, None, None)
                item.update({
                    "rows": int(rows or 0),
                    "min_date": str(min_date)[:10] if min_date else None,
                    "max_date": str(max_date)[:10] if max_date else None,
                    "lag_days": _lag_days(max_date, expected),
                })
            except Exception as exc:
                item["error"] = str(exc)
        result[name] = item
    return result


def index_stats(data_root: str | Path = "data", sample_limit: int = 10) -> dict[str, Any]:
    root = INDEX_DIR(data_root)
    expected = _expected_data_date(data_root, trading_day=True)
    files = sorted(root.glob("*.parquet"))
    try:
        from trade_py.data.market.index.tushare import DEFAULT_INDICES, SW_SECTOR_INDICES

        expected_indices = len(DEFAULT_INDICES) + len(SW_SECTOR_INDICES)
    except Exception:
        expected_indices = 0
    if not files:
        return {
            "dataset": "index",
            "files": 0,
            "indices": 0,
            "expected_indices": expected_indices,
            "coverage_pct": 0.0,
            "rows": 0,
            "min_date": None,
            "max_date": None,
            "expected_trade_date": expected,
            "stale_sample": [],
        }
    try:
        import duckdb

        file_list = [str(path) for path in files]
        con = duckdb.connect()
        try:
            summary = con.execute(
                f"""
                SELECT COUNT(*) AS rows, MIN(date) AS min_date, MAX(date) AS max_date
                FROM read_parquet({file_list!r}, union_by_name=true)
                """
            ).fetchone()
        finally:
            con.close()
        rows, min_date, max_date = summary if summary else (0, None, None)
        stale_sample: list[dict[str, Any]] = []
        for path in files[:sample_limit]:
            try:
                frame = duckdb.sql(
                    f"SELECT COUNT(*) AS rows, MAX(date) AS max_date FROM read_parquet('{path}', union_by_name=true)"
                ).fetchone()
                row_count, index_max = frame if frame else (0, None)
                stale_sample.append({
                    "index": path.stem,
                    "watermark": str(index_max)[:10] if index_max else None,
                    "rows": int(row_count or 0),
                    "lag_days": _lag_days(index_max, expected),
                })
            except Exception:
                continue
        return {
            "dataset": "index",
            "files": len(files),
            "indices": len(files),
            "expected_indices": expected_indices,
            "coverage_pct": round(len(files) / expected_indices * 100.0, 1) if expected_indices else 0.0,
            "rows": int(rows or 0),
            "min_date": str(min_date)[:10] if min_date else None,
            "max_date": str(max_date)[:10] if max_date else None,
            "expected_trade_date": expected,
            "stale_sample": stale_sample,
        }
    except Exception as exc:
        logger.debug("index stats error: %s", exc)
        return {
            "dataset": "index",
            "files": len(files),
            "indices": 0,
            "expected_indices": expected_indices,
            "coverage_pct": 0.0,
            "rows": 0,
            "error": str(exc),
        }


def northbound_stats(data_root: str | Path = "data") -> dict[str, Any]:
    path = NORTHBOUND_DIR(data_root) / "daily.parquet"
    expected = _expected_data_date(data_root, trading_day=True)
    item: dict[str, Any] = {
        "exists": path.exists(),
        "path": str(path),
        "rows": 0,
        "min_date": None,
        "max_date": None,
        "expected_trade_date": expected,
        "lag_days": None,
    }
    if not path.exists():
        return item
    try:
        import duckdb

        con = duckdb.connect()
        try:
            row = con.execute(
                f"""
                SELECT COUNT(*) AS rows, MIN(date) AS min_date, MAX(date) AS max_date
                FROM read_parquet('{path}', union_by_name=true)
                """
            ).fetchone()
        finally:
            con.close()
        rows, min_date, max_date = row if row else (0, None, None)
        item.update({
            "rows": int(rows or 0),
            "min_date": str(min_date)[:10] if min_date else None,
            "max_date": str(max_date)[:10] if max_date else None,
            "lag_days": _lag_days(max_date, expected),
        })
    except Exception as exc:
        item["error"] = str(exc)
    return item


def macro_stats(data_root: str | Path = "data") -> dict[str, Any]:
    root = MACRO_DIR(data_root)
    result: dict[str, Any] = {}
    for name in ("gdp", "cpi", "ppi", "pmi"):
        path = root / f"{name}.parquet"
        item: dict[str, Any] = {
            "exists": path.exists(),
            "path": str(path),
            "rows": 0,
            "min_date": None,
            "max_date": None,
        }
        if path.exists():
            try:
                import duckdb

                con = duckdb.connect()
                try:
                    row = con.execute(
                        f"""
                        SELECT COUNT(*) AS rows, MIN(date) AS min_date, MAX(date) AS max_date
                        FROM read_parquet('{path}', union_by_name=true)
                        """
                    ).fetchone()
                finally:
                    con.close()
                rows, min_date, max_date = row if row else (0, None, None)
                item.update({
                    "rows": int(rows or 0),
                    "min_date": str(min_date)[:10] if min_date else None,
                    "max_date": str(max_date)[:10] if max_date else None,
                })
            except Exception as exc:
                item["error"] = str(exc)
        result[name] = item
    return result


def _recovery(
    command: list[str],
    *,
    mode: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "command": command,
        "mode": mode,
        "detail": detail,
    }


def _component(
    status: str,
    reason_code: str | None = None,
    metrics: dict[str, Any] | None = None,
    recovery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {"status": status, "metrics": metrics or {}}
    if reason_code:
        payload["reason_code"] = reason_code
    if recovery:
        payload["recovery"] = recovery
    return payload


def _provider_readiness_gate_recovery(provider_readiness: dict[str, Any]) -> dict[str, Any]:
    recovery_plan = [
        item
        for item in provider_readiness.get("recovery_plan") or []
        if isinstance(item, dict)
    ]
    if recovery_plan:
        first = dict(recovery_plan[0])
        return {
            "command": list(first.get("command") or ["trade", "data", "status", "--strict", "--json"]),
            "mode": str(first.get("mode") or "configure"),
            "detail": str(
                first.get("detail")
                or "Configure missing provider credentials/packages before running source refresh jobs"
            ),
            "provider": first.get("provider"),
            "missing_required": list(provider_readiness.get("missing_required") or []),
            "warn_optional": list(provider_readiness.get("warn_optional") or []),
        }
    return _recovery(
        ["trade", "data", "status", "--strict", "--json"],
        mode="audit",
        detail="Inspect provider_readiness for missing provider credentials/packages before running source refresh jobs",
    )


def build_data_quality_gate(status: dict[str, Any]) -> dict[str, Any]:
    components: dict[str, dict[str, Any]] = {}

    kline_cov = float((status.get("kline_coverage") or {}).get("coverage_pct") or 0.0)
    kline_lag = int((status.get("kline_freshness") or {}).get("max_trading_day_stale_days") or 0)
    components["kline"] = _component(
        "pass" if kline_cov >= 99.0 and kline_lag <= 3 else ("warn" if kline_cov >= 95.0 else "fail"),
        None if kline_cov >= 99.0 and kline_lag <= 3 else "KLINE_STALE_OR_LOW_COVERAGE",
        {"coverage_pct": kline_cov, "max_trading_day_stale_days": kline_lag},
        _recovery(["trade", "data", "kline", "sync"], mode="refresh", detail="Refresh K-line source data and watermarks")
        if not (kline_cov >= 99.0 and kline_lag <= 3)
        else None,
    )

    fund = status.get("fund_flow") or {}
    fund_cov = float(fund.get("coverage_pct") or 0.0)
    fund_lag = max(
        [int(item.get("trading_day_stale_days") or 0) for item in fund.get("stale_sample") or []],
        default=0,
    )
    components["fund_flow"] = _component(
        "pass" if fund_cov >= 90.0 and fund_lag <= 5 else ("warn" if fund_cov >= 80.0 else "fail"),
        None if fund_cov >= 90.0 and fund_lag <= 5 else "FUND_FLOW_STALE_OR_LOW_COVERAGE",
        {"coverage_pct": fund_cov, "sample_max_trading_day_stale_days": fund_lag},
        _recovery(["trade", "data", "fund-flow", "sync"], mode="refresh", detail="Refresh local fund-flow parquet coverage")
        if not (fund_cov >= 90.0 and fund_lag <= 5)
        else None,
    )

    fundamental = status.get("fundamental") or {}
    fundamental_cov = float(fundamental.get("coverage_pct") or 0.0)
    components["fundamental"] = _component(
        "pass" if fundamental_cov >= 95.0 else ("warn" if fundamental_cov >= 85.0 else "fail"),
        None if fundamental_cov >= 95.0 else "FUNDAMENTAL_LOW_COVERAGE",
        {"coverage_pct": fundamental_cov, "max_report_date": fundamental.get("max_date")},
        _recovery(["trade", "data", "fundamental", "sync"], mode="refresh", detail="Refresh quarterly fundamental parquet coverage")
        if fundamental_cov < 95.0
        else None,
    )

    sentiment = status.get("sentiment") or {}
    gold_lag = (sentiment.get("gold") or {}).get("lag_days")
    components["sentiment_gold"] = _component(
        "pass" if gold_lag is not None and int(gold_lag) <= 3 else "warn",
        None if gold_lag is not None and int(gold_lag) <= 3 else "SENTIMENT_GOLD_STALE",
        {"lag_days": gold_lag, "max_date": (sentiment.get("gold") or {}).get("max_date")},
        _recovery(["trade", "data", "sentiment"], mode="refresh", detail="Refresh sentiment Silver/Gold pipeline")
        if not (gold_lag is not None and int(gold_lag) <= 3)
        else None,
    )

    events = status.get("events") or {}
    event_lag = events.get("lag_days")
    event_count = int(events.get("event_count") or 0)
    components["events"] = _component(
        "pass" if event_count > 0 and event_lag is not None and int(event_lag) <= 3 else "warn",
        None if event_count > 0 and event_lag is not None and int(event_lag) <= 3 else "EVENTS_STALE_OR_EMPTY",
        {"lag_days": event_lag, "event_count": event_count},
        _recovery(["trade", "event", "sync"], mode="recompute", detail="Rebuild market events from sentiment evidence")
        if not (event_count > 0 and event_lag is not None and int(event_lag) <= 3)
        else None,
    )

    cross = status.get("cross_asset") or {}
    cross_metrics = {
        key: {
            "exists": (cross.get(key) or {}).get("exists"),
            "lag_days": (cross.get(key) or {}).get("lag_days"),
        }
        for key in ("gold", "fx_cnh", "btc")
    }
    cross_bad = [
        key
        for key, item in cross_metrics.items()
        if not item.get("exists") or item.get("lag_days") is None or int(item.get("lag_days") or 0) > 7
    ]
    components["cross_asset"] = _component(
        "pass" if not cross_bad else "warn",
        None if not cross_bad else "CROSS_ASSET_STALE_OR_MISSING",
        cross_metrics,
        _recovery(["trade", "data", "cross-asset", "all"], mode="refresh", detail="Refresh gold and FX cross-asset sources")
        if cross_bad
        else None,
    )

    index = status.get("index") or {}
    index_cov = float(index.get("coverage_pct") or 0.0)
    index_sample_lag = max([int(item.get("lag_days") or 0) for item in index.get("stale_sample") or []], default=0)
    components["index"] = _component(
        "pass" if index_cov >= 95.0 and index_sample_lag <= 3 else "warn",
        None if index_cov >= 95.0 and index_sample_lag <= 3 else "INDEX_STALE_OR_LOW_COVERAGE",
        {"coverage_pct": index_cov, "sample_max_lag_days": index_sample_lag},
        _recovery(["trade", "data", "market-index", "sync"], mode="refresh", detail="Refresh broad market index data")
        if not (index_cov >= 95.0 and index_sample_lag <= 3)
        else None,
    )

    north = status.get("northbound") or {}
    north_lag = north.get("lag_days")
    components["northbound"] = _component(
        "pass" if north.get("exists") and north_lag is not None and int(north_lag) <= 3 else "warn",
        None if north.get("exists") and north_lag is not None and int(north_lag) <= 3 else "NORTHBOUND_STALE_OR_MISSING",
        {"exists": north.get("exists"), "lag_days": north_lag},
        _recovery(["trade", "data", "northbound", "sync"], mode="refresh", detail="Refresh northbound capital flow data")
        if not (north.get("exists") and north_lag is not None and int(north_lag) <= 3)
        else None,
    )

    schema = status.get("schema_contracts") or {}
    schema_failed = list(schema.get("failed_contracts") or [])
    components["schema_contracts"] = _component(
        "pass" if not schema_failed and schema.get("status", "pass") == "pass" else "fail",
        None if not schema_failed and schema.get("status", "pass") == "pass" else "SCHEMA_CONTRACT_MISSING_COLUMNS",
        {
            "checked_files": int(schema.get("checked_files") or 0),
            "failed_contracts": schema_failed,
        },
        _recovery(
            ["trade", "data", "status", "--strict", "--json"],
            mode="audit",
            detail="Inspect schema_contracts and regenerate parquet files with the required normalized columns",
        )
        if schema_failed or schema.get("status") == "fail"
        else None,
    )

    value_quality = status.get("value_quality") or {}
    value_failed = list(value_quality.get("failed_checks") or [])
    value_recovery_plan = list(value_quality.get("recovery_plan") or [])
    components["value_quality"] = _component(
        "pass" if not value_failed and value_quality.get("status", "pass") == "pass" else "fail",
        None if not value_failed and value_quality.get("status", "pass") == "pass" else "VALUE_QUALITY_INVALID_ROWS",
        {
            "checked_rows": int(value_quality.get("checked_rows") or 0),
            "failed_checks": value_failed,
            "blocked_contracts": list(value_quality.get("blocked_contracts") or []),
            "recovery_plan": value_recovery_plan,
        },
        _recovery(
            ["trade", "data", "status", "--strict", "--json"],
            mode="audit",
            detail=(
                "Inspect value_quality recovery_plan for targeted refresh commands, "
                "sample symbols, and sample dates"
            ),
        )
        if value_failed or value_quality.get("status") == "fail"
        else None,
    )

    source_stability = status.get("source_stability") or {}
    source_reasons = list(source_stability.get("reason_codes") or [])
    components["source_stability"] = _component(
        "pass" if not source_reasons and source_stability.get("status", "pass") == "pass" else "fail",
        None if not source_reasons and source_stability.get("status", "pass") == "pass" else "SOURCE_STABILITY_DEGRADED",
        {
            "observed_jobs": int(source_stability.get("observed_jobs") or 0),
            "recent_runs": int(source_stability.get("recent_runs") or 0),
            "recent_errors": int(source_stability.get("recent_errors") or 0),
            "stale_running": int(source_stability.get("stale_running") or 0),
            "error_rate": float(source_stability.get("error_rate") or 0.0),
            "reason_codes": source_reasons,
        },
        _recovery(
            ["trade", "data", "backfill", "status"],
            mode="audit",
            detail="Inspect recent data-source job failures and stale running jobs before trusting refreshed data",
        )
        if source_reasons or source_stability.get("status") == "fail"
        else None,
    )

    metadata_reconciliation = status.get("metadata_reconciliation") or {}
    metadata_reasons = list(metadata_reconciliation.get("reason_codes") or [])
    components["metadata_reconciliation"] = _component(
        "pass" if not metadata_reasons and metadata_reconciliation.get("status", "pass") == "pass" else "fail",
        None if not metadata_reasons and metadata_reconciliation.get("status", "pass") == "pass" else "METADATA_RECONCILIATION_MISMATCH",
        {
            "reason_codes": metadata_reasons,
            "manifest": ((metadata_reconciliation.get("manifest") or {}).get("metrics") or {}),
            "sync_state": ((metadata_reconciliation.get("sync_state") or {}).get("metrics") or {}),
        },
        _recovery(
            ["trade", "data", "status", "--strict", "--json"],
            mode="audit",
            detail="Inspect metadata_reconciliation for manifest, sync_state, and parquet drift",
        )
        if metadata_reasons or metadata_reconciliation.get("status") == "fail"
        else None,
    )

    provider_readiness = status.get("provider_readiness") or {}
    provider_status = str(provider_readiness.get("status") or "pass")
    provider_reasons = list(provider_readiness.get("reason_codes") or [])
    components["provider_readiness"] = _component(
        "fail" if provider_status == "fail" else ("warn" if provider_status == "warn" else "pass"),
        None if provider_status == "pass" else "PROVIDER_READINESS_DEGRADED",
        {
            "missing_required": list(provider_readiness.get("missing_required") or []),
            "warn_optional": list(provider_readiness.get("warn_optional") or []),
            "reason_codes": provider_reasons,
            "recovery_plan": list(provider_readiness.get("recovery_plan") or []),
        },
        _provider_readiness_gate_recovery(provider_readiness)
        if provider_status != "pass"
        else None,
    )

    provider_audit = status.get("provider_audit") or {}
    audit_status = str(provider_audit.get("status") or "pass")
    audit_reasons = list(provider_audit.get("reason_codes") or [])
    components["provider_audit"] = _component(
        "fail" if audit_status == "fail" else ("warn" if audit_status == "warn" else "pass"),
        None if audit_status in {"pass", "unknown"} else "PROVIDER_AUDIT_DEGRADED",
        {
            "observed": bool(provider_audit.get("observed")),
            "reason_codes": audit_reasons,
            "providers": {
                name: {
                    "status": item.get("status"),
                    "recent_requests": item.get("recent_requests"),
                    "status_counts": item.get("status_counts"),
                    "fail_statuses": item.get("fail_statuses"),
                    "warn_statuses": item.get("warn_statuses"),
                }
                for name, item in ((provider_audit.get("providers") or {}).items())
                if isinstance(item, dict)
            },
            "recovery_plan": list(provider_audit.get("recovery_plan") or []),
        },
        _recovery(
            ["trade", "data", "status", "--strict", "--json"],
            mode="audit",
            detail="Inspect provider_audit samples and recovery_plan for recent provider request failures",
        )
        if audit_status in {"fail", "warn"}
        else None,
    )

    cross_source = status.get("cross_source_coverage") or {}
    cross_source_status = str(cross_source.get("status") or "pass")
    cross_source_reasons = list(cross_source.get("reason_codes") or [])
    components["cross_source_coverage"] = _component(
        "fail" if cross_source_status == "fail" else ("warn" if cross_source_status == "warn" else "pass"),
        None if cross_source_status == "pass" else "CROSS_SOURCE_COVERAGE_INCOMPLETE",
        {
            "required_missing": list(cross_source.get("required_missing") or []),
            "optional_single_source": list(cross_source.get("optional_single_source") or []),
            "reason_codes": cross_source_reasons,
            "recovery_plan": list(cross_source.get("recovery_plan") or []),
        },
        _recovery(
            ["trade", "data", "status", "--strict", "--json"],
            mode="audit",
            detail="Inspect cross_source_coverage for datasets lacking durable independent-source validation",
        )
        if cross_source_status in {"fail", "warn"}
        else None,
    )

    statuses = [item["status"] for item in components.values()]
    overall = "fail" if "fail" in statuses else ("warn" if "warn" in statuses else "pass")
    reasons = [
        str(item.get("reason_code"))
        for item in components.values()
        if item.get("reason_code")
    ]
    recovery_plan = [
        {"component": key, **dict(item["recovery"])}
        for key, item in components.items()
        if item.get("recovery")
    ]
    return {
        "status": overall,
        "reason_codes": reasons,
        "components": components,
        "recovery_plan": recovery_plan,
    }


def db_instrument_stats(data_root: str | Path = "data") -> dict[str, Any]:
    """Return instrument DB statistics."""
    try:
        from trade_py.db.instruments_db import InstrumentsDB
        db = InstrumentsDB(data_root)
        all_symbols = db.get_all_symbols()
        total = len(all_symbols)
        # Count mapped (industry != 255)
        mapped_rows = db._conn.execute(
            "SELECT COUNT(*) FROM instruments WHERE industry != 255"
        ).fetchone()
        mapped = int(mapped_rows[0]) if mapped_rows else 0
        sector_members = db._conn.execute(
            "SELECT COUNT(*) FROM sector_members"
        ).fetchone()
        sector_count = int(sector_members[0]) if sector_members else 0
        return {
            "total_symbols": total,
            "sector_mapped": mapped,
            "unmapped": total - mapped,
            "coverage_pct": round(mapped / total * 100, 1) if total > 0 else 0.0,
            "sector_member_rows": sector_count,
        }
    except Exception as exc:
        logger.debug("db_instrument_stats error: %s", exc)
        return {"total_symbols": 0, "error": str(exc)}


def sentiment_stats(data_root: str | Path = "data") -> dict[str, Any]:
    """Return Silver/Gold sentiment layer statistics."""
    data_root = Path(data_root)
    result: dict[str, Any] = {}
    expected = _expected_data_date(data_root, trading_day=True)

    silver_dir = data_root / "sentiment" / "silver"
    gold_dir = data_root / "sentiment" / "gold"

    try:
        import duckdb
        if silver_dir.exists():
            silver_glob = str(silver_dir / "**" / "*.parquet")
            con = duckdb.connect()
            row = con.execute(f"""
                SELECT COUNT(*) AS rows,
                       COUNT(DISTINCT date) AS dates,
                       MIN(date) AS min_date,
                       MAX(date) AS max_date
                FROM read_parquet('{silver_glob}', union_by_name=true)
            """).fetchone()
            con.close()
            rows, dates, min_d, max_d = row if row else (0, 0, None, None)
            result["silver"] = {
                "rows": int(rows or 0),
                "dates": int(dates or 0),
                "min_date": str(min_d) if min_d else None,
                "max_date": str(max_d) if max_d else None,
                "expected_date": expected,
                "lag_days": _lag_days(max_d, expected),
            }
        else:
            result["silver"] = {"rows": 0, "dates": 0, "expected_date": expected, "lag_days": None}

        if gold_dir.exists():
            gold_glob = str(gold_dir / "**" / "*.parquet")
            con = duckdb.connect()
            row = con.execute(f"""
                SELECT COUNT(*) AS rows,
                       COUNT(DISTINCT date) AS dates,
                       MIN(date) AS min_date,
                       MAX(date) AS max_date
                FROM read_parquet('{gold_glob}', union_by_name=true)
            """).fetchone()
            con.close()
            rows, dates, min_d, max_d = row if row else (0, 0, None, None)
            result["gold"] = {
                "rows": int(rows or 0),
                "dates": int(dates or 0),
                "min_date": str(min_d) if min_d else None,
                "max_date": str(max_d) if max_d else None,
                "expected_date": expected,
                "lag_days": _lag_days(max_d, expected),
            }
        else:
            result["gold"] = {"rows": 0, "dates": 0, "expected_date": expected, "lag_days": None}
    except Exception as exc:
        logger.debug("sentiment_stats error: %s", exc)
        result["error"] = str(exc)

    return result


def events_stats(data_root: str | Path = "data") -> dict[str, Any]:
    """Return events / event_propagations table statistics."""
    try:
        from trade_py.db.settings_db import SettingsDB
        db = SettingsDB(data_root)
        expected = _expected_data_date(data_root, trading_day=True)
        events_row = db._conn.execute(
            "SELECT COUNT(*), MIN(event_date), MAX(event_date) FROM market_events"
        ).fetchone()
        prop_row = db._conn.execute(
            "SELECT COUNT(*) FROM event_propagations"
        ).fetchone()
        e_count, e_min, e_max = events_row if events_row else (0, None, None)
        p_count = prop_row[0] if prop_row else 0
        return {
            "event_count":       int(e_count or 0),
            "propagation_count": int(p_count or 0),
            "min_date":          str(e_min) if e_min else None,
            "max_date":          str(e_max) if e_max else None,
            "expected_date":     expected,
            "lag_days":          _lag_days(e_max, expected),
        }
    except Exception as exc:
        logger.debug("events_stats error: %s", exc)
        return {"event_count": 0, "error": str(exc)}


def source_stability_stats(
    data_root: str | Path = "data",
    sample_limit: int = 10,
    recent_limit: int = 240,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return operational stability from recent data-source job runs."""
    try:
        from trade_py.db.trade_db import TradeDB

        db = TradeDB(data_root)
        runs = db.job_runs_recent(limit=max(int(recent_limit), len(_DATA_SOURCE_JOB_POLICIES) * 8))
    except Exception as exc:
        logger.debug("source stability stats error: %s", exc)
        return {
            "status": "unknown",
            "tracked_jobs": sorted(_DATA_SOURCE_JOB_POLICIES),
            "observed_jobs": 0,
            "recent_runs": 0,
            "recent_errors": 0,
            "stale_running": 0,
            "reason_codes": ["SOURCE_STABILITY_UNAVAILABLE"],
            "error": str(exc),
            "jobs": {},
            "error_sample": [],
            "stale_sample": [],
        }

    now = now or datetime.now()
    runs_by_job: dict[str, list[dict[str, Any]]] = {}
    for row in runs:
        job_name = str(row.get("job_name") or "")
        if job_name not in _DATA_SOURCE_JOB_POLICIES:
            continue
        runs_by_job.setdefault(job_name, []).append(row)

    jobs: dict[str, dict[str, Any]] = {}
    error_sample: list[dict[str, Any]] = []
    stale_sample: list[dict[str, Any]] = []
    recent_errors = 0
    recent_runs = 0
    stale_running = 0

    for job_name, threshold_hours in _DATA_SOURCE_JOB_POLICIES.items():
        job_runs = runs_by_job.get(job_name, [])
        latest = job_runs[0] if job_runs else None
        recent_window = job_runs[:10]
        error_runs = [row for row in recent_window if str(row.get("status") or "") == "error"]
        running_runs = [row for row in recent_window if str(row.get("status") or "") == "running"]
        stale_runs: list[dict[str, Any]] = []
        for row in running_runs:
            age = _age_hours(row.get("started_at"), now=now)
            if age is not None and age > threshold_hours:
                stale_runs.append({**row, "age_hours": round(age, 2)})
        recent_runs += len(recent_window)
        recent_errors += len(error_runs)
        stale_running += len(stale_runs)
        if error_runs:
            for row in error_runs[:sample_limit]:
                if len(error_sample) >= sample_limit:
                    break
                error_sample.append({
                    "job_name": job_name,
                    "status": row.get("status"),
                    "started_at": row.get("started_at"),
                    "completed_at": row.get("completed_at"),
                    "summary": row.get("result_summary"),
                })
        if stale_runs:
            for row in stale_runs[:sample_limit]:
                if len(stale_sample) >= sample_limit:
                    break
                stale_sample.append({
                    "job_name": job_name,
                    "started_at": row.get("started_at"),
                    "age_hours": row.get("age_hours"),
                    "stale_after_hours": threshold_hours,
                    "summary": row.get("result_summary"),
                })
        latest_age = _age_hours((latest or {}).get("started_at"), now=now) if latest else None
        jobs[job_name] = {
            "status": str((latest or {}).get("status") or "unknown"),
            "latest_run_id": (latest or {}).get("id"),
            "latest_started_at": (latest or {}).get("started_at"),
            "latest_completed_at": (latest or {}).get("completed_at"),
            "latest_age_hours": round(latest_age, 2) if latest_age is not None else None,
            "recent_runs": len(recent_window),
            "recent_errors": len(error_runs),
            "running": len(running_runs),
            "stale_running": len(stale_runs),
            "stale_after_hours": threshold_hours,
            "latest_summary": (latest or {}).get("result_summary"),
        }

    reason_codes: list[str] = []
    if stale_running:
        reason_codes.append("SOURCE_JOB_STALE_RUNNING")
    if recent_errors:
        reason_codes.append("SOURCE_JOB_RECENT_ERRORS")
    observed_jobs = sum(1 for item in jobs.values() if item.get("recent_runs"))
    error_rate = round(recent_errors / recent_runs, 4) if recent_runs else 0.0
    return {
        "status": "fail" if stale_running or recent_errors else "pass",
        "tracked_jobs": sorted(_DATA_SOURCE_JOB_POLICIES),
        "observed_jobs": observed_jobs,
        "recent_runs": recent_runs,
        "recent_errors": recent_errors,
        "stale_running": stale_running,
        "error_rate": error_rate,
        "reason_codes": reason_codes,
        "jobs": jobs,
        "error_sample": error_sample,
        "stale_sample": stale_sample,
    }


def metadata_reconciliation_stats(
    data_root: str | Path = "data",
    sample_limit: int = 10,
) -> dict[str, Any]:
    """Cross-check metadata indexes/watermarks against local parquet artifacts."""
    root = Path(data_root)
    sample_cap = max(1, int(sample_limit))
    manifest = _load_kline_manifest(root)
    entries = manifest.get("entries") if isinstance(manifest, dict) else {}
    entries = entries if isinstance(entries, dict) else {}
    manifest_sample = list(entries.items())[: max(sample_cap, 1)]

    manifest_metrics = {
        "checked_entries": 0,
        "missing_files": 0,
        "row_mismatches": 0,
        "date_mismatches": 0,
        "read_errors": 0,
    }
    manifest_failures: list[dict[str, Any]] = []
    for key, raw_entry in manifest_sample:
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        symbol = key.replace("_", ".")
        path = _resolve_kline_dir(root) / f"{key}.parquet"
        manifest_metrics["checked_entries"] += 1
        if not path.exists():
            manifest_metrics["missing_files"] += 1
            manifest_failures.append({"symbol": symbol, "reason": "missing_file", "path": str(path)})
            continue
        stats = _single_parquet_date_stats(path)
        if stats.get("error"):
            manifest_metrics["read_errors"] += 1
            manifest_failures.append({"symbol": symbol, "reason": "read_error", "path": str(path), "error": stats.get("error")})
            continue
        expected_rows = int(entry.get("rows") or 0)
        actual_rows = int(stats.get("rows") or 0)
        expected_min = str(entry.get("date_min") or "")[:10] or None
        expected_max = str(entry.get("date_max") or "")[:10] or None
        actual_min = stats.get("min_date")
        actual_max = stats.get("max_date")
        reasons: list[str] = []
        if expected_rows != actual_rows:
            manifest_metrics["row_mismatches"] += 1
            reasons.append("row_mismatch")
        if expected_min != actual_min or expected_max != actual_max:
            manifest_metrics["date_mismatches"] += 1
            reasons.append("date_mismatch")
        if reasons:
            manifest_failures.append({
                "symbol": symbol,
                "reason": ",".join(reasons),
                "manifest": {"rows": expected_rows, "min_date": expected_min, "max_date": expected_max},
                "parquet": {"rows": actual_rows, "min_date": actual_min, "max_date": actual_max},
                "path": str(path),
            })
        if len(manifest_failures) >= sample_cap:
            break

    sync_metrics = {
        "checked_rows": 0,
        "missing_files": 0,
        "watermark_ahead": 0,
        "watermark_behind": 0,
        "row_count_mismatches": 0,
        "read_errors": 0,
    }
    sync_failures: list[dict[str, Any]] = []
    try:
        from trade_py.db.trade_db import TradeDB

        db = TradeDB(root)
        with db._conn_lock:
            rows = db._conn.execute(
                """
                SELECT source, dataset, symbol, last_date, row_count
                FROM sync_state
                WHERE source = 'tushare_kline'
                  AND dataset = 'daily'
                  AND COALESCE(symbol, '') != ''
                ORDER BY updated_at DESC, symbol
                LIMIT ?
                """,
                (max(sample_cap * 4, sample_cap),),
            ).fetchall()
    except Exception as exc:
        rows = []
        sync_failures.append({"reason": "sync_state_read_error", "error": str(exc)})
        sync_metrics["read_errors"] += 1

    for row in rows:
        if sync_metrics["checked_rows"] >= sample_cap:
            break
        symbol = str(row["symbol"] or "")
        safe_symbol = symbol.replace(".", "_")
        path = _resolve_kline_dir(root) / f"{safe_symbol}.parquet"
        sync_metrics["checked_rows"] += 1
        if not path.exists():
            sync_metrics["missing_files"] += 1
            sync_failures.append({"symbol": symbol, "reason": "missing_file", "path": str(path), "sync_last_date": row["last_date"]})
            continue
        stats = _single_parquet_date_stats(path)
        if stats.get("error"):
            sync_metrics["read_errors"] += 1
            sync_failures.append({"symbol": symbol, "reason": "read_error", "path": str(path), "error": stats.get("error")})
            continue
        sync_last = str(row["last_date"] or "")[:10] or None
        parquet_last = stats.get("max_date")
        reasons: list[str] = []
        if sync_last and parquet_last:
            if sync_last > parquet_last:
                sync_metrics["watermark_ahead"] += 1
                reasons.append("watermark_ahead")
            elif sync_last < parquet_last:
                sync_metrics["watermark_behind"] += 1
                reasons.append("watermark_behind")
        row_count = row["row_count"]
        if row_count is not None and int(row_count or 0) > int(stats.get("rows") or 0):
            sync_metrics["row_count_mismatches"] += 1
            reasons.append("row_count_exceeds_parquet")
        if reasons:
            sync_failures.append({
                "symbol": symbol,
                "reason": ",".join(reasons),
                "sync": {"last_date": sync_last, "row_count": row_count},
                "parquet": {"max_date": parquet_last, "rows": stats.get("rows")},
                "path": str(path),
            })
        if len(sync_failures) >= sample_cap:
            break

    manifest_failed = sum(value for key, value in manifest_metrics.items() if key != "checked_entries")
    sync_failed = sum(value for key, value in sync_metrics.items() if key != "checked_rows")
    reason_codes: list[str] = []
    if manifest_failed:
        reason_codes.append("MANIFEST_PARQUET_MISMATCH")
    if sync_failed:
        reason_codes.append("SYNC_STATE_PARQUET_MISMATCH")
    return {
        "status": "fail" if reason_codes else "pass",
        "reason_codes": reason_codes,
        "manifest": {
            "status": "fail" if manifest_failed else "pass",
            "metrics": manifest_metrics,
            "sample": manifest_failures[:sample_cap],
        },
        "sync_state": {
            "status": "fail" if sync_failed else "pass",
            "metrics": sync_metrics,
            "sample": sync_failures[:sample_cap],
        },
    }


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def _settings_get(data_root: str | Path, key: str, default: Any = "") -> Any:
    try:
        from trade_py.db.settings_db import SettingsDB

        return SettingsDB(data_root).get(key, default)
    except Exception as exc:
        logger.debug("settings lookup error key=%s: %s", key, exc)
        return default


def _defaults_provider_value(path: tuple[str, ...]) -> Any:
    try:
        from trade_py.infra.settings import load_defaults

        value: Any = load_defaults()
        for key in path:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return value
    except Exception as exc:
        logger.debug("defaults lookup error path=%s: %s", path, exc)
        return None


def provider_readiness_stats(data_root: str | Path = "data") -> dict[str, Any]:
    """Return non-network provider credential/package readiness."""
    tushare_token = str(
        _settings_get(data_root, "tushare_token", "")
        or os.environ.get("TUSHARE_TOKEN", "")
        or _defaults_provider_value(("tushare_token",))
        or _defaults_provider_value(("tushare", "token"))
        or _defaults_provider_value(("providers", "tushare_token"))
        or _defaults_provider_value(("providers", "tushare", "token"))
        or ""
    ).strip()
    coingecko_key = str(
        os.environ.get("COINGECKO_API_KEY")
        or os.environ.get("COINGECKO_DEMO_API_KEY")
        or ""
    ).strip()

    providers: dict[str, dict[str, Any]] = {
        "tushare": {
            "status": "pass" if tushare_token and all(_module_available(m) for m in _PYTHON_PROVIDER_MODULES["tushare"]) else "fail",
            "credential_required": True,
            "credential_present": bool(tushare_token),
            "credential_sources": ["settings:tushare_token", "env:TUSHARE_TOKEN", "defaults"],
            "modules": {
                module: _module_available(module)
                for module in _PYTHON_PROVIDER_MODULES["tushare"]
            },
            "used_by": ["kline", "fund_flow", "fundamental", "index", "northbound", "macro", "calendar"],
        },
        "coingecko": {
            "status": "pass" if coingecko_key and all(_module_available(m) for m in _PYTHON_PROVIDER_MODULES["coingecko"]) else "fail",
            "credential_required": True,
            "credential_present": bool(coingecko_key),
            "credential_sources": ["env:COINGECKO_API_KEY", "env:COINGECKO_DEMO_API_KEY"],
            "modules": {
                module: _module_available(module)
                for module in _PYTHON_PROVIDER_MODULES["coingecko"]
            },
            "used_by": ["cross_asset.btc.shadow_reconciliation"],
        },
        "akshare": {
            "status": "pass" if all(_module_available(m) for m in _PYTHON_PROVIDER_MODULES["akshare"]) else "warn",
            "credential_required": False,
            "credential_present": None,
            "credential_sources": [],
            "modules": {
                module: _module_available(module)
                for module in _PYTHON_PROVIDER_MODULES["akshare"]
            },
            "used_by": ["kline_fallback", "cross_asset.gold", "cross_asset.fx_cnh"],
        },
        "baostock": {
            "status": "pass" if all(_module_available(m) for m in _PYTHON_PROVIDER_MODULES["baostock"]) else "warn",
            "credential_required": False,
            "credential_present": None,
            "credential_sources": [],
            "modules": {
                module: _module_available(module)
                for module in _PYTHON_PROVIDER_MODULES["baostock"]
            },
            "used_by": ["kline_fallback"],
        },
        "tencent": {
            "status": "pass" if all(_module_available(m) for m in _PYTHON_PROVIDER_MODULES["tencent"]) else "warn",
            "credential_required": False,
            "credential_present": None,
            "credential_sources": [],
            "modules": {
                module: _module_available(module)
                for module in _PYTHON_PROVIDER_MODULES["tencent"]
            },
            "used_by": ["kline_fallback"],
        },
        "okx": {
            "status": "pass" if all(_module_available(m) for m in _PYTHON_PROVIDER_MODULES["okx"]) else "fail",
            "credential_required": False,
            "credential_present": None,
            "credential_sources": [],
            "modules": {
                module: _module_available(module)
                for module in _PYTHON_PROVIDER_MODULES["okx"]
            },
            "used_by": ["cross_asset.btc.primary"],
        },
    }

    missing_required = sorted(
        name
        for name, item in providers.items()
        if item.get("status") == "fail"
    )
    warn_optional = sorted(
        name
        for name, item in providers.items()
        if item.get("status") == "warn"
    )
    recovery_plan = []
    for name in missing_required:
        spec = _PROVIDER_RECOVERY.get(name)
        if spec:
            recovery_plan.append({"provider": name, **spec})
    for name in warn_optional:
        missing_modules = [
            module
            for module, available in (providers.get(name, {}).get("modules") or {}).items()
            if not available
        ]
        recovery_plan.append({
            "provider": name,
            "command": ["python", "-m", "pip", "install", *missing_modules] if missing_modules else ["trade", "data", "status", "--json"],
            "mode": "install_optional",
            "detail": f"Install optional provider package(s) for {name} fallback support.",
            "missing_modules": missing_modules,
        })
    reason_codes: list[str] = []
    if missing_required:
        reason_codes.append("PROVIDER_REQUIRED_UNAVAILABLE")
    if warn_optional:
        reason_codes.append("PROVIDER_OPTIONAL_UNAVAILABLE")
    return {
        "status": "fail" if missing_required else ("warn" if warn_optional else "pass"),
        "reason_codes": reason_codes,
        "missing_required": missing_required,
        "warn_optional": warn_optional,
        "recovery_plan": recovery_plan,
        "providers": providers,
    }


def _read_jsonl_tail(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: deque[dict[str, Any]] = deque(maxlen=max(1, int(limit)))
    try:
        with path.open("r", encoding="utf-8") as fp:
            for line in fp:
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
    except Exception as exc:
        logger.debug("jsonl tail read error path=%s: %s", path, exc)
        return [{"status": "read_error", "error_message": str(exc), "endpoint": ""}]
    return list(rows)


def _provider_audit_recovery(status: str) -> dict[str, Any]:
    if status == "auth":
        return {
            "status": status,
            "command": ["trade", "account", "setting-set", "tushare_token", "YOUR_TOKEN"],
            "mode": "configure",
            "detail": "Refresh the Tushare token and rerun the affected data sync.",
        }
    if status == "permission":
        return {
            "status": status,
            "command": ["trade", "data", "status", "--strict", "--json"],
            "mode": "audit",
            "detail": "Check Tushare quota/permissions for the failing endpoint before retrying.",
        }
    if status == "invalid_request":
        return {
            "status": status,
            "command": ["trade", "data", "status", "--strict", "--json"],
            "mode": "audit",
            "detail": "Inspect endpoint parameters or field lists; retries will not fix invalid requests.",
        }
    if status == "rate_limit":
        return {
            "status": status,
            "command": ["trade", "account", "setting-set", "tushare.rate_limit_backoff_sec", "5,15,30,45,60"],
            "mode": "tune",
            "detail": "Increase backoff or lower request concurrency before the next refresh.",
        }
    if status == "transient":
        return {
            "status": status,
            "command": ["trade", "data", "backfill", "status"],
            "mode": "retry",
            "detail": "Retry after provider/network recovers and verify job history.",
        }
    return {
        "status": status,
        "command": ["trade", "data", "status", "--strict", "--json"],
        "mode": "audit",
        "detail": "Inspect provider audit samples for unknown failures.",
    }


def provider_audit_stats(
    data_root: str | Path = "data",
    sample_limit: int = 10,
    recent_limit: int = 200,
) -> dict[str, Any]:
    """Summarize recent provider request audit logs without making network calls."""
    root = Path(data_root)
    path = root / ".db" / _TUSHARE_AUDIT_LOG_NAME
    rows = _read_jsonl_tail(path, max(int(recent_limit), int(sample_limit)))
    if not rows:
        return {
            "status": "unknown",
            "observed": False,
            "reason_codes": [],
            "providers": {
                "tushare": {
                    "status": "unknown",
                    "audit_log_path": str(path),
                    "recent_requests": 0,
                    "status_counts": {},
                    "endpoint_counts": {},
                    "sample": [],
                }
            },
            "recovery_plan": [],
        }

    status_counts = Counter(str(row.get("status") or "unknown") for row in rows)
    endpoint_counts = Counter(str(row.get("endpoint") or "") for row in rows if row.get("endpoint"))
    fail_statuses = sorted(status for status in _TUSHARE_AUDIT_FAIL_STATUSES if status_counts.get(status, 0) > 0)
    warn_statuses = sorted(status for status in _TUSHARE_AUDIT_WARN_STATUSES if status_counts.get(status, 0) > 0)
    reason_codes: list[str] = []
    if fail_statuses:
        reason_codes.append("PROVIDER_AUDIT_RECENT_FAILURES")
    if warn_statuses:
        reason_codes.append("PROVIDER_AUDIT_RECENT_WARNINGS")
    problem_statuses = set(fail_statuses) | set(warn_statuses)
    sample = [
        {
            "provider": "tushare",
            "ts": row.get("ts"),
            "endpoint": row.get("endpoint"),
            "status": row.get("status"),
            "error_type": row.get("error_type"),
            "error_message": str(row.get("error_message") or "")[:200],
            "retry_index": row.get("retry_index"),
            "wait_ms": row.get("wait_ms"),
        }
        for row in rows
        if str(row.get("status") or "unknown") in problem_statuses
    ][: max(1, int(sample_limit))]
    recovery_plan = [_provider_audit_recovery(status) for status in fail_statuses + warn_statuses]
    provider_status = "fail" if fail_statuses else ("warn" if warn_statuses else "pass")
    return {
        "status": provider_status,
        "observed": True,
        "reason_codes": reason_codes,
        "providers": {
            "tushare": {
                "status": provider_status,
                "audit_log_path": str(path),
                "recent_requests": len(rows),
                "status_counts": dict(sorted(status_counts.items())),
                "endpoint_counts": dict(endpoint_counts.most_common(10)),
                "fail_statuses": fail_statuses,
                "warn_statuses": warn_statuses,
                "sample": sample,
            }
        },
        "sample": sample,
        "recovery_plan": recovery_plan,
    }


def _btc_cross_source_item(data_root: str | Path) -> dict[str, Any]:
    current_path = CROSS_ASSET_DIR(data_root) / "btc_current.json"
    item = {
        "dataset": "cross_asset.btc",
        "required": True,
        "status": "fail",
        "evidence_level": "missing",
        "primary_source": "okx",
        "shadow_sources": ["coingecko"],
        "evidence_refs": {"current_pointer": str(current_path)},
        "required_artifact": {
            "current_pointer": str(current_path),
            "manifest_gate": "D3",
            "cross_source_status": "pass",
            "minimum_aligned_rows": 1,
            "maximum_block_rows": 0,
            "required_shadow_sources": ["coingecko"],
        },
        "reason_code": "BTC_RECONCILIATION_MISSING",
        "metrics": {},
    }
    if not current_path.exists():
        return item
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
        manifest_path = Path(str((current or {}).get("manifest_path") or ""))
        item["evidence_refs"]["manifest_path"] = str(manifest_path)
        if not manifest_path.exists():
            item["reason_code"] = "BTC_MANIFEST_MISSING"
            return item
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        item["reason_code"] = "BTC_RECONCILIATION_READ_ERROR"
        item["error"] = str(exc)
        return item

    health = manifest.get("health") if isinstance(manifest, dict) else {}
    cross = (health or {}).get("cross_source_validation") or {}
    gates = manifest.get("gates") or []
    d3 = next((gate for gate in gates if gate.get("gate") == "D3"), {})
    status = str(cross.get("status") or d3.get("status") or "")
    aligned_rows = int(cross.get("aligned_rows") or ((d3.get("metrics") or {}).get("aligned_rows") or 0))
    block_rows = int(cross.get("block_rows") or ((d3.get("metrics") or {}).get("block_rows") or 0))
    item["metrics"] = {
        "aligned_rows": aligned_rows,
        "block_rows": block_rows,
        "max_basis_pct": cross.get("max_basis_pct") or (d3.get("metrics") or {}).get("max_basis_pct"),
    }
    item["run_id"] = manifest.get("run_id")
    if status == "pass" and aligned_rows > 0 and block_rows == 0:
        item.update({
            "status": "pass",
            "evidence_level": "provider_reconciliation",
            "reason_code": None,
        })
    else:
        item["reason_code"] = "BTC_RECONCILIATION_NOT_READY"
    return item


def _kline_reconciliation_path(data_root: str | Path) -> Path:
    return KLINE_DIR(data_root) / "reconciliation" / "current.json"


def _kline_cross_source_item(data_root: str | Path) -> dict[str, Any]:
    path = _kline_reconciliation_path(data_root)
    item = {
        "dataset": "kline",
        "required": True,
        "status": "warn",
        "evidence_level": "provider_fallback_only",
        "primary_source": "tushare",
        "shadow_sources": ["akshare", "tencent", "baostock"],
        "reason_code": "KLINE_RECONCILIATION_NOT_PERSISTED",
        "metrics": {
            "provider_chain": ["tushare", "akshare", "tencent", "baostock"],
        },
        "evidence_refs": {
            "reconciliation_pointer": str(path),
            "failure_log": str(Path(data_root) / ".db" / "kline_failures.jsonl"),
            "manifest_path": str(KLINE_MANIFEST(data_root)),
        },
        "required_artifact": {
            "path": str(path),
            "schema_version": _KLINE_RECONCILIATION_SCHEMA_VERSION,
            "status": "pass",
            "minimum_checked_rows": 1,
            "maximum_block_rows": 0,
            "shadow_sources": "non_empty",
        },
    }
    if not path.exists():
        return item
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        item["status"] = "fail"
        item["evidence_level"] = "invalid_artifact"
        item["reason_code"] = "KLINE_RECONCILIATION_READ_ERROR"
        item["error"] = str(exc)
        return item
    if not isinstance(payload, dict):
        item["status"] = "fail"
        item["evidence_level"] = "invalid_artifact"
        item["reason_code"] = "KLINE_RECONCILIATION_INVALID"
        return item
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    providers = payload.get("providers") if isinstance(payload.get("providers"), dict) else {}
    primary = str(providers.get("primary") or payload.get("primary_source") or "tushare")
    shadows = [str(value) for value in (providers.get("shadow") or payload.get("shadow_sources") or [])]
    checked_rows = int(metrics.get("checked_rows") or metrics.get("aligned_rows") or 0)
    block_rows = int(metrics.get("block_rows") or 0)
    warn_rows = int(metrics.get("warn_rows") or 0)
    status = str(payload.get("status") or "")
    schema_version = str(payload.get("schema_version") or "")
    item.update({
        "primary_source": primary,
        "shadow_sources": shadows,
        "run_id": payload.get("run_id"),
        "observed_at": payload.get("observed_at"),
        "metrics": {
            "checked_rows": checked_rows,
            "block_rows": block_rows,
            "warn_rows": warn_rows,
            "max_close_basis_pct": metrics.get("max_close_basis_pct"),
            "provider_pair_count": len(shadows),
        },
        "evidence_refs": {
            **item["evidence_refs"],
            "artifact_path": str(path),
            "manifest_hash": payload.get("kline_manifest_hash"),
        },
    })
    if schema_version != _KLINE_RECONCILIATION_SCHEMA_VERSION:
        item["status"] = "fail"
        item["evidence_level"] = "invalid_artifact"
        item["reason_code"] = "KLINE_RECONCILIATION_SCHEMA_MISMATCH"
        return item
    if status == "pass" and checked_rows > 0 and block_rows == 0 and shadows:
        item["status"] = "pass"
        item["evidence_level"] = "provider_reconciliation"
        item["reason_code"] = None
        return item
    item["status"] = "fail"
    item["evidence_level"] = "provider_reconciliation_failed"
    item["reason_code"] = "KLINE_RECONCILIATION_NOT_READY"
    return item


def _cross_source_recovery_item(dataset: str, item: dict[str, Any]) -> dict[str, Any]:
    common = {
        "dataset": dataset,
        "status": item.get("status"),
        "reason_code": item.get("reason_code"),
        "evidence_level": item.get("evidence_level"),
        "metrics": dict(item.get("metrics") or {}),
        "evidence_refs": dict(item.get("evidence_refs") or {}),
        "required_artifact": dict(item.get("required_artifact") or {}),
    }
    if dataset == "kline":
        return {
            **common,
            "command": list(_KLINE_RECONCILIATION_COMMAND),
            "preflight_command": [*_KLINE_RECONCILIATION_COMMAND, "--dry-run"],
            "mode": "generate",
            "detail": (
                "Run K-line reconciliation over an explicit liquid-symbol/date sample. "
                "Use the dry-run command first; rerun without --dry-run only when status=pass "
                "to write data/market/kline/reconciliation/current.json."
            ),
        }
    if dataset == "cross_asset.btc":
        return {
            **common,
            "command": ["trade", "data", "cross-asset", "btc", "--mode", "sync", "--strict"],
            "mode": "sync",
            "detail": (
                "Run BTC assurance with OKX primary and CoinGecko shadow evidence until "
                "D3 reconciliation passes and btc_current.json points at the manifest."
            ),
        }
    return {
        **common,
        "command": ["trade", "data", "status", "--strict", "--json"],
        "mode": "audit",
        "detail": "Inspect cross-source evidence before trusting this dataset.",
    }


def cross_source_coverage_stats(data_root: str | Path = "data") -> dict[str, Any]:
    """Inventory datasets with durable independent-source validation evidence."""
    datasets: dict[str, dict[str, Any]] = {
        "kline": _kline_cross_source_item(data_root),
        "cross_asset.btc": _btc_cross_source_item(data_root),
        "cross_asset.gold": {
            "dataset": "cross_asset.gold",
            "required": False,
            "status": "warn",
            "evidence_level": "single_source",
            "primary_source": "akshare",
            "shadow_sources": [],
            "reason_code": "GOLD_SINGLE_SOURCE",
            "metrics": {},
            "evidence_refs": {"path": str(CROSS_ASSET_DIR(data_root) / "gold.parquet")},
        },
        "cross_asset.fx_cnh": {
            "dataset": "cross_asset.fx_cnh",
            "required": False,
            "status": "warn",
            "evidence_level": "single_source",
            "primary_source": "eastmoney",
            "shadow_sources": [],
            "reason_code": "FX_SINGLE_SOURCE",
            "metrics": {},
            "evidence_refs": {"path": str(CROSS_ASSET_DIR(data_root) / "fx_cnh.parquet")},
        },
    }
    required_missing = sorted(
        key
        for key, item in datasets.items()
        if item.get("required") and item.get("status") != "pass"
    )
    optional_single_source = sorted(
        key
        for key, item in datasets.items()
        if not item.get("required") and item.get("status") != "pass"
    )
    reason_codes: list[str] = []
    if required_missing:
        reason_codes.append("REQUIRED_CROSS_SOURCE_EVIDENCE_MISSING")
    if optional_single_source:
        reason_codes.append("OPTIONAL_CROSS_SOURCE_EVIDENCE_MISSING")
    recovery_plan = [
        _cross_source_recovery_item(dataset, datasets[dataset])
        for dataset in required_missing
    ]
    return {
        "status": "fail" if required_missing else ("warn" if optional_single_source else "pass"),
        "reason_codes": reason_codes,
        "required_datasets": list(_REQUIRED_CROSS_SOURCE_DATASETS),
        "required_missing": required_missing,
        "optional_single_source": optional_single_source,
        "datasets": datasets,
        "recovery_plan": recovery_plan,
    }


# ── Aggregate status ──────────────────────────────────────────────────────────

def get_data_status(
    data_root: str | Path = "data",
    sample_limit: int = 10,
    include_value_quality: bool = False,
) -> dict[str, Any]:
    """Return a consolidated status dict across all data layers."""
    schema_contracts = schema_contract_stats(data_root, sample_limit=sample_limit)
    status = {
        "kline":       kline_stats(data_root),
        "kline_coverage": kline_coverage_stats(data_root, sample_limit=sample_limit),
        "kline_freshness": kline_freshness_stats(data_root, sample_limit=sample_limit),
        "fund_flow":   fund_flow_stats(data_root, sample_limit=sample_limit),
        "fundamental": fundamental_stats(data_root, sample_limit=sample_limit),
        "cross_asset": cross_asset_stats(data_root),
        "index":       index_stats(data_root, sample_limit=sample_limit),
        "northbound":  northbound_stats(data_root),
        "macro":       macro_stats(data_root),
        "instruments": db_instrument_stats(data_root),
        "sentiment":   sentiment_stats(data_root),
        "events":      events_stats(data_root),
        "schema_contracts": schema_contracts,
        "source_stability": source_stability_stats(data_root, sample_limit=sample_limit),
        "metadata_reconciliation": metadata_reconciliation_stats(data_root, sample_limit=sample_limit),
        "provider_readiness": provider_readiness_stats(data_root),
        "provider_audit": provider_audit_stats(data_root, sample_limit=sample_limit),
        "cross_source_coverage": cross_source_coverage_stats(data_root),
        "as_of":       date.today().isoformat(),
    }
    if include_value_quality:
        status["value_quality"] = value_quality_stats(
            data_root,
            sample_limit=sample_limit,
            schema_contracts=schema_contracts,
        )
    status["quality_gate"] = build_data_quality_gate(status)
    return status


# ── Display helpers ───────────────────────────────────────────────────────────

def display_status_table(status: dict[str, Any]) -> None:
    """Print a formatted status table (works in plain Python and Jupyter)."""
    try:
        from IPython.display import display, Markdown
        lines = _build_status_md(status)
        display(Markdown("\n".join(lines)))
    except ImportError:
        for line in _build_status_md(status):
            print(line)


def build_status_lines(status: dict[str, Any]) -> list[str]:
    return _build_status_md(status)


def _build_status_md(status: dict[str, Any]) -> list[str]:
    lines = [f"## 数据层状态 ({status.get('as_of', 'N/A')})", ""]

    gate = status.get("quality_gate") or {}
    if gate:
        lines += [
            "### 数据质量门禁",
            f"- status: **{gate.get('status', 'unknown')}**",
            f"- reasons: {', '.join(gate.get('reason_codes') or []) or '—'}",
            "",
        ]

    k = status.get("kline", {})
    k_ok = status_emoji(k.get("symbols", 0), 100)
    lines += [
        "### K线数据",
        f"- {k_ok} 标的数: **{k.get('symbols', 0):,}**",
        f"- 总行数: {k.get('rows', 0):,}",
        f"- 日期范围: {k.get('min_date', '—')} ~ {k.get('max_date', '—')}",
        "",
    ]

    kc = status.get("kline_coverage", {})
    if kc:
        lines += [
            "### K线覆盖",
            f"- 覆盖率: **{kc.get('coverage_pct', 0.0):.1f}%** ({kc.get('db_symbols', 0):,} 仪表 / {kc.get('file_symbols', 0):,} 文件symbol)",
            f"- 缺失 symbol: {kc.get('missing_symbols', 0):,}",
            f"- 可疑 suffix symbol: {kc.get('suspicious_suffix_symbols', 0):,}",
            "",
        ]

    kf = status.get("kline_freshness", {})
    if kf:
        lines += [
            "### K线时效",
            f"- stale >= 1d: {kf.get('stale_ge_1', 0):,}",
            f"- stale >= 5d: {kf.get('stale_ge_5', 0):,}",
            f"- stale >= 30d: {kf.get('stale_ge_30', 0):,}",
            f"- 最大滞后: {kf.get('max_stale_days', 0)} 天",
            f"- 交易日基准: {kf.get('expected_trade_date') or '—'}",
            f"- trading-day stale >= 1d: {kf.get('trading_day_stale_ge_1', 0):,}",
            f"- trading-day stale >= 5d: {kf.get('trading_day_stale_ge_5', 0):,}",
            f"- 最大交易日滞后: {kf.get('max_trading_day_stale_days', 0)} 天",
            "",
        ]

    i = status.get("instruments", {})
    i_total = i.get("total_symbols", 0)
    i_mapped = i.get("sector_mapped", 0)
    i_cov = i.get("coverage_pct", 0.0)
    i_ok = "✅" if i_cov >= 80 else ("⚠️" if i_cov >= 50 else "❌")
    lines += [
        "### 板块映射",
        f"- {i_ok} 覆盖率: **{i_cov:.1f}%** ({i_mapped:,} / {i_total:,})",
        f"- 未映射: {i.get('unmapped', 0):,} 只",
        f"- sector_members 行数: {i.get('sector_member_rows', 0):,}",
        "",
    ]

    ff = status.get("fund_flow", {})
    if ff:
        lines += [
            "### 资金流数据",
            f"- 覆盖率: **{ff.get('coverage_pct', 0.0):.1f}%** ({ff.get('symbols', 0):,} / {ff.get('db_symbols', 0):,})",
            f"- 文件数: {ff.get('files', 0):,}  行数: {ff.get('rows', 0):,}",
            f"- 日期范围: {ff.get('min_date', '—')} ~ {ff.get('max_date', '—')}",
            f"- 交易日基准: {ff.get('expected_trade_date') or '—'}",
            "",
        ]

    fundamental = status.get("fundamental", {})
    if fundamental:
        lines += [
            "### 基本面数据",
            f"- 覆盖率: **{fundamental.get('coverage_pct', 0.0):.1f}%** ({fundamental.get('symbols', 0):,} / {fundamental.get('db_symbols', 0):,})",
            f"- 文件数: {fundamental.get('files', 0):,}  行数: {fundamental.get('rows', 0):,}",
            f"- 报告期范围: {fundamental.get('min_date', '—')} ~ {fundamental.get('max_date', '—')}",
            "",
        ]

    cross = status.get("cross_asset", {})
    if cross:
        lines += ["### 跨资产数据"]
        for key, label in (("gold", "Gold"), ("fx_cnh", "USD/CNH"), ("btc", "BTC")):
            item = cross.get(key, {})
            exists = "yes" if item.get("exists") else "no"
            lines.append(
                f"- {label}: exists={exists} rows={item.get('rows', 0):,} "
                f"range={item.get('min_date') or '—'} ~ {item.get('max_date') or '—'} "
                f"lag={item.get('lag_days', '—')}d layout={item.get('layout') or '—'}"
            )
        lines.append("")

    index = status.get("index", {})
    if index:
        lines += [
            "### 指数数据",
            f"- 覆盖率: **{index.get('coverage_pct', 0.0):.1f}%** ({index.get('indices', 0):,} / {index.get('expected_indices', 0):,})",
            f"- 文件数: {index.get('files', 0):,}  行数: {index.get('rows', 0):,}",
            f"- 日期范围: {index.get('min_date', '—')} ~ {index.get('max_date', '—')}",
            "",
        ]

    northbound = status.get("northbound", {})
    if northbound:
        lines += [
            "### 北向资金",
            f"- exists: {'yes' if northbound.get('exists') else 'no'}",
            f"- 行数: {northbound.get('rows', 0):,}",
            f"- 日期范围: {northbound.get('min_date', '—')} ~ {northbound.get('max_date', '—')}  lag={northbound.get('lag_days', '—')}d",
            "",
        ]

    macro = status.get("macro", {})
    if macro:
        lines += ["### 宏观数据"]
        for key in ("gdp", "cpi", "ppi", "pmi"):
            item = macro.get(key, {})
            lines.append(
                f"- {key}: exists={'yes' if item.get('exists') else 'no'} rows={item.get('rows', 0):,} "
                f"range={item.get('min_date') or '—'} ~ {item.get('max_date') or '—'}"
            )
        lines.append("")

    schema = status.get("schema_contracts", {})
    if schema:
        failed = schema.get("failed_contracts") or []
        lines += [
            "### 数据契约",
            f"- status: **{schema.get('status', 'unknown')}**",
            f"- checked files: {schema.get('checked_files', 0):,}",
            f"- failed contracts: {', '.join(failed) if failed else '—'}",
            "",
        ]

    value_quality = status.get("value_quality", {})
    if value_quality:
        failed = value_quality.get("failed_checks") or []
        recovery_plan = value_quality.get("recovery_plan") or []
        lines += [
            "### 数据取值质量",
            f"- status: **{value_quality.get('status', 'unknown')}**",
            f"- checked rows: {value_quality.get('checked_rows', 0):,}",
            f"- failed checks: {', '.join(failed) if failed else '—'}",
            f"- recovery actions: {len(recovery_plan):,}",
            "",
        ]

    source_stability = status.get("source_stability", {})
    if source_stability:
        reasons = source_stability.get("reason_codes") or []
        lines += [
            "### 数据源稳定性",
            f"- status: **{source_stability.get('status', 'unknown')}**",
            f"- observed jobs: {source_stability.get('observed_jobs', 0):,}",
            f"- recent errors: {source_stability.get('recent_errors', 0):,}",
            f"- stale running: {source_stability.get('stale_running', 0):,}",
            f"- reasons: {', '.join(reasons) if reasons else '—'}",
            "",
        ]

    metadata = status.get("metadata_reconciliation", {})
    if metadata:
        reasons = metadata.get("reason_codes") or []
        manifest_metrics = (metadata.get("manifest") or {}).get("metrics") or {}
        sync_metrics = (metadata.get("sync_state") or {}).get("metrics") or {}
        lines += [
            "### 元数据交叉校验",
            f"- status: **{metadata.get('status', 'unknown')}**",
            f"- manifest checked: {manifest_metrics.get('checked_entries', 0):,}",
            f"- sync_state checked: {sync_metrics.get('checked_rows', 0):,}",
            f"- reasons: {', '.join(reasons) if reasons else '—'}",
            "",
        ]

    providers = status.get("provider_readiness", {})
    if providers:
        reasons = providers.get("reason_codes") or []
        recovery_plan = providers.get("recovery_plan") or []
        lines += [
            "### 数据源可用性",
            f"- status: **{providers.get('status', 'unknown')}**",
            f"- missing required: {', '.join(providers.get('missing_required') or []) or '—'}",
            f"- optional warnings: {', '.join(providers.get('warn_optional') or []) or '—'}",
            f"- recovery actions: {len(recovery_plan):,}",
            f"- reasons: {', '.join(reasons) if reasons else '—'}",
            "",
        ]

    provider_audit = status.get("provider_audit", {})
    if provider_audit:
        reasons = provider_audit.get("reason_codes") or []
        tushare = (provider_audit.get("providers") or {}).get("tushare") or {}
        lines += [
            "### 数据源请求审计",
            f"- status: **{provider_audit.get('status', 'unknown')}**",
            f"- observed: {'yes' if provider_audit.get('observed') else 'no'}",
            f"- tushare recent requests: {tushare.get('recent_requests', 0):,}",
            f"- reasons: {', '.join(reasons) if reasons else '—'}",
            "",
        ]

    cross_source = status.get("cross_source_coverage", {})
    if cross_source:
        reasons = cross_source.get("reason_codes") or []
        recovery_plan = cross_source.get("recovery_plan") or []
        lines += [
            "### 多源交叉验证覆盖",
            f"- status: **{cross_source.get('status', 'unknown')}**",
            f"- required missing: {', '.join(cross_source.get('required_missing') or []) or '—'}",
            f"- optional single-source: {', '.join(cross_source.get('optional_single_source') or []) or '—'}",
            f"- recovery actions: {len(recovery_plan):,}",
            f"- reasons: {', '.join(reasons) if reasons else '—'}",
        ]
        for item in recovery_plan[:3]:
            command = item.get("preflight_command") or item.get("command") or []
            command_text = " ".join(str(part) for part in command)
            lines.append(
                f"- {item.get('dataset', 'unknown')}: {item.get('reason_code') or item.get('status') or 'unknown'}"
                f" mode={item.get('mode', 'audit')} command={command_text or '—'}"
            )
        lines.append("")

    s = status.get("sentiment", {})
    silver = s.get("silver", {})
    gold = s.get("gold", {})
    s_ok = status_emoji(silver.get("dates", 0), 5)
    lines += [
        "### 情绪数据",
        f"- {s_ok} Silver 日期数: **{silver.get('dates', 0)}**  ({silver.get('rows', 0):,} 行)",
        f"  范围: {silver.get('min_date', '—')} ~ {silver.get('max_date', '—')}  lag={silver.get('lag_days', '—')}d",
        f"- Gold  日期数: **{gold.get('dates', 0)}**  ({gold.get('rows', 0):,} 行)",
        f"  范围: {gold.get('min_date', '—')} ~ {gold.get('max_date', '—')}  lag={gold.get('lag_days', '—')}d",
        "",
    ]

    ev = status.get("events", {})
    ev_ok = status_emoji(ev.get("event_count", 0), 5)
    lines += [
        "### 事件 / KG 传导",
        f"- {ev_ok} 事件数: **{ev.get('event_count', 0):,}**",
        f"- 传导记录: {ev.get('propagation_count', 0):,}",
        f"- 日期范围: {ev.get('min_date', '—')} ~ {ev.get('max_date', '—')}  lag={ev.get('lag_days', '—')}d",
        "",
    ]

    return lines
