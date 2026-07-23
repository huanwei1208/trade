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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


class JobQualityWarning(RuntimeError):
    """A job produced auditable evidence but is not yet quality-gate complete."""


@dataclass
class JobDef:
    name: str
    fn: Callable[..., str]  # (data_root, config?, date_from?, date_to?) -> summary_str
    desc: str
    schedule: list[str]  # e.g. ["daily 07:00", "saturday 07:30"]
    stage: str = "fetch"  # fetch | compute | train
    tags: list[str] = field(default_factory=list)


def _iter_target_dates(date_from: str | None = None, date_to: str | None = None) -> list[str]:
    if not date_from and not date_to:
        return [date.today().isoformat()]
    start_day = date.fromisoformat((date_from or date_to or date.today().isoformat())[:10])
    end_day = date.fromisoformat((date_to or date_from or date.today().isoformat())[:10])
    if end_day < start_day:
        start_day, end_day = end_day, start_day
    days: list[str] = []
    cursor = start_day
    while cursor <= end_day:
        days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


# ── FETCH jobs ─────────────────────────────────────────────────────────────────


def _job_sentiment_pipeline(
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    from trade_py.db.trade_db import TradeDB
    from trade_py.engine import ingest_articles

    cfg = config or {}
    db = TradeDB(data_root)
    semantic_mode = (
        str(
            cfg.get("semantic_mode")
            or db.get("sentiment.scheduler_semantic_mode", "base")
            or "base"
        )
        .strip()
        .lower()
    )
    if semantic_mode not in {"base", "hybrid", "llm"}:
        semantic_mode = "base"
    fetch_mode = (
        str(cfg.get("fetch_mode") or ("range" if (date_from or date_to) else "incremental"))
        .strip()
        .lower()
    )
    result = ingest_articles(
        "rss",
        data_root,
        fetch_mode=fetch_mode,
        semantic_mode=semantic_mode,
        date_from=date_from,
        date_to=date_to,
    )
    return result.get(
        "summary", f"情绪流水线完成: fetch_mode={fetch_mode} semantic_mode={semantic_mode}"
    )


def _job_cross_asset(data_root: str, config: dict | None = None) -> str:
    """Deprecated: kept for backwards compatibility.

    Routes gold/FX sync to the new split asset modules. For full crypto/fx/commodity
    coverage use ``asset_batch_ingest`` instead.
    """
    # Prefer new split modules; fall back to legacy cross_asset shim.
    try:
        from trade_py.data.market.commodity.akshare import fetch_gold_ohlc as fetch_gold
    except ImportError:
        from trade_py.data.market.cross_asset import fetch_gold
    try:
        from trade_py.data.market.fx.akshare import fetch_usdcnh_ohlc as _fetch_fx

        def fetch_fx_cnh(data_root: str):
            return _fetch_fx(data_root)
    except ImportError:
        from trade_py.data.market.cross_asset import fetch_fx_cnh

    gold = fetch_gold(data_root)
    fx = fetch_fx_cnh(data_root)
    if gold.empty or fx.empty:
        raise RuntimeError("Gold/FX 多资产数据同步不完整")
    return "多资产数据同步完成 (legacy job, prefer asset_batch_ingest): gold,fx_cnh"


def _job_crypto_btc_fetch(data_root: str, config: dict | None = None) -> str:
    """Legacy BTC fetch: runs assurance-gated sync with BtcMarketDataService."""
    from trade_py.data.market.cross_asset.service import BtcMarketDataService

    service = BtcMarketDataService(data_root)
    payload = service.sync()
    if not payload.get("published", False):
        readiness = payload.get("data_readiness", "unknown")
        gates = {
            str(gate.get("gate")): gate
            for gate in (payload.get("gates") or [])
            if isinstance(gate, dict)
        }
        pilot_pending = (
            readiness == "degraded"
            and bool(payload.get("staged"))
            and (gates.get("D1") or {}).get("reason_code") == "ACQUISITION_STABILITY_INSUFFICIENT"
            and all(
                (gates.get(name) or {}).get("status") == "pass" for name in ("D0", "D2", "D3", "D4")
            )
        )
        if pilot_pending:
            metrics = gates["D1"].get("metrics") or {}
            observed = int(metrics.get("successful_acquisition_days") or 0)
            required = int(metrics.get("required_successful_acquisition_days") or 0)
            raise JobQualityWarning(
                "BTC 候选已暂存，等待采集稳定性门禁: "
                f"run_id={payload.get('run_id')} qualified_days={observed}/{required}"
            )
        raise RuntimeError(f"BTC 数据未发布完成: readiness={readiness}")
    return f"BTC 同步完成: run_id={payload.get('run_id')}"


def _crypto_news_to_sentiment_silver(analyzed: list[dict], today: str) -> list[dict]:
    """Map crypto news analysis records to sentiment/silver-compatible rows.

    One fan-out row per mentioned crypto symbol, plus a _CRYPTO_MARKET_ row
    for market-wide items, so the event pipeline can consume them.
    """
    rows: list[dict] = []
    for a in analyzed:
        symbols = a.get("affected_symbols") or []
        sectors = a.get("affected_sectors") or []
        event_type = a.get("event_type", "other")
        market_scope = a.get("market_scope", "individual")
        scope_map = {"market": "market", "sector": "sector", "individual": "company"}
        impact_scope = scope_map.get(market_scope, "sector" if symbols else "market")
        is_market_wide = impact_scope == "market" or len(sectors) >= 2 or not symbols

        targets: list[str] = []
        if is_market_wide:
            targets.append("_CRYPTO_MARKET_")
        targets.extend(symbols)

        for sym in targets:
            rows.append(
                {
                    "date": today,
                    "symbol": sym,
                    "source": a.get("source", "crypto"),
                    "content_hash": a.get("content_hash", ""),
                    "title": a.get("title", ""),
                    "text": a.get("summary", ""),
                    "sentiment_score": float(a.get("sentiment_score", 0.0)),
                    "sentiment_label": a.get("sentiment_label", "neutral"),
                    "event_type": event_type,
                    "event_magnitude": float(a.get("event_magnitude", 0.0)),
                    "affected_sectors": ",".join(sectors),
                    "key_entities": ",".join(symbols),
                    "summary": (a.get("title", "") or "")[:200],
                    "confidence": float(a.get("event_confidence", 0.5)),
                    "published_at": a.get("published_at", ""),
                    "policy_signal": 1
                    if event_type
                    in {"regulation_ban", "regulatory_action", "etf_approval", "etf_rejection"}
                    else 0,
                    "market_impact_scope": impact_scope,
                    "time_sensitivity": a.get(
                        "urgency", "short_term" if a.get("is_urgent") else "normal"
                    ),
                    "event_chain": event_type,
                    "semantic_mode": "base",
                    "semantic_source": "crypto_base",
                    "base_sentiment_score": float(a.get("sentiment_score", 0.0)),
                    "base_sentiment_label": a.get("sentiment_label", "neutral"),
                    "base_event_type": event_type,
                    "base_event_magnitude": float(a.get("event_magnitude", 0.0)),
                    "base_affected_sectors": ",".join(sectors),
                    "base_key_entities": ",".join(symbols),
                    "base_summary": (a.get("title", "") or "")[:200],
                    "base_confidence": float(a.get("event_confidence", 0.5)),
                    "base_policy_signal": 1
                    if event_type
                    in {"regulation_ban", "regulatory_action", "etf_approval", "etf_rejection"}
                    else 0,
                    "base_market_impact_scope": impact_scope,
                    "base_time_sensitivity": a.get(
                        "urgency", "short_term" if a.get("is_urgent") else "normal"
                    ),
                    "base_event_chain": event_type,
                    "base_entity_density": min(1.0, (len(symbols) + len(sectors)) / 5.0),
                    "base_novelty_score": float(a.get("novelty_score", 1.0)),
                    "base_noise_score": float(a.get("noise_score", 0.0)),
                }
            )
    return rows


def _job_crypto_news_sentiment(data_root: str, config: dict | None = None) -> str:
    """Fetch crypto news and Fear & Greed Index, run base sentiment analysis, publish bus events."""
    from trade_py.bus import Topic, get_bus
    from trade_py.bus.models import AdmissionOutcome
    from trade_py.data.market.cross_asset.crypto_sentiment import (
        fetch_all_crypto_news,
        fetch_fear_greed,
        save_crypto_news_parquet,
        save_fear_greed_parquet,
    )
    from trade_py.db.trade_db import TradeDB
    from trade_py.intelligence.crypto_base_factors import analyze_crypto_news

    root = Path(data_root)
    today = date.today().isoformat()

    # 1. Fear & Greed Index — canonical path is market/crypto/fear_greed.parquet;
    # also mirror to legacy cross_asset path for transition compatibility.
    fng_records = fetch_fear_greed(limit=90)
    fng_canonical = root / "market" / "crypto" / "fear_greed.parquet"
    fng_legacy = root / "market" / "cross_asset" / "crypto" / "fear_greed.parquet"
    if fng_records:
        save_fear_greed_parquet(fng_records, fng_canonical)
        try:
            import shutil

            fng_legacy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fng_canonical, fng_legacy)
        except Exception as exc:
            logger.debug("fear_greed legacy mirror skipped: %s", exc)
    fng_latest = fng_records[-1] if fng_records else None
    fng_summary = (
        f"fear_greed={fng_latest.value} ({fng_latest.value_classification})"
        if fng_latest
        else "fear_greed=unavailable"
    )

    # 2. Crypto news from all free sources
    news_by_source = fetch_all_crypto_news()
    source_counts = {src: len(items) for src, items in news_by_source.items()}
    total_articles = sum(source_counts.values())
    source_counts_str = ", ".join(f"{src}={n}" for src, n in sorted(source_counts.items()))

    # 3. Analyze each article and collect urgent events
    analyzed = []
    urgent_events = []
    source_credibility = {
        "coindesk": 0.9,
        "cointelegraph": 0.7,
        "decrypt": 0.8,
        "bitcoinmagazine": 0.7,
        "binance": 0.85,
        "cryptoslate": 0.75,
        "cryptopanic": 0.5,
    }
    for source, items in news_by_source.items():
        cred = source_credibility.get(source, 0.5 if source.startswith("reddit") else 0.7)
        news_path = root / "news" / "bronze" / source / f"{today}.parquet"
        save_crypto_news_parquet(items, news_path)
        for item in items:
            analysis = analyze_crypto_news(item.title, item.summary, source_credibility=cred)
            record = {
                **item.to_dict(),
                **analysis.to_dict(),
                "date": today,
            }
            analyzed.append(record)
            if analysis.is_urgent:
                urgent_events.append(record)

    # 4. Save analyzed silver data (news-specific path)
    if analyzed:
        import pandas as pd

        silver_df = pd.DataFrame(analyzed)
        silver_path = root / "news" / "silver" / f"{today}.parquet"
        silver_path.parent.mkdir(parents=True, exist_ok=True)
        silver_df.to_parquet(silver_path, index=False)

        # 4b. Also write to main sentiment/silver for event pipeline integration
        sentiment_silver_rows = _crypto_news_to_sentiment_silver(analyzed, today)
        if sentiment_silver_rows:
            sdf = pd.DataFrame(sentiment_silver_rows)
            ss_dir = root / "sentiment" / "silver" / "crypto"
            ss_dir.mkdir(parents=True, exist_ok=True)
            sdf.to_parquet(ss_dir / f"{today}.parquet", index=False)

    notifications = [
        (
            Topic.NEWS_FETCHED,
            {
                "date": today,
                "total_articles": total_articles,
                "source_counts": source_counts,
                "sources": list(news_by_source.keys()),
            },
        ),
        (
            Topic.NEWS_ANALYZED,
            {
                "date": today,
                "total_analyzed": len(analyzed),
                "urgent_count": len(urgent_events),
                "event_types": list(
                    {a["event_type"] for a in analyzed if a["event_type"] != "other"}
                ),
                "fear_greed": fng_latest.to_dict() if fng_latest else None,
                "source_counts": source_counts,
            },
        ),
    ]
    notifications.extend(
        (
            Topic.NEWS_URGENT,
            {
                "date": today,
                "title": event["title"],
                "url": event["url"],
                "source": event["source"],
                "event_type": event["event_type"],
                "sentiment_score": event["sentiment_score"],
                "event_magnitude": event["event_magnitude"],
                "affected_symbols": event["affected_symbols"],
            },
        )
        for event in urgent_events[:10]
    )
    if fng_latest:
        notifications.append((Topic.FEAR_GREED_UPDATED, fng_latest.to_dict()))

    # 5. Publish bus events without letting one durable rejection stop later fan-out.
    db = None
    bus = None
    owns_bus = False
    try:
        db = TradeDB(data_root)
        bus = get_bus(db)
        owns_bus = bus.is_bound_to(db)
        for topic, payload in notifications:
            try:
                result = bus.publish_with_outcome(topic, payload)
            except Exception:
                logger.exception(
                    "News event publish failed before typed outcome: topic=%s",
                    topic,
                )
                continue
            if result.outcome is not AdmissionOutcome.ACCEPTED:
                logger.warning(
                    "News event dispatch deferred: topic=%s event_id=%s outcome=%s "
                    "action=replay_event_bus_event",
                    topic,
                    result.event.id,
                    result.outcome.value,
                )
    except Exception:
        logger.exception("Failed to initialize news event publishing")
    finally:
        if bus is not None and owns_bus:
            try:
                bus.shutdown()
            except Exception:
                logger.exception("Failed to shut down locally created news EventBus")
        if db is not None:
            try:
                db.close()
            except Exception:
                logger.exception("Failed to close news event database")

    event_types_used = {a["event_type"] for a in analyzed if a["event_type"] != "other"}
    return (
        f"Crypto news: {total_articles} articles from {len(news_by_source)} sources "
        f"[{source_counts_str}], {len(urgent_events)} urgent, "
        f"events={event_types_used}, {fng_summary}"
    )


