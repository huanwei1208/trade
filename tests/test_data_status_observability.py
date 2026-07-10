from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd
import pytest

from trade_py.cli import data as data_cli
from trade_py.cli.data import _data_status_exit_code, _running_job_state
from trade_py.db.trade_db import TradeDB
from trade_py.utils.data_inspector import (
    build_status_lines,
    cross_source_coverage_stats,
    fund_flow_stats,
    fundamental_stats,
    get_data_status,
    kline_freshness_stats,
    sentiment_stats,
    events_stats,
    cross_asset_stats,
    index_stats,
    northbound_stats,
    macro_stats,
    metadata_reconciliation_stats,
    provider_audit_stats,
    provider_readiness_stats,
    schema_contract_stats,
    source_stability_stats,
    value_quality_stats,
    build_data_quality_gate,
)


def test_kline_freshness_reports_trading_day_lag(tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.trading_calendar_upsert_batch(
        [
            {"exchange": "SSE", "trade_date": "2026-03-18", "is_open": 1},
            {"exchange": "SSE", "trade_date": "2026-03-19", "is_open": 1},
            {"exchange": "SSE", "trade_date": "2026-03-20", "is_open": 1},
            {"exchange": "SSE", "trade_date": "2026-03-21", "is_open": 0},
        ]
    )
    with db._conn_lock:
        db._conn.executemany(
            """
            INSERT INTO instruments(symbol, name, market, board, industry, status)
            VALUES (?, ?, 1, 1, 1, 0)
            """,
            [
                ("000001.SZ", "A"),
                ("000002.SZ", "B"),
            ],
        )
        db._conn.commit()
    db.record_download("000001.SZ", datetime.fromisoformat("2026-03-18").date(), datetime.fromisoformat("2026-03-18").date(), 1)
    db.record_download("000002.SZ", datetime.fromisoformat("2026-03-20").date(), datetime.fromisoformat("2026-03-20").date(), 1)

    status = kline_freshness_stats(tmp_path, sample_limit=5)
    lines = build_status_lines({"as_of": "2026-03-21", "kline_freshness": status})

    assert status["expected_trade_date"] == "2026-03-20"
    assert status["trading_day_stale_ge_1"] == 1
    assert status["max_trading_day_stale_days"] == 2
    assert any("交易日基准: 2026-03-20" in line for line in lines)


@pytest.mark.parametrize(
    ("job_name", "age_hours", "expected"),
    [
        ("realtime_compute", 0.3, "stale_running"),
        ("kline_update", 1.0, "running"),
        ("kline_update", 7.0, "stale_running"),
    ],
)
def test_running_job_state_classifies_stale_rows(job_name: str, age_hours: float, expected: str) -> None:
    now = datetime.fromisoformat("2026-03-20T12:00:00")
    row = {
        "job_name": job_name,
        "started_at": (now - timedelta(hours=age_hours)).isoformat(sep=" "),
    }

    state = _running_job_state(row, now=now)

    assert state["status"] == expected
    assert state["age_hours"] == pytest.approx(age_hours)


def test_fund_flow_and_fundamental_status_use_local_parquet_coverage(tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.trading_calendar_upsert_batch(
        [
            {"exchange": "SSE", "trade_date": "2026-03-19", "is_open": 1},
            {"exchange": "SSE", "trade_date": "2026-03-20", "is_open": 1},
        ]
    )
    with db._conn_lock:
        db._conn.executemany(
            """
            INSERT INTO instruments(symbol, name, market, board, industry, status)
            VALUES (?, ?, 1, 1, 1, 0)
            """,
            [
                ("000001.SZ", "A"),
                ("000002.SZ", "B"),
                ("000003.SZ", "C"),
            ],
        )
        db._conn.commit()

    fund_flow_root = tmp_path / "market" / "fund_flow"
    fund_flow_root.mkdir(parents=True)
    pd.DataFrame(
        [
            {"symbol": "000001.SZ", "date": "2026-03-19", "large_order_net_ratio": 0.1},
            {"symbol": "000001.SZ", "date": "2026-03-20", "large_order_net_ratio": 0.2},
        ]
    ).to_parquet(fund_flow_root / "000001_SZ.parquet", index=False)
    pd.DataFrame(
        [
            {"symbol": "000002.SZ", "date": "2026-03-19", "large_order_net_ratio": -0.1},
        ]
    ).to_parquet(fund_flow_root / "000002_SZ.parquet", index=False)

    fundamental_root = tmp_path / "market" / "fundamental"
    fundamental_root.mkdir(parents=True)
    pd.DataFrame(
        [
            {"symbol": "000001.SZ", "report_date": pd.Timestamp("2025-12-31"), "roe": 0.1},
            {"symbol": "000001.SZ", "report_date": pd.Timestamp("2026-03-31"), "roe": 0.11},
        ]
    ).to_parquet(fundamental_root / "000001_SZ.parquet", index=False)

    fund_flow = fund_flow_stats(tmp_path, sample_limit=5)
    fundamental = fundamental_stats(tmp_path, sample_limit=5)
    status = get_data_status(tmp_path, sample_limit=5)
    lines = build_status_lines(status)

    assert fund_flow["symbols"] == 2
    assert fund_flow["coverage_pct"] == pytest.approx(66.7)
    assert fund_flow["max_date"] == "2026-03-20"
    assert fund_flow["expected_trade_date"] == "2026-03-20"
    assert fund_flow["missing_sample"] == ["000003.SZ"]
    assert fundamental["symbols"] == 1
    assert fundamental["coverage_pct"] == pytest.approx(33.3)
    assert fundamental["max_date"] == "2026-03-31"
    assert status["fund_flow"]["rows"] == 3
    assert status["fundamental"]["rows"] == 2
    assert any("资金流数据" in line for line in lines)
    assert any("基本面数据" in line for line in lines)
    assert "value_quality" not in status


def test_sentiment_and_events_status_report_lag_against_trade_date(tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.trading_calendar_upsert_batch(
        [
            {"exchange": "SSE", "trade_date": "2026-03-19", "is_open": 1},
            {"exchange": "SSE", "trade_date": "2026-03-20", "is_open": 1},
        ]
    )
    for layer in ("silver", "gold"):
        target = tmp_path / "sentiment" / layer / "2026" / "03"
        target.mkdir(parents=True)
        pd.DataFrame(
            [
                {
                    "date": "2026-03-18",
                    "symbol": "000001.SZ",
                    "net_sentiment": 0.2,
                }
            ]
        ).to_parquet(target / "2026-03-18.parquet", index=False)
    with db._conn_lock:
        db._conn.execute(
            """
            INSERT INTO market_events (
                event_id, event_date, event_type, entity_id,
                magnitude, breadth, sentiment_score, news_volume, summary, source_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("evt-1", "2026-03-18", "policy", "market", 0.2, 1.0, 0.1, 3, "event", "hash"),
        )
        db._conn.execute(
            """
            INSERT INTO event_propagations (
                event_id, symbol, kg_score, hop, typical_days
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("evt-1", "000001.SZ", 0.5, 1, 5),
        )
        db._conn.commit()

    sentiment = sentiment_stats(tmp_path)
    events = events_stats(tmp_path)
    lines = build_status_lines({"as_of": "2026-03-20", "sentiment": sentiment, "events": events})

    assert sentiment["silver"]["expected_date"] == "2026-03-20"
    assert sentiment["silver"]["lag_days"] == 2
    assert sentiment["gold"]["lag_days"] == 2
    assert events["lag_days"] == 2
    assert any("lag=2d" in line for line in lines)


def test_cross_asset_status_reports_canonical_files_and_lag(tmp_path) -> None:
    canonical = tmp_path / "market" / "cross_asset"
    legacy = tmp_path / "cross_asset"
    canonical.mkdir(parents=True)
    legacy.mkdir(parents=True)
    pd.DataFrame(
        [
            {"date": "2026-03-19", "close": 2100.0},
            {"date": "2026-03-20", "close": 2110.0},
        ]
    ).to_parquet(canonical / "gold.parquet", index=False)
    pd.DataFrame(
        [{"date": "2026-03-01", "close": 2000.0}]
    ).to_parquet(legacy / "gold.parquet", index=False)
    pd.DataFrame(
        [{"date": "2026-03-18", "close": 7.2}]
    ).to_parquet(legacy / "fx_cnh.parquet", index=False)

    stats = cross_asset_stats(tmp_path)
    lines = build_status_lines({"as_of": "2026-03-21", "cross_asset": stats})

    assert stats["gold"]["exists"] is True
    assert stats["gold"]["layout"] == "market/cross_asset"
    assert stats["gold"]["rows"] == 2
    assert stats["gold"]["max_date"] == "2026-03-20"
    assert stats["fx_cnh"]["exists"] is True
    assert stats["fx_cnh"]["layout"] == "cross_asset"
    assert stats["btc"]["exists"] is False
    assert any("跨资产数据" in line for line in lines)


def test_index_northbound_and_macro_status_use_local_files(tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.trading_calendar_upsert_batch(
        [
            {"exchange": "SSE", "trade_date": "2026-03-19", "is_open": 1},
            {"exchange": "SSE", "trade_date": "2026-03-20", "is_open": 1},
        ]
    )
    index_root = tmp_path / "market" / "index"
    index_root.mkdir(parents=True)
    pd.DataFrame(
        [
            {"date": "2026-03-19", "close": 3000.0},
            {"date": "2026-03-20", "close": 3010.0},
        ]
    ).to_parquet(index_root / "000001_SH.parquet", index=False)
    pd.DataFrame(
        [{"date": "2026-03-19", "close": 4000.0}]
    ).to_parquet(index_root / "sector_801010_SI.parquet", index=False)

    northbound_root = tmp_path / "market" / "northbound"
    northbound_root.mkdir(parents=True)
    pd.DataFrame(
        [{"date": "2026-03-19", "total_net": 1.2, "net_5d": 3.4}]
    ).to_parquet(northbound_root / "daily.parquet", index=False)

    macro_root = tmp_path / "market" / "macro"
    macro_root.mkdir(parents=True)
    pd.DataFrame([{"date": "2025-12-31", "q_gdp": 5.2}]).to_parquet(macro_root / "gdp.parquet", index=False)
    pd.DataFrame([{"date": "2026-02-28", "nt_yoy": 0.5}]).to_parquet(macro_root / "cpi.parquet", index=False)

    index = index_stats(tmp_path, sample_limit=5)
    northbound = northbound_stats(tmp_path)
    macro = macro_stats(tmp_path)
    lines = build_status_lines({
        "as_of": "2026-03-20",
        "index": index,
        "northbound": northbound,
        "macro": macro,
    })

    assert index["indices"] == 2
    assert index["rows"] == 3
    assert index["max_date"] == "2026-03-20"
    assert index["expected_trade_date"] == "2026-03-20"
    assert northbound["exists"] is True
    assert northbound["max_date"] == "2026-03-19"
    assert northbound["lag_days"] == 1
    assert macro["gdp"]["exists"] is True
    assert macro["gdp"]["max_date"] == "2025-12-31"
    assert macro["ppi"]["exists"] is False
    assert any("指数数据" in line for line in lines)
    assert any("北向资金" in line for line in lines)
    assert any("宏观数据" in line for line in lines)


def test_schema_contract_status_reports_missing_required_columns(tmp_path) -> None:
    kline_root = tmp_path / "market" / "kline"
    kline_root.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "date": "2026-03-20",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "volume": 1000,
                "amount": 102000.0,
                "turnover_rate": 1.2,
                "prev_close": 10.1,
                "vwap": 10.2,
            }
        ]
    ).to_parquet(kline_root / "000001_SZ.parquet", index=False)

    fund_flow_root = tmp_path / "market" / "fund_flow"
    fund_flow_root.mkdir(parents=True)
    pd.DataFrame(
        [{"symbol": "000001.SZ", "date": "2026-03-20"}]
    ).to_parquet(fund_flow_root / "000001_SZ.parquet", index=False)

    cross_asset_root = tmp_path / "market" / "cross_asset"
    cross_asset_root.mkdir(parents=True)
    pd.DataFrame(
        [{"date": "2026-03-20"}]
    ).to_parquet(cross_asset_root / "gold.parquet", index=False)

    macro_root = tmp_path / "market" / "macro"
    macro_root.mkdir(parents=True)
    pd.DataFrame([{"date": "2025-12-31", "gdp": 5.2}]).to_parquet(macro_root / "gdp.parquet", index=False)
    pd.DataFrame([{"date": "2026-03-01", "PMI010000": 50.2}]).to_parquet(macro_root / "pmi.parquet", index=False)

    stats = schema_contract_stats(tmp_path, sample_limit=5)
    lines = build_status_lines({"as_of": "2026-03-20", "schema_contracts": stats})

    assert stats["status"] == "fail"
    assert stats["datasets"]["kline"]["status"] == "pass"
    assert "fund_flow" in stats["failed_contracts"]
    assert stats["datasets"]["fund_flow"]["missing_columns"] == ["large_order_net_ratio"]
    assert "cross_asset.gold" in stats["failed_contracts"]
    assert stats["datasets"]["cross_asset.gold"]["missing_columns"] == ["close"]
    assert stats["datasets"]["macro.gdp"]["status"] == "pass"
    assert stats["datasets"]["macro.gdp"]["column_aliases"] == {"q_gdp": ["gdp"]}
    assert stats["datasets"]["macro.pmi"]["status"] == "pass"
    assert stats["datasets"]["macro.pmi"]["column_aliases"] == {"mfg_pmi": ["PMI010000"]}
    assert any("数据契约" in line for line in lines)


def test_value_quality_status_reports_invalid_values_and_duplicates(tmp_path) -> None:
    kline_root = tmp_path / "market" / "kline"
    kline_root.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "date": "2026-03-20",
                "open": 10.0,
                "high": 9.5,
                "low": 9.8,
                "close": 10.2,
                "volume": 1000,
                "amount": 102000.0,
                "turnover_rate": 1.2,
                "prev_close": 10.1,
                "vwap": 10.2,
            },
            {
                "symbol": "000001.SZ",
                "date": "2026-03-21",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "volume": -1,
                "amount": 102000.0,
                "turnover_rate": 1.2,
                "prev_close": 10.1,
                "vwap": 10.2,
            },
            {
                "symbol": "000001.SZ",
                "date": "2026-03-21",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "volume": 1000,
                "amount": 102000.0,
                "turnover_rate": 1.2,
                "prev_close": 10.1,
                "vwap": 10.2,
            },
        ]
    ).to_parquet(kline_root / "000001_SZ.parquet", index=False)

    fund_flow_root = tmp_path / "market" / "fund_flow"
    fund_flow_root.mkdir(parents=True)
    pd.DataFrame(
        [{"symbol": "000001.SZ", "date": "2026-03-20", "large_order_net_ratio": 1.5}]
    ).to_parquet(fund_flow_root / "000001_SZ.parquet", index=False)

    gold_root = tmp_path / "sentiment" / "gold" / "2026" / "03"
    gold_root.mkdir(parents=True)
    pd.DataFrame(
        [{"date": "2026-03-20", "symbol": "000001.SZ", "net_sentiment": 1.2, "confidence": 1.1}]
    ).to_parquet(gold_root / "2026-03-20.parquet", index=False)

    schema = schema_contract_stats(tmp_path, sample_limit=5)
    stats = value_quality_stats(tmp_path, sample_limit=5, schema_contracts=schema)
    lines = build_status_lines({"as_of": "2026-03-20", "value_quality": stats})

    assert stats["status"] == "fail"
    assert stats["datasets"]["kline"]["metrics"]["invalid_ohlc_relationship"] == 1
    assert stats["datasets"]["kline"]["metrics"]["negative_volume"] == 1
    assert stats["datasets"]["kline"]["metrics"]["duplicate_keys"] == 1
    assert "kline.invalid_ohlc_relationship" in stats["failed_checks"]
    assert "fund_flow.invalid_large_order_net_ratio" in stats["failed_checks"]
    assert "sentiment.gold.net_sentiment_out_of_range" in stats["failed_checks"]
    assert "sentiment.gold.confidence_out_of_range" in stats["failed_checks"]
    plan_by_component = {item["component"]: item for item in stats["recovery_plan"]}
    assert plan_by_component["kline"]["command"] == [
        "trade",
        "data",
        "kline",
        "sync",
        "--mode",
        "range",
        "--symbols",
        "000001.SZ",
        "--start",
        "2026-03-20",
        "--end",
        "2026-03-21",
        "--provider",
        "tushare",
        "--adjust",
        "none",
    ]
    assert plan_by_component["kline"]["mode"] == "targeted_refetch"
    assert plan_by_component["kline"]["target"] == {
        "symbols": ["000001.SZ"],
        "start": "2026-03-20",
        "end": "2026-03-21",
        "provider": "tushare",
        "adjust": "none",
    }
    assert plan_by_component["kline"]["sample_symbols"] == ["000001.SZ"]
    assert stats["datasets"]["kline"]["invalid_extents"]["by_symbol"] == [
        {"symbol": "000001.SZ", "start": "2026-03-20", "end": "2026-03-21", "rows": 2}
    ]
    assert plan_by_component["fund_flow"]["command"] == ["trade", "data", "fund-flow", "sync"]
    assert plan_by_component["sentiment"]["command"] == ["trade", "data", "sentiment"]
    assert any("数据取值质量" in line for line in lines)


