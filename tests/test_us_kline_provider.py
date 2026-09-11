"""US kline provider: market detection, unit conventions, chain wiring."""

from __future__ import annotations

import pandas as pd
import pytest

from trade_py.data.market.kline.providers import (
    YfinanceKlineProvider,
    _finalize_frame,
    _validate_ohlc_frame,
    build_provider_chain,
)
from trade_py.utils.market_symbols import detect_market


@pytest.mark.parametrize("symbol,market", [
    ("600000.SH", "cn"),
    ("000001.SZ", "cn"),
    ("430047.BJ", "cn"),
    ("600000", "cn"),
    ("AAPL", "us"),
    ("BRK-B", "us"),
    ("MSFT.US", "us"),
    ("", "us"),
])
def test_detect_market(symbol: str, market: str) -> None:
    assert detect_market(symbol) == market


def _fake_yahoo_frame() -> pd.DataFrame:
    idx = pd.MultiIndex.from_product(
        [["Open", "High", "Low", "Close", "Volume"], ["AAPL"]],
        names=["Price", "Ticker"],
    )
    return pd.DataFrame(
        [[100.0, 105.0, 99.0, 104.0, 1_000_000],
         [104.0, 106.0, 103.0, 105.5, 2_000_000]],
        index=pd.DatetimeIndex(["2026-01-02", "2026-01-05"], name="Date"),
        columns=idx,
    )


def test_normalize_flattens_yahoo_multiindex() -> None:
    df = YfinanceKlineProvider._normalize(_fake_yahoo_frame(), "2026-01-01", "2026-01-31")
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert len(df) == 2


def test_finalize_us_volume_stays_in_shares() -> None:
    df = YfinanceKlineProvider._normalize(_fake_yahoo_frame(), "2026-01-01", "2026-01-31")
    out = _finalize_frame("AAPL", df)
    assert out["symbol"].iloc[0] == "AAPL"
    assert out["volume"].iloc[0] == 1_000_000
    # Yahoo gives no turnover amount; vwap must be NaN, never fabricated.
    assert out["vwap"].isna().all()
    # prev_close derives from the prior close.
    assert out["prev_close"].iloc[1] == pytest.approx(104.0)


def test_finalize_cn_volume_still_means_lots() -> None:
    df = pd.DataFrame({
        "date": ["2026-01-05", "2026-01-06"],
        "open": [10.0, 10.2], "high": [10.5, 10.6],
        "low": [9.9, 10.1], "close": [10.2, 10.4],
        "volume": [5_000, 6_000],           # lots (手)
        "amount": [5_100_000.0, 6_240_000.0],
    })
    out = _finalize_frame("600000.SH", df)
    # amount / (volume * 100) — the A-share lot convention must survive.
    assert out["vwap"].iloc[0] == pytest.approx(5_100_000.0 / 500_000)


def test_chain_registration() -> None:
    chain = build_provider_chain("yfinance")
    assert [p.name for p in chain._providers] == ["yfinance"]


def _yahoo_frame(dates: list[str]) -> pd.DataFrame:
    idx = pd.MultiIndex.from_product(
        [["Open", "High", "Low", "Close", "Volume"], ["AAPL"]],
        names=["Price", "Ticker"],
    )
    return pd.DataFrame(
        [[100.0, 105.0, 99.0, 104.0, 1_000_000]] * len(dates),
        index=pd.DatetimeIndex(dates, name="Date"),
        columns=idx,
    )


def test_end_is_passed_to_yahoo_as_exclusive(monkeypatch) -> None:
    """Project convention is an inclusive end; yfinance's is exclusive."""
    seen: dict[str, str] = {}

    def fake_fetch(yf, ticker, start, end, adjust):
        seen.update(ticker=ticker, start=start, end=end)
        return _yahoo_frame(["2026-09-02", "2026-09-03", "2026-09-04"])

    monkeypatch.setattr(YfinanceKlineProvider, "_fetch_raw", staticmethod(fake_fetch))
    out = YfinanceKlineProvider().fetch("AAPL", "2026-09-02", "2026-09-04")
    assert seen["end"] == "2026-09-05"          # one day past the request
    assert list(out["date"]) == ["2026-09-02", "2026-09-03", "2026-09-04"]


