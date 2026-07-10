from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from trade_py.cli import data as data_cli
from trade_py.cli.data import _data_status_exit_code, _running_job_state
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
                "date": "2026-03-20",
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
        },
    }

    gate = build_data_quality_gate(clean)

    assert gate["status"] == "fail"
    assert "VALUE_QUALITY_INVALID_ROWS" in gate["reason_codes"]
    assert gate["components"]["value_quality"]["metrics"]["checked_rows"] == 123
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
