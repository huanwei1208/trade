"""Factor IC + quintile backtest for the project's technical factors.

Evaluates trade_py.factors.technical.compute_technical_factors (the project's own
factor code) on HS300 daily kline (hfq), producing:
  - daily cross-sectional RankIC per factor per horizon (1d/5d/20d)
  - mean IC, ICIR, t-stat, hit rate
  - quintile portfolio backtest (daily rebalance, close-to-close)
  - long-short spread and top-quintile excess over equal-weight universe

Usage: uv run python debug/eval_baseline/evaluate_factors.py
Outputs: debug/eval_baseline/results/*.csv + summary printed to stdout.
"""
from __future__ import annotations

import glob
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from trade_py.factors.definitions import TECHNICAL_DEFAULTS  # noqa: E402
from trade_py.factors.technical import compute_technical_factors  # noqa: E402

KLINE_DIR = ROOT / "data" / "market" / "kline"
RESULTS_DIR = Path(__file__).parent / "results"

HORIZONS = {"1d": 1, "5d": 5, "20d": 20}
FACTOR_COLS = list(TECHNICAL_DEFAULTS.keys())
WARMUP_DAYS = 30          # drop first rows per symbol (indicator warmup, default-filled)
MIN_CS_NAMES = 100        # require at least this many names per day for IC
N_QUANTILES = 5
COST_PER_TURNOVER = 0.0015  # one-way cost ~15bp (commission+slippage+stamp avg)
ANNUAL_DAYS = 244


