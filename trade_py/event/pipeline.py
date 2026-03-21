"""Event-driven pipeline: Silver → events → KG propagation → DB.

Flow:
  1. Read Silver layer for target date
  2. Filter + aggregate into HistoricalEvent records
  3. Write to events table (trade.db)
  4. SectorGraph.propagate_event() → affected sectors × kg_score
  5. InstrumentsDB.get_symbols_by_sector() → affected stocks
  6. Write to event_propagations table
  7. signal_cache_upsert(event_kg_score, ...)

Backfill:
  run_event_backfill() computes actual 5d/20d returns for past events.
"""

from __future__ import annotations

import glob as _glob
import hashlib
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_event_id(event_date: str, event_type: str,
                   primary_sector: str, breadth: str = "sector") -> str:
    """SHA1-based 12-char unique ID for an event."""
    raw = f"{event_date}|{event_type}|{primary_sector}|{breadth}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _read_silver_for_date(data_root: Path, target_date: date) -> pd.DataFrame:
    """Read Silver parquet files for a specific date."""
    silver_root = data_root / "sentiment" / "silver"
    if not silver_root.exists():
        return pd.DataFrame()

    all_files = sorted(_glob.glob(str(silver_root / "**" / "*.parquet"), recursive=True))
    if not all_files:
        return pd.DataFrame()

    date_str = target_date.isoformat()
    frames = []
    for fp in all_files:
        try:
            df = pd.read_parquet(fp)
            wanted = [
                "date", "symbol", "event_type", "event_magnitude",
                "affected_sectors", "sentiment_score", "content_hash", "summary",
                "confidence", "market_impact_scope", "base_noise_score",
            ]
            for col in wanted:
                if col not in df.columns:
                    df[col] = None
            df = df[wanted]
            df = df[df["date"] == date_str]
            if not df.empty:
                frames.append(df)
        except Exception as exc:
            logger.debug("Skipping silver file %s: %s", fp, exc)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _normalise_sector_token(token: str) -> str:
    token = str(token).strip()
    if not token:
        return "SW_Unknown"
    raw = token[3:] if token.startswith("SW_") else token
    if not raw:
        return "SW_Unknown"

    try:
        from trade_py.analysis.knowledge_graph import SW
        from trade_py.data.market.index.tushare import _map_industry_to_sw

        sw_by_name = {sw.name.lower(): sw for sw in SW}
        sw_by_flat = {sw.name.replace("_", "").replace("-", "").lower(): sw for sw in SW}
        alias_to_sw = {
            "半导体": SW.Electronics,
            "消费电子": SW.Electronics,
            "科技": SW.Computer,
            "科技股": SW.Computer,
            "人工智能": SW.Computer,
            "ai": SW.Computer,
            "数据中心": SW.Computer,
            "算力租赁": SW.Computer,
            "网络安全": SW.Computer,
            "互联网": SW.Computer,
            "计算机与通信业": SW.Computer,
            "新能源": SW.ElectricalEquipment,
            "电气机械和器材制造业": SW.ElectricalEquipment,
            "金融": SW.NonBankFinancial,
            "债券市场": SW.NonBankFinancial,
            "期货": SW.NonBankFinancial,
            "私募信贷": SW.NonBankFinancial,
            "银行业": SW.Banking,
            "贵金属": SW.NonFerrousMetal,
            "黄金": SW.NonFerrousMetal,
            "电解铝": SW.NonFerrousMetal,
            "白酒": SW.FoodBeverage,
            "食品": SW.FoodBeverage,
            "食品制造业": SW.FoodBeverage,
            "乳制品": SW.FoodBeverage,
            "农产品": SW.Agriculture,
            "消费": SW.Commerce,
            "军工": SW.Defense,
            "国防": SW.Defense,
            "航运": SW.Transportation,
            "海运": SW.Transportation,
            "航空": SW.Transportation,
            "石油": SW.Petroleum,
            "原油": SW.Petroleum,
            "油气设备": SW.Petroleum,
            "制造业": SW.MechanicalEquipment,
            "法律服务": SW.SocialService,
            "电力": SW.Utilities,
            "股市": SW.NonBankFinancial,
        }

        lowered = raw.replace(" ", "").replace("-", "").replace("_", "").lower()
        if lowered in sw_by_name:
            return f"SW_{sw_by_name[lowered].name}"
        if lowered in sw_by_flat:
            return f"SW_{sw_by_flat[lowered].name}"
        if raw in alias_to_sw:
            return f"SW_{alias_to_sw[raw].name}"
        mapped_idx = _map_industry_to_sw(raw)
        if mapped_idx != 255:
            return f"SW_{SW(int(mapped_idx)).name}"
    except Exception:
        pass

    return "SW_Unknown"