def test_value_quality_blocks_on_schema_contract_failures(tmp_path) -> None:
    fund_flow_root = tmp_path / "market" / "fund_flow"
    fund_flow_root.mkdir(parents=True)
    pd.DataFrame(
        [{"symbol": "000001.SZ", "date": "2026-03-20"}]
    ).to_parquet(fund_flow_root / "000001_SZ.parquet", index=False)

    schema = schema_contract_stats(tmp_path, sample_limit=5)
    stats = value_quality_stats(tmp_path, sample_limit=5, schema_contracts=schema)

    assert stats["status"] == "pass"
    assert stats["blocked_contracts"] == ["fund_flow"]
    assert stats["datasets"]["fund_flow"]["status"] == "blocked"
    assert stats["datasets"]["fund_flow"]["blocked_by_schema"] is True


def test_value_quality_recovery_plan_groups_prefixed_datasets(tmp_path) -> None:
    cross_asset_root = tmp_path / "market" / "cross_asset"
    cross_asset_root.mkdir(parents=True)
    pd.DataFrame(
        [{"date": "2026-03-20", "open": 10.0, "high": 9.0, "low": 9.5, "close": 10.2}]
    ).to_parquet(cross_asset_root / "gold.parquet", index=False)

    macro_root = tmp_path / "market" / "macro"
    macro_root.mkdir(parents=True)
    pd.DataFrame([{"date": "2026-03-20", "ppi_yoy": None}]).to_parquet(macro_root / "ppi.parquet", index=False)

    schema = schema_contract_stats(tmp_path, sample_limit=5)
    stats = value_quality_stats(tmp_path, sample_limit=5, schema_contracts=schema)

    plan_by_component = {item["component"]: item for item in stats["recovery_plan"]}
    assert plan_by_component["cross_asset"]["command"] == ["trade", "data", "cross-asset", "gold"]
    assert plan_by_component["cross_asset"]["mode"] == "targeted_refetch"
    assert plan_by_component["cross_asset"]["datasets"] == ["cross_asset.gold"]
    assert plan_by_component["cross_asset"]["target"] == {
        "datasets": ["cross_asset.gold"],
        "start": "2026-03-20",
        "end": "2026-03-20",
    }
    assert stats["datasets"]["cross_asset.gold"]["invalid_extents"]["date_range"] == {
        "start": "2026-03-20",
        "end": "2026-03-20",
        "rows": 1,
    }
    assert plan_by_component["macro"]["command"] == ["trade", "data", "macro", "sync"]
    assert plan_by_component["macro"]["datasets"] == ["macro.ppi"]