def load_panel() -> pd.DataFrame:
    files = sorted(glob.glob(str(KLINE_DIR / "*.parquet")))
    frames = [pd.read_parquet(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    df["date"] = df["date"].astype(str).str.slice(0, 10)
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    return df


def add_forward_returns(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("symbol", group_keys=False)
    close = df["close"]
    for name, h in HORIZONS.items():
        df[f"fwd_{name}"] = g["close"].shift(-h) / close - 1.0
    return df


def build_factor_panel() -> pd.DataFrame:
    kline = load_panel()
    print(f"kline panel: {kline['symbol'].nunique()} symbols, "
          f"{kline['date'].nunique()} dates, {len(kline)} rows", flush=True)
    factors = compute_technical_factors(kline[["symbol", "date", "open", "high", "low", "close", "volume"]])
    panel = kline[["symbol", "date", "close"]].merge(factors, on=["symbol", "date"], how="inner")
    panel = add_forward_returns(panel)
    # drop indicator warmup rows per symbol
    panel["row_idx"] = panel.groupby("symbol").cumcount()
    panel = panel[panel["row_idx"] >= WARMUP_DAYS].drop(columns=["row_idx"])
    return panel


def daily_rank_ic(panel: pd.DataFrame) -> pd.DataFrame:
    """Return long frame: date, factor, horizon, ic."""
    records = []
    for date, day in panel.groupby("date"):
        if len(day) < MIN_CS_NAMES:
            continue
        for hname in HORIZONS:
            tgt = day[f"fwd_{hname}"]
            if tgt.notna().sum() < MIN_CS_NAMES:
                continue
            tgt_rank = tgt.rank()
            for fac in FACTOR_COLS:
                vals = day[fac]
                if vals.nunique() < 10:
                    continue
                ic = vals.rank().corr(tgt_rank)
                if ic is not None and not math.isnan(ic):
                    records.append((date, fac, hname, float(ic)))
    return pd.DataFrame(records, columns=["date", "factor", "horizon", "ic"])


def summarize_ic(ic_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (fac, hname), grp in ic_df.groupby(["factor", "horizon"]):
        s = grp["ic"]
        n = len(s)
        mean, std = s.mean(), s.std()
        # overlapping-horizon autocorrelation shrinks effective N
        eff_n = n / HORIZONS[hname]
        tstat = mean / std * math.sqrt(eff_n) if std > 0 else float("nan")
        rows.append({
            "factor": fac, "horizon": hname, "days": n,
            "mean_ic": round(mean, 4), "icir": round(mean / std, 3) if std > 0 else float("nan"),
            "t_stat": round(tstat, 2), "hit_rate": round((s > 0).mean(), 3),
        })
    out = pd.DataFrame(rows)
    return out.sort_values(["horizon", "mean_ic"], key=lambda c: c if c.name != "mean_ic" else c.abs(),
                           ascending=[True, False])


def quintile_backtest(panel: pd.DataFrame, factor: str) -> dict:
    """Daily-rebalanced quintile portfolios on fwd_1d. Returns summary metrics."""
    df = panel[["date", "symbol", factor, "fwd_1d"]].dropna()
    df = df[df.groupby("date")["symbol"].transform("size") >= MIN_CS_NAMES]
    if df.empty:
        return {}
    df["q"] = df.groupby("date")[factor].transform(
        lambda s: pd.qcut(s.rank(method="first"), N_QUANTILES, labels=False)
    )
    daily = df.groupby(["date", "q"])["fwd_1d"].mean().unstack()  # date × quintile
    bench = df.groupby("date")["fwd_1d"].mean()

    top, bot = daily[N_QUANTILES - 1], daily[0]
    ls = top - bot

    # top-quintile turnover: fraction of names replaced day over day
    top_sets = df[df["q"] == N_QUANTILES - 1].groupby("date")["symbol"].agg(set)
    turns = []
    prev = None
    for _, cur in top_sets.items():
        if prev is not None and len(prev) > 0:
            turns.append(1.0 - len(cur & prev) / len(prev))
        prev = cur
    turnover = float(np.mean(turns)) if turns else float("nan")

    def ann(r: pd.Series) -> float:
        return float(r.mean() * ANNUAL_DAYS)

    def sharpe(r: pd.Series) -> float:
        return float(r.mean() / r.std() * math.sqrt(ANNUAL_DAYS)) if r.std() > 0 else float("nan")

    top_excess = top - bench
    cost_drag = turnover * COST_PER_TURNOVER * ANNUAL_DAYS
    monotonic = daily.mean().is_monotonic_increasing or daily.mean().is_monotonic_decreasing
    return {
        "factor": factor,
        "quintile_ann_returns": [round(ann(daily[q]), 4) for q in range(N_QUANTILES)],
        "monotonic": monotonic,
        "ls_ann": round(ann(ls), 4),
        "ls_sharpe": round(sharpe(ls), 2),
        "top_excess_ann": round(ann(top_excess), 4),
        "top_excess_sharpe": round(sharpe(top_excess), 2),
        "top_turnover_daily": round(turnover, 3),
        "cost_drag_ann": round(cost_drag, 4),
        "top_excess_ann_net": round(ann(top_excess) - cost_drag, 4),
    }


def main() -> int:
    RESULTS_DIR.mkdir(exist_ok=True)
    panel = build_factor_panel()
    dates = sorted(panel["date"].unique())
    print(f"factor panel: {len(panel)} rows, {dates[0]} .. {dates[-1]}", flush=True)
    panel.to_parquet(RESULTS_DIR / "factor_panel.parquet", index=False)

    ic_df = daily_rank_ic(panel)
    ic_df.to_csv(RESULTS_DIR / "daily_ic.csv", index=False)
    summary = summarize_ic(ic_df)
    summary.to_csv(RESULTS_DIR / "ic_summary.csv", index=False)
    print("\n=== RankIC summary ===")
    print(summary.to_string(index=False))

    bt_rows = [r for fac in FACTOR_COLS if (r := quintile_backtest(panel, fac))]
    bt = pd.DataFrame(bt_rows)
    bt.to_csv(RESULTS_DIR / "quintile_backtest.csv", index=False)
    print("\n=== Quintile backtest (fwd_1d, daily rebalance) ===")
    print(bt.to_string(index=False))

    # yearly IC stability for the top factors by |mean_ic| at 5d
    ic_df["year"] = ic_df["date"].str.slice(0, 4)
    top_factors = summary[summary["horizon"] == "5d"].head(5)["factor"].tolist()
    yearly = (ic_df[(ic_df["horizon"] == "5d") & (ic_df["factor"].isin(top_factors))]
              .groupby(["factor", "year"])["ic"].mean().unstack().round(4))
    yearly.to_csv(RESULTS_DIR / "yearly_ic_top5.csv")
    print("\n=== Yearly mean IC (5d, top-5 factors) ===")
    print(yearly.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
