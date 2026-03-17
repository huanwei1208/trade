from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from trade_py.db.trade_db import TradeDB

logger = logging.getLogger(__name__)

FEATURE_COLS = [
    "hop",
    "kg_score",
    "magnitude",
    "confidence",
    "event_type_code",
    "breadth_code",
    "news_volume",
    "decay_factor",
    "max_hop",
    "industry",
    "market",
    "window_score",
    "net_sentiment",
    "bf_net_sentiment",
    "bf_event_strength",
    "bf_policy_intensity",
    "bf_entity_density",
    "bf_novelty",
    "bf_volume_burst",
    "bf_cross_source_confirmation",
    "bf_noise_penalty",
    "tech_rsi_14",
    "tech_macd_hist",
    "tech_macd_cross",
    "tech_kdj_k",
    "tech_kdj_d",
    "tech_kdj_j",
    "tech_kdj_cross",
    "tech_ma_gap_5_20",
    "tech_price_vs_ma20",
    "tech_volatility_20d",
    "tech_volume_ratio_5_20",
]

FACTOR_DEFINITIONS = {
    "hop": {"factor_type": "event", "description": "Event propagation hop count."},
    "kg_score": {"factor_type": "graph", "description": "KG propagation score for the event-symbol pair."},
    "magnitude": {"factor_type": "event", "description": "Event magnitude inferred from article cluster."},
    "confidence": {"factor_type": "event", "description": "Event extraction confidence."},
    "event_type_code": {"factor_type": "event", "description": "Encoded event type."},
    "breadth_code": {"factor_type": "event", "description": "Encoded event breadth."},
    "news_volume": {"factor_type": "sentiment", "description": "News article volume backing the event."},
    "decay_factor": {"factor_type": "graph", "description": "Template decay factor used during propagation."},
    "max_hop": {"factor_type": "graph", "description": "Maximum hop allowed for the event template."},
    "industry": {"factor_type": "instrument", "description": "Instrument industry code."},
    "market": {"factor_type": "instrument", "description": "Instrument market code."},
    "window_score": {"factor_type": "window", "description": "Window quality score from the timing scorer."},
    "net_sentiment": {"factor_type": "sentiment", "description": "Canonical net sentiment score."},
    "bf_net_sentiment": {"factor_type": "sentiment", "description": "Base-factor net sentiment score."},
    "bf_event_strength": {"factor_type": "sentiment", "description": "Base-factor event strength."},
    "bf_policy_intensity": {"factor_type": "sentiment", "description": "Base-factor policy intensity."},
    "bf_entity_density": {"factor_type": "sentiment", "description": "Base-factor entity density."},
    "bf_novelty": {"factor_type": "sentiment", "description": "Base-factor novelty score."},
    "bf_volume_burst": {"factor_type": "sentiment", "description": "Base-factor article volume burst."},
    "bf_cross_source_confirmation": {"factor_type": "sentiment", "description": "Base-factor cross-source confirmation."},
    "bf_noise_penalty": {"factor_type": "sentiment", "description": "Base-factor noise penalty."},
    "tech_rsi_14": {"factor_type": "technical", "description": "14-day RSI."},
    "tech_macd_hist": {"factor_type": "technical", "description": "MACD histogram."},
    "tech_macd_cross": {"factor_type": "technical", "description": "MACD cross direction."},
    "tech_kdj_k": {"factor_type": "technical", "description": "KDJ K line."},
    "tech_kdj_d": {"factor_type": "technical", "description": "KDJ D line."},
    "tech_kdj_j": {"factor_type": "technical", "description": "KDJ J line."},
    "tech_kdj_cross": {"factor_type": "technical", "description": "KDJ cross direction."},
    "tech_ma_gap_5_20": {"factor_type": "technical", "description": "5d versus 20d moving-average gap."},
    "tech_price_vs_ma20": {"factor_type": "technical", "description": "Spot price relative to 20d moving average."},
    "tech_volatility_20d": {"factor_type": "technical", "description": "20-day realized volatility."},
    "tech_volume_ratio_5_20": {"factor_type": "technical", "description": "5d volume divided by 20d volume."},
}

TECHNICAL_DEFAULTS = {
    "tech_rsi_14": 50.0,
    "tech_macd_hist": 0.0,
    "tech_macd_cross": 0.0,
    "tech_kdj_k": 50.0,
    "tech_kdj_d": 50.0,
    "tech_kdj_j": 50.0,
    "tech_kdj_cross": 0.0,
    "tech_ma_gap_5_20": 0.0,
    "tech_price_vs_ma20": 0.0,
    "tech_volatility_20d": 0.0,
    "tech_volume_ratio_5_20": 1.0,
}

