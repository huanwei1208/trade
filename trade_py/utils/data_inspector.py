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
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from trade_py.data.paths import KLINE_DIR, KLINE_MANIFEST

logger = logging.getLogger(__name__)


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
            }
        else:
            result["silver"] = {"rows": 0, "dates": 0}

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
            }
        else:
            result["gold"] = {"rows": 0, "dates": 0}
    except Exception as exc:
        logger.debug("sentiment_stats error: %s", exc)
        result["error"] = str(exc)

    return result


def events_stats(data_root: str | Path = "data") -> dict[str, Any]:
    """Return events / event_propagations table statistics."""
    try:
        from trade_py.db.settings_db import SettingsDB
        db = SettingsDB(data_root)
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
        }
    except Exception as exc:
        logger.debug("events_stats error: %s", exc)
        return {"event_count": 0, "error": str(exc)}


# ── Aggregate status ──────────────────────────────────────────────────────────

def get_data_status(data_root: str | Path = "data", sample_limit: int = 10) -> dict[str, Any]:
    """Return a consolidated status dict across all data layers."""
    return {
        "kline":       kline_stats(data_root),
        "kline_coverage": kline_coverage_stats(data_root, sample_limit=sample_limit),
        "kline_freshness": kline_freshness_stats(data_root, sample_limit=sample_limit),
        "instruments": db_instrument_stats(data_root),
        "sentiment":   sentiment_stats(data_root),
        "events":      events_stats(data_root),
        "as_of":       date.today().isoformat(),
    }


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

    s = status.get("sentiment", {})
    silver = s.get("silver", {})
    gold = s.get("gold", {})
    s_ok = status_emoji(silver.get("dates", 0), 5)
    lines += [
        "### 情绪数据",
        f"- {s_ok} Silver 日期数: **{silver.get('dates', 0)}**  ({silver.get('rows', 0):,} 行)",
        f"  范围: {silver.get('min_date', '—')} ~ {silver.get('max_date', '—')}",
        f"- Gold  日期数: **{gold.get('dates', 0)}**  ({gold.get('rows', 0):,} 行)",
        f"  范围: {gold.get('min_date', '—')} ~ {gold.get('max_date', '—')}",
        "",
    ]

    ev = status.get("events", {})
    ev_ok = status_emoji(ev.get("event_count", 0), 5)
    lines += [
        "### 事件 / KG 传导",
        f"- {ev_ok} 事件数: **{ev.get('event_count', 0):,}**",
        f"- 传导记录: {ev.get('propagation_count', 0):,}",
        f"- 日期范围: {ev.get('min_date', '—')} ~ {ev.get('max_date', '—')}",
        "",
    ]

    return lines
