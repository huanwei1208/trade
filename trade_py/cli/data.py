from __future__ import annotations

import argparse
import csv
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from trade_py.infra.settings import default_data_root, load_defaults
from trade_py.data.market.cross_asset import fetch_all, fetch_btc, fetch_fx_cnh, fetch_gold
from trade_py.data.market.kline import KlineSyncOptions, KlineSyncService
from trade_py.db.settings_db import SettingsDB

logger = logging.getLogger(__name__)

_DATA_ROOT_ARG = str(default_data_root())
_READ_ONLY_SENTIMENT_COMMANDS = {"status", "sources", "doctor", "inspect", "sample"}
_DEFAULT_RESEARCH_SOURCE_CATALOG = Path("trade_py/infra/config/research_sources.csv")


@dataclass
class DataRunResult:
    summary: str
    exit_code: int = 0
    symbols_processed: int | None = None


def _truncate_summary(text: str, limit: int = 500) -> str:
    return text if len(text) <= limit else text[:limit]


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
    from trade_py.cli import epilog_from_subparsers

    defaults = _kline_defaults()

    def d(name: str, fallback):
        return defaults.get(name, fallback)

    parser = argparse.ArgumentParser(
        prog="trade data",
        description="数据采集 — K线/情绪/跨资产",
        formatter_class=argparse.RawDescriptionHelpFormatter,
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

    p_backfill = sub.add_parser(
        "backfill",
        description="查看后台回补与同步进度",
        epilog=(
            "trade data backfill status\n"
            "trade data backfill status --limit 20"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    backfill_sub = p_backfill.add_subparsers(dest="backfill_cmd", required=True)
    p_backfill_status = backfill_sub.add_parser("status", description="查看回补任务、sync_state 和覆盖快照")
    p_backfill_status.add_argument("--data-root", default=str(default_data_root()))
    p_backfill_status.add_argument("--limit", type=int, default=12)

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
    p_sync.add_argument("--provider", choices=["auto", "tushare", "akshare", "baostock"], default=d("provider", "auto"))
    p_sync.add_argument("--delay-ms", type=int, default=int(d("delay_ms", 300)))
    p_sync.add_argument("--fail-fast", action="store_true")

    p_instruments = kline_sub.add_parser("instruments", description="刷新标的列表")
    p_instruments.add_argument("--data-root", default=str(default_data_root()))

    p_status = kline_sub.add_parser("status", description="显示 K线同步状态")
    p_status.add_argument("--data-root", default=str(default_data_root()))
    p_status.add_argument("--stale-days", type=int, default=None, help="Only show symbols stale >= N days")
    p_status.add_argument("--limit", type=int, default=50)

    p_cross = sub.add_parser(
        "cross-asset",
        description="跨资产行情抓取 (gold/btc/fx/cnh)",
        epilog=(
            "trade data cross-asset all\n"
            "trade data cross-asset gold"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_cross.add_argument("asset", nargs="?", choices=["all", "gold", "fx", "btc"], default="all")
    p_cross.add_argument("--data-root", default=str(default_data_root()))

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
    p_wh_fetch.add_argument("--min-interval-seconds", type=float, default=1.0)
    p_wh_fetch.add_argument("--timeout-seconds", type=int, default=10)
    p_wh_fetch.add_argument("--dry-run", action="store_true")
    p_wh_fetch.add_argument("--no-materialize", action="store_true")
    p_wh_fetch.add_argument("--json", action="store_true", dest="as_json")

    parser.epilog = epilog_from_subparsers(parser)
    return parser


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
        from trade_py.utils.data_inspector import build_status_lines, get_data_status

        status = get_data_status(args.data_root, sample_limit=args.limit)
        if args.as_json:
            print(json.dumps(status, ensure_ascii=False, indent=2))
            return 0

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
        return 0

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

    if args.command == "warehouse" and args.warehouse_cmd == "fetch-rss":
        from trade_py.data.warehouse import (
            ControlledFetchPolicy,
            WarehouseLayout,
            controlled_fetch_rss_sources,
            materialize_rss_research_loop,
            write_table,
        )

        catalog_rows = _read_records_file(args.catalog)
        policy = ControlledFetchPolicy(
            min_interval_seconds=args.min_interval_seconds,
            timeout_seconds=args.timeout_seconds,
            max_sources=args.max_sources,
            dry_run=args.dry_run,
        )
        dim_data_source, attempts, rss_entries = controlled_fetch_rss_sources(
            catalog_rows,
            policy=policy,
        )
        layout = WarehouseLayout.from_data_root(args.data_root)
        fetch_paths = {
            "dim.dim_data_source": write_table(layout, "dim", "dim_data_source", dim_data_source),
            "ods.ods_fetch_attempt": write_table(layout, "ods", "ods_fetch_attempt", attempts),
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

    if args.command == "backfill" and args.backfill_cmd == "status":
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
            print(
                f"  {row['job_name']:<20} stage={row['stage'] or '—':<8} "
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

    if args.command == "cross-asset":
        def _run_cross_asset() -> DataRunResult:
            fn_map = {
                "gold": lambda: fetch_gold(args.data_root),
                "fx": lambda: fetch_fx_cnh(args.data_root),
                "btc": lambda: fetch_btc(args.data_root),
                "all": lambda: fetch_all(args.data_root),
            }
            fn_map[args.asset]()
            return DataRunResult(summary=f"跨资产同步完成: {args.asset}")

        return _track_data_run(args.data_root, "cross_asset_fetch", _run_cross_asset)

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