FACTOR_TYPE_MAP = {
    name: spec.get("factor_type", "model_feature")
    for name, spec in FACTOR_DEFINITIONS.items()
}


def factor_registry_rows() -> list[dict]:
    rows: list[dict] = []
    for factor_name in FEATURE_COLS:
        spec = FACTOR_DEFINITIONS.get(factor_name, {})
        rows.append(
            {
                "factor_name": factor_name,
                "factor_type": spec.get("factor_type", "model_feature"),
                "factor_layer": "feature_store",
                "description": spec.get("description", factor_name),
                "source": "propagation_runtime",
            }
        )
    return rows


def _events_maps_path(data_root: str) -> Path:
    return Path(data_root) / "events" / "feature_maps.json"


def _models_maps_path(data_root: str) -> Path:
    return Path(data_root) / "models" / "propagation" / "feature_maps.json"


def _stable_code_map(values: pd.Series) -> dict[str, int]:
    items = sorted({str(v).strip() for v in values.fillna("").tolist() if str(v).strip()})
    return {name: idx + 1 for idx, name in enumerate(items)}


def _load_gold_factors(data_root: str, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame:
    gold_glob = str(Path(data_root) / "sentiment" / "gold" / "**" / "*.parquet")
    try:
        import duckdb

        con = duckdb.connect()
        clauses = []
        if start_date:
            clauses.append(f"date >= '{start_date}'")
        if end_date:
            clauses.append(f"date <= '{end_date}'")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        df = con.execute(
            f"""
            SELECT
                date, symbol,
                COALESCE(bf_net_sentiment, 0.0) AS bf_net_sentiment,
                COALESCE(bf_event_strength, 0.0) AS bf_event_strength,
                COALESCE(bf_policy_intensity, 0.0) AS bf_policy_intensity,
                COALESCE(bf_entity_density, 0.0) AS bf_entity_density,
                COALESCE(bf_novelty, 1.0) AS bf_novelty,
                COALESCE(bf_volume_burst, 0.0) AS bf_volume_burst,
                COALESCE(bf_cross_source_confirmation, 0.0) AS bf_cross_source_confirmation,
                COALESCE(bf_noise_penalty, 1.0) AS bf_noise_penalty
            FROM read_parquet('{gold_glob}', union_by_name=true)
            {where_sql}
            """
        ).df()
        con.close()
        return df
    except Exception as exc:
        logger.debug("failed to load gold factors: %s", exc)
        return pd.DataFrame()


def _load_kline_history(data_root: str, start_date: str, end_date: str) -> pd.DataFrame:
    try:
        import duckdb
        from trade_py.utils.data_inspector import _resolve_kline_dir

        kline_glob = str(_resolve_kline_dir(data_root) / "**" / "*.parquet")
        con = duckdb.connect()
        df = con.execute(
            f"""
            SELECT symbol, date, open, high, low, close, volume
            FROM read_parquet('{kline_glob}', union_by_name=true)
            WHERE date >= '{start_date}' AND date <= '{end_date}'
            ORDER BY symbol, date
            """
        ).df()
        con.close()
        return df
    except Exception as exc:
        logger.debug("failed to load kline history: %s", exc)
        return pd.DataFrame()


def _compute_technical_factors(kline_df: pd.DataFrame) -> pd.DataFrame:
    if kline_df.empty:
        return pd.DataFrame(columns=["date", "symbol", *TECHNICAL_DEFAULTS.keys()])
    work = kline_df.copy()
    work["date"] = work["date"].astype(str).str.slice(0, 10)
    for col in ("open", "high", "low", "close", "volume"):
        work[col] = pd.to_numeric(work.get(col), errors="coerce")
    work = work.dropna(subset=["symbol", "date", "close"]).sort_values(["symbol", "date"]).reset_index(drop=True)
    if work.empty:
        return pd.DataFrame(columns=["date", "symbol", *TECHNICAL_DEFAULTS.keys()])

    def _per_symbol(group: pd.DataFrame) -> pd.DataFrame:
        g = group.sort_values("date").copy()
        close = g["close"]
        high = g["high"].fillna(close)
        low = g["low"].fillna(close)
        volume = g["volume"].fillna(0.0)

        ma5 = close.rolling(5, min_periods=5).mean()
        ma20 = close.rolling(20, min_periods=20).mean()
        returns = close.pct_change()
        g["tech_ma_gap_5_20"] = (ma5 / ma20.replace(0, np.nan) - 1.0).replace([np.inf, -np.inf], np.nan)
        g["tech_price_vs_ma20"] = (close / ma20.replace(0, np.nan) - 1.0).replace([np.inf, -np.inf], np.nan)
        g["tech_volatility_20d"] = returns.rolling(20, min_periods=20).std().fillna(0.0)

        vol5 = volume.rolling(5, min_periods=5).mean()
        vol20 = volume.rolling(20, min_periods=20).mean()
        g["tech_volume_ratio_5_20"] = (vol5 / vol20.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)

        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta.clip(upper=0.0))
        avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        g["tech_rsi_14"] = (100.0 - 100.0 / (1.0 + rs)).replace([np.inf, -np.inf], np.nan)

        ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
        ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False, min_periods=9).mean()
        hist = dif - dea
        g["tech_macd_hist"] = hist.fillna(0.0)
        g["tech_macd_cross"] = np.where(
            (dif > dea) & (dif.shift(1) <= dea.shift(1)),
            1.0,
            np.where((dif < dea) & (dif.shift(1) >= dea.shift(1)), -1.0, 0.0),
        )

        low9 = low.rolling(9, min_periods=9).min()
        high9 = high.rolling(9, min_periods=9).max()
        rsv = ((close - low9) / (high9 - low9).replace(0, np.nan) * 100.0).clip(0.0, 100.0)
        k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
        d = k.ewm(alpha=1 / 3, adjust=False).mean()
        j = 3.0 * k - 2.0 * d
        g["tech_kdj_k"] = k
        g["tech_kdj_d"] = d
        g["tech_kdj_j"] = j
        g["tech_kdj_cross"] = np.where(
            (k > d) & (k.shift(1) <= d.shift(1)),
            1.0,
            np.where((k < d) & (k.shift(1) >= d.shift(1)), -1.0, 0.0),
        )
        return g[["date", "symbol", *TECHNICAL_DEFAULTS.keys()]]

    factors = work.groupby("symbol", group_keys=False).apply(_per_symbol)
    for col, default in TECHNICAL_DEFAULTS.items():
        factors[col] = pd.to_numeric(factors.get(col), errors="coerce").fillna(default)
    return factors.reset_index(drop=True)


