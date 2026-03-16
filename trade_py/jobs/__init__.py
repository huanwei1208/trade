"""Job registry — scheduled jobs, each a plain (data_root) -> str callable.

DAG Stages:
  FETCH:   kline_update, cross_asset_fetch, market_index, fund_flow_update,
           northbound, sentiment_pipeline, sector_refresh, fundamental, macro
  COMPUTE: window_score, morning_brief, event_pipeline, event_backfill,
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
    fn: Callable[[str], str]   # (data_root) -> summary_str
    desc: str
    schedule: list[str]        # e.g. ["daily 07:00", "saturday 07:30"]
    stage: str = "fetch"       # fetch | compute | train
    tags: list[str] = field(default_factory=list)


# ── FETCH jobs ─────────────────────────────────────────────────────────────────

def _job_sentiment_pipeline(data_root: str) -> str:
    from trade_py.cli._sentiment import main as sentiment_main
    sentiment_main(["--fetch-mode", "incremental", "--data-root", data_root])
    return "情绪流水线完成"


def _job_cross_asset(data_root: str) -> str:
    from trade_py.data.market.cross_asset import fetch_all
    fetch_all(data_root)
    return "跨资产数据同步完成"


def _job_calendar_sync(data_root: str) -> str:
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
    return (
        f"交易日历同步: exchanges={summary.exchange_count} rows={summary.row_count} "
        f"range={summary.start_date}..{summary.end_date}"
    )


def _job_planned_event_sync(data_root: str) -> str:
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
    return (
        f"未来事件同步: eco={summary.eco_rows} disclosure={summary.disclosure_rows} "
        f"agenda={summary.agenda_rows} range={summary.start_date}..{summary.end_date}"
    )


def _job_planned_event_realize(data_root: str) -> str:
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


def _job_kline(data_root: str) -> str:
    from trade_py.data.market.kline import KlineSyncOptions, KlineSyncService
    service = KlineSyncService(data_root)
    summary = service.sync(KlineSyncOptions(mode="incremental"))
    return (
        f"K线同步: mode={summary.sync_mode} api_calls={summary.api_calls if summary.api_calls is not None else '-'} "
        f"{summary.total_symbols} symbols, {summary.total_rows} 行"
    )


def _job_realtime_quote_sync(data_root: str) -> str:
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
    return (
        f"实时分钟同步: requested={summary.requested_symbols} saved={summary.symbols_saved} "
        f"api_calls={summary.api_calls} rows={summary.rows_fetched}"
    )


def _job_realtime_compute(data_root: str) -> str:
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


def _job_market_index(data_root: str) -> str:
    from trade_py.data.market.index import IndexFetcher
    fetcher = IndexFetcher(data_root)
    fetcher.fetch_all()
    fetcher.fetch_sector_all()
    return "指数/板块日线同步完成"


def _job_fund_flow(data_root: str) -> str:
    from trade_py.data.market.fund_flow import FundFlowFetcher
    from trade_py.db.trade_db import TradeDB

    db = TradeDB(data_root)
    fetcher = FundFlowFetcher(data_root)
    watchlist = db.watchlist_get()
    symbols = watchlist or db.get_all_symbols()[:50]
    logger.info("Updating fund flow for %d symbols", len(symbols))
    fetcher.fetch_batch(symbols)
    return f"资金流向: {len(symbols)} symbols"


def _job_northbound(data_root: str) -> str:
    from trade_py.data.market.northbound import NorthboundFetcher
    fetcher = NorthboundFetcher(data_root)
    df = fetcher.fetch_and_save()
    return f"北向资金同步: {len(df)} 行"


def _job_fundamental(data_root: str) -> str:
    from trade_py.data.market.fundamental import FundamentalFetcher
    from trade_py.db.trade_db import TradeDB

    db = TradeDB(data_root)
    symbols = db.get_all_symbols()
    fetcher = FundamentalFetcher(data_root)
    fetcher.fetch_batch(symbols)
    return f"基本面数据同步: {len(symbols)} symbols"


def _job_macro(data_root: str) -> str:
    from trade_py.data.market.macro import MacroFetcher
    fetcher = MacroFetcher(data_root)
    datasets = ["gdp", "cpi", "ppi", "pmi"]
    for name in datasets:
        try:
            fetcher.fetch_and_save(name)
        except Exception as exc:
            logger.error("macro job: %s failed: %s", name, exc)
    return f"宏观数据同步完成: {', '.join(datasets)}"


def _job_sector_refresh(data_root: str) -> str:
    from trade_py.data.market.index import IndexFetcher
    fetcher = IndexFetcher(data_root)
    updated = fetcher.refresh_sector_members()
    return f"板块映射刷新: {len(updated)} 只标的"


# ── COMPUTE jobs ───────────────────────────────────────────────────────────────

def _job_window_score(data_root: str) -> str:
    from trade_py.signals.window_scorer import score_universe
    scores = score_universe(data_root)
    return f"全市场评分完成: {len(scores)} symbols"


def _job_morning_brief(data_root: str) -> str:
    from trade_py.report.morning_brief import generate
    path = generate(data_root)
    return f"晨报已生成: {path}"


def _job_event_pipeline(data_root: str) -> str:
    from trade_py.event import sync_events
    return sync_events(data_root).format()


def _job_event_backfill(data_root: str) -> str:
    from trade_py.event import backfill_events
    return backfill_events(data_root)


def _job_build_features(data_root: str) -> str:
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


def _job_build_labels(data_root: str) -> str:
    """Ensure event_propagations.actual_return_5d/20d are filled via backfill."""
    from trade_py.event import backfill_events
    result = backfill_events(data_root)
    return f"标签构建完成: {result}"


def _job_model_train(data_root: str) -> str:
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
        "sentiment_pipeline", _job_sentiment_pipeline, "LLM情绪流水线",
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
    "morning_brief": JobDef(
        "morning_brief", _job_morning_brief, "晨报生成",
        ["daily 07:45"], "compute", ["report"],
    ),
    "event_pipeline": JobDef(
        "event_pipeline", _job_event_pipeline, "事件提取+KG传导",
        ["daily 22:30"], "compute", ["event"],
    ),
    "event_backfill": JobDef(
        "event_backfill", _job_event_backfill, "回填超额收益",
        ["daily 15:35"], "compute", ["event"],
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
}


def run_job(name: str, data_root: str) -> str:
    """Execute a single job by name and return the summary string."""
    job_def = JOB_REGISTRY.get(name)
    if job_def is None:
        raise ValueError(f"Unknown job: {name!r}. Available: {sorted(JOB_REGISTRY)}")
    return job_def.fn(data_root)