def test_value_quality_targets_fundamental_invalid_report_extents(tmp_path) -> None:
    fundamental_root = tmp_path / "market" / "fundamental"
    fundamental_root.mkdir(parents=True)
    pd.DataFrame(
        [
            {"symbol": "000001.SZ", "report_date": "2020-12-31", "roe": 0.2},
            {"symbol": "000001.SZ", "report_date": "2021-03-31", "roe": 2.1},
            {"symbol": "000001.SZ", "report_date": "2021-06-30", "roe": -2.2},
            {"symbol": "000002.SZ", "report_date": "2022-12-31", "roe": 1.7},
            {"symbol": "000003.SZ", "report_date": "2020-12-31", "roe": 1.8},
        ]
    ).to_parquet(fundamental_root / "sample.parquet", index=False)

    schema = schema_contract_stats(tmp_path, sample_limit=5)
    stats = value_quality_stats(tmp_path, sample_limit=5, schema_contracts=schema)
    fundamental = stats["datasets"]["fundamental"]
    plan_by_component = {item["component"]: item for item in stats["recovery_plan"]}

    assert fundamental["invalid_extents"]["by_symbol"] == [
        {"symbol": "000001.SZ", "start": "2021-03-31", "end": "2021-06-30", "rows": 2},
        {"symbol": "000002.SZ", "start": "2022-12-31", "end": "2022-12-31", "rows": 1},
        {"symbol": "000003.SZ", "start": "2020-12-31", "end": "2020-12-31", "rows": 1},
    ]
    assert plan_by_component["fundamental"]["command"] == [
        "trade",
        "data",
        "fundamental",
        "sync",
        "--symbols",
        "000001.SZ,000002.SZ,000003.SZ",
        "--start",
        "2020-12-31",
    ]
    assert plan_by_component["fundamental"]["mode"] == "targeted_refetch"
    assert plan_by_component["fundamental"]["target"] == {
        "symbols": ["000001.SZ", "000002.SZ", "000003.SZ"],
        "start": "2020-12-31",
        "end": "2022-12-31",
    }


def test_value_quality_waives_index_quote_precision_ohlc_drift(tmp_path) -> None:
    index_root = tmp_path / "market" / "index"
    index_root.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "date": "2026-03-20",
                "open": 4236.15,
                "high": 4349.82,
                "low": 4206.75,
                "close": 4349.83,
            }
        ]
    ).to_parquet(index_root / "000001_SH.parquet", index=False)

    schema = schema_contract_stats(tmp_path, sample_limit=5)
    stats = value_quality_stats(tmp_path, sample_limit=5, schema_contracts=schema)
    index = stats["datasets"]["index"]

    assert index["status"] == "pass"
    assert index["metrics"]["invalid_ohlc_relationship"] == 0
    assert index["metrics"]["waived_invalid_ohlc_relationship"] == 1
    assert "index.invalid_ohlc_relationship" not in stats["failed_checks"]


def test_value_quality_fails_index_ohlc_breaks_beyond_precision(tmp_path) -> None:
    index_root = tmp_path / "market" / "index"
    index_root.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "date": "2026-03-20",
                "open": 4236.15,
                "high": 4349.82,
                "low": 4206.75,
                "close": 4350.0,
            }
        ]
    ).to_parquet(index_root / "000001_SH.parquet", index=False)

    schema = schema_contract_stats(tmp_path, sample_limit=5)
    stats = value_quality_stats(tmp_path, sample_limit=5, schema_contracts=schema)
    index = stats["datasets"]["index"]

    assert index["status"] == "fail"
    assert index["metrics"]["invalid_ohlc_relationship"] == 1
    assert index["metrics"]["waived_invalid_ohlc_relationship"] == 0
    assert "index.invalid_ohlc_relationship" in stats["failed_checks"]


def test_value_quality_does_not_waive_cross_asset_ohlc_breaks(tmp_path) -> None:
    cross_asset_root = tmp_path / "market" / "cross_asset"
    cross_asset_root.mkdir(parents=True)
    pd.DataFrame(
        [{"date": "2026-03-20", "open": 280.40, "high": 281.25, "low": 279.50, "close": 281.83}]
    ).to_parquet(cross_asset_root / "gold.parquet", index=False)

    schema = schema_contract_stats(tmp_path, sample_limit=5)
    stats = value_quality_stats(tmp_path, sample_limit=5, schema_contracts=schema)
    gold = stats["datasets"]["cross_asset.gold"]

    assert gold["status"] == "fail"
    assert gold["metrics"]["invalid_ohlc_relationship"] == 1
    assert "waived_invalid_ohlc_relationship" not in gold["metrics"]
    assert "cross_asset.gold.invalid_ohlc_relationship" in stats["failed_checks"]


