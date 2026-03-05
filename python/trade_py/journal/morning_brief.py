from __future__ import annotations

"""Morning brief generator (09:10 each trading day).

Reads:
    - signal_cache from settings DB (watchlist window scores)
    - data/cross_asset/ (gold, BTC, USD/CNH latest values)
    - data/sentiment/gold/*.json (latest news headlines)
    - data/journal/decisions.parquet (yesterday's prediction retrospective)

Writes:
    - data/briefs/YYYY-MM-DD.md   (full morning brief)

If ANTHROPIC_API_KEY is set, calls Claude Haiku to generate the
3-sentence intelligence digest; otherwise uses a template placeholder.
"""

import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path
import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_DATA_ROOT = "data"


# ── Data loaders ───────────────────────────────────────────────────────────────

def _load_cross_asset(data_root: str) -> dict[str, dict]:
    """Return latest price + pct change for gold, BTC, USD/CNH."""
    result: dict[str, dict[str, float]] = {}
    assets = {
        "gold":   ("黄金 (Au99.99, CNY/g)", "close"),
        "btc":    ("BTC/USD", "close"),
        "fx_cnh": ("USD/CNH", "close"),
    }
    ca_dir = Path(data_root) / "cross_asset"
    for key, (label, col) in assets.items():
        p = ca_dir / f"{key}.parquet"
        if not p.exists():
            result[key] = {"label": label, "value": None, "pct": None}
            continue
        try:
            df = pd.read_parquet(p).sort_values("date")
            if len(df) < 2:
                result[key] = {"label": label, "value": df.iloc[-1][col], "pct": None}
                continue
            last = df.iloc[-1][col]
            prev = df.iloc[-2][col]
            pct = (last - prev) / prev * 100 if prev else None
            result[key] = {"label": label, "value": last, "pct": pct}
        except Exception:
            result[key] = {"label": label, "value": None, "pct": None}
    return result


def _cross_asset_env_score(ca: dict) -> float:
    """Rough macro environment score: higher = more risk-on (0-10)."""
    score = 5.0
    gold = ca.get("gold", {})
    btc  = ca.get("btc",  {})
    fx   = ca.get("fx_cnh", {})

    if gold.get("pct") is not None:
        # Gold rising = risk-off → lower score for equities
        score -= gold["pct"] * 0.3
    if btc.get("pct") is not None:
        # BTC rising = risk-on
        score += btc["pct"] * 0.1
    if fx.get("pct") is not None:
        # USD strengthening (CNH weakening = pct > 0) is mildly negative for A-shares
        score -= fx["pct"] * 0.5

    return max(0.0, min(10.0, round(score, 1)))


def _load_watchlist_signals(data_root: str, date_str: str) -> list[dict]:
    """Load today's signal cache from DB sorted by window_score desc."""
    try:
        import sys
        sys.path.insert(0, str(Path(data_root).parent / "python"))
        from trade_py.db.settings_db import SettingsDB
        db = SettingsDB(data_root)
        return db.signal_cache_get(date_str)
    except Exception:
        return []


def _load_recent_decisions(data_root: str, lookback_days: int = 5) -> list[dict]:
    """Load recent decisions for retrospective section."""
    path = Path(data_root) / "journal" / "decisions.parquet"
    if not path.exists():
        return []
    try:
        df = pd.read_parquet(path)
        cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
        if "entry_date" in df.columns:
            df = df[df["entry_date"].astype(str) >= cutoff]
        return df.tail(5).to_dict("records")
    except Exception:
        return []


def _load_latest_headlines(data_root: str, n: int = 5) -> list[str]:
    """Load the most recent news headlines from Silver Parquet (most recent date)."""
    silver_dir = Path(data_root) / "sentiment" / "silver"
    if not silver_dir.exists():
        return []
    # Find the most recent silver parquet file
    parquet_files = sorted(silver_dir.rglob("*.parquet"), reverse=True)
    if not parquet_files:
        return []
    try:
        df = pd.read_parquet(parquet_files[0])
        if "title" not in df.columns:
            return []
        # Sort by published_at if available; deduplicate titles
        if "published_at" in df.columns:
            df = df.sort_values("published_at", ascending=False)
        seen: set[str] = set()
        headlines = []
        for title in df["title"].dropna():
            t = str(title).strip()
            if t and t not in seen:
                seen.add(t)
                headlines.append(t)
            if len(headlines) >= n:
                break
        return headlines
    except Exception:
        return []