def _pick_primary_sector(cell: object) -> str:
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return "SW_Unknown"
    parts = [p.strip() for p in str(cell).split(",") if p and str(p).strip()]
    if not parts:
        return "SW_Unknown"
    return _normalise_sector_token(parts[0])


def _normalise_event_type(raw_type: object, primary_sector: str,
                          sentiment_score: float, summary: object) -> str:
    raw = str(raw_type or "").strip().lower()
    if not raw:
        return "other"

    sector = str(primary_sector or "SW_Unknown")
    is_positive = float(sentiment_score or 0.0) >= 0
    summary_text = str(summary or "").lower()

    known = {
        "semiconductor_policy", "new_energy_policy",
        "real_estate_easing", "real_estate_tightening",
        "rate_cut", "rate_hike", "commodity_surge", "commodity_slump",
        "defense_spending_up", "macro_recovery", "macro_slowdown",
        "geopolitical_risk", "earnings_beat", "earnings_miss",
        "merger_acquisition", "regulatory_tightening",
        "supply_disruption", "other",
    }
    if raw in known:
        return raw

    if raw == "policy":
        if sector in {"SW_Electronics", "SW_Computer", "SW_Telecom"}:
            return "semiconductor_policy" if is_positive else "regulatory_tightening"
        if sector in {"SW_ElectricalEquipment", "SW_Auto", "SW_Environment", "SW_Chemical"}:
            return "new_energy_policy" if is_positive else "regulatory_tightening"
        if sector in {
            "SW_RealEstate", "SW_Construction", "SW_BuildingMaterial",
            "SW_Banking", "SW_HouseholdAppliance", "SW_Steel", "SW_Commerce",
        }:
            return "real_estate_easing" if is_positive else "real_estate_tightening"
        if sector == "SW_Defense":
            return "defense_spending_up" if is_positive else "regulatory_tightening"
        return "macro_recovery" if is_positive else "macro_slowdown"

    if raw in {"macro", "expansion"}:
        return "macro_recovery" if is_positive else "macro_slowdown"

    if raw == "earnings":
        return "earnings_beat" if is_positive else "earnings_miss"

    if raw == "regulation":
        return "macro_recovery" if is_positive else "regulatory_tightening"

    if raw == "acquisition":
        return "merger_acquisition"

    if raw == "product":
        if sector in {"SW_Electronics", "SW_Computer", "SW_Telecom"}:
            return "semiconductor_policy" if is_positive else "earnings_miss"
        if sector in {"SW_ElectricalEquipment", "SW_Auto"}:
            return "new_energy_policy" if is_positive else "earnings_miss"
        return "earnings_beat" if is_positive else "earnings_miss"

    if raw == "personnel":
        if "军工" in summary_text or sector == "SW_Defense":
            return "defense_spending_up" if is_positive else "macro_slowdown"
        return "macro_recovery" if is_positive else "macro_slowdown"

    return "other"