def _merge_technical_factors(data_root: str, df: pd.DataFrame, date_col: str) -> pd.DataFrame:
    if df.empty or date_col not in df.columns:
        return df
    start = pd.to_datetime(df[date_col], errors="coerce").min()
    end = pd.to_datetime(df[date_col], errors="coerce").max()
    if pd.isna(start) or pd.isna(end):
        return df
    warm_start = (start - pd.Timedelta(days=120)).date().isoformat()
    end_iso = end.date().isoformat()
    tech_df = _compute_technical_factors(_load_kline_history(data_root, warm_start, end_iso))
    if tech_df.empty:
        for col, default in TECHNICAL_DEFAULTS.items():
            df[col] = default
        return df
    merged = df.merge(
        tech_df,
        left_on=[date_col, "symbol"],
        right_on=["date", "symbol"],
        how="left",
        suffixes=("", "_tech"),
    )
    if date_col != "date":
        merged = merged.drop(columns=["date"], errors="ignore")
    for col, default in TECHNICAL_DEFAULTS.items():
        merged[col] = pd.to_numeric(merged.get(col), errors="coerce").fillna(default)
    return merged


def _encode_with_maps(df: pd.DataFrame, maps: dict[str, dict[str, int]]) -> pd.DataFrame:
    out = df.copy()
    event_map = maps.get("event_type", {})
    breadth_map = maps.get("breadth", {})
    out["event_type_code"] = (
        out.get("event_type", pd.Series([], dtype=object))
        .fillna("")
        .astype(str)
        .map(event_map)
        .fillna(0)
        .astype(int)
    )
    out["breadth_code"] = (
        out.get("breadth", pd.Series([], dtype=object))
        .fillna("")
        .astype(str)
        .map(breadth_map)
        .fillna(0)
        .astype(int)
    )
    return out


def save_feature_maps(data_root: str, maps: dict[str, dict[str, int]], *, model_copy: bool = False) -> Path:
    path = _models_maps_path(data_root) if model_copy else _events_maps_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(maps, ensure_ascii=False, indent=2))
    return path


