from __future__ import annotations

import json

import pandas as pd

from trade_py.data.paths import KLINE_DIR
from trade_py.db.trade_db import TradeDB
from trade_py.services import CausalService, DecisionService, ExplanationService, StateService


def _seed_symbol_state(db: TradeDB, symbol: str, as_of_date: str) -> None:
    db.trading_calendar_upsert_batch([
        {"exchange": "SSE", "trade_date": as_of_date, "is_open": 1},
    ])
    db.signal_upsert(
        as_of_date,
        symbol,
        window_score=78,
        net_sentiment=0.18,
        event_kg_score=0.42,
        event_type="policy_support",
        model_score=0.68,
        model_risk=0.12,
    )
    db.belief_state_upsert(
        as_of_date,
        symbol,
        {"mu": 0.22, "sigma": 0.18},
        "belief-v1",
        confidence=0.78,
        uncertainty=0.18,
    )
    db.factor_upsert_batch([
        {"date": as_of_date, "symbol": symbol, "factor_name": "window_score", "factor_type": "signal", "value": 78.0},
        {"date": as_of_date, "symbol": symbol, "factor_name": "net_sentiment", "factor_type": "sentiment", "value": 0.18},
        {"date": as_of_date, "symbol": symbol, "factor_name": "kg_score", "factor_type": "event", "value": 0.42},
        {"date": as_of_date, "symbol": symbol, "factor_name": "tech_rsi_14", "factor_type": "technical", "value": 44.0},
        {"date": as_of_date, "symbol": symbol, "factor_name": "tech_macd_cross", "factor_type": "technical", "value": 1.0},
        {"date": as_of_date, "symbol": symbol, "factor_name": "tech_volume_ratio_5_20", "factor_type": "technical", "value": 1.32},
    ])
    db.sync_state_set("tushare_kline", "daily", last_date=as_of_date)
    db.sync_state_set("tushare_fund_flow", "daily", last_date=as_of_date)
    db.sync_state_set("tushare_fundamental", "daily", last_date=as_of_date)

    with db._conn_lock:
        db._conn.execute(
            """
            INSERT INTO market_events (
                event_id, event_date, event_type, entity_id, magnitude,
                confidence, breadth, sentiment_score, news_volume, summary, source_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "evt-1",
                as_of_date,
                "policy_support",
                "SW_Bank",
                0.8,
                0.9,
                "sector",
                0.65,
                3,
                "政策支持银行板块",
                "hash-evt-1",
            ),
        )
        db._conn.execute(
            """
            INSERT INTO event_propagations (
                event_id, symbol, kg_score, hop, typical_days
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("evt-1", symbol, 0.42, 1, 5),
        )
        db._conn.execute(
            """
            INSERT INTO dataset_snapshots (
                snapshot_name, eval_date, start_date, end_date,
                source_count, market_event_count, propagation_count,
                feature_rows, labeled_rows_5d, labeled_rows_20d,
                signal_dates, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                "daily",
                as_of_date,
                as_of_date,
                as_of_date,
                1,
                1,
                1,
                6,
                1,
                1,
                1,
                json.dumps({"fund_flow_coverage": 1.0, "fundamental_coverage": 1.0}),
            ),
        )
        db._conn.commit()


def _write_kline_history(data_root, symbol: str, start: str = "2026-03-03", periods: int = 30) -> None:
    path = KLINE_DIR(data_root)
    path.mkdir(parents=True, exist_ok=True)
    dates = pd.bdate_range(start, periods=periods)
    close = [10.0 + idx * 0.18 for idx in range(periods)]
    df = pd.DataFrame(
        {
            "symbol": [symbol] * periods,
            "date": dates.strftime("%Y-%m-%d"),
            "open": [value - 0.05 for value in close],
            "high": [value + 0.15 for value in close],
            "low": [value - 0.12 for value in close],
            "close": close,
            "volume": [1_000_000 + idx * 10_000 for idx in range(periods)],
            "amount": [close[idx] * (1_000_000 + idx * 10_000) for idx in range(periods)],
        }
    )
    df.to_parquet(path / f"{symbol.replace('.', '_')}.parquet", index=False)


def test_causal_service_builds_chain_and_persists_snapshot(tmp_path) -> None:
    db = TradeDB(tmp_path)
    _seed_symbol_state(db, "000001.SZ", "2026-03-20")

    state_svc = StateService(str(tmp_path), db=db)
    causal_svc = CausalService(state_svc, DecisionService(), data_root=str(tmp_path))

    chain = causal_svc.build_for_symbol("000001.SZ", as_of_date="2026-03-20", db=db, persist=True)

    assert chain.snapshot_id is not None
    assert len(chain.observed_facts) >= 8
    assert any(item.factor_type == "trend_factor" for item in chain.causal_factors)
    assert chain.conviction_vector.data_model_trust is not None
    assert chain.conviction_vector.sector_conviction is None

    stored = db.causal_snapshot_get(chain.snapshot_id)
    assert stored is not None
    assert stored["symbol"] == "000001.SZ"
    assert stored["chain"]["conviction_vector"]["sector_conviction"] is None

    explain = ExplanationService(state_svc, DecisionService()).explain("000001.SZ", as_of_date="2026-03-20")
    assert explain.causal_chain is not None
    assert explain.causal_chain["symbol"] == "000001.SZ"
    assert "observed_facts" in explain.causal_chain


def test_causal_service_validates_snapshot_and_generates_reward_records(tmp_path) -> None:
    symbol = "000001.SZ"
    as_of_date = "2026-03-10"
    db = TradeDB(tmp_path)
    _seed_symbol_state(db, symbol, as_of_date)
    _write_kline_history(tmp_path, symbol, start="2026-03-03", periods=35)

    state_svc = StateService(str(tmp_path), db=db)
    causal_svc = CausalService(state_svc, DecisionService(), data_root=str(tmp_path))

    chain = causal_svc.build_for_symbol(symbol, as_of_date=as_of_date, db=db, persist=True)
    outcomes, rewards = causal_svc.validate_chain(db, chain, persist=True)

    assert {item.horizon for item in outcomes} == {"1d", "5d", "20d"}
    assert any(item.decision_correctness in {"correct", "partial"} for item in outcomes if item.horizon == "5d")
    assert all(item.to_dict()["realized_volatility"] is None or isinstance(item.to_dict()["realized_volatility"], float) for item in outcomes)
    assert any(item.target_type == "expectation" for item in rewards)
    assert any(item.target_type == "factor" for item in rewards)

    stored_outcomes = db.causal_validation_list(chain.snapshot_id or "")
    stored_rewards = db.causal_reward_records_list(chain.snapshot_id or "")
    assert len(stored_outcomes) == 3
    assert len(stored_rewards) >= len(rewards)