def _job_global_macro(data_root: str, config: dict | None = None) -> str:
    """Fetch global macro data from FRED (requires FRED_API_KEY env var). Graceful no-op without key."""
    from trade_py.data.market.macro.fred import fetch_all_global_macro, save_macro_parquet

    root = Path(data_root)
    points = fetch_all_global_macro(limit=365)
    if not points:
        return "Global macro: no FRED_API_KEY set or network unavailable, skipped"
    counts = save_macro_parquet(points, root / "macro")
    return f"Global macro (FRED): fetched {sum(counts.values())} points for {len(counts)} series: {list(counts.keys())}"


def _job_asset_batch_ingest(
    data_root: str,
    config: dict | None = None,
    asset_class: str | None = None,
) -> str:
    """Generic meta-driven asset batch ingest.

    Config options:
        asset_class: filter by asset class (crypto/fx/commodity/stock)
        symbols: optional list of symbols to sync
        full_refresh: if True, ignore watermark and re-fetch all history
    """
    from trade_py.data.ingest.batch import BatchIngestEngine

    config = config or {}
    target_class = asset_class or config.get("asset_class")
    symbols = config.get("symbols")
    full_refresh = bool(config.get("full_refresh", False))

    engine = BatchIngestEngine(data_root)
    try:
        results = engine.ingest_by_class(
            asset_class=target_class,
            symbols=symbols,
            full_refresh=full_refresh,
        )
    finally:
        engine.stop()

    success = sum(1 for r in results if r.success)
    failed = len(results) - success
    new_rows = sum(r.new_rows for r in results if r.success)
    assets = ", ".join(r.asset_id for r in results if r.success)

    if not results:
        requested = f"class={target_class or 'all'} symbols={symbols or 'all'}"
        raise RuntimeError(f"No eligible assets selected: {requested}")

    if failed > 0:
        failed_assets = ", ".join(r.asset_id for r in results if not r.success)
        raise RuntimeError(
            f"Asset ingest incomplete: succeeded={success}/{len(results)} failed=[{failed_assets}]"
        )

    msg = f"Assets synced: {success}/{len(results)}, new rows={new_rows}, assets=[{assets}]"
    if failed > 0:
        msg += f", FAILED={failed}"
    return msg