def test_value_quality_waives_known_historical_ppi_yoy_gap(tmp_path) -> None:
    macro_root = tmp_path / "market" / "macro"
    macro_root.mkdir(parents=True)
    pd.DataFrame(
        [
            {"date": "1993-01-01", "ppi_yoy": None, "ppi_accu": 17.90},
            {"date": "1996-09-01", "ppi_yoy": None, "ppi_accu": 3.53},
            {"date": "1996-10-01", "ppi_yoy": 0.34, "ppi_accu": 3.21},
        ]
    ).to_parquet(macro_root / "ppi.parquet", index=False)

    schema = schema_contract_stats(tmp_path, sample_limit=5)
    stats = value_quality_stats(tmp_path, sample_limit=5, schema_contracts=schema)
    ppi = stats["datasets"]["macro.ppi"]

    assert ppi["status"] == "pass"
    assert ppi["metrics"]["null_macro_value"] == 0
    assert ppi["metrics"]["waived_null_macro_value"] == 2
    assert "macro.ppi.null_macro_value" not in stats["failed_checks"]
    assert "macro" not in {item["component"] for item in stats["recovery_plan"]}


def test_value_quality_still_fails_on_actionable_ppi_yoy_nulls(tmp_path) -> None:
    macro_root = tmp_path / "market" / "macro"
    macro_root.mkdir(parents=True)
    pd.DataFrame(
        [
            {"date": "1996-09-01", "ppi_yoy": None, "ppi_accu": 3.53},
            {"date": "1996-10-01", "ppi_yoy": None, "ppi_accu": 3.21},
        ]
    ).to_parquet(macro_root / "ppi.parquet", index=False)

    schema = schema_contract_stats(tmp_path, sample_limit=5)
    stats = value_quality_stats(tmp_path, sample_limit=5, schema_contracts=schema)
    ppi = stats["datasets"]["macro.ppi"]

    assert ppi["status"] == "fail"
    assert ppi["metrics"]["null_macro_value"] == 1
    assert ppi["metrics"]["waived_null_macro_value"] == 1
    assert "macro.ppi.null_macro_value" in stats["failed_checks"]
    assert stats["recovery_plan"][0]["component"] == "macro"


def test_data_quality_gate_summarizes_clean_and_degraded_status() -> None:
    clean = {
        "kline_coverage": {"coverage_pct": 100.0},
        "kline_freshness": {"max_trading_day_stale_days": 0},
        "fund_flow": {"coverage_pct": 95.0, "stale_sample": [{"trading_day_stale_days": 0}]},
        "fundamental": {"coverage_pct": 100.0, "max_date": "2025-12-31"},
        "sentiment": {"gold": {"lag_days": 0, "max_date": "2026-03-20"}},
        "events": {"lag_days": 0, "event_count": 3},
        "cross_asset": {
            "gold": {"exists": True, "lag_days": 0},
            "fx_cnh": {"exists": True, "lag_days": 0},
            "btc": {"exists": True, "lag_days": 0},
        },
        "index": {"coverage_pct": 100.0, "stale_sample": [{"lag_days": 0}]},
        "northbound": {"exists": True, "lag_days": 0},
        "schema_contracts": {"status": "pass", "checked_files": 9, "failed_contracts": []},
        "value_quality": {"status": "pass", "checked_rows": 100, "failed_checks": []},
    }
    degraded = {
        **clean,
        "kline_coverage": {"coverage_pct": 80.0},
        "sentiment": {"gold": {"lag_days": 20, "max_date": "2026-03-01"}},
        "events": {"lag_days": 20, "event_count": 0},
    }

    clean_gate = build_data_quality_gate(clean)
    degraded_gate = build_data_quality_gate(degraded)
    degraded_lines = build_status_lines({"as_of": "2026-03-20", "quality_gate": degraded_gate})

    assert clean_gate["status"] == "pass"
    assert clean_gate["reason_codes"] == []
    assert clean_gate["recovery_plan"] == []
    assert degraded_gate["status"] == "fail"
    assert "KLINE_STALE_OR_LOW_COVERAGE" in degraded_gate["reason_codes"]
    assert "SENTIMENT_GOLD_STALE" in degraded_gate["reason_codes"]
    plan_by_component = {item["component"]: item for item in degraded_gate["recovery_plan"]}
    assert plan_by_component["kline"]["command"] == ["trade", "data", "kline", "sync"]
    assert plan_by_component["sentiment_gold"]["command"] == ["trade", "data", "sentiment"]
    assert degraded_gate["components"]["kline"]["recovery"]["mode"] == "refresh"
    assert any("数据质量门禁" in line for line in degraded_lines)


def test_data_quality_gate_fails_on_value_quality_breakage() -> None:
    clean = {
        "kline_coverage": {"coverage_pct": 100.0},
        "kline_freshness": {"max_trading_day_stale_days": 0},
        "fund_flow": {"coverage_pct": 95.0, "stale_sample": [{"trading_day_stale_days": 0}]},
        "fundamental": {"coverage_pct": 100.0, "max_date": "2025-12-31"},
        "sentiment": {"gold": {"lag_days": 0, "max_date": "2026-03-20"}},
        "events": {"lag_days": 0, "event_count": 3},
        "cross_asset": {
            "gold": {"exists": True, "lag_days": 0},
            "fx_cnh": {"exists": True, "lag_days": 0},
            "btc": {"exists": True, "lag_days": 0},
        },
        "index": {"coverage_pct": 100.0, "stale_sample": [{"lag_days": 0}]},
        "northbound": {"exists": True, "lag_days": 0},
        "schema_contracts": {"status": "pass", "checked_files": 12, "failed_contracts": []},
        "value_quality": {
            "status": "fail",
            "checked_rows": 123,
            "failed_checks": ["kline.invalid_ohlc_relationship", "fund_flow.invalid_large_order_net_ratio"],
            "blocked_contracts": [],
            "recovery_plan": [
                {
                    "component": "kline",
                    "command": ["trade", "data", "kline", "sync", "--mode", "full"],
                    "mode": "refetch",
                    "detail": "repair kline",
                    "datasets": ["kline"],
                    "failed_checks": ["kline.invalid_ohlc_relationship"],
                    "sample_symbols": ["000001.SZ"],
                    "sample_dates": ["2026-03-20"],
                }
            ],
        },
    }

    gate = build_data_quality_gate(clean)

    assert gate["status"] == "fail"
    assert "VALUE_QUALITY_INVALID_ROWS" in gate["reason_codes"]
    assert gate["components"]["value_quality"]["metrics"]["checked_rows"] == 123
    assert gate["components"]["value_quality"]["metrics"]["recovery_plan"][0]["component"] == "kline"
    plan_by_component = {item["component"]: item for item in gate["recovery_plan"]}
    assert plan_by_component["value_quality"]["mode"] == "audit"


def test_data_quality_gate_fails_on_schema_contract_breakage() -> None:
    clean = {
        "kline_coverage": {"coverage_pct": 100.0},
        "kline_freshness": {"max_trading_day_stale_days": 0},
        "fund_flow": {"coverage_pct": 95.0, "stale_sample": [{"trading_day_stale_days": 0}]},
        "fundamental": {"coverage_pct": 100.0, "max_date": "2025-12-31"},
        "sentiment": {"gold": {"lag_days": 0, "max_date": "2026-03-20"}},
        "events": {"lag_days": 0, "event_count": 3},
        "cross_asset": {
            "gold": {"exists": True, "lag_days": 0},
            "fx_cnh": {"exists": True, "lag_days": 0},
            "btc": {"exists": True, "lag_days": 0},
        },
        "index": {"coverage_pct": 100.0, "stale_sample": [{"lag_days": 0}]},
        "northbound": {"exists": True, "lag_days": 0},
        "schema_contracts": {
            "status": "fail",
            "checked_files": 12,
            "failed_contracts": ["fund_flow", "cross_asset.gold"],
        },
        "value_quality": {"status": "pass", "checked_rows": 0, "failed_checks": []},
    }

    gate = build_data_quality_gate(clean)

    assert gate["status"] == "fail"
    assert "SCHEMA_CONTRACT_MISSING_COLUMNS" in gate["reason_codes"]
    assert gate["components"]["schema_contracts"]["metrics"]["failed_contracts"] == [
        "fund_flow",
        "cross_asset.gold",
    ]
    plan_by_component = {item["component"]: item for item in gate["recovery_plan"]}
    assert plan_by_component["schema_contracts"]["mode"] == "audit"


