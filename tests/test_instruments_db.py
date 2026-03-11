from __future__ import annotations

import sqlite3
import pandas as pd

from trade_py.data.market.index.tushare import IndexFetcher, _fetch_raw
from trade_py.db.instruments_db import InstrumentsDB


def test_upsert_instrument_sets_board_status_and_unknown_industry(tmp_path) -> None:
    db = InstrumentsDB(tmp_path)
    db.upsert_instrument("688001.SH", "科创样本")
    db.upsert_instrument("300001.SZ", "创业样本")
    db.upsert_instrument("430001.BJ", "北交样本")
    db.upsert_instrument("000001.SZ", "ST样本")
    db.upsert_instrument("000002.SZ", "*ST样本")

    rows = {
        row["symbol"]: dict(row)
        for row in db._conn.execute(
            "SELECT symbol, board, status, industry FROM instruments ORDER BY symbol"
        ).fetchall()
    }

    assert rows["688001.SH"]["board"] == 2
    assert rows["300001.SZ"]["board"] == 3
    assert rows["430001.BJ"]["board"] == 4
    assert rows["000001.SZ"]["board"] == 1
    assert rows["000001.SZ"]["status"] == 2
    assert rows["000002.SZ"]["status"] == 3
    assert all(row["industry"] == 255 for row in rows.values())


def test_classification_view_handles_old_st_rows_and_sector_mapping(tmp_path) -> None:
    db = InstrumentsDB(tmp_path)
    db.upsert_instrument("000001.SZ", "ST旧数据")
    db._conn.execute(
        "UPDATE instruments SET status = 1, board = 0, industry = 255 WHERE symbol = ?",
        ("000001.SZ",),
    )
    db._conn.execute(
        """
        INSERT INTO instrument_sector_members(symbol, sector_code, sector_name, industry_code)
        VALUES (?, ?, ?, ?)
        """,
        ("000001.SZ", "801170.SI", "银行", 17),
    )
    db._conn.commit()

    row = db._conn.execute(
        """
        SELECT is_st, sector_code, sector_name, industry_code, industry_name, status_name, board_name
        FROM instrument_classification_v
        WHERE symbol = ?
        """,
        ("000001.SZ",),
    ).fetchone()

    assert dict(row) == {
        "is_st": 1,
        "sector_code": "801170.SI",
        "sector_name": "银行",
        "industry_code": 17,
        "industry_name": "银行",
        "status_name": "停牌",
        "board_name": "主板",
    }


def test_refresh_sector_members_resolves_conflicts_by_latest_in_date(tmp_path, monkeypatch) -> None:
    """Conflicts (stock in 2+ current indices) are resolved by picking the most-recent in_date,
    not discarded. The stock_basic baseline also gets a separate call."""
    db = InstrumentsDB(tmp_path)
    db.upsert_instrument("000001.SZ", "平安银行")
    db.upsert_instrument("000002.SZ", "万科A")

    class FakePro:
        def call(self, name: str, **kwargs):
            if name == "stock_basic":
                return pd.DataFrame()  # empty baseline → rely solely on index_member
            assert name == "index_member"
            code = kwargs["index_code"]
            if code == "801170.SI":
                # 000001.SZ 在银行指数（in_date 20200101）
                return _frame_dated(["000001.SZ"], in_dates=["20200101"], out_dates=[""])
            if code == "801140.SI":
                # 000002.SZ 曾在房地产指数，早加入
                return _frame_dated(["000002.SZ"], in_dates=["20200101"], out_dates=[""])
            if code == "801180.SI":
                # 000002.SZ 也在非银金融指数，更晚加入 → 应胜出
                return _frame_dated(["000002.SZ"], in_dates=["20230101"], out_dates=[""])
            return pd.DataFrame()

    monkeypatch.setattr(
        "trade_py.data.market.tushare_client.get_pro_api",
        lambda _data_root: FakePro(),
    )

    fetcher = IndexFetcher(tmp_path)
    updated = fetcher.refresh_sector_members()

    # Both symbols must be mapped
    assert updated.get("000001.SZ") == 17   # 银行
    assert updated.get("000002.SZ") == 18   # 非银金融 (later in_date wins)

    conn = sqlite3.connect(str(tmp_path / ".metadata" / "trade.db"))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT symbol, sector_code, industry_code FROM instrument_sector_members ORDER BY symbol"
    ).fetchall()
    instruments = {
        row["symbol"]: row["industry"]
        for row in conn.execute(
            "SELECT symbol, industry FROM instruments ORDER BY symbol"
        ).fetchall()
    }
    conn.close()

    assert {r["symbol"]: r["industry_code"] for r in rows} == {
        "000001.SZ": 17,
        "000002.SZ": 18,
    }
    assert instruments == {
        "000001.SZ": 17,
        "000002.SZ": 18,
    }


def test_fetch_raw_uses_sw_daily_for_shenwan_indices(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class FakePro:
        def call(self, name: str, **kwargs):
            calls.append((name, kwargs["ts_code"]))
            return pd.DataFrame()

    monkeypatch.setattr(
        "trade_py.data.market.tushare_client.get_pro_api",
        lambda _data_root: FakePro(),
    )

    _fetch_raw("801010.SI", "data", start_date="2024-01-01", end_date="2024-01-31")
    _fetch_raw("000300.SH", "data", start_date="2024-01-01", end_date="2024-01-31")

    assert calls == [
        ("sw_daily", "801010.SI"),
        ("index_daily", "000300.SH"),
    ]


def _frame(symbols: list[str]):
    return pd.DataFrame({"ts_code": symbols})


def _frame_dated(
    symbols: list[str],
    in_dates: list[str] | None = None,
    out_dates: list[str] | None = None,
) -> pd.DataFrame:
    """Helper: create index_member-style DataFrame with in_date / out_date columns."""
    return pd.DataFrame({
        "ts_code":  symbols,
        "in_date":  in_dates  if in_dates  else [""] * len(symbols),
        "out_date": out_dates if out_dates else [""] * len(symbols),
    })
