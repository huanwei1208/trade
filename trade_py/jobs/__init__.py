"""Job registry — scheduled jobs, each a plain (data_root) -> str callable.

DAG Stages:
  FETCH:   kline_update, cross_asset_fetch, market_index, fund_flow_update,
           northbound, sentiment_pipeline, sector_refresh, fundamental, macro
  COMPUTE: window_score, event_pipeline, event_backfill,
           build_features, build_labels
  TRAIN:   model_train  (writes to model_registry; inference is a separate service)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class JobDef:
    name: str
    fn: Callable[..., str]   # (data_root, config?, date_from?, date_to?) -> summary_str
    desc: str
    schedule: list[str]        # e.g. ["daily 07:00", "saturday 07:30"]
    stage: str = "fetch"       # fetch | compute | train
    tags: list[str] = field(default_factory=list)


# ── FETCH jobs ─────────────────────────────────────────────────────────────────

def _job_sentiment_pipeline(data_root: str, config: dict | None = None) -> str:
    from trade_py.engine import ingest_articles
    from trade_py.db.trade_db import TradeDB

    db = TradeDB(data_root)
    semantic_mode = str(db.get("sentiment.scheduler_semantic_mode", "base") or "base").strip().lower()
    if semantic_mode not in {"base", "hybrid", "llm"}:
        semantic_mode = "base"
    result = ingest_articles(
        "rss", data_root,
        fetch_mode="incremental",
        semantic_mode=semantic_mode,
    )
    return result.get("summary", f"情绪流水线完成: semantic_mode={semantic_mode}")


def _job_cross_asset(data_root: str, config: dict | None = None) -> str:
    from trade_py.data.market.cross_asset import fetch_all
    fetch_all(data_root)
    return "跨资产数据同步完成"


def _job_calendar_sync(data_root: str, config: dict | None = None) -> str:
    from trade_py.data.market.calendar import TradingCalendarService

    today = date.today()
    service = TradingCalendarService(data_root)
    try:
        summary = service.sync_calendar(
            start_date=date(today.year, 1, 1),
            end_date=date(today.year + 1, 12, 31),
        )
    finally:
        service.close()
    fallback = f" fallback={summary.fallback_reason}" if summary.fallback_used and summary.fallback_reason else ""
    return (
        f"交易日历同步: exchanges={summary.exchange_count} rows={summary.row_count} "
        f"range={summary.start_date}..{summary.end_date}{fallback}"
    )


def _job_planned_event_sync(data_root: str, config: dict | None = None) -> str:
    from trade_py.data.market.calendar import TradingCalendarService

    today = date.today()
    service = TradingCalendarService(data_root)
    try:
        summary = service.sync_planned_events(
            start_date=today - timedelta(days=7),
            end_date=today + timedelta(days=90),
            build_agenda=True,
        )
    finally:
        service.close()
    fallback = f" fallback={summary.fallback_reason}" if summary.fallback_used and summary.fallback_reason else ""
    return (
        f"未来事件同步: eco={summary.eco_rows} disclosure={summary.disclosure_rows} "
        f"agenda={summary.agenda_rows} cached={summary.cached_rows} "
        f"range={summary.start_date}..{summary.end_date}{fallback}"
    )


def _job_planned_event_realize(data_root: str, config: dict | None = None) -> str:
    from trade_py.event import realize_planned_events

    return realize_planned_events(data_root)


def _job_realtime_symbols(data_root: str, limit: int = 50) -> list[str]:
    from trade_py.db.trade_db import TradeDB

    db = TradeDB(data_root)
    watchlist = db.watchlist_get()
    if watchlist:
        return watchlist[:limit]
    rows = db.signal_suggest(limit=limit, by="model_score")
    return [str(row.get("symbol") or "").strip().upper() for row in rows if str(row.get("symbol") or "").strip()]


def _job_kline(data_root: str, config: dict | None = None,
               date_from: str | None = None, date_to: str | None = None) -> str:
    from trade_py.data.market.kline import KlineSyncOptions, KlineSyncService
    service = KlineSyncService(data_root)
    opts_kwargs: dict = {"mode": "incremental"}
    if date_from:
        opts_kwargs["start_date"] = date_from
    if date_to:
        opts_kwargs["end_date"] = date_to
    summary = service.sync(KlineSyncOptions(**opts_kwargs))
    return (
        f"K线同步: mode={summary.sync_mode} api_calls={summary.api_calls if summary.api_calls is not None else '-'} "
        f"{summary.total_symbols} symbols, {summary.total_rows} 行"
    )


def _job_realtime_quote_sync(data_root: str, config: dict | None = None) -> str:
    from trade_py.data.market.intraday import TushareIntradayFetcher

    symbols = _job_realtime_symbols(data_root, limit=50)
    fetcher = TushareIntradayFetcher(data_root)
    summary = fetcher.fetch_batch(
        symbols,
        freq="1MIN",
        lookback_minutes=90,
        chunk_size=50,
        asset="E",
    )
    degraded = f" degraded={summary.degraded_reason}" if summary.degraded_reason else ""
    return (
        f"实时分钟同步: requested={summary.requested_symbols} saved={summary.symbols_saved} "
        f"api_calls={summary.api_calls} rows={summary.rows_fetched} provider={summary.provider}{degraded}"
    )


def _job_realtime_compute(data_root: str, config: dict | None = None) -> str:
    from trade_py.analysis.intraday_runtime import compute_intraday_snapshot

    symbols = _job_realtime_symbols(data_root, limit=50)
    result = compute_intraday_snapshot(
        data_root,
        symbols=symbols,
        freq="1MIN",
        lookback_bars=30,
        top=20,
        persist_factors=True,
    )
    return (
        f"盘中计算: row_count={int(result.get('row_count') or 0)} "
        f"snapshot={result.get('snapshot_path') or '-'}"
    )


def _job_market_index(data_root: str, config: dict | None = None) -> str:
    from trade_py.data.market.index import IndexFetcher
    fetcher = IndexFetcher(data_root)
    fetcher.fetch_all()
    fetcher.fetch_sector_all()
    return "指数/板块日线同步完成"


def _job_fund_flow(data_root: str, config: dict | None = None) -> str:
    from trade_py.data.market.fund_flow import FundFlowFetcher
    from trade_py.db.trade_db import TradeDB

    db = TradeDB(data_root)
    fetcher = FundFlowFetcher(data_root)
    watchlist = db.watchlist_get()
    symbols = watchlist or db.get_all_symbols()[:50]
    logger.info("Updating fund flow for %d symbols", len(symbols))
    fetcher.fetch_batch(symbols)
    return f"资金流向: {len(symbols)} symbols"


def _job_northbound(data_root: str, config: dict | None = None) -> str:
    from trade_py.data.market.northbound import NorthboundFetcher
    fetcher = NorthboundFetcher(data_root)
    df = fetcher.fetch_and_save()
    return f"北向资金同步: {len(df)} 行"


def _job_fundamental(data_root: str, config: dict | None = None) -> str:
    from trade_py.data.market.fundamental import FundamentalFetcher
    from trade_py.db.trade_db import TradeDB

    db = TradeDB(data_root)
    symbols = db.get_all_symbols()
    fetcher = FundamentalFetcher(data_root)
    fetcher.fetch_batch(symbols)
    return f"基本面数据同步: {len(symbols)} symbols"


def _job_macro(data_root: str, config: dict | None = None) -> str:
    from trade_py.data.market.macro import MacroFetcher
    fetcher = MacroFetcher(data_root)
    datasets = ["gdp", "cpi", "ppi", "pmi"]
    for name in datasets:
        try:
            fetcher.fetch_and_save(name)
        except Exception as exc:
            logger.error("macro job: %s failed: %s", name, exc)
    return f"宏观数据同步完成: {', '.join(datasets)}"


def _job_sector_refresh(data_root: str, config: dict | None = None) -> str:
    from trade_py.data.market.index import IndexFetcher
    fetcher = IndexFetcher(data_root)
    updated = fetcher.refresh_sector_members()
    return f"板块映射刷新: {len(updated)} 只标的"


# ── COMPUTE jobs ───────────────────────────────────────────────────────────────

def _job_window_score(data_root: str, config: dict | None = None) -> str:
    from trade_py.signals.window_scorer import score_universe
    scores = score_universe(data_root)
    return f"全市场评分完成: {len(scores)} symbols"


def _job_event_pipeline(data_root: str, config: dict | None = None,
                         date_from: str | None = None, date_to: str | None = None) -> str:
    from trade_py.event import sync_events
    kwargs: dict = {}
    if date_from:
        kwargs["start"] = date_from
    if date_to:
        kwargs["end"] = date_to
    return sync_events(data_root, **kwargs).format()


def _job_event_backfill(data_root: str, config: dict | None = None) -> str:
    from trade_py.event import backfill_events
    return backfill_events(data_root)


def _job_evaluate_daily(data_root: str, config: dict | None = None) -> str:
    from trade_py.evaluation.service import evaluate_daily

    outcome = evaluate_daily(
        data_root,
        eval_date=date.today().isoformat(),
        use_cache=False,
    )
    return outcome.summary


def _job_build_features(data_root: str, config: dict | None = None) -> str:
    """Build feature matrix from event_propagations + signals + instruments."""
    from trade_py.analysis.propagation_runtime import (
        build_training_feature_frame,
        save_feature_maps,
    )

    out_dir = Path(data_root) / "events"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "features.parquet"
    df, maps = build_training_feature_frame(data_root)
    if df.empty:
        return "特征构建: 无事件传播数据，跳过"

    df.to_parquet(out_path, index=False)
    save_feature_maps(data_root, maps)
    labeled = df["actual_return_5d"].notna().sum()
    return f"特征构建完成: {len(df)} 条传播记录, {labeled} 条有标签"


def _job_build_labels(data_root: str, config: dict | None = None) -> str:
    """Ensure event_propagations.actual_return_5d/20d are filled via backfill."""
    from trade_py.event import backfill_events
    result = backfill_events(data_root)
    return f"标签构建完成: {result}"


def _job_model_train(data_root: str, config: dict | None = None) -> str:
    """Train propagation models and register candidates in model_registry."""
    from trade_py.analysis.propagation_training import train_models

    try:
        rows = train_models(data_root, backend="all", cv_splits=5, activate_backend=None)
    except FileNotFoundError:
        return "特征文件不存在，跳过训练（请先运行 build_features）"
    except Exception as exc:
        return f"模型训练失败: {exc}"

    if not rows:
        return "模型训练跳过：可用标签不足"

    summaries = []
    for row in rows:
        metrics = row.get("metrics", {})
        metric_name = metrics.get("cv_metric_name", "metric")
        metric_val = metrics.get("cv_metric")
        state = row.get("promotion_state", "candidate")
        if metric_val is not None:
            summaries.append(f"{row['target_name']}[{row['backend']}/{state}] {metric_name}={metric_val}")
        else:
            summaries.append(f"{row['target_name']}[{row['backend']}/{state}]")
    return "模型训练完成: " + "; ".join(summaries)


def _job_sentiment_fetch(data_root: str, config: dict | None = None,
                         date_from: str | None = None, date_to: str | None = None) -> str:
    """Fetch raw news to Bronze layer.

    fetch_mode:
      "incremental" (default) — existing batch path via sentiment CLI.
      "streaming"             — per-channel incremental fetch driven by
                                per-channel timestamp cursors stored in sync_state.
    """
    from trade_py.db.trade_db import TradeDB

    cfg = config or {}
    db = TradeDB(data_root)
    fetch_mode = str(cfg.get("fetch_mode", "incremental")).strip()

    if fetch_mode == "streaming":
        from trade_py.data.news.gdelt.source import GdeltSource
        src = GdeltSource()
        result = src.fetch_streaming(
            data_root, db,
            progress_cb=lambda msg: logger.info(msg),
        )
        ch_lines = []
        for r in result["channels"]:
            tag = f"[{r['new_articles']}新]"
            err = f" ⚠{r['error']}" if r["error"] else ""
            ch_lines.append(f"  {r['channel']}: {tag}{err}")
        # Identify useless channels from stats
        useless = sorted({
            s["channel"] for s in result["stats"] if s["useless"]
        })
        summary = "\n".join(ch_lines) if ch_lines else "  (无活跃频道)"
        useless_note = f"\n无效频道(avg<2/day): {', '.join(useless)}" if useless else ""
        return (
            f"streaming 抓取完成: 新增 {result['new_articles']} 篇\n"
            + summary + useless_note
        )

    # ── incremental / batch path via engine ─────────────────────────────────
    from trade_py.engine import ingest_articles

    semantic_mode = str(
        cfg.get("semantic_mode") or
        db.get("sentiment.scheduler_semantic_mode", "base") or "base"
    ).strip().lower()
    if semantic_mode not in {"base", "hybrid", "llm"}:
        semantic_mode = "base"
    result = ingest_articles(
        "rss", data_root,
        fetch_mode=fetch_mode,
        semantic_mode=semantic_mode,
        date_from=date_from,
        date_to=date_to,
    )
    return result.get("summary", f"情绪抓取完成: fetch_mode={fetch_mode} semantic_mode={semantic_mode}")


def _job_sentiment_silver(data_root: str, config: dict | None = None,
                           date_from: str | None = None, date_to: str | None = None) -> str:
    """Bronze → Silver: per-article sentiment scoring (checkpoint)."""
    from pathlib import Path
    silver_root = Path(data_root) / "sentiment" / "silver"
    files = list(silver_root.rglob("*.parquet")) if silver_root.exists() else []
    return f"情绪 Silver 检查: {len(files)} 个 parquet 文件"


def _job_sentiment_gold(data_root: str, config: dict | None = None,
                         date_from: str | None = None, date_to: str | None = None) -> str:
    """Silver → Gold: per-symbol/date aggregation (checkpoint)."""
    from pathlib import Path
    gold_root = Path(data_root) / "sentiment" / "gold"
    files = list(gold_root.rglob("*.parquet")) if gold_root.exists() else []
    return f"情绪 Gold 检查: {len(files)} 个 parquet 文件"


def _job_event_extract(data_root: str, config: dict | None = None,
                        date_from: str | None = None, date_to: str | None = None) -> str:
    """Extract market events from gold sentiment data."""
    from trade_py.event import sync_events
    kwargs: dict = {}
    if date_from:
        kwargs["start"] = date_from
    if date_to:
        kwargs["end"] = date_to
    return sync_events(data_root, **kwargs).format()


def _job_kg_propagate(data_root: str, config: dict | None = None,
                       date_from: str | None = None, date_to: str | None = None) -> str:
    """KG propagation: backfill actual returns for event propagations."""
    from trade_py.event import backfill_events
    return backfill_events(data_root)


def _job_influence_score(data_root: str, config: dict | None = None) -> str:
    """Score all feed sources and write InfluenceSignal records (EBRT Trust layer)."""
    from trade_py.intelligence.feed_scorer import score_all_sources
    from pathlib import Path
    scores = score_all_sources(Path(data_root))
    return f"信源影响力评分完成: {len(scores)} 个信源"


def _job_belief_update(data_root: str, config: dict | None = None) -> str:
    """Run BeliefEngine: compute attention + residual update → BeliefState."""
    from trade_py.engine import update_belief
    today = date.today().isoformat()
    result = update_belief(today, data_root)
    updated = result.get("symbols_updated", 0)
    errors = result.get("errors", 0)
    return f"信念更新完成: {updated} 个标的, errors={errors}"


def _job_recommend(data_root: str, config: dict | None = None) -> str:
    """Produce Recommendation + RecommendationTrace from BeliefState."""
    from trade_py.engine import produce_picks
    today = date.today().isoformat()
    recs = produce_picks(today, data_root)
    buys = sum(1 for r in recs if r.get("action") == "buy")
    return f"推荐决策完成: {len(recs)} 条, buy={buys}"


def _job_reliability_update(data_root: str, config: dict | None = None) -> str:
    """Update per-source reliability weights using Brier loss from T-5 recommendations."""
    from trade_py.evaluation.service import _update_source_reliabilities
    from trade_py.db.trade_db import TradeDB
    today = date.today().isoformat()
    db = TradeDB(data_root)
    try:
        n = _update_source_reliabilities(db, today)
    finally:
        db.close()
    return f"信源可靠性更新完成: {n} 个信源"


# ── Registry ───────────────────────────────────────────────────────────────────

JOB_REGISTRY: dict[str, JobDef] = {
    # FETCH stage
    "calendar_sync": JobDef(
        "calendar_sync", _job_calendar_sync, "交易日历同步",
        ["sunday 07:30"], "fetch", ["calendar", "meta"],
    ),
    "planned_event_sync": JobDef(
        "planned_event_sync", _job_planned_event_sync, "未来计划事件同步",
        ["daily 22:05"], "fetch", ["calendar", "event"],
    ),
    "planned_event_realize": JobDef(
        "planned_event_realize", _job_planned_event_realize, "未来计划事件落地",
        ["agenda post"], "compute", ["calendar", "event"],
    ),
    "kline_update": JobDef(
        "kline_update", _job_kline, "K线增量同步",
        ["daily 07:00"], "fetch", ["market"],
    ),
    "realtime_quote_sync": JobDef(
        "realtime_quote_sync", _job_realtime_quote_sync, "盘中分钟行情同步",
        ["weekday intraday"], "fetch", ["market", "intraday"],
    ),
    "cross_asset_fetch": JobDef(
        "cross_asset_fetch", _job_cross_asset, "跨资产行情抓取",
        ["daily 07:00"], "fetch", ["market"],
    ),
    "market_index": JobDef(
        "market_index", _job_market_index, "市场/行业指数同步",
        ["daily 07:05"], "fetch", ["market"],
    ),
    "fund_flow_update": JobDef(
        "fund_flow_update", _job_fund_flow, "资金流向同步",
        ["daily 07:30", "daily 15:15"], "fetch", ["market"],
    ),
    "northbound": JobDef(
        "northbound", _job_northbound, "北向资金同步",
        ["daily 15:20"], "fetch", ["market"],
    ),
    "sentiment_pipeline": JobDef(
        "sentiment_pipeline", _job_sentiment_pipeline, "情绪流水线",
        ["daily 22:00"], "fetch", ["nlp"],
    ),
    "sector_refresh": JobDef(
        "sector_refresh", _job_sector_refresh, "板块成分映射刷新",
        ["saturday 07:30"], "fetch", ["market"],
    ),
    "fundamental": JobDef(
        "fundamental", _job_fundamental, "财务数据同步",
        ["saturday 08:00"], "fetch", ["market"],
    ),
    "macro": JobDef(
        "macro", _job_macro, "宏观数据同步",
        ["sunday 08:00"], "fetch", ["market"],
    ),
    # COMPUTE stage
    "window_score": JobDef(
        "window_score", _job_window_score, "全市场窗口评分",
        ["daily 07:35", "daily 15:30"], "compute", ["signal"],
    ),
    "realtime_compute": JobDef(
        "realtime_compute", _job_realtime_compute, "盘中分钟因子计算",
        ["weekday intraday"], "compute", ["signal", "intraday"],
    ),
    "event_pipeline": JobDef(
        "event_pipeline", _job_event_pipeline, "事件提取+KG传导",
        ["daily 22:30"], "compute", ["event"],
    ),
    "event_backfill": JobDef(
        "event_backfill", _job_event_backfill, "回填超额收益",
        ["daily 15:35"], "compute", ["event"],
    ),
    "evaluate_daily": JobDef(
        "evaluate_daily", _job_evaluate_daily, "日常全链路评估",
        ["daily 22:45"], "compute", ["evaluate"],
    ),
    "build_features": JobDef(
        "build_features", _job_build_features, "特征矩阵构建",
        ["sunday 09:00"], "compute", ["model"],
    ),
    "build_labels": JobDef(
        "build_labels", _job_build_labels, "标签构建（回填收益）",
        ["sunday 09:05"], "compute", ["model"],
    ),
    # TRAIN stage
    "model_train": JobDef(
        "model_train", _job_model_train, "KG事件传播模型训练",
        ["sunday 09:10"], "train", ["model"],
    ),
    # EBRT: trust + belief + recommendation
    "influence_score": JobDef(
        "influence_score", _job_influence_score, "信源影响力评分（EBRT Trust）",
        ["sunday 09:05"], "compute", ["trust", "ebrt"],
    ),
    "belief_update": JobDef(
        "belief_update", _job_belief_update, "信念状态更新（EBRT）",
        [], "compute", ["belief", "ebrt"],
    ),
    "recommend": JobDef(
        "recommend", _job_recommend, "推荐决策生成（EBRT）",
        [], "compute", ["decision", "ebrt"],
    ),
    "reliability_update": JobDef(
        "reliability_update", _job_reliability_update, "信源可靠性奖惩更新（EBRT）",
        ["daily 15:40"], "compute", ["trust", "ebrt"],
    ),
    # Sentiment chain (split jobs)
    "sentiment_fetch": JobDef(
        "sentiment_fetch", _job_sentiment_fetch, "情绪抓取（增量/流式）",
        ["daily 22:00"], "fetch", ["nlp"],
    ),
    "sentiment_silver": JobDef(
        "sentiment_silver", _job_sentiment_silver, "情绪 Silver 评分",
        [], "fetch", ["nlp"],
    ),
    "sentiment_gold": JobDef(
        "sentiment_gold", _job_sentiment_gold, "情绪 Gold 聚合",
        [], "fetch", ["nlp"],
    ),
    "event_extract": JobDef(
        "event_extract", _job_event_extract, "事件提取",
        ["daily 22:30"], "compute", ["event"],
    ),
    "kg_propagate": JobDef(
        "kg_propagate", _job_kg_propagate, "KG 传导",
        [], "compute", ["event"],
    ),
}


def run_job(name: str, data_root: str,
            config: dict | None = None,
            date_from: str | None = None,
            date_to: str | None = None) -> str:
    """Execute a single job by name and return the summary string."""
    import json as _json
    job_def = JOB_REGISTRY.get(name)
    if job_def is None:
        raise ValueError(f"Unknown job: {name!r}. Available: {sorted(JOB_REGISTRY)}")
    # Load config from pipeline_dag if not provided
    if config is None:
        try:
            from trade_py.db.trade_db import TradeDB
            db = TradeDB(data_root)
            dag_meta = db.pipeline_dag_get_by_job(name)
            if dag_meta:
                config = _json.loads(dag_meta.get("config_json") or "{}")
        except Exception:
            config = {}
    cfg = config or {}
    import inspect as _inspect
    sig = _inspect.signature(job_def.fn)
    params = set(sig.parameters.keys())
    kwargs: dict = {}
    if "config" in params:
        kwargs["config"] = cfg
    if "date_from" in params and date_from is not None:
        kwargs["date_from"] = date_from
    if "date_to" in params and date_to is not None:
        kwargs["date_to"] = date_to
    return job_def.fn(data_root, **kwargs)