def _load_sentiment_context(data_root: str, date_str: str) -> dict:
    """Load Silver data for today: policy signals, negative shocks, market alerts.

    Returns dict with:
      policy_signals: list of (title, event_chain, time_sensitivity) for policy articles
      neg_shock_symbols: list of (symbol, neg_shock) sorted by severity
      market_scope_counts: {individual, sector, market} article counts
    """
    import datetime
    silver_dir = Path(data_root) / "sentiment" / "silver"
    if not silver_dir.exists():
        return {}

    target = datetime.date.fromisoformat(date_str)
    silver_path = (
        silver_dir / f"{target.year:04d}" / f"{target.month:02d}"
        / f"{date_str}.parquet"
    )
    if not silver_path.exists():
        return {}

    try:
        df = pd.read_parquet(silver_path)
    except Exception:
        return {}

    result: dict = {}

    # Policy signals
    if "policy_signal" in df.columns:
        policy_df = df[df["policy_signal"] == True][  # noqa: E712
            ["title", "event_chain", "time_sensitivity"]
        ].drop_duplicates(subset=["title"]).head(5)
        result["policy_signals"] = policy_df.to_dict("records")

    # Negative shock symbols (from Gold if available, else approximate from Silver)
    gold_path = (
        Path(data_root) / "sentiment" / "gold"
        / f"{target.year:04d}" / f"{target.month:02d}" / f"{date_str}.parquet"
    )
    if gold_path.exists():
        try:
            gold_df = pd.read_parquet(gold_path)
            if "neg_shock" in gold_df.columns:
                shocks = (
                    gold_df[gold_df["symbol"] != "_MARKET_"]
                    .nlargest(5, "neg_shock")[["symbol", "neg_shock", "net_sentiment"]]
                )
                result["neg_shock_symbols"] = shocks.to_dict("records")
        except Exception:
            pass

    # Market scope breakdown
    if "market_impact_scope" in df.columns:
        counts = df["market_impact_scope"].value_counts().to_dict()
        result["market_scope_counts"] = counts

    return result


