"""Facts for an earnings lesson: the event, the price path around it, the history.

Everything is fetched fresh from Yahoo rather than read from data/market/kline,
whose backfill is missing roughly one session a month (the yfinance end-date
bug fixed in #23 for increments but never re-run for history).
"""
from __future__ import annotations

import warnings

import pandas as pd


def _closes(ticker: str, start: str) -> pd.Series:
    import yfinance as yf

    d = yf.download(ticker, start=start, auto_adjust=True, progress=False)
    d.columns = [c[0].lower() for c in d.columns]
    d.index = pd.to_datetime(d.index).tz_localize(None)
    return d["close"]


def fetch_earnings_case(ticker: str, bench: str = "SPY", *, n_history: int = 9,
                        before: int = 15, after: int = 25, start: str = "2024-05-01") -> dict:
    """The most recent reported quarter, framed for teaching.

    ``base`` is the last close that could not yet reflect the news, so every
    move is measured from it. Returns are kept at four decimals so rounding
    happens exactly once, at display time.
    """
    import yfinance as yf

    warnings.filterwarnings("ignore")
    px, bm = _closes(ticker, start), _closes(bench, start)
    if not px.index.equals(bm.index):
        raise ValueError(f"{ticker} and {bench} trading calendars differ")

    raw = yf.Ticker(ticker).get_earnings_dates(limit=n_history + 6)
    raw = raw.dropna(subset=["Reported EPS"]).sort_index()

    history = []
    for ts, r in raw.iterrows():
        local = ts.tz_convert("America/New_York")
        day = pd.Timestamp(local.date())
        after_close = local.hour >= 16
        base_i = (px.index.searchsorted(day, side="right") if after_close
                  else px.index.searchsorted(day)) - 1
        if base_i < 0 or (after_close and px.index[base_i] != day):
            continue  # announcement day missing from the price calendar

        def move(s: pd.Series, n: int, base_i: int = base_i) -> float | None:
            j = base_i + n
            return None if j >= len(s) else round(float(s.iloc[j] / s.iloc[base_i] - 1) * 100, 4)

        history.append(dict(
            announce=day.date().isoformat(), after_close=after_close, base_i=int(base_i),
            est=round(float(r["EPS Estimate"]), 2), act=round(float(r["Reported EPS"]), 2),
            surprise=round(float(r["Surprise(%)"]), 2),
            d1=move(px, 1), d5=move(px, 5), d20=move(px, 20),
            b1=move(bm, 1), b5=move(bm, 5), b20=move(bm, 20)))
    history = history[-n_history:]
    event = history[-1]
    b = event["base_i"]
    series = [dict(date=px.index[i].date().isoformat(), rel=i - b, close=round(float(px.iloc[i]), 2),
                   stock=round(float(px.iloc[i] / px.iloc[b] - 1) * 100, 4),
                   bench=round(float(bm.iloc[i] / bm.iloc[b] - 1) * 100, 4))
              for i in range(max(0, b - before), min(b + after, len(px) - 1) + 1)]
    return dict(ticker=ticker, bench=bench, event=event, series=series, history=history,
                base_close=round(float(px.iloc[b]), 2), data_through=px.index[-1].date().isoformat())