def _job_crypto_research_validation(data_root: str, config: dict | None = None) -> str:
    from trade_py.data.warehouse.crypto import validate_crypto_btc_profile

    result = validate_crypto_btc_profile(data_root)
    validation = result["validation"]
    if result.get("io_error"):
        raise RuntimeError(f"Crypto 研究验证 I/O 失败: {result['io_error']}")
    if validation.get("data_readiness") != "ready":
        raise RuntimeError(
            "Crypto 研究验证被数据门禁抑制: "
            f"readiness={validation.get('data_readiness')} status={validation.get('status')}"
        )
    lifecycle = validation.get("lifecycle") or {}
    return (
        f"Crypto 研究验证完成: status={validation.get('status')} "
        f"active={lifecycle.get('active_signal_status')} run_id={validation.get('run_id')}"
    )


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
    fallback = (
        f" fallback={summary.fallback_reason}"
        if summary.fallback_used and summary.fallback_reason
        else ""
    )
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
    fallback = (
        f" fallback={summary.fallback_reason}"
        if summary.fallback_used and summary.fallback_reason
        else ""
    )
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
    return [
        str(row.get("symbol") or "").strip().upper()
        for row in rows
        if str(row.get("symbol") or "").strip()
    ]


def _job_kline(
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    from trade_py.data.market.kline import KlineSyncOptions, KlineSyncService

    service = KlineSyncService(data_root)
    opts_kwargs: dict = {"mode": "incremental"}
    if date_from:
        opts_kwargs["start"] = date_from
    if date_to:
        opts_kwargs["end"] = date_to
    if date_from or date_to:
        # Recovery/backfill needs an explicit window instead of the incremental watermark path.
        opts_kwargs["mode"] = "range"
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


def _job_fund_flow(
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    from trade_py.data.market.fund_flow import FundFlowFetcher
    from trade_py.db.trade_db import TradeDB

    db = TradeDB(data_root)
    fetcher = FundFlowFetcher(data_root)
    if date_from or date_to:
        # Recovery/backfill must cover the full universe for the requested window.
        symbols = db.get_all_symbols()
    else:
        watchlist = db.watchlist_get()
        symbols = watchlist or db.get_all_symbols()[:50]
    logger.info("Updating fund flow for %d symbols", len(symbols))
    summary = fetcher.fetch_batch(symbols, start_date=date_from, end_date=date_to)
    return (
        f"资金流向: {len(symbols)} symbols "
        f"mode={summary.get('mode')} saved={summary.get('saved_symbols')} api_calls={summary.get('api_calls')}"
    )


def _job_northbound(data_root: str, config: dict | None = None) -> str:
    from trade_py.data.market.northbound import NorthboundFetcher

    fetcher = NorthboundFetcher(data_root)
    df = fetcher.fetch_and_save()
    return f"北向资金同步: {len(df)} 行"


def _job_fundamental(
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    from trade_py.data.market.fundamental import FundamentalFetcher
    from trade_py.db.trade_db import TradeDB

    db = TradeDB(data_root)
    symbols = db.get_all_symbols()
    fetcher = FundamentalFetcher(data_root)
    summary = fetcher.fetch_batch(symbols, start_date=date_from)
    return (
        f"基本面数据同步: {len(symbols)} symbols "
        f"mode={summary.get('mode')} saved={summary.get('saved_symbols')} api_calls={summary.get('api_calls')}"
    )


def _job_macro(data_root: str, config: dict | None = None) -> str:
    from trade_py.data.market.macro import MacroFetcher

    fetcher = MacroFetcher(data_root)
    datasets = ["gdp", "cpi", "ppi", "pmi"]
    failures: list[str] = []
    for name in datasets:
        try:
            fetcher.fetch_and_save(name)
        except Exception as exc:
            failures.append(f"{name}={type(exc).__name__}: {exc}")
            logger.error("macro job: %s failed: %s", name, exc)
    if failures:
        raise RuntimeError(f"宏观数据同步不完整: {'; '.join(failures)}")
    return f"宏观数据同步完成: {', '.join(datasets)}"


def _job_sector_refresh(data_root: str, config: dict | None = None) -> str:
    from trade_py.data.market.index import IndexFetcher

    fetcher = IndexFetcher(data_root)
    updated = fetcher.refresh_sector_members()
    return f"板块映射刷新: {len(updated)} 只标的"


# ── COMPUTE jobs ───────────────────────────────────────────────────────────────


def _job_window_score(
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    from trade_py.signals.window_scorer import score_universe

    days = _iter_target_dates(date_from, date_to)
    total_scored = 0
    latest_factor_symbols = 0
    latest_predictions = 0
    for day_str in days:
        scores = score_universe(data_root, date_str=day_str)
        total_scored = max(total_scored, len(scores))
        target_date, factor_symbols, predicted = _refresh_inference_artifacts(data_root, day_str)
        if target_date:
            latest_factor_symbols = factor_symbols
            latest_predictions = predicted
    return (
        f"全市场评分完成: dates={len(days)} latest_symbols={total_scored} "
        f"factors={latest_factor_symbols} predictions={latest_predictions}"
    )


def _refresh_inference_artifacts(data_root: str, day_str: str) -> tuple[str, int, int]:
    from trade_py.analysis.propagation_runtime import (
        materialize_inference_factors,
        sync_signal_predictions,
    )

    target_date, n_symbols, _feature_cols, _freshness = materialize_inference_factors(
        data_root, day_str
    )
    if not target_date:
        return "", 0, 0
    pred_date, updated = sync_signal_predictions(data_root, day_str)
    return pred_date or target_date, int(n_symbols or 0), int(updated or 0)


def _job_materialize_factors(
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    from trade_py.analysis.propagation_runtime import materialize_inference_factors

    latest_symbols = 0
    latest_date = ""
    days = _iter_target_dates(date_from, date_to)
    for day_str in days:
        latest_date, latest_symbols, _feature_cols, _freshness = materialize_inference_factors(
            data_root, day_str
        )
    return f"推理特征物化完成: dates={len(days)} latest_date={latest_date or '-'} symbols={latest_symbols}"


def _job_sync_signal_predictions(
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    from trade_py.analysis.propagation_runtime import sync_signal_predictions

    latest_date = ""
    latest_updated = 0
    days = _iter_target_dates(date_from, date_to)
    for day_str in days:
        latest_date, latest_updated = sync_signal_predictions(data_root, day_str)
    return f"信号模型分数同步完成: dates={len(days)} latest_date={latest_date or '-'} updated={latest_updated}"


def _job_event_pipeline(
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    from trade_py.event import sync_events

    kwargs: dict = {}
    if date_from:
        kwargs["start"] = date_from
    if date_to:
        kwargs["end"] = date_to
    return sync_events(data_root, **kwargs).format()


def _job_event_backfill(
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    from trade_py.event import backfill_events

    return backfill_events(data_root, start=date_from, end=date_to)


def _job_evaluate_daily(
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    from trade_py.evaluation.service import evaluate_daily

    summaries: list[str] = []
    for day_str in _iter_target_dates(date_from, date_to):
        outcome = evaluate_daily(
            data_root,
            eval_date=day_str,
            use_cache=False,
        )
        summaries.append(outcome.summary)
    return summaries[-1] if summaries else "日常全链路评估未执行"


def _job_build_features(data_root: str, config: dict | None = None) -> str:
    """Build feature matrix from event_propagations + signals + instruments."""
    from trade_py.analysis.propagation_runtime import (
        build_training_feature_frame,
        save_feature_maps,
    )

    out_dir = Path(data_root) / "events"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "features.parquet"
    df, maps, _trust = build_training_feature_frame(data_root)
    if df.empty:
        return "特征构建: 无事件传播数据，跳过"

    df.to_parquet(out_path, index=False)
    save_feature_maps(data_root, maps)
    labeled = df["actual_return_5d"].notna().sum()
    return f"特征构建完成: {len(df)} 条传播记录, {labeled} 条有标签"


def _job_build_labels(
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Ensure event_propagations.actual_return_5d/20d are filled via backfill."""
    from trade_py.event import backfill_events

    result = backfill_events(data_root, start=date_from, end=date_to)
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
            summaries.append(
                f"{row['target_name']}[{row['backend']}/{state}] {metric_name}={metric_val}"
            )
        else:
            summaries.append(f"{row['target_name']}[{row['backend']}/{state}]")
    return "模型训练完成: " + "; ".join(summaries)


def _job_sentiment_fetch(
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
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
            data_root,
            db,
            progress_cb=lambda msg: logger.info(msg),
        )
        ch_lines = []
        for r in result["channels"]:
            tag = f"[{r['new_articles']}新]"
            err = f" ⚠{r['error']}" if r["error"] else ""
            ch_lines.append(f"  {r['channel']}: {tag}{err}")
        # Identify useless channels from stats
        useless = sorted({s["channel"] for s in result["stats"] if s["useless"]})
        summary = "\n".join(ch_lines) if ch_lines else "  (无活跃频道)"
        useless_note = f"\n无效频道(avg<2/day): {', '.join(useless)}" if useless else ""
        return f"streaming 抓取完成: 新增 {result['new_articles']} 篇\n" + summary + useless_note

    # ── incremental / batch path via engine ─────────────────────────────────
    from trade_py.engine import ingest_articles

    semantic_mode = (
        str(
            cfg.get("semantic_mode")
            or db.get("sentiment.scheduler_semantic_mode", "base")
            or "base"
        )
        .strip()
        .lower()
    )
    if semantic_mode not in {"base", "hybrid", "llm"}:
        semantic_mode = "base"
    result = ingest_articles(
        "rss",
        data_root,
        fetch_mode=fetch_mode,
        semantic_mode=semantic_mode,
        date_from=date_from,
        date_to=date_to,
    )
    return result.get(
        "summary", f"情绪抓取完成: fetch_mode={fetch_mode} semantic_mode={semantic_mode}"
    )


def _job_sentiment_silver(
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Recover Silver by running the real sentiment pipeline for the requested window."""
    cfg = dict(config or {})
    cfg.setdefault("fetch_mode", "range" if (date_from or date_to) else "incremental")
    return _job_sentiment_pipeline(data_root, config=cfg, date_from=date_from, date_to=date_to)


def _job_sentiment_gold(
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Recover Gold by running the real sentiment pipeline for the requested window."""
    cfg = dict(config or {})
    cfg.setdefault("fetch_mode", "range" if (date_from or date_to) else "incremental")
    return _job_sentiment_pipeline(data_root, config=cfg, date_from=date_from, date_to=date_to)


def _job_event_extract(
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Extract market events from gold sentiment data."""
    from trade_py.event import sync_events

    kwargs: dict = {}
    if date_from:
        kwargs["start"] = date_from
    if date_to:
        kwargs["end"] = date_to
    return sync_events(data_root, **kwargs).format()


def _job_kg_propagate(
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """KG propagation: backfill actual returns for event propagations."""
    from trade_py.event import backfill_events

    return backfill_events(data_root, start=date_from, end=date_to)


def _job_influence_score(data_root: str, config: dict | None = None) -> str:
    """Score all feed sources and write InfluenceSignal records (EBRT Trust layer)."""
    from trade_py.intelligence.feed_scorer import score_all_sources

    scores = score_all_sources(Path(data_root))
    return f"信源影响力评分完成: {len(scores)} 个信源"


def _job_belief_update(
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Run BeliefEngine: compute attention + residual update → BeliefState."""
    from trade_py.engine import update_belief

    total_updated = 0
    total_errors = 0
    days = _iter_target_dates(date_from, date_to)
    for day_str in days:
        result = update_belief(day_str, data_root)
        total_updated += int(result.get("symbols_updated", 0) or 0)
        total_errors += int(result.get("errors", 0) or 0)
    return f"信念更新完成: dates={len(days)} symbols={total_updated} errors={total_errors}"


def _job_recommend(
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
    """Produce Recommendation + RecommendationTrace from BeliefState."""
    from trade_py.engine import produce_picks

    latest_count = 0
    latest_adds = 0
    days = _iter_target_dates(date_from, date_to)
    for day_str in days:
        recs = produce_picks(day_str, data_root)
        latest_count = len(recs)
        latest_adds = sum(1 for r in recs if str(r.get("action") or "").lower() in {"buy", "add"})
    return f"推荐决策完成: dates={len(days)} latest={latest_count} add={latest_adds}"


def _job_reliability_update(data_root: str, config: dict | None = None) -> str:
    """Update per-source reliability weights using Brier loss from T-5 recommendations."""
    from trade_py.db.trade_db import TradeDB
    from trade_py.evaluation.trust import _update_source_reliabilities

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
        "calendar_sync",
        _job_calendar_sync,
        "交易日历同步",
        ["sunday 07:30"],
        "fetch",
        ["calendar", "meta"],
    ),
    "planned_event_sync": JobDef(
        "planned_event_sync",
        _job_planned_event_sync,
        "未来计划事件同步",
        ["daily 22:05"],
        "fetch",
        ["calendar", "event"],
    ),
    "planned_event_realize": JobDef(
        "planned_event_realize",
        _job_planned_event_realize,
        "未来计划事件落地",
        ["agenda post"],
        "compute",
        ["calendar", "event"],
    ),
    "kline_update": JobDef(
        "kline_update",
        _job_kline,
        "K线增量同步",
        ["daily 07:00"],
        "fetch",
        ["market"],
    ),
    "realtime_quote_sync": JobDef(
        "realtime_quote_sync",
        _job_realtime_quote_sync,
        "盘中分钟行情同步",
        ["weekday intraday"],
        "fetch",
        ["market", "intraday"],
    ),
    "cross_asset_fetch": JobDef(
        "cross_asset_fetch",
        _job_cross_asset,
        "跨资产行情抓取 (deprecated, superseded by asset_batch_ingest)",
        [],
        "fetch",
        ["deprecated", "market", "gold", "fx"],
    ),
    "crypto_btc_fetch": JobDef(
        "crypto_btc_fetch",
        _job_crypto_btc_fetch,
        "BTC assurance-gated UTC 日线同步",
        ["daily 09:00"],
        "fetch",
        ["market", "crypto"],
    ),
    "asset_batch_ingest": JobDef(
        "asset_batch_ingest",
        _job_asset_batch_ingest,
        "Meta-driven 批量资产数据采集 (crypto/fx/commodity)",
        ["daily 09:00"],
        "fetch",
        ["market", "ingest", "crypto", "fx", "commodity"],
    ),
    "crypto_research_validation": JobDef(
        "crypto_research_validation",
        _job_crypto_research_validation,
        "Crypto BTC 研究验证与状态复核",
        ["after crypto sync"],
        "compute",
        ["market", "crypto", "validation"],
    ),
    "crypto_news_sentiment": JobDef(
        "crypto_news_sentiment",
        _job_crypto_news_sentiment,
        "Crypto news + Fear & Greed + base sentiment",
        ["daily 08:30", "intraday every_30min"],
        "fetch",
        ["news", "crypto", "sentiment", "nlp"],
    ),
    "market_index": JobDef(
        "market_index",
        _job_market_index,
        "市场/行业指数同步",
        ["daily 07:05"],
        "fetch",
        ["market"],
    ),
    "fund_flow_update": JobDef(
        "fund_flow_update",
        _job_fund_flow,
        "资金流向同步",
        ["daily 07:30", "daily 15:15"],
        "fetch",
        ["market"],
    ),
    "northbound": JobDef(
        "northbound",
        _job_northbound,
        "北向资金同步",
        ["daily 15:20"],
        "fetch",
        ["market"],
    ),
    "sentiment_pipeline": JobDef(
        "sentiment_pipeline",
        _job_sentiment_pipeline,
        "情绪流水线",
        ["daily 22:00"],
        "fetch",
        ["nlp"],
    ),
    "sector_refresh": JobDef(
        "sector_refresh",
        _job_sector_refresh,
        "板块成分映射刷新",
        ["saturday 07:30"],
        "fetch",
        ["market"],
    ),
    "fundamental": JobDef(
        "fundamental",
        _job_fundamental,
        "财务数据同步",
        ["saturday 08:00"],
        "fetch",
        ["market"],
    ),
    "macro": JobDef(
        "macro",
        _job_macro,
        "宏观数据同步",
        ["sunday 08:00"],
        "fetch",
        ["market"],
    ),
    "global_macro": JobDef(
        "global_macro",
        _job_global_macro,
        "Global macro (FRED: DXY/VIX/rates/CPI)",
        ["daily 09:00", "sunday 08:15"],
        "fetch",
        ["macro", "global"],
    ),
    # COMPUTE stage
    "window_score": JobDef(
        "window_score",
        _job_window_score,
        "全市场窗口评分",
        ["daily 07:35", "daily 15:30"],
        "compute",
        ["signal"],
    ),
    "materialize_factors": JobDef(
        "materialize_factors",
        _job_materialize_factors,
        "推理特征物化",
        [],
        "compute",
        ["signal", "model"],
    ),
    "sync_signal_predictions": JobDef(
        "sync_signal_predictions",
        _job_sync_signal_predictions,
        "信号模型分数同步",
        [],
        "compute",
        ["signal", "model"],
    ),
    "realtime_compute": JobDef(
        "realtime_compute",
        _job_realtime_compute,
        "盘中分钟因子计算",
        ["weekday intraday"],
        "compute",
        ["signal", "intraday"],
    ),
    "event_pipeline": JobDef(
        "event_pipeline",
        _job_event_pipeline,
        "事件提取+KG传导",
        ["daily 22:30"],
        "compute",
        ["event"],
    ),
    "event_backfill": JobDef(
        "event_backfill",
        _job_event_backfill,
        "回填超额收益",
        ["daily 15:35"],
        "compute",
        ["event"],
    ),
    "evaluate_daily": JobDef(
        "evaluate_daily",
        _job_evaluate_daily,
        "日常全链路评估",
        ["daily 22:45"],
        "compute",
        ["evaluate"],
    ),
    "build_features": JobDef(
        "build_features",
        _job_build_features,
        "特征矩阵构建",
        ["sunday 09:00"],
        "compute",
        ["model"],
    ),
    "build_labels": JobDef(
        "build_labels",
        _job_build_labels,
        "标签构建（回填收益）",
        ["sunday 09:05"],
        "compute",
        ["model"],
    ),
    # TRAIN stage
    "model_train": JobDef(
        "model_train",
        _job_model_train,
        "KG事件传播模型训练",
        ["sunday 09:10"],
        "train",
        ["model"],
    ),
    # EBRT: trust + belief + recommendation
    "influence_score": JobDef(
        "influence_score",
        _job_influence_score,
        "信源影响力评分（EBRT Trust）",
        ["sunday 09:05"],
        "compute",
        ["trust", "ebrt"],
    ),
    "belief_update": JobDef(
        "belief_update",
        _job_belief_update,
        "信念状态更新（EBRT）",
        [],
        "compute",
        ["belief", "ebrt"],
    ),
    "recommend": JobDef(
        "recommend",
        _job_recommend,
        "推荐决策生成（EBRT）",
        [],
        "compute",
        ["decision", "ebrt"],
    ),
    "reliability_update": JobDef(
        "reliability_update",
        _job_reliability_update,
        "信源可靠性奖惩更新（EBRT）",
        ["daily 15:40"],
        "compute",
        ["trust", "ebrt"],
    ),
    # Sentiment chain (split jobs)
    "sentiment_fetch": JobDef(
        "sentiment_fetch",
        _job_sentiment_fetch,
        "情绪抓取（增量/流式）",
        ["daily 22:00"],
        "fetch",
        ["nlp"],
    ),
    "sentiment_silver": JobDef(
        "sentiment_silver",
        _job_sentiment_silver,
        "情绪 Silver 评分",
        [],
        "fetch",
        ["nlp"],
    ),
    "sentiment_gold": JobDef(
        "sentiment_gold",
        _job_sentiment_gold,
        "情绪 Gold 聚合",
        [],
        "fetch",
        ["nlp"],
    ),
    "event_extract": JobDef(
        "event_extract",
        _job_event_extract,
        "事件提取",
        ["daily 22:30"],
        "compute",
        ["event"],
    ),
    "kg_propagate": JobDef(
        "kg_propagate",
        _job_kg_propagate,
        "KG 传导",
        [],
        "compute",
        ["event"],
    ),
}


def run_job(
    name: str,
    data_root: str,
    config: dict | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> str:
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
