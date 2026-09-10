"""US morning sentinel report — what happened overnight, in three minutes.

Phase 2 of docs/美股路线计划.md. US markets close at 06:00 JST, so the
overnight job runs after the close and this renders what it found. The
report is an *information* surface, not a recommendation: every line is a
fact with a source, no scores or actions, because nothing in this pipeline
has been validated well enough to tell anyone what to buy (see #19, #22).

Sections, in the order a reader wants them:
  1. Watchlist — anything that touched a symbol the user actually follows
  2. Insider trades — open-market buys/sells, ranked by dollar value
  3. Material events — 8-K filings, grouped by the SEC's own item codes
  4. Price moves — biggest movers among covered symbols

Reads only Bronze/kline data already on disk; never fetches.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from trade_py.data.news.edgar import FORM4_CODE_LABELS, ITEM_8K_LABELS
from trade_py.data.pipeline.paths import bronze_path

logger = logging.getLogger(__name__)

# How much an 8-K item earns its place in a three-minute read. A market-wide
# day is ~200 filings dominated by micro-caps, so ordering by materiality is
# what makes the section readable; tier 0 is shown for watchlist names only.
ITEM_MATERIALITY = {
    "1.03": 3,  # bankruptcy
    "4.02": 3,  # financials no longer reliable
    "5.01": 3,  # change of control
    "2.01": 3,  # acquisition/disposition completed
    "2.02": 3,  # results announcement
    "2.06": 3,  # material impairment
    "1.01": 2,  # material agreement
    "1.02": 2,  # agreement terminated
    "2.05": 2,  # exit/restructuring costs
    "3.01": 2,  # listing deficiency
    "4.01": 2,  # auditor change
    "5.02": 2,  # officer/director change
    "2.03": 1, "2.04": 1, "3.02": 1, "3.03": 1, "5.03": 1,
    "5.07": 0, "7.01": 0, "8.01": 0, "9.01": 0,
}
MIN_MATERIALITY = 1  # below this, only watchlist symbols are shown
# Form 4 codes representing actual open-market decisions.
OPEN_MARKET_CODES = {"P", "S"}
MIN_INSIDER_USD = 100_000.0
TOP_N = 10


def _read_bronze(data_root: str | Path, source: str, day: date) -> pd.DataFrame:
    path = bronze_path(data_root, source, day)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _kline_move(data_root: str | Path, symbols: set[str], day: date) -> pd.DataFrame:
    """Close-to-close percent move for `day`, for symbols with local klines."""
    kdir = Path(data_root) / "market" / "kline"
    rows = []
    for sym in sorted(symbols):
        f = kdir / f"{sym}.parquet"
        if not f.exists():
            continue
        try:
            df = pd.read_parquet(f, columns=["date", "close"])
        except Exception:
            continue
        df = df.sort_values("date")
        idx = df.index[df["date"] == day.isoformat()]
        if len(idx) == 0:
            continue
        pos = df.index.get_loc(idx[0])
        if pos == 0:
            continue
        prev, cur = df["close"].iloc[pos - 1], df["close"].iloc[pos]
        if prev and prev > 0:
            rows.append({"ticker": sym, "close": cur, "pct": (cur / prev - 1) * 100})
    return pd.DataFrame(rows)


@dataclass
class SentinelReport:
    day: date
    watchlist: list[str] = field(default_factory=list)
    watchlist_hits: list[dict] = field(default_factory=list)
    insider: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    movers: list[dict] = field(default_factory=list)
    counts: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["day"] = self.day.isoformat()
        return d


def build_report(data_root: str | Path, day: date,
                 watchlist: list[str] | None = None) -> SentinelReport:
    watch = {w.strip().upper() for w in (watchlist or []) if w.strip()}
    rep = SentinelReport(day=day, watchlist=sorted(watch))

    filings = _read_bronze(data_root, "edgar", day)
    form4 = _read_bronze(data_root, "edgar_form4", day)
    rep.counts = {"filings_8k": len(filings), "insider_transactions": len(form4)}

    # --- Material events (8-K), expanded one row per item code ---------------
    if not filings.empty:
        ev = filings[filings["ticker"] != ""].copy()
        ev["item_list"] = ev["items"].map(json.loads)
        ev = ev.explode("item_list").dropna(subset=["item_list"])
        ev["materiality"] = ev["item_list"].map(ITEM_MATERIALITY).fillna(1).astype(int)
        ev = ev[(ev["materiality"] >= MIN_MATERIALITY) | ev["ticker"].isin(watch)]
        ev["label"] = ev["item_list"].map(ITEM_8K_LABELS).fillna(ev["item_list"])
        # One row per company: keep its most material item as the sort key and
        # collapse the labels, most material first, into a single line.
        grouped = (ev.sort_values("materiality", ascending=False)
                     .groupby(["ticker", "company", "url"])
                     .agg(label=("label", lambda s: list(dict.fromkeys(s))),
                          materiality=("materiality", "max"))
                     .reset_index())
        grouped["in_watchlist"] = grouped["ticker"].isin(watch)
        rep.events = (grouped.sort_values(["in_watchlist", "materiality", "ticker"],
                                          ascending=[False, False, True])
                             .head(TOP_N * 3).to_dict("records"))

    # --- Insider trades (Form 4), open-market only, by dollar value ----------
    if not form4.empty:
        ins = form4[form4["code"].isin(OPEN_MARKET_CODES)].copy()
        ins = ins[ins["value_usd"].notna() & (ins["value_usd"] >= MIN_INSIDER_USD)]
        if not ins.empty:
            agg = (ins.groupby(["ticker", "owner_name", "owner_title", "code"])
                      .agg(shares=("shares", "sum"), value_usd=("value_usd", "sum"),
                           url=("url", "first"))
                      .reset_index())
            agg["action"] = agg["code"].map(FORM4_CODE_LABELS).fillna(agg["code"])
            agg["in_watchlist"] = agg["ticker"].isin(watch)
            rep.insider = (agg.sort_values(["in_watchlist", "value_usd"], ascending=[False, False])
                              .head(TOP_N * 2).to_dict("records"))

    # --- Price moves among symbols that appeared, plus the watchlist ---------
    covered = set(watch)
    for frame in (filings, form4):
        if not frame.empty and "ticker" in frame:
            covered |= set(frame.loc[frame["ticker"] != "", "ticker"])
    moves = _kline_move(data_root, covered, day)
    if not moves.empty:
        moves["in_watchlist"] = moves["ticker"].isin(watch)
        moves["abs_pct"] = moves["pct"].abs()
        rep.movers = (moves.sort_values(["in_watchlist", "abs_pct"], ascending=[False, False])
                           .head(TOP_N).drop(columns="abs_pct").to_dict("records"))

    # --- Watchlist roll-up ---------------------------------------------------
    if watch:
        hits: dict[str, dict] = {}
        for e in rep.events:
            if e["in_watchlist"]:
                hits.setdefault(e["ticker"], {"ticker": e["ticker"], "events": [], "insider": []})
                hits[e["ticker"]]["events"] = e["label"]
        for i in rep.insider:
            if i["in_watchlist"]:
                h = hits.setdefault(i["ticker"], {"ticker": i["ticker"], "events": [], "insider": []})
                h["insider"].append(f"{i['owner_name']} ({i['owner_title'] or 'insider'}) "
                                    f"{i['action']} ${i['value_usd']:,.0f}")
        for m in rep.movers:
            if m["in_watchlist"] and m["ticker"] in hits:
                hits[m["ticker"]]["pct"] = m["pct"]
        rep.watchlist_hits = [hits[k] for k in sorted(hits)]
    return rep


def render_text(rep: SentinelReport) -> str:
    """Plain-text morning report."""
    L: list[str] = []
    L.append(f"美股哨兵 · {rep.day.isoformat()}")
    L.append(f"8-K 申报 {rep.counts.get('filings_8k', 0)} 份 · "
             f"内部人交易 {rep.counts.get('insider_transactions', 0)} 笔")

    if rep.watchlist:
        L.append("")
        L.append(f"── 自选股 ({len(rep.watchlist)} 只) " + "─" * 30)
        if not rep.watchlist_hits:
            L.append("  昨夜无事发生。")
        for h in rep.watchlist_hits:
            move = f"  [{h['pct']:+.2f}%]" if "pct" in h else ""
            L.append(f"  {h['ticker']}{move}")
            for e in h.get("events", []):
                L.append(f"    · 8-K: {e}")
            for i in h.get("insider", []):
                L.append(f"    · 内部人: {i}")

    if rep.insider:
        L.append("")
        L.append("── 内部人公开市场交易 (≥$100k) " + "─" * 20)
        for i in rep.insider[:TOP_N]:
            star = "*" if i["in_watchlist"] else " "
            L.append(f" {star}{i['ticker']:<6} {i['action']:<22} ${i['value_usd']:>12,.0f}  "
                     f"{i['owner_name']} ({i['owner_title'] or 'insider'})")

    if rep.events:
        L.append("")
        L.append("── 重大事件 (8-K) " + "─" * 32)
        for e in rep.events[:TOP_N * 2]:
            star = "*" if e["in_watchlist"] else " "
            L.append(f" {star}{e['ticker']:<6} {', '.join(e['label'])}")
            L.append(f"        {e['company'][:60]}")

    if rep.movers:
        L.append("")
        L.append("── 价格异动 " + "─" * 38)
        for m in rep.movers:
            star = "*" if m["in_watchlist"] else " "
            L.append(f" {star}{m['ticker']:<6} {m['pct']:+7.2f}%   close {m['close']:.2f}")

    L.append("")
    L.append("以上为事实陈述，非投资建议；本系统的预测能力尚未通过验证。")
    return "\n".join(L)