def _extract_events(silver: pd.DataFrame, min_magnitude: float = 0.4) -> list[dict]:
    """Extract and aggregate events from Silver data.

    Groups by (event_type, primary_sector), takes max-magnitude row.
    Returns list of event dicts ready for DB insertion.
    """
    from trade_py.db.event_db import EventType

    valid_event_types = {e.value for e in EventType}
    silver = silver.copy()
    silver["event_type"] = silver["event_type"].astype(str).str.strip()
    silver["event_magnitude"] = pd.to_numeric(silver["event_magnitude"], errors="coerce").fillna(0.0)
    silver["sentiment_score"] = pd.to_numeric(silver["sentiment_score"], errors="coerce").fillna(0.0)
    silver["confidence"] = pd.to_numeric(silver.get("confidence"), errors="coerce").fillna(0.5)
    silver["base_noise_score"] = pd.to_numeric(silver.get("base_noise_score"), errors="coerce").fillna(0.0)
    silver["_primary_sector"] = silver["affected_sectors"].apply(_pick_primary_sector)
    silver["_event_type_norm"] = silver.apply(
        lambda row: _normalise_event_type(
            row["event_type"],
            row["_primary_sector"],
            float(row["sentiment_score"]),
            row.get("summary"),
        ),
        axis=1,
    )

    if "market_impact_scope" in silver.columns:
        scope = silver["market_impact_scope"].astype(str).str.strip().str.lower()
    else:
        scope = pd.Series([""] * len(silver), index=silver.index)

    def _breadth_for_row(row: pd.Series) -> str:
        if row["symbol"] == "_MARKET_" or row["_scope"] == "market":
            return "market"
        if row["_scope"] in {"individual", "stock", "company"}:
            return "company"
        return "sector"

    silver["_scope"] = scope
    silver["_breadth"] = silver.apply(_breadth_for_row, axis=1)

    # Filter: magnitude >= threshold, known event type
    filtered = silver[
        (silver["event_magnitude"] >= min_magnitude) &
        (silver["_event_type_norm"].isin(valid_event_types)) &
        (silver["_event_type_norm"] != "other") &
        ((silver["base_noise_score"] <= 0.75) | (silver["confidence"] >= 0.6))
    ]
    if filtered.empty:
        return []

    events: list[dict] = []
    date_str: str = str(filtered["date"].iloc[0])

    for (ev_type, primary_sector, _breadth), grp in filtered.groupby(
        ["_event_type_norm", "_primary_sector", "_breadth"]
    ):
        magnitude = float(grp["event_magnitude"].max())
        sentiment_score = float(grp["sentiment_score"].mean())
        confidence = float(grp["confidence"].mean())
        news_volume = int(grp["content_hash"].nunique()) if "content_hash" in grp.columns else len(grp)
        summary_row = grp.sort_values(["event_magnitude", "confidence"], ascending=False).iloc[0]
        summary = str(summary_row.get("summary") or "").strip()
        hashes = sorted({str(v).strip() for v in grp.get("content_hash", []) if str(v).strip()})
        source_hash = hashlib.sha1("|".join(hashes).encode()).hexdigest()[:16] if hashes else None
        event_id = _make_event_id(date_str, str(ev_type), primary_sector, str(_breadth))

        events.append({
            "event_id":       event_id,
            "event_date":     date_str,
            "event_type":     str(ev_type),
            "magnitude":      magnitude,
            "entity_id":      primary_sector,
            "breadth":        str(_breadth),
            "confidence":     confidence,
            "sentiment_score": sentiment_score,
            "news_volume":    news_volume,
            "summary":        summary[:500] if summary else "",
            "source_hash":    source_hash,
        })

    return events


