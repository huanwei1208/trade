"""US sentinel report: materiality ranking, insider filtering, watchlist roll-up."""

from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from trade_py.data.pipeline.paths import bronze_path
from trade_py.reports.us_sentinel import build_report, render_text

DAY = date(2026, 8, 25)


def _write(tmp_path, source: str, rows: list[dict]) -> None:
    p = bronze_path(tmp_path, source, DAY)
    p.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(p, index=False)


def _filing(ticker: str, items: list[str], company: str = "") -> dict:
    return {"adsh": f"a-{ticker}", "cik": "1", "company": company or f"{ticker} Inc",
            "form": "8-K", "file_date": DAY.isoformat(), "period_ending": "",
            "items": json.dumps(items), "sics": "[]", "ticker": ticker,
            "url": f"https://sec.gov/{ticker}"}


def _txn(ticker: str, code: str, value: float, owner: str = "Jane Doe",
         title: str = "CFO") -> dict:
    return {"adsh": f"f4-{ticker}-{owner}", "file_date": DAY.isoformat(),
            "url": f"https://sec.gov/f4/{ticker}", "issuer_cik": "1",
            "issuer_name": f"{ticker} Inc", "ticker": ticker,
            "owner_name": owner, "owner_title": title,
            "is_director": False, "is_officer": True,
            "transaction_date": DAY.isoformat(), "code": code,
            "acquired_disposed": "D" if code == "S" else "A",
            "shares": 100.0, "price": value / 100.0, "value_usd": value,
            "shares_after": 1000.0}


def test_events_ranked_by_materiality(tmp_path) -> None:
    _write(tmp_path, "edgar", [
        _filing("LOWSIG", ["8.01"]),          # tier 0 -> dropped (not watchlist)
        _filing("MIDSIG", ["5.02"]),          # tier 2
        _filing("TOPSIG", ["2.02", "9.01"]),  # tier 3
    ])
    rep = build_report(tmp_path, DAY)
    tickers = [e["ticker"] for e in rep.events]
    assert tickers == ["TOPSIG", "MIDSIG"]
    # most material label leads the collapsed line
    assert rep.events[0]["label"][0] == "results announcement"


def test_low_materiality_kept_for_watchlist(tmp_path) -> None:
    _write(tmp_path, "edgar", [_filing("MINE", ["8.01"])])
    rep = build_report(tmp_path, DAY, watchlist=["mine"])   # case-insensitive
    assert [e["ticker"] for e in rep.events] == ["MINE"]
    assert rep.events[0]["in_watchlist"]


def test_insider_open_market_only_and_threshold(tmp_path) -> None:
    _write(tmp_path, "edgar_form4", [
        _txn("BIG", "S", 5_000_000),
        _txn("SMALL", "S", 50_000),        # below MIN_INSIDER_USD
        _txn("GRANT", "A", 9_000_000),     # not an open-market decision
        _txn("BUY", "P", 200_000),
    ])
    rep = build_report(tmp_path, DAY)
    assert [i["ticker"] for i in rep.insider] == ["BIG", "BUY"]
    assert rep.insider[0]["action"] == "open-market sale"
    assert rep.insider[1]["action"] == "open-market purchase"


def test_insider_aggregates_per_person(tmp_path) -> None:
    _write(tmp_path, "edgar_form4", [
        _txn("ACME", "S", 400_000), _txn("ACME", "S", 300_000),
    ])
    rep = build_report(tmp_path, DAY)
    assert len(rep.insider) == 1
    assert rep.insider[0]["value_usd"] == pytest.approx(700_000)


def test_watchlist_rollup_and_render(tmp_path) -> None:
    _write(tmp_path, "edgar", [_filing("AMZN", ["2.02"]), _filing("OTHER", ["2.02"])])
    _write(tmp_path, "edgar_form4", [_txn("AMZN", "S", 5_180_213, "Jassy Andrew R", "CEO")])
    rep = build_report(tmp_path, DAY, watchlist=["AMZN"])

    assert [h["ticker"] for h in rep.watchlist_hits] == ["AMZN"]
    hit = rep.watchlist_hits[0]
    assert hit["events"] == ["results announcement"]
    assert "Jassy Andrew R" in hit["insider"][0] and "$5,180,213" in hit["insider"][0]

    text = render_text(rep)
    assert "美股哨兵 · 2026-08-25" in text
    assert "非投资建议" in text          # the report never recommends
    assert "*AMZN" in text               # watchlist marker


def test_empty_day_renders_without_error(tmp_path) -> None:
    rep = build_report(tmp_path, DAY, watchlist=["AAPL"])
    assert rep.events == [] and rep.insider == [] and rep.watchlist_hits == []
    assert "昨夜无事发生" in render_text(rep)


def test_symbols_file_skips_comments_and_blanks(tmp_path) -> None:
    from trade_py.cli.data import _read_symbols_file

    f = tmp_path / "universe.txt"
    f.write_text("# header comment\n\nAAPL\n  MSFT  \n# trailing note\nBRK-B\n")
    assert _read_symbols_file(f) == ["AAPL", "MSFT", "BRK-B"]