def load_feature_maps(data_root: str) -> dict[str, dict[str, int]]:
    for path in (_models_maps_path(data_root), _events_maps_path(data_root)):
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception as exc:
                logger.warning("failed to load feature maps from %s: %s", path, exc)
    return {"event_type": {}, "breadth": {}}


def build_training_feature_frame(data_root: str) -> tuple[pd.DataFrame, dict[str, dict[str, int]]]:
    db = TradeDB(data_root)
    rows = db._conn.execute(
        """
        SELECT
            ep.event_id, ep.symbol, ep.hop, ep.kg_score, ep.typical_days,
            ep.rel_path, ep.actual_return_5d, ep.actual_return_20d,
            me.event_type, me.magnitude, me.confidence, me.breadth,
            me.news_volume, me.event_date,
            COALESCE(et.decay_factor, 0.6) AS decay_factor,
            COALESCE(et.max_hop, 2) AS max_hop,
            i.industry, i.market,
            s.window_score, s.net_sentiment
        FROM event_propagations ep
        JOIN market_events me ON me.event_id = ep.event_id
        JOIN instruments i ON i.symbol = ep.symbol
        LEFT JOIN event_templates et ON et.event_type = me.event_type
        LEFT JOIN signals s ON s.symbol = ep.symbol AND s.date = me.event_date
        """
    ).fetchall()
    if not rows:
        return pd.DataFrame(), {"event_type": {}, "breadth": {}}

    df = pd.DataFrame([dict(r) for r in rows])
    gold_df = _load_gold_factors(data_root)
    if not gold_df.empty:
        df = df.merge(
            gold_df,
            left_on=["event_date", "symbol"],
            right_on=["date", "symbol"],
            how="left",
            suffixes=("", "_gold"),
        ).drop(columns=["date"], errors="ignore")
    df = _merge_technical_factors(data_root, df, "event_date")
    maps = {
        "event_type": _stable_code_map(df["event_type"]),
        "breadth": _stable_code_map(df["breadth"]),
    }
    df = _encode_with_maps(df, maps)
    df["hop"] = df["hop"].fillna(0).astype(int)
    df["kg_score"] = pd.to_numeric(df["kg_score"], errors="coerce").fillna(0.0)
    df["magnitude"] = pd.to_numeric(df["magnitude"], errors="coerce").fillna(0.0)
    df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce").fillna(1.0)
    df["news_volume"] = pd.to_numeric(df["news_volume"], errors="coerce").fillna(0.0)
    df["decay_factor"] = pd.to_numeric(df["decay_factor"], errors="coerce").fillna(0.6)
    df["max_hop"] = pd.to_numeric(df["max_hop"], errors="coerce").fillna(2).astype(int)
    df["industry"] = pd.to_numeric(df["industry"], errors="coerce").fillna(255).astype(int)
    df["market"] = pd.to_numeric(df["market"], errors="coerce").fillna(0).astype(int)
    df["window_score"] = pd.to_numeric(df["window_score"], errors="coerce").fillna(50.0)
    df["net_sentiment"] = pd.to_numeric(df["net_sentiment"], errors="coerce").fillna(0.0)
    for col, default in {
        "bf_net_sentiment": 0.0,
        "bf_event_strength": 0.0,
        "bf_policy_intensity": 0.0,
        "bf_entity_density": 0.0,
        "bf_novelty": 1.0,
        "bf_volume_burst": 0.0,
        "bf_cross_source_confirmation": 0.0,
        "bf_noise_penalty": 1.0,
    }.items():
        df[col] = pd.to_numeric(df.get(col), errors="coerce").fillna(default)
    for col, default in TECHNICAL_DEFAULTS.items():
        df[col] = pd.to_numeric(df.get(col), errors="coerce").fillna(default)
    return df, maps