@pytest.mark.parametrize(
    ("gate_status", "strict", "expected"),
    [
        ("pass", False, 0),
        ("warn", False, 0),
        ("pass", True, 0),
        ("warn", True, 3),
        ("fail", True, 2),
        ("unknown", True, 2),
    ],
)
def test_data_status_strict_exit_code_uses_quality_gate(
    gate_status: str,
    strict: bool,
    expected: int,
) -> None:
    assert _data_status_exit_code({"quality_gate": {"status": gate_status}}, strict=strict) == expected


def test_data_status_parser_accepts_strict_flag() -> None:
    parser = data_cli.make_parser()
    parsed = parser.parse_args(["status", "--strict", "--json"])

    assert parsed.command == "status"
    assert parsed.strict is True
    assert parsed.as_json is True


def test_data_status_cli_opts_into_value_quality(monkeypatch, tmp_path, capsys) -> None:
    seen: dict[str, object] = {}

    def fake_get_data_status(data_root, sample_limit=10, include_value_quality=False):
        seen["data_root"] = data_root
        seen["sample_limit"] = sample_limit
        seen["include_value_quality"] = include_value_quality
        return {
            "as_of": "2026-03-20",
            "quality_gate": {"status": "pass", "reason_codes": []},
            "schema_contracts": {"status": "pass", "checked_files": 0, "failed_contracts": []},
            "value_quality": {"status": "pass", "checked_rows": 0, "failed_checks": []},
        }

    monkeypatch.setattr("trade_py.utils.data_inspector.get_data_status", fake_get_data_status)

    rc = data_cli.main([
        "status",
        "--data-root",
        str(tmp_path),
        "--limit",
        "3",
        "--json",
        "--strict",
    ])

    assert rc == 0
    assert seen == {
        "data_root": str(tmp_path),
        "sample_limit": 3,
        "include_value_quality": True,
    }
    assert '"value_quality"' in capsys.readouterr().out


def test_kline_reconcile_cli_wires_arguments(monkeypatch, tmp_path, capsys) -> None:
    seen: dict[str, object] = {}

    def fake_reconcile_kline(data_root, **kwargs):
        seen["data_root"] = data_root
        seen.update(kwargs)
        return {
            "status": "pass",
            "artifact_path": str(tmp_path / "market" / "kline" / "reconciliation" / "current.json"),
            "metrics": {"checked_rows": 2, "block_rows": 0, "warn_rows": 0},
        }

    monkeypatch.setattr("trade_py.data.market.kline.reconciliation.reconcile_kline", fake_reconcile_kline)

    rc = data_cli.main([
        "kline",
        "reconcile",
        "--data-root",
        str(tmp_path),
        "--symbols",
        "000001.SZ,000002.SZ",
        "--start",
        "2026-03-19",
        "--end",
        "2026-03-20",
        "--shadow-provider",
        "akshare",
        "--adjust",
        "none",
        "--dry-run",
    ])

    assert rc == 0
    assert seen["data_root"] == str(tmp_path)
    assert seen["symbols"] == ["000001.SZ", "000002.SZ"]
    assert seen["start"] == "2026-03-19"
    assert seen["end"] == "2026-03-20"
    assert seen["shadow_provider"] == "akshare"
    assert seen["dry_run"] is True
    assert "kline_reconcile" in capsys.readouterr().out


def test_source_stability_reports_recent_errors_and_stale_running_jobs(tmp_path) -> None:
    db = TradeDB(tmp_path)
    now = datetime.fromisoformat("2026-03-20T12:00:00")
    with db._conn_lock:
        db._conn.executemany(
            """
            INSERT INTO job_runs(job_name, stage, status, started_at, completed_at, result_summary)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "kline_update",
                    "fetch",
                    "error",
                    "2026-03-20 10:00:00",
                    "2026-03-20 10:02:00",
                    "provider timeout",
                ),
                (
                    "fund_flow_update",
                    "fetch",
                    "running",
                    "2026-03-20 10:30:00",
                    None,
                    None,
                ),
                (
                    "macro",
                    "fetch",
                    "ok",
                    "2026-03-20 11:30:00",
                    "2026-03-20 11:31:00",
                    "ok",
                ),
                (
                    "recommend",
                    "decision",
                    "error",
                    "2026-03-20 11:00:00",
                    "2026-03-20 11:02:00",
                    "not a data-source job",
                ),
            ],
        )
        db._conn.commit()

    stats = source_stability_stats(tmp_path, sample_limit=5, now=now)
    lines = build_status_lines({"as_of": "2026-03-20", "source_stability": stats})

    assert stats["status"] == "fail"
    assert stats["observed_jobs"] == 3
    assert stats["recent_errors"] == 1
    assert stats["stale_running"] == 1
    assert "recommend" not in stats["jobs"]
    assert "SOURCE_JOB_RECENT_ERRORS" in stats["reason_codes"]
    assert "SOURCE_JOB_STALE_RUNNING" in stats["reason_codes"]
    assert stats["error_sample"][0]["job_name"] == "kline_update"
    assert stats["stale_sample"][0]["job_name"] == "fund_flow_update"
    assert any("数据源稳定性" in line for line in lines)


def test_source_stability_passes_without_recent_data_source_failures(tmp_path) -> None:
    db = TradeDB(tmp_path)
    now = datetime.fromisoformat("2026-03-20T12:00:00")
    with db._conn_lock:
        db._conn.executemany(
            """
            INSERT INTO job_runs(job_name, stage, status, started_at, completed_at, result_summary)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("kline_update", "fetch", "ok", "2026-03-20 09:00:00", "2026-03-20 09:10:00", "ok"),
                ("fund_flow_update", "fetch", "running", "2026-03-20 11:30:00", None, None),
            ],
        )
        db._conn.commit()

    stats = source_stability_stats(tmp_path, sample_limit=5, now=now)

    assert stats["status"] == "pass"
    assert stats["recent_errors"] == 0
    assert stats["stale_running"] == 0
    assert stats["reason_codes"] == []


def test_data_quality_gate_fails_on_source_stability_breakage() -> None:
    clean = {
        "kline_coverage": {"coverage_pct": 100.0},
        "kline_freshness": {"max_trading_day_stale_days": 0},
        "fund_flow": {"coverage_pct": 95.0, "stale_sample": [{"trading_day_stale_days": 0}]},
        "fundamental": {"coverage_pct": 100.0, "max_date": "2025-12-31"},
        "sentiment": {"gold": {"lag_days": 0, "max_date": "2026-03-20"}},
        "events": {"lag_days": 0, "event_count": 3},
        "cross_asset": {
            "gold": {"exists": True, "lag_days": 0},
            "fx_cnh": {"exists": True, "lag_days": 0},
            "btc": {"exists": True, "lag_days": 0},
        },
        "index": {"coverage_pct": 100.0, "stale_sample": [{"lag_days": 0}]},
        "northbound": {"exists": True, "lag_days": 0},
        "schema_contracts": {"status": "pass", "checked_files": 12, "failed_contracts": []},
        "value_quality": {"status": "pass", "checked_rows": 0, "failed_checks": []},
        "source_stability": {
            "status": "fail",
            "observed_jobs": 2,
            "recent_runs": 3,
            "recent_errors": 1,
            "stale_running": 1,
            "error_rate": 0.3333,
            "reason_codes": ["SOURCE_JOB_RECENT_ERRORS", "SOURCE_JOB_STALE_RUNNING"],
        },
    }

    gate = build_data_quality_gate(clean)

    assert gate["status"] == "fail"
    assert "SOURCE_STABILITY_DEGRADED" in gate["reason_codes"]
    assert gate["components"]["source_stability"]["metrics"]["recent_errors"] == 1
    plan_by_component = {item["component"]: item for item in gate["recovery_plan"]}
    assert plan_by_component["source_stability"]["command"] == ["trade", "data", "backfill", "status"]


