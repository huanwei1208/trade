"""Fetch HS300 daily kline (hfq) via Sina into project-standard parquet files.

Standalone data backfill for factor evaluation — does not touch product code.
Resumable: skips symbols whose parquet already exists.

Usage: uv run python debug/eval_baseline/fetch_hs300.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import akshare as ak
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "market" / "kline"
SYMBOLS_FILE = Path(__file__).parent / "hs300_symbols.txt"
START, END = "20210101", "20260704"
DELAY_SEC = 0.6
RETRIES = 3

COLUMN_ORDER = [
    "symbol", "date", "open", "high", "low", "close",
    "volume", "amount", "turnover_rate", "prev_close", "vwap",
]


def fetch_one(symbol: str) -> pd.DataFrame:
    code, suffix = symbol.split(".")
    sina_code = suffix.lower() + code
    df = ak.stock_zh_a_daily(symbol=sina_code, start_date=START, end_date=END, adjust="hfq")
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.reset_index() if "date" not in df.columns else df
    out = pd.DataFrame()
    out["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    for col in ("open", "high", "low", "close", "volume", "amount"):
        out[col] = pd.to_numeric(df.get(col), errors="coerce")
    out["turnover_rate"] = pd.to_numeric(df.get("turnover"), errors="coerce") * 100.0
    out["symbol"] = symbol
    out = out.sort_values("date").reset_index(drop=True)
    out["prev_close"] = out["close"].shift(1)
    vol = out["volume"].replace(0, pd.NA)
    out["vwap"] = out["amount"] / vol
    return out[COLUMN_ORDER]


def main() -> int:
    symbols = SYMBOLS_FILE.read_text().strip().split(",")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    done = skipped = failed = 0
    failures: list[str] = []
    for i, symbol in enumerate(symbols, 1):
        path = OUT_DIR / f"{symbol.replace('.', '_')}.parquet"
        if path.exists():
            skipped += 1
            continue
        ok = False
        for attempt in range(1, RETRIES + 1):
            try:
                df = fetch_one(symbol)
                if df.empty:
                    print(f"[{i}/{len(symbols)}] {symbol} EMPTY", flush=True)
                    break
                df.to_parquet(path, index=False)
                print(f"[{i}/{len(symbols)}] {symbol} ok rows={len(df)} "
                      f"range={df['date'].iloc[0]}..{df['date'].iloc[-1]}", flush=True)
                ok = True
                break
            except Exception as exc:
                wait = 2.0 * attempt
                print(f"[{i}/{len(symbols)}] {symbol} attempt={attempt} "
                      f"err={type(exc).__name__}: {str(exc)[:100]} retry_in={wait}s", flush=True)
                time.sleep(wait)
        if ok:
            done += 1
        else:
            failed += 1
            failures.append(symbol)
        time.sleep(DELAY_SEC)
    print(f"DONE fetched={done} skipped={skipped} failed={failed}", flush=True)
    if failures:
        print("FAILED_SYMBOLS=" + ",".join(failures), flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