def _run_kg_propagation(events: list[dict], data_root: str) -> list[dict]:
    """Run KG propagation for all events. Returns event_propagations rows."""
    from trade_py.analysis.knowledge_graph import SectorGraph
    from trade_py.db.instruments_db import InstrumentsDB

    graph = SectorGraph.from_snapshot_or_db(data_root, merge_defaults=True, prefer_snapshot=True)
    inst_db = InstrumentsDB(data_root)
    available_events = set(graph.available_events())

    prop_rows: list[dict] = []
    for ev in events:
        ev_type = ev["event_type"]
        if ev_type not in available_events:
            logger.debug("No KG mapping for event_type=%s, skipping propagation", ev_type)
            continue
        try:
            propagations = graph.propagate_event(ev_type, max_hop=2)
        except ValueError as exc:
            logger.warning("KG propagation failed for %s: %s", ev_type, exc)
            continue

        for p in propagations:
            symbols = inst_db.get_symbols_by_sector(p.sector)
            for sym in symbols:
                prop_rows.append({
                    "event_id":     ev["event_id"],
                    "event_date":   ev["event_date"],
                    "symbol":       sym,
                    "sector":       f"SW_{p.sector.name}",
                    "kg_score":     p.score,
                    "hop":          p.hop,
                    "typical_days": p.typical_days,
                })
    return prop_rows


def _compute_excess_returns(data_root: str, event_date: str,
                            window: int, symbols: list[str]) -> dict[str, float]:
    """Compute simple returns over `window` trading days starting after event_date.

    Uses DuckDB to read kline parquet. Returns {symbol: return_pct}.
    """
    if not symbols:
        return {}
    try:
        import duckdb
        from trade_py.utils.data_inspector import _resolve_kline_glob

        kline_glob = _resolve_kline_glob(data_root)
        con = duckdb.connect()
        # Get close prices on event_date and window trading days later
        df = con.execute(f"""
            SELECT symbol, date, close
            FROM read_parquet('{kline_glob}', union_by_name=true)
            WHERE symbol IN ({', '.join(repr(s) for s in symbols)})
              AND date >= '{event_date}'
            ORDER BY symbol, date
        """).df()
        con.close()
    except Exception as exc:
        logger.warning("Cannot compute returns (DuckDB error): %s", exc)
        return {}

    if df.empty:
        return {}

    returns: dict[str, float] = {}
    for sym, grp in df.groupby("symbol"):
        grp = grp.sort_values("date").reset_index(drop=True)
        if len(grp) < window + 1:
            continue
        price_start = float(grp.iloc[0]["close"])
        price_end = float(grp.iloc[window]["close"])
        if price_start > 0:
            returns[str(sym)] = round((price_end / price_start - 1) * 100, 4)
    return returns


# ── Public API ────────────────────────────────────────────────────────────────

def run_event_pipeline(data_root: str, date_str: Optional[str] = None) -> str:
    """Extract events from Silver, run KG propagation, write to trade.db.

    Args:
        data_root: Project data root directory.
        date_str:  Target date (YYYY-MM-DD). Defaults to today.

    Returns:
        Summary string for display/logging.
    """
    from trade_py.db.settings_db import SettingsDB

    target_date = date.fromisoformat(date_str) if date_str else date.today()
    db = SettingsDB(data_root)
    min_magnitude = float(db.get("event.min_magnitude", 0.4))

    # Step 1: Read Silver layer
    silver = _read_silver_for_date(Path(data_root), target_date)
    if silver.empty:
        return f"Silver 层 {target_date} 无数据，跳过事件管道"

    # Step 2: Extract events
    events = _extract_events(silver, min_magnitude=min_magnitude)
    if not events:
        return f"Silver 层 {target_date} 无符合条件的事件 (min_magnitude={min_magnitude})"

    # Step 3: Write events table
    for ev in events:
        db.event_upsert(ev)

    # Step 4+5: KG propagation
    prop_rows = _run_kg_propagation(events, data_root)

    # Step 6: Write event_propagations
    db.event_propagation_insert_batch(prop_rows)

    # Step 7: Write signal_cache (per symbol, keep strongest |kg_score|)
    per_symbol: dict[str, dict] = {}
    for r in prop_rows:
        sym = r["symbol"]
        if sym not in per_symbol or abs(r["kg_score"]) > abs(per_symbol[sym]["kg_score"]):
            per_symbol[sym] = r

    # Find event_type for each propagation row (look up from events by event_id)
    event_by_id = {ev["event_id"]: ev for ev in events}
    date_iso = target_date.isoformat()
    for sym, r in per_symbol.items():
        ev = event_by_id.get(r["event_id"], {})
        db.signal_cache_upsert(
            date_iso, sym,
            event_kg_score=r["kg_score"],
            event_affected=1,
            event_type=ev.get("event_type", ""),
            event_typical_days=r["typical_days"],
        )

    return (
        f"检测到 {len(events)} 个事件，"
        f"KG传导 {len(prop_rows)} 条记录，"
        f"影响 {len(per_symbol)} 只股票"
    )


