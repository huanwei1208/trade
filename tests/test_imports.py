"""Smoke tests: verify all top-level modules import cleanly."""

import pytest


def test_config():
    from trade_py.infra.settings import get_config_context, default_data_root
    ctx = get_config_context()
    assert ctx.repo_root.exists()
    assert not hasattr(ctx, "python_root"), "python_root should have been removed"


def test_utils():
    from trade_py.utils.html import clean_html
    from trade_py.utils.scoring import meta_score
    from trade_py.utils.time import today_cst, CST
    from trade_py.utils.progress import noop_progress

    assert clean_html("<b>hello</b>") == "hello"
    assert 0 <= meta_score({}) <= 100
    assert callable(noop_progress)


def test_meta():
    from trade_py.meta.records.raw import RawRecord
    from trade_py.meta.feed import FeedScore
    from trade_py.meta.schema.meta_store import FEED_SCORES, SOURCE_CONFIGS

    assert RawRecord is not None
    assert FeedScore is not None
    assert "CREATE TABLE" in FEED_SCORES.upper()
    assert "CREATE TABLE" in SOURCE_CONFIGS.upper()


def test_data_source():
    from trade_py.data.source import DataSource, RawRecord
    assert DataSource is not None


def test_data_registry():
    from trade_py.data.registry import list_sources
    sources = list_sources()
    assert "rss" in sources
    assert "tushare_news" in sources


def test_data_market_imports():
    from trade_py.data.market.kline import KlineFetcher
    from trade_py.data.market.fund_flow import FundFlowFetcher
    from trade_py.data.market.cross_asset import fetch_gold, fetch_all


def test_data_news_rss():
    from trade_py.data.news.rss import RssSource, resolve_feeds, build_feed_catalog
    from trade_py.data.news.rss.catalog import load_feed_index


def test_data_news_gdelt():
    from trade_py.data.news.gdelt.source import GdeltSource
    from trade_py.data.news.gdelt.channels import Channel, load_channels


def test_intelligence_clients():
    from trade_py.intelligence.clients import (
        SentimentResult, content_hash, create_client,
        AnthropicClient, OllamaClient,
    )
    r = SentimentResult()
    assert r.sentiment_label == "neutral"
    h = content_hash("title", "text")
    assert len(h) == 16


def test_runtime_imports():
    from trade_py.app.runtime.scheduler import register_schedule
    from trade_py.app.pipelines.event_pipeline import run_event_pipeline
    from trade_py.domain.kg import learn_kg_candidates
    from trade_py.domain.factors import score_watchlist
    from trade_py.domain.events import sync_events
    from trade_web import create_app

    assert callable(register_schedule)
    assert callable(run_event_pipeline)
    assert callable(learn_kg_candidates)
    assert callable(score_watchlist)
    assert callable(sync_events)
    assert callable(create_app)


def test_signals():
    from trade_py.signals.window_scorer import score_watchlist
    from trade_py.signals.cross_asset_signal import CrossAssetSignal


def test_cli_help(capsys):
    from trade_py.cli.main import main
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
