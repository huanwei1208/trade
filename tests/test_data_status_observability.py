from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from trade_py.cli.data import _running_job_state
from trade_py.db.trade_db import TradeDB
from trade_py.utils.data_inspector import (
    build_status_lines,
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