def run_event_pipeline_for(event_dict: dict, data_root: str) -> str:
    """Run KG propagation for a single manually-created event dict.

    Used by CLI `trade model event add --trigger`.
    """
    from trade_py.db.settings_db import SettingsDB

    db = SettingsDB(data_root)
    db.event_upsert(event_dict)

    prop_rows = _run_kg_propagation([event_dict], data_root)
    db.event_propagation_insert_batch(prop_rows)

    per_symbol: dict[str, dict] = {}
    for r in prop_rows:
        sym = r["symbol"]
        if sym not in per_symbol or abs(r["kg_score"]) > abs(per_symbol[sym]["kg_score"]):
            per_symbol[sym] = r

    for sym, r in per_symbol.items():
        db.signal_cache_upsert(
            event_dict["event_date"], sym,
            event_kg_score=r["kg_score"],
            event_affected=1,
            event_type=event_dict.get("event_type", ""),
            event_typical_days=r["typical_days"],
        )

    return f"事件 {event_dict['event_id']} 传导完成，影响 {len(per_symbol)} 只股票"


def run_event_pipeline_batch(data_root: str, event_dicts: list[dict]) -> tuple[int, int, int]:
    """Run KG propagation for a batch of event dicts and write to trade.db.

    Events are upserted into the events table, then propagated through the KG.
    signal_cache is updated with the strongest kg_score per symbol.

    Args:
        data_root:   Project data root directory.
        event_dicts: List of event dicts (same structure as event_upsert expects).

    Returns:
        (n_events, n_prop_rows, n_symbols)
    """
    from trade_py.db.settings_db import SettingsDB

    if not event_dicts:
        return 0, 0, 0

    db = SettingsDB(data_root)
    for ev in event_dicts:
        db.event_upsert(ev)

    prop_rows = _run_kg_propagation(event_dicts, data_root)
    db.event_propagation_insert_batch(prop_rows)

    per_symbol: dict[str, dict] = {}
    for r in prop_rows:
        sym = r["symbol"]
        if sym not in per_symbol or abs(r["kg_score"]) > abs(per_symbol[sym]["kg_score"]):
            per_symbol[sym] = r

    event_by_id = {ev["event_id"]: ev for ev in event_dicts}
    for sym, r in per_symbol.items():
        ev = event_by_id.get(r["event_id"], {})
        db.signal_cache_upsert(
            r["event_date"], sym,
            event_kg_score=r["kg_score"],
            event_affected=1,
            event_type=ev.get("event_type", ""),
            event_typical_days=r["typical_days"],
        )

    return len(event_dicts), len(prop_rows), len(per_symbol)


