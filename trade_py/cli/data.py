"""trade data — data fetch/ingest domain (post CLI convergence).

Status / jobs-status / source-CRUD subcommands are DEPRECATED at top-level and
print DeprecationWarnings pointing to ``trade status data`` / ``trade status jobs`` /
``trade config source``. Their implementations remain here because ``config source``
delegates CRUD operations to this module via ``source_main_internal()``.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from trade_py.infra.settings import default_data_root, load_defaults
from trade_py.data.market.kline import KlineSyncOptions, KlineSyncService
from trade_py.db.settings_db import SettingsDB

logger = logging.getLogger(__name__)

# When set to True, deprecation warnings for moved subcommands are suppressed.
# Used by config.py which internally delegates source CRUD to this module.
_INTERNAL_CALL = False


def _depr_warn(old: str, new: str) -> None:
    if _INTERNAL_CALL:
        return
    msg = (
        f"DeprecationWarning: 'trade data {old}' is deprecated; "
        f"use '{new}' instead."
    )
    print(msg, file=sys.stderr)

_DATA_ROOT_ARG = str(default_data_root())
_READ_ONLY_SENTIMENT_COMMANDS = {"status", "sources", "doctor", "inspect", "sample"}
_DEFAULT_RESEARCH_SOURCE_CATALOG = Path("trade_py/infra/config/research_sources.csv")
_RUNNING_JOB_STALE_HOURS = {
    "realtime_quote_sync": 0.25,
    "realtime_compute": 0.25,
    "planned_event_sync": 0.5,
    "planned_event_realize": 0.5,
    "window_score": 1.0,
    "fund_flow_update": 1.0,
    "northbound": 1.0,
    "crypto_btc_fetch": 1.0,
    "crypto_research_validation": 1.0,
    "asset_batch_ingest": 1.0,
    "evaluate_gate": 0.5,
    "evaluate_source": 2.0,
    "evaluate_daily": 2.0,
    "event_pipeline": 2.0,
    "sentiment_pipeline": 4.0,
    "kline_update": 6.0,
}


@dataclass
class DataRunResult:
    summary: str
    exit_code: int = 0
    symbols_processed: int | None = None


def _truncate_summary(text: str, limit: int = 500) -> str:
    return text if len(text) <= limit else text[:limit]


# ── Multi-asset path helpers (post asset-split) ──────────────────────────────
# Canonical paths live under market/<class>/; legacy fallback paths are checked
# during transition so existing on-disk data keeps working.

def _resolve_fear_greed_path(data_root) -> Path:
    """Return the first existing fear_greed.parquet path, else canonical."""
    root = Path(data_root)
    candidates = [
        root / "market" / "crypto" / "fear_greed.parquet",
        root / "market" / "cross_asset" / "crypto" / "fear_greed.parquet",
        root / "market" / "cross_asset" / "fear_greed.parquet",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def _resolve_crypto_dir(data_root) -> Path:
    """Return the crypto data directory, preferring the canonical market/crypto/."""
    root = Path(data_root)
    canonical = root / "market" / "crypto"
    legacy_crypto = root / "market" / "cross_asset" / "crypto"
    legacy_flat = root / "market" / "cross_asset"
    if canonical.exists() and any(canonical.glob("*.parquet")):
        return canonical
    if legacy_crypto.exists() and any(legacy_crypto.glob("*.parquet")):
        return legacy_crypto
    return canonical


def _parse_job_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace(" ", "T"))
    except ValueError:
        return None


def _running_job_state(row: dict, *, now: datetime | None = None) -> dict[str, object]:
    job_name = str(row.get("job_name") or "")
    started = _parse_job_datetime(row.get("started_at"))
    threshold = float(_RUNNING_JOB_STALE_HOURS.get(job_name, 4.0))
    age_hours = None
    if started is not None:
        age_hours = max(((now or datetime.now()) - started).total_seconds() / 3600.0, 0.0)
    stale = age_hours is not None and age_hours > threshold
    return {
        "status": "stale_running" if stale else "running",
        "age_hours": round(age_hours, 2) if age_hours is not None else None,
        "stale_after_hours": threshold,
    }


def _data_status_exit_code(status: dict, *, strict: bool) -> int:
    if not strict:
        return 0
    gate_status = str((status.get("quality_gate") or {}).get("status") or "unknown")
    if gate_status == "pass":
        return 0
    if gate_status == "warn":
        return 3
    return 2


def _extract_flag_value(argv: list[str], flag: str, default: str) -> str:
    for i, token in enumerate(argv):
        if token == flag and i + 1 < len(argv):
            return argv[i + 1]
        if token.startswith(flag + "="):
            return token.split("=", 1)[1]
    return default


def _track_data_run(
    data_root: str,
    job_name: str,
    runner: Callable[[], DataRunResult],
    *,
    stage: str = "fetch",
) -> int:
    db = SettingsDB(data_root)
    run_id = db.job_run_start(job_name, stage=stage)
    started = time.time()
    try:
        result = runner()
        elapsed_ms = int((time.time() - started) * 1000)
        status = "ok" if result.exit_code == 0 else "error"
        db.job_run_finish(
            run_id,
            status,
            result_summary=_truncate_summary(result.summary),
            symbols_processed=result.symbols_processed,
            elapsed_ms=elapsed_ms,
        )
        return result.exit_code
    except KeyboardInterrupt:
        elapsed_ms = int((time.time() - started) * 1000)
        db.job_run_finish(
            run_id,
            "error",
            result_summary=_truncate_summary("interrupted by user"),
            elapsed_ms=elapsed_ms,
        )
        logger.warning("data command interrupted job=%s", job_name)
        return 130
    except Exception as exc:
        elapsed_ms = int((time.time() - started) * 1000)
        db.job_run_finish(
            run_id,
            "error",
            result_summary=_truncate_summary(str(exc)),
            elapsed_ms=elapsed_ms,
        )
        logger.error("data command failed job=%s: %s", job_name, exc, exc_info=True)
        return 1


def _kline_defaults() -> dict:
    all_defaults = load_defaults()
    defaults = all_defaults.get("kline", {}) if isinstance(all_defaults, dict) else {}
    return defaults if isinstance(defaults, dict) else {}


def _resolve_kline_start(data_root: str, explicit_start: str | None, fallback: str | None = None) -> str:
    if explicit_start:
        return explicit_start
    resolved_fallback = str(fallback or "2024-01-01")
    try:
        value = SettingsDB(data_root).get("kline.start", resolved_fallback)
        return str(value or resolved_fallback)
    except Exception:
        return resolved_fallback


def _parquet_tree_summary(root: Path) -> dict[str, str | int | None]:
    if not root.exists():
        return {"files": 0, "min_date": None, "max_date": None}
    files = [p for p in root.rglob("*.parquet")]
    if not files:
        return {"files": 0, "min_date": None, "max_date": None}
    dates: list[str] = []
    for path in files:
        stem = path.stem
        if len(stem) == 10 and stem[4] == "-" and stem[7] == "-":
            dates.append(stem)
    return {
        "files": len(files),
        "min_date": min(dates) if dates else None,
        "max_date": max(dates) if dates else None,
    }


def _resolve_default_symbols(data_root: str, raw_symbols: str | None, *, top: int = 50) -> list[str]:
    if raw_symbols:
        return [s.strip().upper() for s in str(raw_symbols).split(",") if s.strip()]
    from trade_py.db.trade_db import TradeDB

    db = TradeDB(data_root)
    watchlist = db.watchlist_get()
    if watchlist:
        return watchlist
    rows = db.signal_suggest(limit=top, by="model_score")
    return [str(row.get("symbol") or "").strip().upper() for row in rows if str(row.get("symbol") or "").strip()]


def _read_records_file(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    if p.suffix.lower() == ".json":
        payload = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [dict(item) for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
            return [dict(item) for item in payload["rows"] if isinstance(item, dict)]
        raise ValueError(f"{p} must contain a JSON list or an object with rows")
    with p.open("r", encoding="utf-8-sig", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def make_parser() -> argparse.ArgumentParser:
    from trade_py.cli import epilog_from_subparsers, global_flag_parent

    defaults = _kline_defaults()

    def d(name: str, fallback):
        return defaults.get(name, fallback)

    parser = argparse.ArgumentParser(
        prog="trade data",
        description="数据采集 — K线/情绪/跨资产/资金流/财务/北向/指数/宏观/新闻/仓库/实时/BTC",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[global_flag_parent()],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "sentiment",
        description="新闻情绪流水线 (fetch → LLM → Gold)",
        epilog=(
            "trade data sentiment --date 2026-03-05\n"
            "trade data sentiment --fetch-mode none --start 2026-01-01 --end 2026-03-05\n"
            "trade data sentiment status\n"
            "trade data sentiment sources --default-only\n"
            "trade data sentiment doctor --rss-feeds catalog:global_public\n"
            "trade data sentiment sample --date 2026-03-05 --label negative -n 20\n"
            "trade data sentiment apply-corrections --date 2026-03-05"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    p_data_status = sub.add_parser(
        "status",
        description="显示数据层完整性/时效性/覆盖率状态",
        epilog=(
            "trade data status\n"
            "trade data status --json\n"
            "trade data status --limit 20"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_data_status.add_argument("--data-root", default=str(default_data_root()))
    p_data_status.add_argument("--json", action="store_true", dest="as_json")
    p_data_status.add_argument("--limit", type=int, default=10, help="Missing/stale samples to show")
    p_data_status.add_argument("--strict", action="store_true", help="Exit non-zero when the aggregate quality gate is not pass")

    p_backfill = sub.add_parser(
        "backfill",
        description="查看后台回补与同步进度 (别名: jobs)",
        epilog=(
            "trade data backfill status\n"
            "trade data jobs status\n"
            "trade data backfill status --limit 20"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_jobs = sub.add_parser(
        "jobs",
        description="查看任务运行状态与 sync_state watermark (原 backfill)",
        epilog=(
            "trade data jobs status\n"
            "trade data jobs status --limit 20"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    for _p in (p_backfill, p_jobs):
        _bsub = _p.add_subparsers(dest="backfill_cmd", required=True)
        _bstat = _bsub.add_parser("status", description="查看任务/sync_state/覆盖快照")
        _bstat.add_argument("--data-root", default=str(default_data_root()))
        _bstat.add_argument("--limit", type=int, default=12)

    p_kline = sub.add_parser(
        "kline",
        description="A-share K线数据同步",
        epilog=(
            "trade data kline sync\n"
            "trade data kline sync --mode full --start 2025-01-01\n"
            "trade data kline status\n"
            "trade data kline instruments"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    kline_sub = p_kline.add_subparsers(dest="kline_cmd", required=True)

    p_sync = kline_sub.add_parser("sync", description="K线同步 (incremental/range/full)")
    p_sync.add_argument("--data-root", default=str(default_data_root()))
    p_sync.add_argument("--mode", choices=["incremental", "range", "full"], default=d("mode", "range"))
    p_sync.add_argument("--symbols", default=None, help="Comma-separated symbols. Empty means all instruments.")
    p_sync.add_argument("--start", default=None)
    p_sync.add_argument("--end", default=None)
    p_sync.add_argument("--adjust", choices=["hfq", "qfq", "none"], default=d("adjust", "none"))
    p_sync.add_argument("--provider", choices=["auto", "tushare", "akshare", "baostock", "tencent"], default=d("provider", "auto"))
    p_sync.add_argument("--delay-ms", type=int, default=int(d("delay_ms", 300)))
    p_sync.add_argument("--fail-fast", action="store_true")

    p_instruments = kline_sub.add_parser("instruments", description="刷新标的列表")
    p_instruments.add_argument("--data-root", default=str(default_data_root()))

    p_status = kline_sub.add_parser("status", description="显示 K线同步状态")
    p_status.add_argument("--data-root", default=str(default_data_root()))
    p_status.add_argument("--stale-days", type=int, default=None, help="Only show symbols stale >= N days")
    p_status.add_argument("--limit", type=int, default=50)

    p_reconcile = kline_sub.add_parser(
        "reconcile",
        description="对本地 K线与影子 provider 做收盘价交叉校验并写入 reconciliation/current.json",
    )
    p_reconcile.add_argument("--data-root", default=str(default_data_root()))
    p_reconcile.add_argument("--symbols", required=True, help="Comma-separated symbols to reconcile")
    p_reconcile.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    p_reconcile.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    p_reconcile.add_argument("--shadow-provider", choices=["akshare", "tencent", "baostock"], default="akshare")
    p_reconcile.add_argument("--adjust", choices=["hfq", "qfq", "none"], default="none")
    p_reconcile.add_argument("--warn-basis-pct", type=float, default=0.5)
    p_reconcile.add_argument("--block-basis-pct", type=float, default=2.0)
    p_reconcile.add_argument("--minimum-checked-rows", type=int, default=1)
    p_reconcile.add_argument("--dry-run", action="store_true")
    p_reconcile.add_argument("--json", action="store_true", dest="as_json")

    # Unified meta-driven sync command (new)
    p_sync_unified = sub.add_parser(
        "sync",
        description=(
            "统一资产数据同步 (meta驱动, 批量ingest, QPS控制, watermark增量).\n"
            "Supported asset classes: crypto (BTC/ETH/SOL/BNB/XRP + Fear&Greed), "
            "fx (USD/CNH), commodity (gold); stock coming in a future release."
        ),
        epilog=(
            "trade data sync                     # Sync all enabled assets\n"
            "trade data sync --crypto            # Sync only crypto (BTC, ETH, SOL, BNB, XRP, fear_greed)\n"
            "trade data sync --symbols BTC,ETH   # Sync specific crypto symbols\n"
            "trade data sync --full-refresh      # Ignore watermark, full history backfill\n"
            "trade data sync --class commodity,fx # Sync gold and USD/CNH only\n"
            "trade data btc                      # Run BTC assurance flow (primary+shadow+D3 gate)\n"
            "trade data btc-assurance            # Alias for BTC assurance flow\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_sync_unified.add_argument("--data-root", default=str(default_data_root()))
    p_sync_unified.add_argument("--crypto", action="store_true", help="Only sync crypto assets (BTC/ETH/SOL/BNB/XRP + Fear&Greed) — shorthand for --class crypto")
    p_sync_unified.add_argument("--class", dest="asset_class", default=None,
                                help="Comma-separated asset classes to sync: crypto,fx,commodity (stock future)")
    p_sync_unified.add_argument("--symbols", default=None, help="Comma-separated symbols to sync")
    p_sync_unified.add_argument("--full-refresh", action="store_true", help="Ignore watermark, full refresh")
    p_sync_unified.add_argument("--json", action="store_true", dest="as_json")

    # ── Source management ───────────────────────────────────────────────────
    p_src = sub.add_parser(
        "source",
        aliases=["sources"],
        description="数据源管理 (asset_registry) — 查看/启停/增删 meta 驱动的数据源",
        epilog=(
            "trade data source list                 # 列出所有已注册数据源\n"
            "trade data source list --class crypto  # 按类别过滤\n"
            "trade data source show BTC             # 查看单个数据源详情\n"
            "trade data source enable BTC           # 启用数据源\n"
            "trade data source disable USDCNH       # 停用数据源\n"
            "trade data source add --asset-id stock.AAPL --class stock --symbol AAPL \\\n"
            "                       --venue yfinance --quote USD --interval 1d\n"
            "trade data source remove stock.AAPL    # 删除数据源"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    src_sub = p_src.add_subparsers(dest="src_cmd", required=True)

    p_src_list = src_sub.add_parser("list", description="列出所有已注册数据源")
    p_src_list.add_argument("--data-root", default=str(default_data_root()))
    p_src_list.add_argument("--class", dest="asset_class", default=None,
                            help="按资产类别过滤: crypto,fx,commodity,stock")
    p_src_list.add_argument("--venue", default=None, help="按 venue 过滤: okx,binance,eastmoney,sge")
    p_src_list.add_argument("--disabled", action="store_true", help="只显示已停用的")
    p_src_list.add_argument("--json", action="store_true", dest="as_json")

    p_src_show = src_sub.add_parser("show", description="查看单个数据源详情")
    p_src_show.add_argument("asset_id", help="数据源 ID, 如 BTC/ETH/fx.USDCNH/commodity.gold")
    p_src_show.add_argument("--data-root", default=str(default_data_root()))
    p_src_show.add_argument("--json", action="store_true", dest="as_json")

    p_src_enable = src_sub.add_parser("enable", description="启用数据源")
    p_src_enable.add_argument("asset_id")
    p_src_enable.add_argument("--data-root", default=str(default_data_root()))

    p_src_disable = src_sub.add_parser("disable", description="停用数据源")
    p_src_disable.add_argument("asset_id")
    p_src_disable.add_argument("--data-root", default=str(default_data_root()))

    p_src_add = src_sub.add_parser("add", description="新增数据源到 asset_registry")
    p_src_add.add_argument("--asset-id", required=True, help="唯一 ID, 如 crypto.DOGE, stock.AAPL")
    p_src_add.add_argument("--class", dest="asset_class", required=True,
                           help="资产类别: crypto,fx,commodity,stock")
    p_src_add.add_argument("--symbol", required=True, help="交易对/代码, 如 DOGE, AAPL")
    p_src_add.add_argument("--venue", required=True, help="数据提供方: okx,binance,eastmoney,sge,yfinance 等")
    p_src_add.add_argument("--quote", default="USD", help="计价货币, 默认 USD")
    p_src_add.add_argument("--interval", default="1d", help="K线周期, 默认 1d")
    p_src_add.add_argument("--priority", type=int, default=5, help="调度优先级, 小=先执行")
    p_src_add.add_argument("--batch-size", type=int, default=100, help="批量抓取大小")
    p_src_add.add_argument("--min-interval-ms", type=int, default=300, help="最小请求间隔(ms), 控制QPS")
    p_src_add.add_argument("--backfill-days", type=int, default=730, help="首次回填天数")
    p_src_add.add_argument("--data-root", default=str(default_data_root()))

    p_src_remove = src_sub.add_parser("remove", description="从 asset_registry 删除数据源 (不删除已落盘的 parquet)")
    p_src_remove.add_argument("asset_id")
    p_src_remove.add_argument("--data-root", default=str(default_data_root()))
    p_src_remove.add_argument("--yes", action="store_true", help="跳过确认")

    p_rt = sub.add_parser(
        "realtime",
        description="实时分钟行情抓取与盘中因子计算 (Tushare rt_min)",
        epilog=(
            "trade data realtime sync --symbols 601288.SH,600111.SH\n"
            "trade data realtime compute --symbols 601288.SH,600111.SH\n"
            "trade data realtime run --freq 1MIN --lookback-minutes 45"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    rt_sub = p_rt.add_subparsers(dest="rt_cmd", required=True)

    p_rt_sync = rt_sub.add_parser("sync", description="批量抓取实时分钟行情")
    p_rt_sync.add_argument("--data-root", default=str(default_data_root()))
    p_rt_sync.add_argument("--symbols", default=None, help="逗号分隔股票代码，空=自选股或最新推荐")
    p_rt_sync.add_argument("--freq", default="1MIN", help="分钟频率，如 1MIN/5MIN")
    p_rt_sync.add_argument("--start-time", default=None, help="起始时间 YYYY-MM-DD HH:MM:SS")
    p_rt_sync.add_argument("--end-time", default=None, help="结束时间 YYYY-MM-DD HH:MM:SS")
    p_rt_sync.add_argument("--lookback-minutes", type=int, default=30)
    p_rt_sync.add_argument("--chunk-size", type=int, default=50)
    p_rt_sync.add_argument("--asset", default="E", help="Tushare rt_min asset，默认 E")

    p_rt_compute = rt_sub.add_parser("compute", description="根据已同步分钟行情计算盘中快照与因子")
    p_rt_compute.add_argument("--data-root", default=str(default_data_root()))
    p_rt_compute.add_argument("--symbols", default=None, help="逗号分隔股票代码，空=自选股或最新推荐")
    p_rt_compute.add_argument("--freq", default="1MIN", help="分钟频率，如 1MIN/5MIN")
    p_rt_compute.add_argument("--top", type=int, default=20)
    p_rt_compute.add_argument("--lookback-bars", type=int, default=30)
    p_rt_compute.add_argument("--no-persist-factors", action="store_true")

    p_rt_run = rt_sub.add_parser("run", description="先抓分钟行情，再计算盘中快照")
    p_rt_run.add_argument("--data-root", default=str(default_data_root()))
    p_rt_run.add_argument("--symbols", default=None, help="逗号分隔股票代码，空=自选股或最新推荐")
    p_rt_run.add_argument("--freq", default="1MIN", help="分钟频率，如 1MIN/5MIN")
    p_rt_run.add_argument("--start-time", default=None, help="起始时间 YYYY-MM-DD HH:MM:SS")
    p_rt_run.add_argument("--end-time", default=None, help="结束时间 YYYY-MM-DD HH:MM:SS")
    p_rt_run.add_argument("--lookback-minutes", type=int, default=30)
    p_rt_run.add_argument("--chunk-size", type=int, default=50)
    p_rt_run.add_argument("--asset", default="E", help="Tushare rt_min asset，默认 E")
    p_rt_run.add_argument("--top", type=int, default=20)
    p_rt_run.add_argument("--lookback-bars", type=int, default=30)
    p_rt_run.add_argument("--no-persist-factors", action="store_true")

    # --- Tushare-backed data commands ---

    p_fund = sub.add_parser(
        "fundamental",
        description="财务数据同步 (Tushare fina_indicator)",
        epilog=(
            "trade data fundamental sync --symbols 600000.SH,000001.SZ\n"
            "trade data fundamental sync --start 2026-01-01"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    fund_sub = p_fund.add_subparsers(dest="fund_cmd", required=True)
    p_fund_sync = fund_sub.add_parser("sync", description="同步财务数据")
    p_fund_sync.add_argument("--data-root", default=str(default_data_root()))
    p_fund_sync.add_argument("--symbols", default=None, help="逗号分隔的股票代码，空=全部自选股")
    p_fund_sync.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD")

    p_ff = sub.add_parser(
        "fund-flow",
        description="资金流向同步 (Tushare moneyflow)",
        epilog=(
            "trade data fund-flow sync --symbols 600000.SH\n"
            "trade data fund-flow sync --start 2025-01-01"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ff_sub = p_ff.add_subparsers(dest="ff_cmd", required=True)
    p_ff_sync = ff_sub.add_parser("sync", description="同步资金流向数据")
    p_ff_sync.add_argument("--data-root", default=str(default_data_root()))
    p_ff_sync.add_argument("--symbols", default=None)
    p_ff_sync.add_argument("--start", default=None)
    p_ff_sync.add_argument("--end", default=None)

    p_nb = sub.add_parser(
        "northbound",
        description="北向资金同步 (Tushare moneyflow_hsgt)",
        epilog="trade data northbound sync --start 2025-01-01",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    nb_sub = p_nb.add_subparsers(dest="nb_cmd", required=True)
    p_nb_sync = nb_sub.add_parser("sync", description="同步北向资金数据")
    p_nb_sync.add_argument("--data-root", default=str(default_data_root()))
    p_nb_sync.add_argument("--start", default=None)
    p_nb_sync.add_argument("--end", default=None)

    p_idx = sub.add_parser(
        "market-index",
        aliases=["index"],
        description="市场指数与行业指数同步 (Tushare index_daily)",
        epilog=(
            "trade data market-index sync\n"
            "trade data market-index sync --codes 000001.SH,000300.SH --start 2026-01-01\n"
            "trade data market-index sync-industry --start 2024-01-01\n"
            "trade data market-index refresh-industry-members"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    idx_sub = p_idx.add_subparsers(dest="idx_cmd", required=True)
    p_idx_sync = idx_sub.add_parser("sync", description="同步宽基/市场指数行情")
    p_idx_sync.add_argument("--data-root", default=str(default_data_root()))
    p_idx_sync.add_argument("--codes", default=None, help="逗号分隔指数代码，空=默认4个")
    p_idx_sync.add_argument("--start", default=None)

    p_idx_sector = idx_sub.add_parser(
        "sync-industry",
        aliases=["sync-sector"],
        description="同步申万31个一级行业指数",
    )
    p_idx_sector.add_argument("--data-root", default=str(default_data_root()))
    p_idx_sector.add_argument("--start", default=None, help="起始日期 YYYY-MM-DD，空=近3年")

    p_idx_members = idx_sub.add_parser(
        "refresh-industry-members",
        aliases=["refresh-members"],
        description="刷新股票→申万行业成分映射",
    )
    p_idx_members.add_argument("--data-root", default=str(default_data_root()))

    p_macro = sub.add_parser(
        "macro",
        description="宏观经济数据同步 (Tushare cn_gdp/cpi/ppi/pmi)",
        epilog="trade data macro sync",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    macro_sub = p_macro.add_subparsers(dest="macro_cmd", required=True)
    p_macro_sync = macro_sub.add_parser("sync", description="同步宏观数据")
    p_macro_sync.add_argument("--data-root", default=str(default_data_root()))
    p_macro_sync.add_argument("--dataset", default=None, help="gdp/cpi/ppi/pmi，空=全部")

    p_warehouse = sub.add_parser(
        "warehouse",
        description="研究数仓闭环：DIM/ODS/DWD/DWS/ADS 落表与验证",
        epilog=(
            "trade data warehouse materialize-rss --catalog feeds.csv --entries rss_entries.csv\n"
            "trade data warehouse materialize-rss --catalog feeds.json --entries rss_entries.json --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    wh_sub = p_warehouse.add_subparsers(dest="warehouse_cmd", required=True)
    p_wh_rss = wh_sub.add_parser(
        "materialize-rss",
        description="从本地 RSS catalog/entry 文件生成研究数仓分层表和 ADS 验证报告",
    )
    p_wh_rss.add_argument("--data-root", default=str(default_data_root()))
    p_wh_rss.add_argument("--catalog", required=True, help="CSV/JSON, columns: 名称,rss link")
    p_wh_rss.add_argument("--entries", required=True, help="CSV/JSON RSS entry rows")
    p_wh_rss.add_argument("--positions", default=None, help="Optional CSV/JSON local position/watchlist rows")
    p_wh_rss.add_argument("--json", action="store_true", dest="as_json")

    p_wh_fetch = wh_sub.add_parser(
        "fetch-rss",
        description="按本地 source catalog 受控抓取 RSS，并可直接落研究数仓",
    )
    p_wh_fetch.add_argument("--data-root", default=str(default_data_root()))
    p_wh_fetch.add_argument("--catalog", default=str(_DEFAULT_RESEARCH_SOURCE_CATALOG))
    p_wh_fetch.add_argument("--positions", default=None, help="Optional CSV/JSON local position/watchlist rows")
    p_wh_fetch.add_argument("--max-sources", type=int, default=None)
    p_wh_fetch.add_argument("--skip-sources", type=int, default=0)
    p_wh_fetch.add_argument("--min-interval-seconds", type=float, default=1.0)
    p_wh_fetch.add_argument("--timeout-seconds", type=int, default=10)
    p_wh_fetch.add_argument("--dry-run", action="store_true")
    p_wh_fetch.add_argument("--no-materialize", action="store_true")
    p_wh_fetch.add_argument("--json", action="store_true", dest="as_json")

    p_wh_crypto = wh_sub.add_parser(
        "validate-research",
        description="运行预注册研究验证并落审计型 ADS 输出",
    )
    p_wh_crypto.add_argument("--data-root", default=str(default_data_root()))
    p_wh_crypto.add_argument("--profile", choices=["crypto-btc-v1"], required=True)
    p_wh_crypto.add_argument("--as-of", choices=["latest-common"], default="latest-common")
    p_wh_crypto.add_argument("--dry-run", action="store_true")
    p_wh_crypto.add_argument("--strict", action="store_true")
    p_wh_crypto.add_argument("--json", action="store_true", dest="as_json")

    # ── news subcommand ────────────────────────────────────────────────────────
    p_news = sub.add_parser(
        "news",
        description="Crypto news fetch & sentiment analysis (free RSS/Reddit/Fear&Greed, no API key needed)",
        epilog=(
            "trade data news fetch          # fetch crypto news + F&G + run analysis\n"
            "trade data news fng            # show Fear & Greed Index\n"
            "trade data news urgent         # show recent urgent events\n"
            "trade data news status         # show news data status\n"
        ),
    )
    p_news.add_argument("news_cmd", nargs="?", default="fetch", choices=["fetch", "fng", "urgent", "status"])
    p_news.add_argument("--data-root", default=str(default_data_root()))
    p_news.add_argument("--json", action="store_true", dest="as_json")
    p_news.add_argument("--limit", type=int, default=20)

    # ── Crypto market data ──────────────────────────────────────────────────────
    p_crypto = sub.add_parser(
        "crypto",
        description="Crypto market data viewer (24/7 market)",
        epilog=(
            "trade data crypto show [SYMBOL]  # show latest crypto kline\n"
            "trade data crypto list            # list available crypto assets\n"
            "trade data crypto fng             # show Fear & Greed Index\n"
        ),
    )
    p_crypto.add_argument("crypto_cmd", nargs="?", default="show", choices=["show", "list", "fng"])
    p_crypto.add_argument("symbol", nargs="?", default="BTC", help="Crypto symbol: BTC, ETH, SOL, BNB, XRP")
    p_crypto.add_argument("--data-root", default=str(default_data_root()))
    p_crypto.add_argument("--limit", type=int, default=10, help="Number of recent rows to show")
    p_crypto.add_argument("--json", action="store_true", dest="as_json")

    # ── BTC assurance flow (primary OKX + shadow Binance + D3 reconciliation) ──
    p_btc = sub.add_parser(
        "btc",
        aliases=["btc-assurance"],
        description="BTC assurance-gated sync (OKX primary, Binance shadow, D3 reconciliation).",
        epilog=(
            "trade data btc                   # Run sync, validate, publish\n"
            "trade data btc --mode validate   # Validate current snapshot only\n"
            "trade data btc --mode status     # Show current assurance status\n"
            "trade data btc --strict          # Exit non-zero on degraded\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_btc.add_argument("--data-root", default=str(default_data_root()))
    p_btc.add_argument("--mode", choices=["sync", "validate", "status"], default="sync")
    p_btc.add_argument("--dry-run", action="store_true")
    p_btc.add_argument("--strict", action="store_true")
    p_btc.add_argument("--json", action="store_true", dest="as_json")

    parser.epilog = epilog_from_subparsers(parser)
    return parser


def _dispatch_sync(args) -> int:
    from trade_py.data.ingest.batch import BatchIngestEngine, BatchIngestConfig
    from trade_py.db.trade_db import TradeDB

    data_root = Path(args.data_root)

    asset_classes = None
    if getattr(args, "crypto", False):
        asset_classes = ["crypto"]
    elif getattr(args, "asset_class", None):
        asset_classes = [c.strip() for c in args.asset_class.split(",") if c.strip()]

    symbols = None
    if getattr(args, "symbols", None):
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    full_refresh = getattr(args, "full_refresh", False)

    def _run_unified_sync() -> DataRunResult:
        db = TradeDB(data_root)
        config = BatchIngestConfig()
        engine = BatchIngestEngine(data_root, db=db, config=config)

        all_results = []
        try:
            engine.start()
            if asset_classes and len(asset_classes) > 1:
                for cls in asset_classes:
                    results = engine.ingest_by_class(
                        asset_class=cls,
                        symbols=symbols,
                        full_refresh=full_refresh,
                    )
                    all_results.extend(results)
            else:
                single_class = asset_classes[0] if asset_classes else None
                all_results = engine.ingest_by_class(
                    asset_class=single_class,
                    symbols=symbols,
                    full_refresh=full_refresh,
                )
        finally:
            engine.stop()

        results = all_results
        ok_count = sum(1 for r in results if r.success)
        fail_count = len(results) - ok_count
        total_new_rows = sum(r.new_rows for r in results)
        total_rows = sum(r.rows for r in results)
        errors = [f"{r.asset_id}: {r.error}" for r in results if r.error]

        asset_map = {}
        if results:
            for a in db.asset_registry_list():
                asset_map[a["asset_id"]] = a

        summary_lines = [
            f"Unified sync completed: {ok_count}/{len(results)} assets succeeded, {total_new_rows} new rows, {total_rows} total rows",
        ]
        if errors:
            summary_lines.append(f"Errors: {'; '.join(errors[:5])}")

        if getattr(args, "as_json", False):
            payload = {
                "total": len(results),
                "succeeded": ok_count,
                "failed": fail_count,
                "new_rows": total_new_rows,
                "total_rows": total_rows,
                "results": [
                    {
                        "asset_id": r.asset_id,
                        "symbol": asset_map.get(r.asset_id, {}).get("symbol", r.asset_id),
                        "asset_class": asset_map.get(r.asset_id, {}).get("asset_class", ""),
                        "success": r.success,
                        "new_rows": r.new_rows,
                        "total_rows": r.rows,
                        "watermark_date": r.watermark_date,
                        "error": r.error,
                    }
                    for r in results
                ],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            for line in summary_lines:
                print(line)
            print()
            print(f"{'Asset':<20} {'Class':<12} {'Status':<8} {'New':>6} {'Total':>8} {'Watermark':<12}")
            print("-" * 72)
            sorted_results = sorted(results, key=lambda r: (
                asset_map.get(r.asset_id, {}).get("asset_class", ""),
                asset_map.get(r.asset_id, {}).get("symbol", r.asset_id),
            ))
            for r in sorted_results:
                a = asset_map.get(r.asset_id, {})
                status = "OK" if r.success else "FAIL"
                cls = a.get("asset_class", "-")
                sym = a.get("symbol", r.asset_id)
                wm = r.watermark_date or "-"
                print(f"{sym:<20} {cls:<12} {status:<8} {r.new_rows:>6} {r.rows:>8} {wm:<12}")

        exit_code = 0 if fail_count == 0 else 1
        return DataRunResult(
            summary=summary_lines[0],
            exit_code=exit_code,
            symbols_processed=len(results),
        )

    return _track_data_run(str(data_root), "asset_batch_ingest", _run_unified_sync, stage="fetch")


def main(argv: list[str] | None = None) -> int:
    argv = argv or []
    if argv and argv[0] == "sentiment":
        from trade_py.cli._sentiment import main as sentiment_main
        sentiment_argv = argv[1:]
        if sentiment_argv and sentiment_argv[0] in ("-h", "--help"):
            return sentiment_main(sentiment_argv)
        if sentiment_argv and sentiment_argv[0] in _READ_ONLY_SENTIMENT_COMMANDS:
            return sentiment_main(sentiment_argv)
        data_root = _extract_flag_value(sentiment_argv, "--data-root", str(default_data_root()))
        stage = "compute" if sentiment_argv and sentiment_argv[0] == "apply-corrections" else "fetch"
        job_name = "sentiment_apply_corrections" if stage == "compute" else "sentiment_pipeline"

        def _run_sentiment() -> DataRunResult:
            exit_code = sentiment_main(sentiment_argv)
            action = "情绪校正" if stage == "compute" else "情绪流水线"
            args_text = " ".join(sentiment_argv) if sentiment_argv else "default"
            return DataRunResult(
                summary=f"{action}: {args_text}",
                exit_code=exit_code,
            )

        return _track_data_run(data_root, job_name, _run_sentiment, stage=stage)

    args = make_parser().parse_args(argv)

    if args.command == "status":
        _depr_warn("status", "trade status data")
        from trade_py.utils.data_inspector import build_status_lines, get_data_status

        status = get_data_status(args.data_root, sample_limit=args.limit, include_value_quality=True)
        if args.as_json:
            print(json.dumps(status, ensure_ascii=False, indent=2))
            return _data_status_exit_code(status, strict=args.strict)

        for line in build_status_lines(status):
            print(line)

        coverage = status.get("kline_coverage", {})
        if coverage.get("missing_sample"):
            print("### 缺失 K线样例")
            for symbol in coverage["missing_sample"]:
                print(f"- {symbol}")
            print()
        if coverage.get("suspicious_sample"):
            print("### 可疑 suffix 样例")
            for symbol in coverage["suspicious_sample"]:
                print(f"- {symbol}")
            print()

        freshness = status.get("kline_freshness", {})
        stale_sample = [
            row for row in freshness.get("stale_sample", [])
            if int(str(row.get("stale_days", "0"))) >= 1
        ]
        if stale_sample:
            print("### 滞后样例")
            print(f"{'symbol':<12} {'watermark':<12} {'last_download':<12} {'stale_days':>10}")
            print("-" * 56)
            for row in stale_sample:
                print(
                    f"{row['symbol']:<12} {row['watermark']:<12} {row['last_download']:<12} "
                    f"{row['stale_days']:>10}"
                )
            print()
        return _data_status_exit_code(status, strict=args.strict)

    if args.command == "sync":
        return _dispatch_sync(args)


    if args.command == "warehouse" and args.warehouse_cmd == "materialize-rss":
        from trade_py.data.warehouse import materialize_rss_research_loop

        catalog_rows = _read_records_file(args.catalog)
        rss_entries = _read_records_file(args.entries)
        position_rows = _read_records_file(args.positions) if args.positions else None
        result = materialize_rss_research_loop(
            args.data_root,
            catalog_rows=catalog_rows,
            rss_entries=rss_entries,
            position_rows=position_rows,
        )
        payload = result.to_dict()
        if args.as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        print(f"warehouse_root={result.layout_root}")
        print("tables:")
        for key in sorted(result.table_paths):
            print(f"  {key}: {result.table_paths[key]}")
        print("validation:")
        for row in result.validation_report.to_dict(orient="records"):
            print(
                f"  {row['status']:<5} {row['check_name']:<36} "
                f"rows={row['row_count']} {row['detail']}"
            )
        return 0

    if args.command == "warehouse" and args.warehouse_cmd == "validate-research":
        from trade_py.data.warehouse.crypto import validate_crypto_btc_profile

        try:
            payload = validate_crypto_btc_profile(args.data_root, dry_run=args.dry_run)
        except Exception as exc:
            payload = {
                "profile": args.profile,
                "as_of": args.as_of,
                "dry_run": args.dry_run,
                "status": "error",
                "reason_code": "RESEARCH_VALIDATION_IO_ERROR",
                "error": f"{type(exc).__name__}: {exc}",
            }
            if args.as_json:
                print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            else:
                print(f"research_validation=error reason={payload['reason_code']} error={payload['error']}")
            return 3
        validation = payload["validation"]
        if args.as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(
                f"profile={payload['profile']} data_readiness={validation['data_readiness']} "
                f"signal_status={validation['status']} run_id={validation['run_id']} "
                f"dry_run={payload['dry_run']}"
            )
            print(f"reasons={','.join(validation.get('reasons') or []) or '-'}")
            for table, path in payload["outputs"].items():
                print(f"  {table}: {path}")
        if payload.get("io_error"):
            return 3
        if validation["status"] == "invalid":
            return 2
        if args.strict and validation["data_readiness"] == "degraded":
            return 3
        return 0

    if args.command == "warehouse" and args.warehouse_cmd == "fetch-rss":
        from trade_py.data.warehouse import (
            ControlledFetchPolicy,
            WarehouseLayout,
            controlled_fetch_rss_sources,
            materialize_rss_research_loop,
            upsert_table,
            write_table,
        )

        catalog_rows = _read_records_file(args.catalog)
        policy = ControlledFetchPolicy(
            min_interval_seconds=args.min_interval_seconds,
            timeout_seconds=args.timeout_seconds,
            max_sources=args.max_sources,
            skip_sources=args.skip_sources,
            dry_run=args.dry_run,
        )
        dim_data_source, attempts, rss_entries = controlled_fetch_rss_sources(
            catalog_rows,
            policy=policy,
        )
        layout = WarehouseLayout.from_data_root(args.data_root)
        fetch_paths = {
            "dim.dim_data_source": write_table(layout, "dim", "dim_data_source", dim_data_source),
            "ods.ods_fetch_attempt": upsert_table(
                layout,
                "ods",
                "ods_fetch_attempt",
                attempts,
                key_cols=["source_id", "requested_at"],
            ),
        }
        result_payload = {
            "warehouse_root": str(layout.root),
            "fetch_paths": {key: str(value) for key, value in fetch_paths.items()},
            "attempts": attempts.to_dict(orient="records"),
            "entries": len(rss_entries),
            "materialized": None,
        }
        if not args.no_materialize and not args.dry_run:
            position_rows = _read_records_file(args.positions) if args.positions else None
            result = materialize_rss_research_loop(
                args.data_root,
                catalog_rows=catalog_rows,
                rss_entries=rss_entries,
                position_rows=position_rows,
            )
            result_payload["materialized"] = result.to_dict()
        if args.as_json:
            print(json.dumps(result_payload, ensure_ascii=False, indent=2))
            return 0
        print(f"warehouse_root={layout.root}")
        print(f"fetch_attempts={len(attempts)} entries={len(rss_entries)} dry_run={args.dry_run}")
        for row in attempts.to_dict(orient="records"):
            print(
                f"  {row['status']:<7} {row['source_id']:<28} "
                f"entries={row['entries']} elapsed_ms={row['elapsed_ms']} error={row['error_kind'] or '-'}"
            )
        if result_payload["materialized"]:
            print("materialized=true")
        return 0

    if args.command == "news":
        from pathlib import Path as _Path
        if args.news_cmd == "fetch":
            from trade_py.jobs import run_job
            def _run_news() -> DataRunResult:
                summary = run_job("crypto_news_sentiment", args.data_root)
                return DataRunResult(summary=summary, exit_code=0)
            return _track_data_run(args.data_root, "crypto_news_sentiment", _run_news, stage="fetch")

        if args.news_cmd == "fng":
            import pandas as pd
            fng_path = _resolve_fear_greed_path(args.data_root)
            if not fng_path.exists():
                print("Fear & Greed data not found. Run 'trade data news fetch' or 'trade data sync --class crypto' first.")
                return 1
            df = pd.read_parquet(fng_path).tail(args.limit)
            if args.as_json:
                print(df.to_json(orient="records", date_format="iso"))
            else:
                print(f"{'Date':<12} {'Value':>5}  {'Classification':<20}")
                print("-" * 42)
                for _, row in df.iterrows():
                    print(f"{str(row['date'])[:10]:<12} {int(row['value']):>5}  {row['classification']:<20}")
            return 0

        if args.news_cmd == "urgent":
            import pandas as pd
            from datetime import date as _date
            today = _date.today().isoformat()
            silver_path = _Path(args.data_root) / "news" / "silver" / f"{today}.parquet"
            if not silver_path.exists():
                print(f"No news data for {today}. Run 'trade data news fetch' first.")
                return 1
            df = pd.read_parquet(silver_path)
            urgent = df[df.get("is_urgent", False) == True].tail(args.limit) if "is_urgent" in df.columns else pd.DataFrame()
            if args.as_json:
                print(urgent.to_json(orient="records", date_format="iso"))
            else:
                if urgent.empty:
                    print(f"No urgent crypto news for {today}")
                else:
                    print(f"Urgent crypto news ({len(urgent)} items):")
                    for _, row in urgent.iterrows():
                        print(f"  [{row.get('event_type', '?'):<22}] sent={row.get('sentiment_score', 0):+.2f} {row.get('title', '')[:80]}")
                        if row.get('affected_symbols'):
                            print(f"         symbols={row.get('affected_symbols')}")
            return 0

        if args.news_cmd == "status":
            from datetime import date as _date
            root = _Path(args.data_root)
            today = _date.today().isoformat()
            fng_path = _resolve_fear_greed_path(args.data_root)
            silver_dir = root / "news" / "silver"
            bronze_dir = root / "news" / "bronze"
            status = {
                "fear_greed_exists": fng_path.exists(),
                "news_silver_today": (silver_dir / f"{today}.parquet").exists(),
                "news_sources": [],
            }
            if bronze_dir.exists():
                for src_dir in sorted(bronze_dir.iterdir()):
                    if src_dir.is_dir():
                        files = list(src_dir.glob("*.parquet"))
                        latest = max((f.name for f in files), default=None)
                        status["news_sources"].append({"source": src_dir.name, "articles": len(files), "latest": latest})
            import pandas as pd
            if fng_path.exists():
                fng_df = pd.read_parquet(fng_path)
                if not fng_df.empty:
                    latest = fng_df.iloc[-1]
                    status["fear_greed_latest"] = {"value": int(latest["value"]), "classification": latest["classification"], "date": str(latest["date"])}
            if (silver_dir / f"{today}.parquet").exists():
                silver_df = pd.read_parquet(silver_dir / f"{today}.parquet")
                status["today_articles"] = len(silver_df)
                if "is_urgent" in silver_df.columns:
                    status["today_urgent"] = int(silver_df["is_urgent"].sum())
                if "event_type" in silver_df.columns:
                    evts = silver_df[silver_df["event_type"] != "other"]["event_type"].value_counts().to_dict()
                    status["today_event_types"] = evts
            if args.as_json:
                print(json.dumps(status, ensure_ascii=False, indent=2, default=str))
            else:
                print("Crypto News Status:")
                if status.get("fear_greed_latest"):
                    fg = status["fear_greed_latest"]
                    print(f"  Fear & Greed: {fg['value']} ({fg['classification']}) as of {fg['date']}")
                print(f"  News silver today: {'YES' if status['news_silver_today'] else 'NO'}")
                if "today_articles" in status:
                    print(f"  Today articles: {status['today_articles']}, urgent={status.get('today_urgent', 0)}")
                print(f"  Sources ({len(status['news_sources'])}):")
                for src in status["news_sources"]:
                    print(f"    {src['source']:<20} days={src['articles']}  latest={src['latest']}")
            return 0

    if args.command in {"btc", "btc-assurance"}:
        from trade_py.data.market.crypto.service import BtcMarketDataService

        service = BtcMarketDataService(args.data_root)
        try:
            if args.mode == "sync":
                payload = service.sync(dry_run=args.dry_run)
            elif args.mode == "validate":
                if args.dry_run:
                    payload = {**service.validate_current(), "dry_run": True}
                else:
                    payload = service.validate_current()
            else:
                payload = service.status()
        except Exception as exc:
            payload = {
                "mode": args.mode,
                "data_readiness": "invalid",
                "reason_code": "BTC_DATA_IO_ERROR",
                "error": f"{type(exc).__name__}: {exc}",
            }
            if args.as_json:
                print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            else:
                print(f"btc_mode={args.mode} readiness=invalid error={payload['error']}")
            return 3

        if args.as_json:
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(
                f"btc_mode={args.mode} readiness={payload.get('data_readiness', 'invalid')} "
                f"run_id={payload.get('run_id') or '-'} published={payload.get('published', False)}"
            )
            gates = payload.get("gates") or (payload.get("manifest") or {}).get("gates") or []
            for gate in gates:
                print(
                    f"  {gate.get('gate', '-')}: {gate.get('status', '-')} "
                    f"{gate.get('reason_code', '-')}"
                )

        readiness = str(payload.get("data_readiness") or "invalid")
        gates = payload.get("gates") or (payload.get("manifest") or {}).get("gates") or []
        d3 = next((gate for gate in gates if gate.get("gate") == "D3"), {})
        if d3.get("status") == "fail" and d3.get("reason_code") == "SOURCE_DIVERGENCE":
            return 4
        if readiness == "invalid":
            return 2
        acquisition = payload.get("acquisition") or {}
        if args.mode == "sync" and int(acquisition.get("failed") or 0) > 0:
            return 3
        if args.mode == "sync" and (acquisition.get("predecessor") or {}).get("status") == "read_error":
            return 3
        if args.strict and readiness == "degraded":
            return 3
        return 0

    if args.command == "crypto":
        from pathlib import Path as _Path
        import pandas as pd

        root = _Path(args.data_root)
        crypto_dir = _resolve_crypto_dir(args.data_root)

        if args.crypto_cmd == "list":
            from trade_py.db.trade_db import TradeDB
            db = TradeDB(args.data_root)
            assets = db._conn.execute(
                "SELECT symbol, asset_class, venue, interval, watermark_date, "
                "last_sync_status, last_rows, enabled "
                "FROM asset_registry WHERE asset_class = 'crypto' ORDER BY symbol"
            ).fetchall()
            if args.as_json:
                cols = ["symbol", "asset_class", "venue", "interval", "watermark_date",
                        "last_sync_status", "last_rows", "enabled"]
                print(json.dumps([dict(zip(cols, a)) for a in assets], ensure_ascii=False, indent=2, default=str))
            else:
                print("Crypto assets (24/7 market, daily UTC bars):")
                print(f"  {'Symbol':<8} {'Venue':<12} {'Interval':<10} {'Watermark':<12} {'Rows':>6}  {'Status'}")
                print("  " + "-" * 72)
                for a in assets:
                    sym, cls, venue, interval, wm, status, rows, enabled = a
                    wm_str = str(wm)[:10] if wm else "N/A"
                    en = "" if enabled else " [DISABLED]"
                    rows_n = rows or 0
                    print(f"  {sym:<8} {(venue or ''):<12} {interval:<10} {wm_str:<12} {rows_n:>6}  {status or ''}{en}")
                print(f"\n  Data directory: {crypto_dir}")
            return 0

        if args.crypto_cmd == "fng":
            fng_path = crypto_dir / "fear_greed.parquet"
            if not fng_path.exists():
                print("Fear & Greed data not found. Run 'trade data news fetch' first.")
                return 1
            df = pd.read_parquet(fng_path).tail(args.limit)
            if args.as_json:
                print(df.to_json(orient="records", date_format="iso"))
            else:
                print("Crypto Fear & Greed Index (24/7 market):")
                print(f"{'Date':<12} {'Value':>5}  {'Classification':<20}")
                print("-" * 42)
                for _, row in df.iterrows():
                    print(f"{str(row['date'])[:10]:<12} {int(row['value']):>5}  {row['classification']:<20}")
            return 0

        if args.crypto_cmd == "show":
            symbol = args.symbol.upper()
            sym_lower = symbol.lower()
            kline_path = crypto_dir / f"{sym_lower}.parquet"
            if not kline_path.exists():
                print(f"Crypto K-line data not found for {symbol}.")
                print(f"Expected path: {kline_path}")
                print("Run 'trade data sync' first to fetch crypto data.")
                return 1
            full = pd.read_parquet(kline_path)
            total = len(full)
            df = full.tail(args.limit + 1).copy()
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
            if "close" in df.columns and len(df) >= 2:
                df["pct_chg"] = df["close"].pct_change() * 100
            df = df.tail(args.limit)
            if args.as_json:
                for col in ["open", "high", "low", "close", "pct_chg"]:
                    if col in df.columns:
                        df[col] = df[col].round(2)
                if "volume" in df.columns:
                    df["volume"] = df["volume"].round(4)
                print(df.to_json(orient="records", date_format="iso"))
            else:
                pct_col = "pct_chg" if "pct_chg" in df.columns else None
                cols = [c for c in ["date", "open", "high", "low", "close", "volume", pct_col] if c and c in df.columns]
                print(f"Crypto K-line: {symbol} (24/7 market, daily bars UTC)")
                print(f"Total rows: {total}  |  Showing last {len(df)} bars")
                print()
                header_fmt = f"{'Date':<12} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10} {'Volume':>12}"
                if pct_col:
                    header_fmt += f" {'Chg%':>7}"
                print(header_fmt)
                print("-" * (len(header_fmt) + 5))
                for _, row in df.iterrows():
                    line = f"{row['date']:<12} "
                    for c in ["open", "high", "low", "close"]:
                        line += f"{row[c]:>10.2f} "
                    vol = row.get("volume", 0)
                    if abs(vol) >= 1e9:
                        line += f"{vol/1e9:>10.2f}B "
                    elif abs(vol) >= 1e6:
                        line += f"{vol/1e6:>10.2f}M "
                    else:
                        line += f"{vol:>11.2f} "
                    if pct_col and not pd.isna(row.get(pct_col)):
                        chg = row[pct_col]
                        sign = "+" if chg >= 0 else ""
                        line += f" {sign}{chg:>6.2f}%"
                    print(line)
                print()
                print("Note: Crypto markets trade 24/7 including weekends. Daily bars finalized at UTC 00:00.")
            return 0

    if args.command in ("source", "sources"):
        _depr_warn("source", "trade config source")
        from trade_py.db.trade_db import TradeDB
        db = TradeDB(args.data_root)

        if args.src_cmd == "list":
            rows = db.asset_registry_list(
                asset_class=args.asset_class,
                enabled_only=False,
            )
            if args.venue:
                rows = [r for r in rows if r.get("venue") == args.venue]
            if args.disabled:
                rows = [r for r in rows if not r.get("enabled")]
            if args.as_json:
                print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2, default=str))
                return 0
            print(f"Data sources ({len(rows)} total):")
            print(f"  {'ID':<22} {'Class':<10} {'Sym':<8} {'Venue':<12} {'Interval':<8} {'QPS':>5} {'Watermark':<12} {'Status'}")
            print("  " + "-" * 105)
            for r in rows:
                aid = r["asset_id"]
                cls = r["asset_class"]
                sym = r["symbol"]
                ven = r.get("venue") or ""
                iv = r.get("interval") or ""
                mim = r.get("min_interval_ms", 300)
                qps = f"{1000/max(mim,1):.1f}" if mim else "?"
                wm = str(r.get("watermark_date") or "")[:10]
                st = r.get("last_sync_status") or ""
                en = "" if r.get("enabled") else " [OFF]"
                print(f"  {aid:<22} {cls:<10} {sym:<8} {ven:<12} {iv:<8} {qps:>5} {wm:<12} {st}{en}")
            print(f"\n  Hint: use 'trade data source show <ID>' for details, 'trade data sync' to fetch.")
            return 0

        if args.src_cmd == "show":
            aid = args.asset_id
            row = db.asset_registry_get(aid)
            if not row:
                print(f"Source not found: {aid}")
                return 1
            d = dict(row)
            if args.as_json:
                print(json.dumps(d, ensure_ascii=False, indent=2, default=str))
                return 0
            print(f"Source: {d['asset_id']}")
            print(f"  class:        {d['asset_class']}")
            print(f"  symbol:       {d['symbol']} / {d.get('quote_asset','USD')}")
            print(f"  venue:        {d.get('venue') or '(none)'}")
            print(f"  interval:     {d.get('interval')}")
            print(f"  enabled:      {'yes' if d.get('enabled') else 'NO'}")
            print(f"  priority:     {d.get('priority')}")
            print(f"  QPS limit:    {1000/max(d.get('min_interval_ms',300),1):.1f} req/sec (min_interval={d.get('min_interval_ms')}ms)")
            print(f"  batch_size:   {d.get('batch_size')}")
            print(f"  backfill:     {d.get('backfill_days')} days")
            print(f"  watermark:    {d.get('watermark_date') or '(never synced)'}")
            if d.get("last_sync_at"):
                print(f"  last sync:    {d['last_sync_at']}  ({d.get('last_sync_status') or '?'})")
            if d.get("last_rows"):
                print(f"  last rows:    {d['last_rows']}")
            if d.get("last_error"):
                print(f"  last error:   {d['last_error']}")
            return 0

        if args.src_cmd == "enable":
            db.asset_registry_set_enabled(args.asset_id, True)
            print(f"Enabled: {args.asset_id}")
            return 0

        if args.src_cmd == "disable":
            db.asset_registry_set_enabled(args.asset_id, False)
            print(f"Disabled: {args.asset_id}")
            return 0

        if args.src_cmd == "add":
            asset = {
                "asset_id": args.asset_id,
                "asset_class": args.asset_class,
                "symbol": args.symbol,
                "quote_asset": args.quote,
                "venue": args.venue,
                "interval": args.interval,
                "enabled": 1,
                "priority": args.priority,
                "batch_size": args.batch_size,
                "min_interval_ms": args.min_interval_ms,
                "backfill_days": args.backfill_days,
            }
            existing = db.asset_registry_get(args.asset_id)
            db.asset_registry_upsert(asset)
            action = "Updated" if existing else "Added"
            print(f"{action} source: {args.asset_id} ({args.asset_class}/{args.symbol} via {args.venue})")
            return 0

        if args.src_cmd == "remove":
            existing = db.asset_registry_get(args.asset_id)
            if not existing:
                print(f"Source not found: {args.asset_id}")
                return 1
            if not args.yes:
                print(f"Remove source '{args.asset_id}'? This does NOT delete parquet data. [y/N] ", end="", flush=True)
                try:
                    ans = input().strip().lower()
                except EOFError:
                    ans = "n"
                if ans not in ("y", "yes"):
                    print("Aborted.")
                    return 1
            if db.asset_registry_delete(args.asset_id):
                print(f"Removed: {args.asset_id}")
                return 0
            print(f"Failed to remove: {args.asset_id}")
            return 1

    if args.command in ("backfill", "jobs") and args.backfill_cmd == "status":
        _depr_warn("jobs status", "trade status jobs")
        from trade_py.db.trade_db import TradeDB

        db = TradeDB(args.data_root)
        running = db._conn.execute(
            """
            SELECT job_name, stage, status, started_at, result_summary
            FROM job_runs
            WHERE status = 'running'
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (args.limit,),
        ).fetchall()
        tracked_jobs = {
            "sentiment_pipeline",
            "event_sync",
            "event_rebuild",
            "kline_update",
            "realtime_quote_sync",
            "realtime_compute",
            "instrument_refresh",
            "fundamental",
            "fund_flow_update",
            "northbound",
            "market_index",
            "market_index_sector",
            "sector_refresh",
            "macro",
            "cross_asset_fetch",
            "asset_batch_ingest",
            "crypto_btc_fetch",
            "crypto_news_sentiment",
            "crypto_research_validation",
        }
        latest_by_job: dict[str, dict] = {}
        for row in db.job_runs_recent(limit=max(args.limit * 8, 96)):
            name = str(row.get("job_name") or "")
            if name not in tracked_jobs or name in latest_by_job:
                continue
            latest_by_job[name] = row
        sync_rows = db._conn.execute(
            """
            SELECT dataset,
                   COUNT(*) AS tracked_rows,
                   SUM(CASE WHEN last_date IS NOT NULL THEN 1 ELSE 0 END) AS dated_rows,
                   MIN(last_date) AS min_last_date,
                   MAX(last_date) AS max_last_date
            FROM sync_state
            GROUP BY dataset
            ORDER BY dataset
            """
        ).fetchall()
        events_row = db._conn.execute(
            "SELECT COUNT(*) AS event_count, MIN(event_date) AS min_date, MAX(event_date) AS max_date FROM market_events"
        ).fetchone()
        propagation_row = db._conn.execute(
            "SELECT COUNT(*) AS propagation_count FROM event_propagations"
        ).fetchone()
        kline_watermark = db._conn.execute(
            """
            SELECT COUNT(*) AS tracked_rows,
                   MIN(last_date) AS min_last_date,
                   MAX(last_date) AS max_last_date
            FROM sync_state
            WHERE dataset = 'kline'
            """
        ).fetchone()
        fundamental_watermark = db._conn.execute(
            """
            SELECT COUNT(*) AS tracked_rows,
                   MIN(last_date) AS min_last_date,
                   MAX(last_date) AS max_last_date
            FROM sync_state
            WHERE dataset = 'fundamental'
            """
        ).fetchone()
        fund_flow_watermark = db._conn.execute(
            """
            SELECT COUNT(*) AS tracked_rows,
                   MIN(last_date) AS min_last_date,
                   MAX(last_date) AS max_last_date
            FROM sync_state
            WHERE dataset = 'fund_flow'
            """
        ).fetchone()
        sentiment_silver = _parquet_tree_summary(Path(args.data_root) / "sentiment" / "silver")
        sentiment_gold = _parquet_tree_summary(Path(args.data_root) / "sentiment" / "gold")

        print("running_jobs:")
        if not running:
            print("  none")
        for row in running:
            state = _running_job_state(dict(row))
            print(
                f"  {row['job_name']:<20} status={state['status']:<14} stage={row['stage'] or '—':<8} "
                f"age_h={state['age_hours'] if state['age_hours'] is not None else '—'} "
                f"stale_after_h={state['stale_after_hours']} "
                f"started_at={row['started_at']} summary={row['result_summary'] or ''}"
            )
        print()
        print("latest_jobs:")
        for job_name in sorted(latest_by_job):
            row = latest_by_job[job_name]
            print(
                f"  {job_name:<20} status={row['status']:<8} started={row['started_at']} "
                f"completed={row['completed_at'] or '—'}"
            )
        print()
        print("sync_state:")
        for row in sync_rows:
            print(
                f"  {row['dataset']:<18} tracked={int(row['tracked_rows'] or 0):>6} "
                f"dated={int(row['dated_rows'] or 0):>6} "
                f"range={row['min_last_date'] or '—'} -> {row['max_last_date'] or '—'}"
            )
        print()
        print("coverage_snapshot:")
        print(
            f"  kline_sync_rows={int((kline_watermark['tracked_rows'] if kline_watermark else 0) or 0)} "
            f"date_range={(kline_watermark['min_last_date'] if kline_watermark else None) or '—'} -> {(kline_watermark['max_last_date'] if kline_watermark else None) or '—'}"
        )
        print(
            f"  fundamental_sync_rows={int((fundamental_watermark['tracked_rows'] if fundamental_watermark else 0) or 0)} "
            f"date_range={(fundamental_watermark['min_last_date'] if fundamental_watermark else None) or '—'} -> {(fundamental_watermark['max_last_date'] if fundamental_watermark else None) or '—'}"
        )
        print(
            f"  fund_flow_sync_rows={int((fund_flow_watermark['tracked_rows'] if fund_flow_watermark else 0) or 0)} "
            f"date_range={(fund_flow_watermark['min_last_date'] if fund_flow_watermark else None) or '—'} -> {(fund_flow_watermark['max_last_date'] if fund_flow_watermark else None) or '—'}"
        )
        print(
            f"  sentiment_silver_files={sentiment_silver['files']} "
            f"date_range={sentiment_silver['min_date'] or '—'} -> {sentiment_silver['max_date'] or '—'}"
        )
        print(
            f"  sentiment_gold_files={sentiment_gold['files']} "
            f"date_range={sentiment_gold['min_date'] or '—'} -> {sentiment_gold['max_date'] or '—'}"
        )
        print(
            f"  market_events={int((events_row['event_count'] if events_row else 0) or 0)} "
            f"propagations={int((propagation_row['propagation_count'] if propagation_row else 0) or 0)} "
            f"date_range={(events_row['min_date'] if events_row else None) or '—'} -> {(events_row['max_date'] if events_row else None) or '—'}"
        )
        return 0

    if args.command == "kline":
        service = KlineSyncService(args.data_root)
        if args.kline_cmd == "sync":
            def _run_kline_sync() -> DataRunResult:
                symbols = None
                if args.symbols:
                    symbols = [s.strip() for s in str(args.symbols).split(",") if s.strip()]
                defaults = _kline_defaults()
                start = _resolve_kline_start(args.data_root, args.start, defaults.get("start"))
                opts = KlineSyncOptions(
                    mode=args.mode,
                    symbols=symbols,
                    start=start,
                    end=args.end,
                    adjust=args.adjust,
                    provider=args.provider,
                    delay_ms=args.delay_ms,
                    fail_fast=args.fail_fast,
                )
                summary = service.sync(opts)
                logger.info(
                    "kline sync summary: mode=%s api_calls=%s total=%d succeeded=%d failed=%d empty=%d rows=%d",
                    summary.sync_mode,
                    summary.api_calls if summary.api_calls is not None else "-",
                    summary.total_symbols,
                    summary.succeeded,
                    summary.failed,
                    summary.empty,
                    summary.total_rows,
                )
                if summary.failed > 0:
                    for symbol, res in summary.results.items():
                        if not res.ok:
                            logger.error(
                                "kline sync failed symbol=%s kind=%s error=%s",
                                symbol, res.error_kind, res.error_message,
                            )
                return DataRunResult(
                    summary=(
                        f"K线同步: mode={summary.sync_mode} "
                        f"api_calls={summary.api_calls if summary.api_calls is not None else '-'} "
                        f"total={summary.total_symbols} ok={summary.succeeded} "
                        f"failed={summary.failed} skip={summary.empty} rows={summary.total_rows}"
                    ),
                    exit_code=0 if summary.failed == 0 else 1,
                    symbols_processed=summary.total_symbols,
                )

            return _track_data_run(args.data_root, "kline_update", _run_kline_sync)
        if args.kline_cmd == "instruments":
            def _run_instruments_refresh() -> DataRunResult:
                instruments = service.refresh_instruments()
                return DataRunResult(
                    summary=f"标的列表刷新: {len(instruments)} 条",
                    exit_code=0 if instruments else 1,
                    symbols_processed=len(instruments),
                )

            return _track_data_run(args.data_root, "instrument_refresh", _run_instruments_refresh)
        if args.kline_cmd == "status":
            rows = service.status(stale_days=args.stale_days, limit=args.limit)
            if not rows:
                print("No symbols found.")
                return 0
            print(f"{'symbol':<12} {'watermark':<12} {'last_download':<12} {'stale_days':>10} {'last_error':<20}")
            print("-" * 72)
            for row in rows:
                print(
                    f"{row['symbol']:<12} {row['watermark']:<12} {row['last_download']:<12} "
                    f"{row['stale_days']:>10} {row['last_error_kind']:<20}"
                )
            return 0
        if args.kline_cmd == "reconcile":
            from trade_py.data.market.kline.reconciliation import reconcile_kline

            symbols = [symbol.strip() for symbol in str(args.symbols).split(",") if symbol.strip()]
            payload = reconcile_kline(
                args.data_root,
                symbols=symbols,
                start=args.start,
                end=args.end,
                shadow_provider=args.shadow_provider,
                adjust=args.adjust,
                warn_basis_pct=args.warn_basis_pct,
                block_basis_pct=args.block_basis_pct,
                minimum_checked_rows=args.minimum_checked_rows,
                dry_run=args.dry_run,
            )
            if args.as_json:
                print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            else:
                metrics = payload.get("metrics") or {}
                mode = "dry-run" if payload.get("dry_run") else "write"
                print(
                    f"kline_reconcile mode={mode} status={payload.get('status')} "
                    f"checked_rows={metrics.get('checked_rows', 0)} "
                    f"block_rows={metrics.get('block_rows', 0)} "
                    f"warn_rows={metrics.get('warn_rows', 0)} "
                    f"artifact={payload.get('artifact_path') or '-'}"
                )
            return 0 if str(payload.get("status") or "") == "pass" else 2

    if args.command == "realtime":
        from trade_py.analysis.intraday_runtime import compute_intraday_snapshot
        from trade_py.data.market.intraday import TushareIntradayFetcher

        if args.rt_cmd == "sync":
            def _run_realtime_sync() -> DataRunResult:
                symbols = _resolve_default_symbols(args.data_root, args.symbols)
                fetcher = TushareIntradayFetcher(args.data_root)
                summary = fetcher.fetch_batch(
                    symbols,
                    freq=args.freq,
                    start_time=args.start_time,
                    end_time=args.end_time,
                    lookback_minutes=args.lookback_minutes,
                    chunk_size=args.chunk_size,
                    asset=args.asset,
                )
                logger.info(
                    "realtime sync summary: symbols=%d api_calls=%d rows=%d saved=%d freq=%s provider=%s degraded=%s window=%s..%s",
                    summary.requested_symbols,
                    summary.api_calls,
                    summary.rows_fetched,
                    summary.symbols_saved,
                    summary.freq,
                    summary.provider,
                    summary.degraded_reason or "-",
                    summary.start_time,
                    summary.end_time,
                )
                return DataRunResult(
                    summary=(
                        f"实时分钟同步: requested={summary.requested_symbols} saved={summary.symbols_saved} "
                        f"api_calls={summary.api_calls} rows={summary.rows_fetched} freq={summary.freq} "
                        f"provider={summary.provider}"
                        + (f" degraded={summary.degraded_reason}" if summary.degraded_reason else "")
                    ),
                    symbols_processed=summary.symbols_saved,
                )

            return _track_data_run(args.data_root, "realtime_quote_sync", _run_realtime_sync, stage="fetch")

        if args.rt_cmd == "compute":
            def _run_realtime_compute() -> DataRunResult:
                symbols = _resolve_default_symbols(args.data_root, args.symbols)
                result = compute_intraday_snapshot(
                    args.data_root,
                    symbols=symbols,
                    freq=args.freq,
                    lookback_bars=args.lookback_bars,
                    top=args.top,
                    persist_factors=not args.no_persist_factors,
                )
                rows = result.get("rows", [])
                if rows:
                    print(json.dumps(rows, ensure_ascii=False, indent=2))
                return DataRunResult(
                    summary=(
                        f"实时因子计算: row_count={int(result.get('row_count') or 0)} "
                        f"snapshot={result.get('snapshot_path') or '-'}"
                    ),
                    symbols_processed=int(result.get("row_count") or 0),
                )

            return _track_data_run(args.data_root, "realtime_compute", _run_realtime_compute, stage="compute")

        if args.rt_cmd == "run":
            def _run_realtime_pipeline() -> DataRunResult:
                symbols = _resolve_default_symbols(args.data_root, args.symbols)
                fetcher = TushareIntradayFetcher(args.data_root)
                sync_summary = fetcher.fetch_batch(
                    symbols,
                    freq=args.freq,
                    start_time=args.start_time,
                    end_time=args.end_time,
                    lookback_minutes=args.lookback_minutes,
                    chunk_size=args.chunk_size,
                    asset=args.asset,
                )
                result = compute_intraday_snapshot(
                    args.data_root,
                    symbols=symbols,
                    freq=args.freq,
                    lookback_bars=args.lookback_bars,
                    top=args.top,
                    persist_factors=not args.no_persist_factors,
                )
                rows = result.get("rows", [])
                if rows:
                    print(json.dumps(rows, ensure_ascii=False, indent=2))
                return DataRunResult(
                    summary=(
                        f"实时流水线: requested={sync_summary.requested_symbols} saved={sync_summary.symbols_saved} "
                        f"api_calls={sync_summary.api_calls} row_count={int(result.get('row_count') or 0)} "
                        f"snapshot={result.get('snapshot_path') or '-'} provider={sync_summary.provider}"
                        + (f" degraded={sync_summary.degraded_reason}" if sync_summary.degraded_reason else "")
                    ),
                    symbols_processed=int(result.get("row_count") or 0),
                )

            return _track_data_run(args.data_root, "realtime_pipeline", _run_realtime_pipeline, stage="compute")

    if args.command == "fundamental":
        from trade_py.data.market.fundamental.tushare import FundamentalFetcher
        from trade_py.db.instruments_db import InstrumentsDB
        fetcher = FundamentalFetcher(args.data_root)
        if args.fund_cmd == "sync":
            def _run_fundamental() -> DataRunResult:
                if args.symbols:
                    symbols = [s.strip() for s in str(args.symbols).split(",") if s.strip()]
                else:
                    db = InstrumentsDB(args.data_root)
                    symbols = db.get_all_symbols()
                logger.info("Syncing fundamental data for %d symbols", len(symbols))
                summary = fetcher.fetch_batch(symbols, start_date=args.start)
                logger.info("fundamental sync mode=%s api_calls=%s", summary.get("mode"), summary.get("api_calls"))
                return DataRunResult(
                    summary=(
                        f"基本面同步: symbols={len(symbols)} mode={summary.get('mode')} "
                        f"saved={summary.get('saved_symbols')} api_calls={summary.get('api_calls')}"
                    ),
                    symbols_processed=len(symbols),
                )

            return _track_data_run(args.data_root, "fundamental", _run_fundamental)

    if args.command == "fund-flow":
        from trade_py.data.market.fund_flow.tushare import FundFlowFetcher
        from trade_py.db.instruments_db import InstrumentsDB
        fetcher = FundFlowFetcher(args.data_root)
        if args.ff_cmd == "sync":
            def _run_fund_flow() -> DataRunResult:
                if args.symbols:
                    symbols = [s.strip() for s in str(args.symbols).split(",") if s.strip()]
                else:
                    db = InstrumentsDB(args.data_root)
                    symbols = db.get_all_symbols()
                logger.info("Syncing fund-flow data for %d symbols", len(symbols))
                summary = fetcher.fetch_batch(symbols, start_date=args.start, end_date=args.end)
                logger.info("fund-flow sync mode=%s api_calls=%s", summary.get("mode"), summary.get("api_calls"))
                return DataRunResult(
                    summary=(
                        f"资金流向同步: symbols={len(symbols)} mode={summary.get('mode')} "
                        f"saved={summary.get('saved_symbols')} api_calls={summary.get('api_calls')}"
                    ),
                    symbols_processed=len(symbols),
                )

            return _track_data_run(args.data_root, "fund_flow_update", _run_fund_flow)

    if args.command == "northbound":
        from trade_py.data.market.northbound.tushare import NorthboundFetcher
        fetcher = NorthboundFetcher(args.data_root)
        if args.nb_cmd == "sync":
            def _run_northbound() -> DataRunResult:
                df = fetcher.fetch_and_save(start_date=args.start, end_date=args.end)
                logger.info("Northbound sync complete")
                return DataRunResult(
                    summary=f"北向资金同步: {len(df)} 行",
                    symbols_processed=len(df),
                )

            return _track_data_run(args.data_root, "northbound", _run_northbound)

    if args.command in {"index", "market-index"}:
        from trade_py.data.market.index.tushare import IndexFetcher
        fetcher = IndexFetcher(args.data_root)
        if args.idx_cmd == "sync":
            def _run_market_index() -> DataRunResult:
                codes = None
                if args.codes:
                    codes = [c.strip() for c in str(args.codes).split(",") if c.strip()]
                fetcher.fetch_all(indices=codes, start_date=args.start)
                logger.info("Index sync complete")
                return DataRunResult(
                    summary=f"指数同步完成: {len(codes) if codes else 4} 个指数",
                    symbols_processed=len(codes) if codes else 4,
                )

            return _track_data_run(args.data_root, "market_index", _run_market_index)
        if args.idx_cmd in {"sync-sector", "sync-industry"}:
            def _run_sector_index() -> DataRunResult:
                fetcher.fetch_sector_all(start_date=args.start)
                logger.info("Sector index sync complete")
                return DataRunResult(summary="行业指数同步完成: 31 个申万一级行业")

            return _track_data_run(args.data_root, "market_index_sector", _run_sector_index)
        if args.idx_cmd in {"refresh-members", "refresh-industry-members"}:
            def _run_sector_refresh() -> DataRunResult:
                updated = fetcher.refresh_sector_members()
                logger.info("Sector members refreshed: %d instruments updated", len(updated))
                return DataRunResult(
                    summary=f"板块映射刷新: {len(updated)} 只标的",
                    symbols_processed=len(updated),
                )

            return _track_data_run(args.data_root, "sector_refresh", _run_sector_refresh)

    if args.command == "macro":
        from trade_py.data.market.macro.tushare import MacroFetcher
        fetcher = MacroFetcher(args.data_root)
        if args.macro_cmd == "sync":
            def _run_macro() -> DataRunResult:
                if args.dataset:
                    fetcher.fetch_and_save(args.dataset)
                    summary = f"宏观同步完成: {args.dataset}"
                else:
                    fetcher.fetch_all()
                    summary = "宏观同步完成: gdp,cpi,ppi,pmi"
                logger.info("Macro sync complete")
                return DataRunResult(summary=summary)

            return _track_data_run(args.data_root, "macro", _run_macro)

    return 1