def materialize_inference_factors(data_root: str, date_str: str | None = None) -> tuple[str, int, list[str]]:
    db = TradeDB(data_root)
    target_date = date_str or db._conn.execute("SELECT MAX(date) FROM signals").fetchone()[0]
    if not target_date:
        return "", 0, []

    rows = db._conn.execute(
        """
        WITH ranked_events AS (
            SELECT
                ep.event_date,
                ep.symbol,
                ep.hop,
                ep.kg_score,
                me.event_type,
                me.magnitude,
                me.confidence,
                me.breadth,
                me.news_volume,
                COALESCE(et.decay_factor, 0.6) AS decay_factor,
                COALESCE(et.max_hop, 2) AS max_hop,
                ROW_NUMBER() OVER (
                    PARTITION BY ep.event_date, ep.symbol
                    ORDER BY ABS(ep.kg_score) DESC, ep.hop ASC, ep.event_id
                ) AS rn
            FROM event_propagations ep
            JOIN market_events me ON me.event_id = ep.event_id
            LEFT JOIN event_templates et ON et.event_type = me.event_type
            WHERE ep.event_date = ?
        )
        SELECT
            s.date,
            s.symbol,
            COALESCE(re.hop, 0) AS hop,
            COALESCE(re.kg_score, s.event_kg_score, 0.0) AS kg_score,
            COALESCE(re.magnitude, 0.0) AS magnitude,
            COALESCE(re.confidence, 1.0) AS confidence,
            COALESCE(re.event_type, s.event_type, '') AS event_type,
            COALESCE(re.breadth, '') AS breadth,
            COALESCE(re.news_volume, 0.0) AS news_volume,
            COALESCE(re.decay_factor, 0.6) AS decay_factor,
            COALESCE(re.max_hop, 2) AS max_hop,
            COALESCE(i.industry, 255) AS industry,
            COALESCE(i.market, 0) AS market,
            COALESCE(s.window_score, 50.0) AS window_score,
            COALESCE(s.net_sentiment, 0.0) AS net_sentiment
        FROM signals s
        LEFT JOIN ranked_events re
            ON re.event_date = s.date AND re.symbol = s.symbol AND re.rn = 1
        LEFT JOIN instruments i ON i.symbol = s.symbol
        WHERE s.date = ?
        """,
        (target_date, target_date),
    ).fetchall()
    if not rows:
        return target_date, 0, []

    df = pd.DataFrame([dict(r) for r in rows])
    gold_df = _load_gold_factors(data_root, start_date=target_date, end_date=target_date)
    if not gold_df.empty:
        df = df.merge(
            gold_df,
            left_on=["date", "symbol"],
            right_on=["date", "symbol"],
            how="left",
        )
    df = _merge_technical_factors(data_root, df, "date")
    maps = load_feature_maps(data_root)
    df = _encode_with_maps(df, maps)
    for col, default in {
        "bf_net_sentiment": 0.0,
        "bf_event_strength": 0.0,
        "bf_policy_intensity": 0.0,
        "bf_entity_density": 0.0,
        "bf_novelty": 1.0,
        "bf_volume_burst": 0.0,
        "bf_cross_source_confirmation": 0.0,
        "bf_noise_penalty": 1.0,
    }.items():
        df[col] = pd.to_numeric(df.get(col), errors="coerce").fillna(default)
    for col, default in TECHNICAL_DEFAULTS.items():
        df[col] = pd.to_numeric(df.get(col), errors="coerce").fillna(default)
    db.factor_registry_upsert_batch(factor_registry_rows())
    factor_rows: list[dict] = []
    for record in df.to_dict(orient="records"):
        date_val = str(record["date"])
        symbol = str(record["symbol"])
        for col in FEATURE_COLS:
            factor_rows.append(
                {
                    "date": date_val,
                    "symbol": symbol,
                    "factor_name": col,
                    "factor_type": FACTOR_TYPE_MAP.get(col, "model_feature"),
                    "value": float(record.get(col, 0.0) or 0.0),
                }
            )
    db.factor_upsert_batch(factor_rows)
    return target_date, len(df), FEATURE_COLS


def sync_signal_predictions(data_root: str, date_str: str | None = None) -> tuple[str, int]:
    db = TradeDB(data_root)
    target_date = date_str or db._conn.execute("SELECT MAX(date) FROM signals").fetchone()[0]
    if not target_date:
        return "", 0
    symbols = [
        str(r[0])
        for r in db._conn.execute(
            "SELECT symbol FROM signals WHERE date = ? ORDER BY symbol",
            (target_date,),
        ).fetchall()
    ]
    if not symbols:
        return target_date, 0

    from trade_web.inference import InferenceService

    service = InferenceService(data_root)
    preds = service.predict(symbols, target_date)
    updated = 0
    for symbol, payload in preds.items():
        if payload.get("model_score") is None:
            continue
        db.signal_upsert(
            target_date,
            symbol,
            model_score=payload.get("model_score"),
            model_risk=payload.get("model_risk"),
            model_version=payload.get("model_version"),
        )
        updated += 1
    return target_date, updated