def run_event_backfill_range(data_root: str, start: str, end: str) -> tuple[int, int]:
    """Fill actual_return_5d / actual_return_20d for all event propagation rows
    in [start, end] date range (inclusive).

    Args:
        data_root: Project data root directory.
        start:     Start date ISO string (YYYY-MM-DD).
        end:       End date ISO string (YYYY-MM-DD).

    Returns:
        (n5, n20): total rows updated for 5d and 20d windows.
    """
    from trade_py.db.settings_db import SettingsDB

    db = SettingsDB(data_root)
    today = date.today()

    # Get distinct event dates in range that have NULL returns
    rows = db._conn.execute(
        """
        SELECT DISTINCT me.event_date
        FROM event_propagations ep
        JOIN market_events me ON me.event_id = ep.event_id
        WHERE me.event_date >= ? AND me.event_date <= ?
          AND (ep.actual_return_5d IS NULL OR ep.actual_return_20d IS NULL)
        ORDER BY me.event_date
        """,
        (start, end),
    ).fetchall()
    event_dates = [r[0] for r in rows]

    total_5, total_20 = 0, 0
    for event_date_str in event_dates:
        ev_date = date.fromisoformat(event_date_str)

        # Only fill 5d returns if 5+ trading days have elapsed (~7 calendar days)
        if (today - ev_date).days >= 7:
            sym_rows = db._conn.execute(
                """
                SELECT DISTINCT ep.symbol
                FROM event_propagations ep
                JOIN market_events me ON me.event_id = ep.event_id
                WHERE me.event_date = ? AND ep.actual_return_5d IS NULL
                """,
                (event_date_str,),
            ).fetchall()
            symbols = [r[0] for r in sym_rows]
            returns = _compute_excess_returns(data_root, event_date_str, 5, symbols)
            n5 = db.event_propagations_fill_returns(event_date_str, returns, window=5)
            total_5 += n5

        # Only fill 20d returns if 20+ trading days have elapsed (~28 calendar days)
        if (today - ev_date).days >= 28:
            sym_rows = db._conn.execute(
                """
                SELECT DISTINCT ep.symbol
                FROM event_propagations ep
                JOIN market_events me ON me.event_id = ep.event_id
                WHERE me.event_date = ? AND ep.actual_return_20d IS NULL
                """,
                (event_date_str,),
            ).fetchall()
            symbols = [r[0] for r in sym_rows]
            returns = _compute_excess_returns(data_root, event_date_str, 20, symbols)
            n20 = db.event_propagations_fill_returns(event_date_str, returns, window=20)
            total_20 += n20

    logger.info(
        "run_event_backfill_range [%s, %s]: %d dates, 5d=%d rows, 20d=%d rows",
        start, end, len(event_dates), total_5, total_20,
    )
    return total_5, total_20


def run_event_backfill(data_root: str) -> tuple[int, int]:
    """Fill actual_return_5d / actual_return_20d for past event propagation rows.

    Returns:
        (n5, n20): number of rows updated for 5d and 20d windows.
    """
    from trade_py.db.settings_db import SettingsDB

    today = date.today()
    db = SettingsDB(data_root)

    # 5-day window: event_date = today - 7 calendar days
    date_5d = (today - timedelta(days=7)).isoformat()
    rows_5d = db._conn.execute(
        """
        SELECT DISTINCT ep.symbol
        FROM event_propagations ep
        JOIN market_events me ON me.event_id = ep.event_id
        WHERE me.event_date = ? AND ep.actual_return_5d IS NULL
        """,
        (date_5d,),
    ).fetchall()
    symbols_5d = [r[0] for r in rows_5d]
    returns_5d = _compute_excess_returns(data_root, date_5d, 5, symbols_5d)
    n5 = db.event_propagations_fill_returns(date_5d, returns_5d, window=5)

    # 20-day window: event_date = today - 28 calendar days
    date_20d = (today - timedelta(days=28)).isoformat()
    rows_20d = db._conn.execute(
        """
        SELECT DISTINCT ep.symbol
        FROM event_propagations ep
        JOIN market_events me ON me.event_id = ep.event_id
        WHERE me.event_date = ? AND ep.actual_return_20d IS NULL
        """,
        (date_20d,),
    ).fetchall()
    symbols_20d = [r[0] for r in rows_20d]
    returns_20d = _compute_excess_returns(data_root, date_20d, 20, symbols_20d)
    n20 = db.event_propagations_fill_returns(date_20d, returns_20d, window=20)

    return n5, n20