def _generate_intelligence_digest(headlines: list[str], api_key: str | None) -> str:
    """Call Claude Haiku to produce a 3-sentence intelligence digest."""
    if not api_key or not headlines:
        if not headlines:
            return "1. 暂无最新情报\n2. —\n3. —"
        # Template fallback
        lines = []
        for i, h in enumerate(headlines[:3], 1):
            lines.append(f"{i}. {h}")
        return "\n".join(lines)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        headline_text = "\n".join(f"- {h}" for h in headlines[:10])
        prompt = (
            "以下是今日A股市场重要新闻摘要。请用3句话提炼出最重要的3条市场情报，"
            "格式：\n1. [情报1]\n2. [情报2]\n3. [情报3]\n\n"
            f"新闻列表：\n{headline_text}\n\n"
            "只输出编号的3句话，不要其他内容。"
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        logger.warning("Claude API call failed: %s", e)
        return "\n".join(f"{i+1}. {h}" for i, h in enumerate(headlines[:3]))


# ── Markdown builder ───────────────────────────────────────────────────────────

def _fmt_pct(pct: float | None) -> str:
    if pct is None:
        return "—"
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"


def build_brief_markdown(
    date_str: str,
    ca: dict,
    env_score: float,
    signals: list[dict],
    decisions: list[dict],
    digest: str,
    sentiment_ctx: dict | None = None,
) -> str:
    lines: list[str] = []
    lines.append(f"# 今日作战简报 {date_str}")
    lines.append("")

    # Macro environment
    lines.append("## 宏观环境")
    lines.append("")
    bar_filled = int(env_score)
    bar_str = "█" * bar_filled + "░" * (10 - bar_filled)
    lines.append(f"| 指标 | 最新值 | 变动 |")
    lines.append(f"|------|--------|------|")
    gold = ca.get("gold", {})
    btc  = ca.get("btc", {})
    fx   = ca.get("fx_cnh", {})
    lines.append(f"| 黄金 (Au99.99) | {gold.get('value', '—'):.2f} CNY/g | {_fmt_pct(gold.get('pct'))} |"
                 if gold.get("value") else "| 黄金 | — | — |")
    lines.append(f"| BTC/USD | {btc.get('value', '—'):.0f} | {_fmt_pct(btc.get('pct'))} |"
                 if btc.get("value") else "| BTC/USD | — | — |")
    lines.append(f"| USD/CNH | {fx.get('value', '—'):.4f} | {_fmt_pct(fx.get('pct'))} |"
                 if fx.get("value") else "| USD/CNH | — | — |")
    lines.append("")
    lines.append(f"**宏观情绪评分：** `{bar_str}` {env_score:.1f}/10")
    lines.append("")

    # Today's recommendation
    if env_score >= 7.0:
        rec = "✅ 积极布局"
        rec_reason = "跨资产风险偏好良好，可适当建仓"
    elif env_score >= 5.0:
        rec = "👀 谨慎观察"
        rec_reason = "市场中性，聚焦高窗口质量标的"
    else:
        rec = "⚠️ 观望为主"
        rec_reason = "避险情绪上升，降低仓位风险"

    lines.append("## 今日建议")
    lines.append("")
    lines.append(f"> **{rec}**")
    lines.append(f"> {rec_reason}")
    lines.append("")

    # Focus symbols (top 3 by window_score) — now includes sentiment column
    lines.append("## 重点关注（自选池 Top 3）")
    lines.append("")
    top3 = sorted(signals, key=lambda x: x.get("window_score") or 0, reverse=True)[:3]
    if top3:
        lines.append("| 股票 | 窗口质量 | 净情绪 | 信号 |")
        lines.append("|------|----------|--------|------|")
        for s in top3:
            sym       = s.get("symbol", "—")
            ws        = s.get("window_score", "—")
            net_sent  = s.get("net_sentiment")
            sent_str  = f"{net_sent:+.2f}" if net_sent is not None else "—"
            trend     = s.get("large_order_trend", "—") or "—"
            lines.append(f"| {sym} | {ws}/100 | {sent_str} | {trend} |")
    else:
        lines.append("*自选池为空或尚未评分 — 请先运行 `run_window_score.py`*")
    lines.append("")

    # Sentiment alerts (policy signals + negative shocks from Phase 4 Gold/Silver)
    ctx = sentiment_ctx or {}
    policy_signals = ctx.get("policy_signals", [])
    neg_shocks = ctx.get("neg_shock_symbols", [])
    scope_counts = ctx.get("market_scope_counts", {})

    if policy_signals or neg_shocks:
        lines.append("## 情绪预警")
        lines.append("")
        if policy_signals:
            lines.append("**政策/监管信号：**")
            lines.append("")
            for p in policy_signals[:3]:
                title = str(p.get("title", ""))[:50]
                chain = p.get("event_chain", "") or ""
                sens  = p.get("time_sensitivity", "") or ""
                tag   = f" `{chain}`" if chain else ""
                sens_tag = f" · {sens}" if sens else ""
                lines.append(f"- {title}{tag}{sens_tag}")
            lines.append("")
        if neg_shocks:
            lines.append("**负面冲击（个股）：**")
            lines.append("")
            lines.append("| 股票 | 负面冲击 | 净情绪 |")
            lines.append("|------|----------|--------|")
            for ns in neg_shocks:
                sym  = ns.get("symbol", "—")
                shock = float(ns.get("neg_shock", 0))
                net   = float(ns.get("net_sentiment", 0))
                lines.append(f"| {sym} | {shock:+.3f} | {net:+.2f} |")
            lines.append("")
        if scope_counts:
            total = sum(scope_counts.values())
            market_pct = scope_counts.get("market", 0) / total * 100 if total else 0
            if market_pct >= 30:
                lines.append(
                    f"> 今日 **{market_pct:.0f}%** 的新闻影响范围为全市场，"
                    f"请注意系统性风险。"
                )
                lines.append("")

    # Retrospective
    lines.append("## 昨日预测回溯")
    lines.append("")
    if decisions:
        lines.append("| 日期 | 股票 | 行动 | 叙事 |")
        lines.append("|------|------|------|------|")
        for d in decisions[-3:]:
            dt   = str(d.get("entry_date", d.get("date", "—")))[:10]
            sym  = d.get("symbol", "—")
            act  = d.get("action", "—")
            narr = str(d.get("narrative", ""))[:40]
            lines.append(f"| {dt} | {sym} | {act} | {narr} |")
    else:
        lines.append("*决策日志为空*")
    lines.append("")

    # Intelligence digest
    lines.append("## 今日情报（三句话）")
    lines.append("")
    for line in digest.strip().split("\n"):
        lines.append(line)
    lines.append("")

    lines.append("---")
    lines.append(f"*Generated at {date_str} — Trade 决策支持系统*")

    return "\n".join(lines)


# ── Main generate function ─────────────────────────────────────────────────────

def generate(
    data_root: str = _DEFAULT_DATA_ROOT,
    date_str: str | None = None,
    api_key: str | None = None,
) -> str:
    """Generate and save the morning brief. Returns the output file path."""
    if date_str is None:
        date_str = date.today().isoformat()

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    # Load inputs
    ca = _load_cross_asset(data_root)
    env_score = _cross_asset_env_score(ca)
    signals = _load_watchlist_signals(data_root, date_str)
    decisions = _load_recent_decisions(data_root)
    headlines = _load_latest_headlines(data_root)
    digest = _generate_intelligence_digest(headlines, api_key)
    sentiment_ctx = _load_sentiment_context(data_root, date_str)

    # Build markdown
    md = build_brief_markdown(date_str, ca, env_score, signals, decisions, digest,
                              sentiment_ctx=sentiment_ctx)

    # Save
    out_dir = Path(data_root) / "briefs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_str}.md"
    out_path.write_text(md, encoding="utf-8")
    logger.info("Morning brief saved: %s", out_path)
    return str(out_path)
