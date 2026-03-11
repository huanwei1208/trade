"""Job registry — 14 scheduled jobs, each a plain (data_root) -> str callable.

Scheduler (scheduler.py) wraps these with tracking/notifications.
CLI (cli/run.py) calls run_job() directly for ad-hoc execution.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class JobDef:
    name: str
    fn: Callable[[str], str]   # (data_root) -> summary_str
    desc: str
    schedule: list[str]        # e.g. ["daily 07:00", "saturday 07:30"]
    tags: list[str] = field(default_factory=list)


# ── Job implementations ────────────────────────────────────────────────────────

def _job_sentiment_pipeline(data_root: str) -> str:
    from trade_py.cli._sentiment import main as sentiment_main
    sentiment_main(["--fetch-mode", "incremental", "--data-root", data_root])
    return "情绪流水线完成"


def _job_cross_asset(data_root: str) -> str:
    from trade_py.data.market.cross_asset import fetch_all
    fetch_all(data_root)
    return "跨资产数据同步完成"


def _job_kline(data_root: str) -> str:
    from trade_py.data.market.kline import KlineSyncOptions, KlineSyncService
    service = KlineSyncService(data_root)
    summary = service.sync(KlineSyncOptions(mode="incremental"))
    return f"K线同步: {summary.total_symbols} symbols, {summary.total_rows} 行"


def _job_market_index(data_root: str) -> str:
    from trade_py.data.market.index import IndexFetcher
    fetcher = IndexFetcher(data_root)
    fetcher.fetch_all()
    fetcher.fetch_sector_all()
    return "指数/板块日线同步完成"


def _job_fund_flow(data_root: str) -> str:
    from trade_py.data.market.fund_flow import FundFlowFetcher
    from trade_py.db.instruments_db import InstrumentsDB
    from trade_py.db.settings_db import SettingsDB

    db = InstrumentsDB(data_root)
    fetcher = FundFlowFetcher(data_root)
    watchlist = SettingsDB(data_root).watchlist_get()
    symbols = watchlist or db.get_all_symbols()[:50]
    logger.info("Updating fund flow for %d symbols", len(symbols))
    fetcher.fetch_batch(symbols)
    return f"资金流向: {len(symbols)} symbols"


def _job_northbound(data_root: str) -> str:
    from trade_py.data.market.northbound import NorthboundFetcher
    fetcher = NorthboundFetcher(data_root)
    df = fetcher.fetch_and_save()
    return f"北向资金同步: {len(df)} 行"


def _job_window_score(data_root: str) -> str:
    from trade_py.signals.window_scorer import score_watchlist
    scores = score_watchlist(data_root)
    return f"窗口评分计算完成: {len(scores)} symbols"


def _job_morning_brief(data_root: str) -> str:
    from trade_py.report.morning_brief import generate
    path = generate(data_root)
    return f"晨报已生成: {path}"


def _job_fundamental(data_root: str) -> str:
    from trade_py.data.market.fundamental import FundamentalFetcher
    from trade_py.db.instruments_db import InstrumentsDB

    db = InstrumentsDB(data_root)
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


def _job_event_pipeline(data_root: str) -> str:
    from trade_py.event import sync_events

    return sync_events(data_root).format()


def _job_event_backfill(data_root: str) -> str:
    from trade_py.event import backfill_events

    return backfill_events(data_root)


def _job_sector_refresh(data_root: str) -> str:
    from trade_py.data.market.index import IndexFetcher
    fetcher = IndexFetcher(data_root)
    updated = fetcher.refresh_sector_members()
    return f"板块映射刷新: {len(updated)} 只标的"


def _job_model_inference(data_root: str) -> str:
    import json
    import numpy as np
    import pandas as pd
    from datetime import date as _date
    from trade_py.db.settings_db import SettingsDB

    model_dir = Path(data_root) / "models" / "propagation"
    features_path = Path(data_root) / "events" / "features.parquet"

    if not (model_dir / "return_5d.pkl").exists():
        return "模型文件不存在，跳过推理（请先运行 trade model train）"
    if not features_path.exists():
        return "特征文件不存在，跳过推理（请先运行 trade model build-features）"

    try:
        import joblib
    except ImportError:
        return "joblib 未安装，跳过推理"

    feat_cols_path = model_dir / "feature_cols.json"
    if feat_cols_path.exists():
        feat_cols = json.loads(feat_cols_path.read_text())
    else:
        from trade_py.analysis.feature_builder import ALL_FEATURE_COLS
        feat_cols = ALL_FEATURE_COLS

    df = pd.read_parquet(features_path)
    if df.empty:
        return "特征数据为空，跳过推理"
    latest = df.sort_values("date").groupby("symbol").last().reset_index()
    available_cols = [c for c in feat_cols if c in latest.columns]
    X = latest[available_cols].fillna(0).to_numpy(dtype=np.float32)
    symbols = latest["symbol"].tolist()

    model_5d = joblib.load(model_dir / "return_5d.pkl")
    scores_5d = model_5d.predict(X)
    ranks = np.argsort(np.argsort(scores_5d)) / max(len(scores_5d) - 1, 1) * 100

    risk_proba = None
    risk_path = model_dir / "loss_5pct_20d.pkl"
    if risk_path.exists():
        try:
            risk_model = joblib.load(risk_path)
            risk_proba = risk_model.predict_proba(X)[:, 1]
        except Exception as exc:
            logger.warning("risk model predict_proba failed: %s", exc)

    date_str = _date.today().isoformat()
    db = SettingsDB(data_root)
    for i, sym in enumerate(symbols):
        db.signal_cache_upsert(
            date_str, sym,
            model_score=float(ranks[i]),
            model_risk=float(risk_proba[i]) if risk_proba is not None else None,
            model_updated=date_str,
        )

    return f"模型推理完成: {len(symbols)} 只标的，model_score 已更新"


# ── Registry ───────────────────────────────────────────────────────────────────

JOB_REGISTRY: dict[str, JobDef] = {
    "kline_update": JobDef(
        "kline_update", _job_kline, "K线增量同步",
        ["daily 07:00"], ["market"],
    ),
    "cross_asset_fetch": JobDef(
        "cross_asset_fetch", _job_cross_asset, "跨资产行情抓取",
        ["daily 07:00"], ["market"],
    ),
    "market_index": JobDef(
        "market_index", _job_market_index, "市场/行业指数同步",
        ["daily 07:05"], ["market"],
    ),
    "fund_flow_update": JobDef(
        "fund_flow_update", _job_fund_flow, "资金流向同步",
        ["daily 07:30", "daily 15:15"], ["market"],
    ),
    "northbound": JobDef(
        "northbound", _job_northbound, "北向资金同步",
        ["daily 15:20"], ["market"],
    ),
    "window_score": JobDef(
        "window_score", _job_window_score, "窗口评分计算",
        ["daily 07:35", "daily 15:30"], ["signal"],
    ),
    "morning_brief": JobDef(
        "morning_brief", _job_morning_brief, "晨报生成",
        ["daily 07:45"], ["report"],
    ),
    "sentiment_pipeline": JobDef(
        "sentiment_pipeline", _job_sentiment_pipeline, "LLM情绪流水线",
        ["daily 22:00"], ["nlp"],
    ),
    "event_pipeline": JobDef(
        "event_pipeline", _job_event_pipeline, "事件提取+KG传导",
        ["daily 22:30"], ["event"],
    ),
    "event_backfill": JobDef(
        "event_backfill", _job_event_backfill, "回填超额收益",
        ["daily 15:35"], ["event"],
    ),
    "sector_refresh": JobDef(
        "sector_refresh", _job_sector_refresh, "板块成分映射刷新",
        ["saturday 07:30"], ["market"],
    ),
    "fundamental": JobDef(
        "fundamental", _job_fundamental, "财务数据同步",
        ["saturday 08:00"], ["market"],
    ),
    "macro": JobDef(
        "macro", _job_macro, "宏观数据同步",
        ["sunday 08:00"], ["market"],
    ),
    "model_inference": JobDef(
        "model_inference", _job_model_inference, "模型推理更新评分",
        ["daily 07:10"], ["model"],
    ),
}


def run_job(name: str, data_root: str) -> str:
    """Execute a single job by name and return the summary string."""
    job_def = JOB_REGISTRY.get(name)
    if job_def is None:
        raise ValueError(f"Unknown job: {name!r}. Available: {sorted(JOB_REGISTRY)}")
    return job_def.fn(data_root)