def test_metadata_reconciliation_reports_manifest_and_sync_state_drift(tmp_path) -> None:
    db = TradeDB(tmp_path)
    kline_root = tmp_path / "market" / "kline"
    kline_root.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "date": "2026-03-19",
                "open": 10.0,
                "high": 10.2,
                "low": 9.8,
                "close": 10.1,
                "volume": 1000,
                "amount": 101000.0,
                "turnover_rate": 1.0,
                "prev_close": 10.0,
                "vwap": 10.1,
            },
            {
                "symbol": "000001.SZ",
                "date": "2026-03-20",
                "open": 10.1,
                "high": 10.4,
                "low": 10.0,
                "close": 10.3,
                "volume": 1200,
                "amount": 123600.0,
                "turnover_rate": 1.1,
                "prev_close": 10.1,
                "vwap": 10.3,
            },
        ]
    ).to_parquet(kline_root / "000001_SZ.parquet", index=False)
    (kline_root / "_manifest.json").write_text(
        json.dumps(
            {
                "dataset": "kline",
                "layout": "per_symbol",
                "entries": {
                    "000001_SZ": {
                        "rows": 3,
                        "date_min": "2026-03-18",
                        "date_max": "2026-03-21",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    db.sync_state_set("tushare_kline", "daily", "000001.SZ", last_date="2026-03-21", row_count=3)

    stats = metadata_reconciliation_stats(tmp_path, sample_limit=5)
    lines = build_status_lines({"as_of": "2026-03-20", "metadata_reconciliation": stats})

    assert stats["status"] == "fail"
    assert "MANIFEST_PARQUET_MISMATCH" in stats["reason_codes"]
    assert "SYNC_STATE_PARQUET_MISMATCH" in stats["reason_codes"]
    assert stats["manifest"]["metrics"]["row_mismatches"] == 1
    assert stats["manifest"]["metrics"]["date_mismatches"] == 1
    assert stats["sync_state"]["metrics"]["watermark_ahead"] == 1
    assert stats["sync_state"]["metrics"]["row_count_mismatches"] == 1
    assert any("元数据交叉校验" in line for line in lines)


def test_metadata_reconciliation_passes_when_manifest_sync_and_parquet_match(tmp_path) -> None:
    db = TradeDB(tmp_path)
    kline_root = tmp_path / "market" / "kline"
    kline_root.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "date": "2026-03-20",
                "open": 10.0,
                "high": 10.2,
                "low": 9.8,
                "close": 10.1,
                "volume": 1000,
                "amount": 101000.0,
                "turnover_rate": 1.0,
                "prev_close": 10.0,
                "vwap": 10.1,
            }
        ]
    ).to_parquet(kline_root / "000001_SZ.parquet", index=False)
    (kline_root / "_manifest.json").write_text(
        json.dumps(
            {
                "dataset": "kline",
                "layout": "per_symbol",
                "entries": {
                    "000001_SZ": {
                        "rows": 1,
                        "date_min": "2026-03-20",
                        "date_max": "2026-03-20",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    db.sync_state_set("tushare_kline", "daily", "000001.SZ", last_date="2026-03-20", row_count=1)

    stats = metadata_reconciliation_stats(tmp_path, sample_limit=5)

    assert stats["status"] == "pass"
    assert stats["reason_codes"] == []
    assert stats["manifest"]["metrics"]["checked_entries"] == 1
    assert stats["sync_state"]["metrics"]["checked_rows"] == 1


def test_data_quality_gate_fails_on_metadata_reconciliation_mismatch() -> None:
    clean = {
        "kline_coverage": {"coverage_pct": 100.0},
        "kline_freshness": {"max_trading_day_stale_days": 0},
        "fund_flow": {"coverage_pct": 95.0, "stale_sample": [{"trading_day_stale_days": 0}]},
        "fundamental": {"coverage_pct": 100.0, "max_date": "2025-12-31"},
        "sentiment": {"gold": {"lag_days": 0, "max_date": "2026-03-20"}},
        "events": {"lag_days": 0, "event_count": 3},
        "cross_asset": {
            "gold": {"exists": True, "lag_days": 0},
            "fx_cnh": {"exists": True, "lag_days": 0},
            "btc": {"exists": True, "lag_days": 0},
        },
        "index": {"coverage_pct": 100.0, "stale_sample": [{"lag_days": 0}]},
        "northbound": {"exists": True, "lag_days": 0},
        "schema_contracts": {"status": "pass", "checked_files": 12, "failed_contracts": []},
        "value_quality": {"status": "pass", "checked_rows": 0, "failed_checks": []},
        "source_stability": {"status": "pass", "reason_codes": []},
        "metadata_reconciliation": {
            "status": "fail",
            "reason_codes": ["MANIFEST_PARQUET_MISMATCH"],
            "manifest": {"metrics": {"checked_entries": 1, "row_mismatches": 1}},
            "sync_state": {"metrics": {"checked_rows": 0}},
        },
    }

    gate = build_data_quality_gate(clean)

    assert gate["status"] == "fail"
    assert "METADATA_RECONCILIATION_MISMATCH" in gate["reason_codes"]
    assert gate["components"]["metadata_reconciliation"]["metrics"]["reason_codes"] == ["MANIFEST_PARQUET_MISMATCH"]
    plan_by_component = {item["component"]: item for item in gate["recovery_plan"]}
    assert plan_by_component["metadata_reconciliation"]["mode"] == "audit"


def test_provider_readiness_reports_required_credentials_and_optional_modules(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "tushare-token")
    monkeypatch.delenv("COINGECKO_API_KEY", raising=False)
    monkeypatch.delenv("COINGECKO_DEMO_API_KEY", raising=False)
    monkeypatch.setattr(
        "trade_py.utils.data_inspector._module_available",
        lambda module: module != "akshare",
    )

    stats = provider_readiness_stats(tmp_path)
    lines = build_status_lines({"as_of": "2026-03-20", "provider_readiness": stats})

    assert stats["status"] == "fail"
    assert "coingecko" in stats["missing_required"]
    assert "akshare" in stats["warn_optional"]
    assert stats["providers"]["tushare"]["credential_present"] is True
    assert stats["providers"]["coingecko"]["credential_present"] is False
    assert "PROVIDER_REQUIRED_UNAVAILABLE" in stats["reason_codes"]
    assert "PROVIDER_OPTIONAL_UNAVAILABLE" in stats["reason_codes"]
    plan_by_provider = {item["provider"]: item for item in stats["recovery_plan"]}
    assert plan_by_provider["coingecko"]["command"] == ["export", "COINGECKO_API_KEY=YOUR_KEY"]
    assert plan_by_provider["akshare"]["missing_modules"] == ["akshare"]
    assert any("数据源可用性" in line for line in lines)


def test_provider_readiness_passes_when_required_credentials_and_modules_exist(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "tushare-token")
    monkeypatch.setenv("COINGECKO_API_KEY", "coingecko-key")
    monkeypatch.setattr("trade_py.utils.data_inspector._module_available", lambda _module: True)

    stats = provider_readiness_stats(tmp_path)

    assert stats["status"] == "pass"
    assert stats["missing_required"] == []
    assert stats["warn_optional"] == []
    assert stats["recovery_plan"] == []
    assert stats["providers"]["coingecko"]["credential_present"] is True


def test_data_quality_gate_fails_on_provider_readiness_breakage() -> None:
    clean = {
        "kline_coverage": {"coverage_pct": 100.0},
        "kline_freshness": {"max_trading_day_stale_days": 0},
        "fund_flow": {"coverage_pct": 95.0, "stale_sample": [{"trading_day_stale_days": 0}]},
        "fundamental": {"coverage_pct": 100.0, "max_date": "2025-12-31"},
        "sentiment": {"gold": {"lag_days": 0, "max_date": "2026-03-20"}},
        "events": {"lag_days": 0, "event_count": 3},
        "cross_asset": {
            "gold": {"exists": True, "lag_days": 0},
            "fx_cnh": {"exists": True, "lag_days": 0},
            "btc": {"exists": True, "lag_days": 0},
        },
        "index": {"coverage_pct": 100.0, "stale_sample": [{"lag_days": 0}]},
        "northbound": {"exists": True, "lag_days": 0},
        "schema_contracts": {"status": "pass", "checked_files": 12, "failed_contracts": []},
        "value_quality": {"status": "pass", "checked_rows": 0, "failed_checks": []},
        "source_stability": {"status": "pass", "reason_codes": []},
        "metadata_reconciliation": {"status": "pass", "reason_codes": []},
        "provider_readiness": {
            "status": "fail",
            "reason_codes": ["PROVIDER_REQUIRED_UNAVAILABLE"],
            "missing_required": ["tushare", "coingecko"],
            "warn_optional": [],
            "recovery_plan": [
                {
                    "provider": "coingecko",
                    "command": ["export", "COINGECKO_API_KEY=YOUR_KEY"],
                    "mode": "configure",
                    "detail": "set CoinGecko key",
                }
            ],
        },
    }

    gate = build_data_quality_gate(clean)

    assert gate["status"] == "fail"
    assert "PROVIDER_READINESS_DEGRADED" in gate["reason_codes"]
    assert gate["components"]["provider_readiness"]["metrics"]["missing_required"] == [
        "tushare",
        "coingecko",
    ]
    assert gate["components"]["provider_readiness"]["metrics"]["recovery_plan"][0]["provider"] == "coingecko"
    plan_by_component = {item["component"]: item for item in gate["recovery_plan"]}
    assert plan_by_component["provider_readiness"]["mode"] == "configure"
    assert plan_by_component["provider_readiness"]["provider"] == "coingecko"
    assert plan_by_component["provider_readiness"]["command"] == ["export", "COINGECKO_API_KEY=YOUR_KEY"]
    assert plan_by_component["provider_readiness"]["missing_required"] == ["tushare", "coingecko"]


def test_provider_audit_reports_recent_tushare_auth_failures(tmp_path) -> None:
    audit_path = tmp_path / ".db" / "tushare_requests.jsonl"
    audit_path.parent.mkdir(parents=True)
    rows = [
        {"ts": "2026-03-20T09:00:00", "endpoint": "daily", "status": "success", "retry_index": 0},
        {
            "ts": "2026-03-20T09:01:00",
            "endpoint": "daily_basic",
            "status": "auth",
            "error_type": "TushareAuthError",
            "error_message": "invalid token",
            "retry_index": 0,
            "wait_ms": 0.0,
        },
    ]
    audit_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    stats = provider_audit_stats(tmp_path, sample_limit=5)
    lines = build_status_lines({"as_of": "2026-03-20", "provider_audit": stats})

    assert stats["status"] == "fail"
    assert stats["observed"] is True
    assert stats["providers"]["tushare"]["status_counts"]["auth"] == 1
    assert stats["providers"]["tushare"]["fail_statuses"] == ["auth"]
    assert stats["sample"][0]["endpoint"] == "daily_basic"
    assert stats["recovery_plan"][0]["command"] == ["trade", "account", "setting-set", "tushare_token", "YOUR_TOKEN"]
    assert "PROVIDER_AUDIT_RECENT_FAILURES" in stats["reason_codes"]
    assert any("数据源请求审计" in line for line in lines)


def test_provider_audit_warns_on_recent_rate_limits(tmp_path) -> None:
    audit_path = tmp_path / ".db" / "tushare_requests.jsonl"
    audit_path.parent.mkdir(parents=True)
    audit_path.write_text(
        json.dumps(
            {
                "ts": "2026-03-20T09:01:00",
                "endpoint": "moneyflow",
                "status": "rate_limit",
                "error_type": "TushareRateLimitError",
                "error_message": "too many requests",
                "retry_index": 2,
                "wait_ms": 15000,
            }
        ),
        encoding="utf-8",
    )

    stats = provider_audit_stats(tmp_path, sample_limit=5)

    assert stats["status"] == "warn"
    assert stats["providers"]["tushare"]["warn_statuses"] == ["rate_limit"]
    assert "PROVIDER_AUDIT_RECENT_WARNINGS" in stats["reason_codes"]
    assert stats["recovery_plan"][0]["mode"] == "tune"


def test_provider_audit_is_unknown_when_no_log_exists(tmp_path) -> None:
    stats = provider_audit_stats(tmp_path, sample_limit=5)

    assert stats["status"] == "unknown"
    assert stats["observed"] is False
    assert stats["reason_codes"] == []
    assert stats["providers"]["tushare"]["recent_requests"] == 0


def test_data_quality_gate_fails_on_provider_audit_failures() -> None:
    clean = {
        "kline_coverage": {"coverage_pct": 100.0},
        "kline_freshness": {"max_trading_day_stale_days": 0},
        "fund_flow": {"coverage_pct": 95.0, "stale_sample": [{"trading_day_stale_days": 0}]},
        "fundamental": {"coverage_pct": 100.0, "max_date": "2025-12-31"},
        "sentiment": {"gold": {"lag_days": 0, "max_date": "2026-03-20"}},
        "events": {"lag_days": 0, "event_count": 3},
        "cross_asset": {
            "gold": {"exists": True, "lag_days": 0},
            "fx_cnh": {"exists": True, "lag_days": 0},
            "btc": {"exists": True, "lag_days": 0},
        },
        "index": {"coverage_pct": 100.0, "stale_sample": [{"lag_days": 0}]},
        "northbound": {"exists": True, "lag_days": 0},
        "schema_contracts": {"status": "pass", "checked_files": 12, "failed_contracts": []},
        "value_quality": {"status": "pass", "checked_rows": 0, "failed_checks": []},
        "source_stability": {"status": "pass", "reason_codes": []},
        "metadata_reconciliation": {"status": "pass", "reason_codes": []},
        "provider_readiness": {"status": "pass", "reason_codes": []},
        "provider_audit": {
            "status": "fail",
            "observed": True,
            "reason_codes": ["PROVIDER_AUDIT_RECENT_FAILURES"],
            "providers": {
                "tushare": {
                    "status": "fail",
                    "recent_requests": 2,
                    "status_counts": {"auth": 1, "success": 1},
                    "fail_statuses": ["auth"],
                    "warn_statuses": [],
                }
            },
            "recovery_plan": [
                {
                    "status": "auth",
                    "command": ["trade", "account", "setting-set", "tushare_token", "YOUR_TOKEN"],
                    "mode": "configure",
                    "detail": "refresh token",
                }
            ],
        },
    }

    gate = build_data_quality_gate(clean)

    assert gate["status"] == "fail"
    assert "PROVIDER_AUDIT_DEGRADED" in gate["reason_codes"]
    assert gate["components"]["provider_audit"]["metrics"]["providers"]["tushare"]["status_counts"] == {
        "auth": 1,
        "success": 1,
    }
    plan_by_component = {item["component"]: item for item in gate["recovery_plan"]}
    assert plan_by_component["provider_audit"]["mode"] == "audit"


def test_cross_source_coverage_reports_required_missing_and_single_source_optional(tmp_path) -> None:
    stats = cross_source_coverage_stats(tmp_path)
    lines = build_status_lines({"as_of": "2026-03-20", "cross_source_coverage": stats})

    assert stats["status"] == "fail"
    assert stats["required_missing"] == ["cross_asset.btc", "kline"]
    assert stats["optional_single_source"] == ["cross_asset.fx_cnh", "cross_asset.gold"]
    assert "REQUIRED_CROSS_SOURCE_EVIDENCE_MISSING" in stats["reason_codes"]
    assert stats["datasets"]["kline"]["evidence_level"] == "provider_fallback_only"
    assert stats["datasets"]["kline"]["required_artifact"] == {
        "path": str(tmp_path / "market" / "kline" / "reconciliation" / "current.json"),
        "schema_version": "kline-reconciliation-v1",
        "status": "pass",
        "minimum_checked_rows": 1,
        "maximum_block_rows": 0,
        "shadow_sources": "non_empty",
    }
    assert stats["datasets"]["cross_asset.btc"]["reason_code"] == "BTC_RECONCILIATION_MISSING"
    plan_by_dataset = {item["dataset"]: item for item in stats["recovery_plan"]}
    assert plan_by_dataset["kline"]["mode"] == "generate"
    assert plan_by_dataset["kline"]["command"] == [
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
    assert plan_by_dataset["kline"]["preflight_command"][-1] == "--dry-run"
    assert plan_by_dataset["kline"]["required_artifact"]["schema_version"] == "kline-reconciliation-v1"
    assert plan_by_dataset["cross_asset.btc"]["mode"] == "sync"
    assert plan_by_dataset["cross_asset.btc"]["required_artifact"]["manifest_gate"] == "D3"
    assert any("多源交叉验证覆盖" in line for line in lines)
    assert any("recovery actions: 2" in line for line in lines)
    assert any("trade data kline reconcile" in line and "--dry-run" in line for line in lines)


def test_cross_source_coverage_accepts_ready_btc_reconciliation_manifest(tmp_path) -> None:
    btc_root = tmp_path / "market" / "cross_asset"
    run_dir = btc_root / "runs" / "btc" / "run-ready"
    run_dir.mkdir(parents=True)
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "run-ready",
                "health": {
                    "cross_source_validation": {
                        "status": "pass",
                        "aligned_rows": 3,
                        "block_rows": 0,
                        "max_basis_pct": 0.1,
                    }
                },
                "gates": [
                    {
                        "gate": "D3",
                        "status": "pass",
                        "metrics": {"aligned_rows": 3, "block_rows": 0},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (btc_root / "btc_current.json").write_text(
        json.dumps(
            {
                "run_id": "run-ready",
                "manifest_path": str(manifest_path),
                "canonical_sha256": "0" * 64,
            }
        ),
        encoding="utf-8",
    )

    stats = cross_source_coverage_stats(tmp_path)

    assert stats["datasets"]["cross_asset.btc"]["status"] == "pass"
    assert stats["datasets"]["cross_asset.btc"]["evidence_level"] == "provider_reconciliation"
    assert stats["datasets"]["cross_asset.btc"]["metrics"]["aligned_rows"] == 3
    assert stats["required_missing"] == ["kline"]


def test_cross_source_coverage_accepts_ready_kline_reconciliation_artifact(tmp_path) -> None:
    recon_root = tmp_path / "market" / "kline" / "reconciliation"
    recon_root.mkdir(parents=True)
    (recon_root / "current.json").write_text(
        json.dumps(
            {
                "schema_version": "kline-reconciliation-v1",
                "run_id": "kline-recon-ready",
                "status": "pass",
                "observed_at": "2026-03-20T15:30:00Z",
                "providers": {
                    "primary": "tushare",
                    "shadow": ["akshare", "tencent"],
                },
                "kline_manifest_hash": "f" * 64,
                "metrics": {
                    "checked_rows": 42,
                    "block_rows": 0,
                    "warn_rows": 1,
                    "max_close_basis_pct": 0.12,
                },
            }
        ),
        encoding="utf-8",
    )

    stats = cross_source_coverage_stats(tmp_path)
    item = stats["datasets"]["kline"]

    assert item["status"] == "pass"
    assert item["evidence_level"] == "provider_reconciliation"
    assert item["metrics"]["checked_rows"] == 42
    assert item["shadow_sources"] == ["akshare", "tencent"]
    assert stats["required_missing"] == ["cross_asset.btc"]


def test_cross_source_coverage_rejects_invalid_kline_reconciliation_artifact(tmp_path) -> None:
    recon_root = tmp_path / "market" / "kline" / "reconciliation"
    recon_root.mkdir(parents=True)
    (recon_root / "current.json").write_text(
        json.dumps(
            {
                "schema_version": "old-schema",
                "status": "pass",
                "providers": {"primary": "tushare", "shadow": ["akshare"]},
                "metrics": {"checked_rows": 10, "block_rows": 0},
            }
        ),
        encoding="utf-8",
    )

    stats = cross_source_coverage_stats(tmp_path)

    assert stats["datasets"]["kline"]["status"] == "fail"
    assert stats["datasets"]["kline"]["evidence_level"] == "invalid_artifact"
    assert stats["datasets"]["kline"]["reason_code"] == "KLINE_RECONCILIATION_SCHEMA_MISMATCH"


def test_cross_source_coverage_rejects_failing_kline_reconciliation_artifact(tmp_path) -> None:
    recon_root = tmp_path / "market" / "kline" / "reconciliation"
    recon_root.mkdir(parents=True)
    (recon_root / "current.json").write_text(
        json.dumps(
            {
                "schema_version": "kline-reconciliation-v1",
                "status": "fail",
                "providers": {"primary": "tushare", "shadow": ["akshare"]},
                "metrics": {"checked_rows": 10, "block_rows": 2},
            }
        ),
        encoding="utf-8",
    )

    stats = cross_source_coverage_stats(tmp_path)

    assert stats["datasets"]["kline"]["status"] == "fail"
    assert stats["datasets"]["kline"]["evidence_level"] == "provider_reconciliation_failed"
    assert stats["datasets"]["kline"]["reason_code"] == "KLINE_RECONCILIATION_NOT_READY"


def test_data_quality_gate_fails_on_cross_source_coverage_gap() -> None:
    clean = {
        "kline_coverage": {"coverage_pct": 100.0},
        "kline_freshness": {"max_trading_day_stale_days": 0},
        "fund_flow": {"coverage_pct": 95.0, "stale_sample": [{"trading_day_stale_days": 0}]},
        "fundamental": {"coverage_pct": 100.0, "max_date": "2025-12-31"},
        "sentiment": {"gold": {"lag_days": 0, "max_date": "2026-03-20"}},
        "events": {"lag_days": 0, "event_count": 3},
        "cross_asset": {
            "gold": {"exists": True, "lag_days": 0},
            "fx_cnh": {"exists": True, "lag_days": 0},
            "btc": {"exists": True, "lag_days": 0},
        },
        "index": {"coverage_pct": 100.0, "stale_sample": [{"lag_days": 0}]},
        "northbound": {"exists": True, "lag_days": 0},
        "schema_contracts": {"status": "pass", "checked_files": 12, "failed_contracts": []},
        "value_quality": {"status": "pass", "checked_rows": 0, "failed_checks": []},
        "source_stability": {"status": "pass", "reason_codes": []},
        "metadata_reconciliation": {"status": "pass", "reason_codes": []},
        "provider_readiness": {"status": "pass", "reason_codes": []},
        "provider_audit": {"status": "pass", "reason_codes": []},
        "cross_source_coverage": {
            "status": "fail",
            "reason_codes": ["REQUIRED_CROSS_SOURCE_EVIDENCE_MISSING"],
            "required_missing": ["kline", "cross_asset.btc"],
            "optional_single_source": ["cross_asset.gold"],
            "recovery_plan": [{"dataset": "kline", "mode": "generate"}],
        },
    }

    gate = build_data_quality_gate(clean)

    assert gate["status"] == "fail"
    assert "CROSS_SOURCE_COVERAGE_INCOMPLETE" in gate["reason_codes"]
    assert gate["components"]["cross_source_coverage"]["metrics"]["required_missing"] == [
        "kline",
        "cross_asset.btc",
    ]
    plan_by_component = {item["component"]: item for item in gate["recovery_plan"]}
    assert plan_by_component["cross_source_coverage"]["mode"] == "audit"
    assert gate["components"]["cross_source_coverage"]["metrics"]["recovery_plan"][0]["mode"] == "generate"


def test_stale_job_policy_converges_data_jobs(tmp_path) -> None:
    db = TradeDB(tmp_path)
    with db._conn_lock:
        db._conn.execute(
            """
            INSERT INTO job_runs(job_name, stage, status, started_at)
            VALUES (?, ?, 'running', datetime('now', 'localtime', '-8 hours'))
            """,
            ("kline_update", "fetch"),
        )
        db._conn.execute(
            """
            INSERT INTO job_runs(job_name, stage, status, started_at)
            VALUES (?, ?, 'running', datetime('now', 'localtime', '-2 hours'))
            """,
            ("crypto_btc_fetch", "fetch"),
        )
        db._conn.execute(
            """
            INSERT INTO job_runs(job_name, stage, status, started_at)
            VALUES (?, ?, 'running', datetime('now', 'localtime', '-10 minutes'))
            """,
            ("kline_update", "fetch"),
        )
        db._conn.commit()

    marked = db.job_runs_mark_stale_by_policy()

    with db._conn_lock:
        rows = db._conn.execute(
            "SELECT job_name, status, result_summary FROM job_runs ORDER BY id"
        ).fetchall()

    assert marked == 2
    assert [row["status"] for row in rows] == ["error", "error", "running"]
    assert "marked stale by policy" in rows[0]["result_summary"]
    assert "marked stale by policy" in rows[1]["result_summary"]