def test_rows_outside_the_window_are_clipped(monkeypatch) -> None:
    """Yahoo answers an empty window with the last bar before it."""
    monkeypatch.setattr(
        YfinanceKlineProvider, "_fetch_raw",
        staticmethod(lambda *a, **k: _yahoo_frame(["2026-09-09"])))
    out = YfinanceKlineProvider().fetch("AAPL", "2026-09-10", "2026-09-10")
    assert out.empty


def test_dotted_ticker_is_translated_for_yahoo(monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_fetch(yf, ticker, start, end, adjust):
        seen["ticker"] = ticker
        return _yahoo_frame(["2026-09-02"])

    monkeypatch.setattr(YfinanceKlineProvider, "_fetch_raw", staticmethod(fake_fetch))
    YfinanceKlineProvider().fetch("BRK.B", "2026-09-02", "2026-09-02")
    assert seen["ticker"] == "BRK-B"


def test_progress_disabled_respects_env(monkeypatch) -> None:
    from trade_py.utils.progress import progress_disabled

    # dagu's ssh2 executor allocates a PTY, so isatty() alone would say "show
    # the bar" for a scheduled run whose output goes to a log file.
    monkeypatch.setattr("sys.stderr", type("F", (), {"isatty": lambda self: True})())
    monkeypatch.delenv("TRADE_NO_PROGRESS", raising=False)
    assert progress_disabled() is False
    monkeypatch.setenv("TRADE_NO_PROGRESS", "1")
    assert progress_disabled() is True
    monkeypatch.setenv("TRADE_NO_PROGRESS", "0")
    assert progress_disabled() is False


def _bar(open_, high, low, close, date="2026-09-10") -> pd.DataFrame:
    return pd.DataFrame([{"date": date, "open": open_, "high": high,
                          "low": low, "close": close, "volume": 1_000}])


def test_repairs_high_that_predates_the_opening_print() -> None:
    """Real WSM 2026-09-10 bar as Yahoo served it ~2h after the close."""
    fixed = YfinanceKlineProvider._repair_stale_extremes(
        _bar(227.11000061035156, 225.64999389648438,
             221.14500427246094, 223.74000549316406), "WSM")
    # Yahoo itself later settled this bar at High=227.11.
    assert fixed["high"].iloc[0] == pytest.approx(227.11, abs=1e-6)
    _validate_ohlc_frame("WSM", fixed)          # must now pass validation


def test_repairs_low_above_the_body() -> None:
    fixed = YfinanceKlineProvider._repair_stale_extremes(
        _bar(100.0, 105.0, 99.5, 99.0), "X")    # low 99.5 > close 99.0
    assert fixed["low"].iloc[0] == pytest.approx(99.0)
    assert fixed["high"].iloc[0] == pytest.approx(105.0)   # untouched


def test_sound_bars_are_left_alone() -> None:
    good = _bar(100.0, 105.0, 99.0, 104.0)
    assert YfinanceKlineProvider._repair_stale_extremes(good, "X").equals(good)


def test_corruption_beyond_tolerance_is_not_repaired() -> None:
    """A hair off is a stale feed; wildly off is corruption the validator owns."""
    corrupt = _bar(300.0, 100.0, 90.0, 95.0)
    out = YfinanceKlineProvider._repair_stale_extremes(corrupt, "X")
    assert out["high"].iloc[0] == 100.0          # untouched
    with pytest.raises(ValueError, match="failed validation"):
        _validate_ohlc_frame("X", out)


def test_repair_runs_inside_fetch(monkeypatch) -> None:
    raw = pd.DataFrame(
        [[227.11000061035156, 225.64999389648438, 221.14500427246094,
          223.74000549316406, 1_000]],
        index=pd.DatetimeIndex(["2026-09-10"], name="Date"),
        columns=pd.MultiIndex.from_product(
            [["Open", "High", "Low", "Close", "Volume"], ["WSM"]],
            names=["Price", "Ticker"]),
    )
    monkeypatch.setattr(YfinanceKlineProvider, "_fetch_raw",
                        staticmethod(lambda *a, **k: raw))
    out = YfinanceKlineProvider().fetch("WSM", "2026-09-10", "2026-09-10")
    assert len(out) == 1
    assert out["high"].iloc[0] == pytest.approx(227.11, abs=1e-6)
