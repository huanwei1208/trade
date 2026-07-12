from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from trade_py.cli import global_flag_parent
from trade_py.infra.settings.context import default_data_root, resolve_repo_path


def _config_yaml_path() -> Path:
    configured = os.environ.get("TRADE_CONFIG_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return resolve_repo_path("config/trade.yaml")


def _config_example_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    return root / "infra" / "config" / "trade.yaml.example"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml
    except ImportError:
        print("Warning: pyyaml not installed; cannot read YAML config", file=sys.stderr)
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _save_yaml(path: Path, data: dict[str, Any]) -> None:
    try:
        import yaml
    except ImportError:
        print("Error: pyyaml not installed; cannot write YAML config", file=sys.stderr)
        raise SystemExit(1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False), encoding="utf-8")


def _db(data_root: str):
    from trade_py.db.trade_db import TradeDB
    return TradeDB(data_root)


def _flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def _sensitive(key: str) -> bool:
    k = key.lower()
    return any(tok in k for tok in ("token", "key", "secret", "password", "apikey", "api_key"))


def _mask(value: Any) -> str:
    s = str(value)
    if len(s) <= 4:
        return "***"
    return s[:2] + "***" + s[-2:]


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trade config",
        description="配置管理 — 数据源/密钥/路径/DAG 开关/自选股/备份",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[global_flag_parent()],
        epilog=(
            "trade config init                         # 从 example 创建 config/trade.yaml\n"
            "trade config path                         # 显示当前 data_root / config 路径\n"
            "trade config show                         # 显示所有已持久化的设置\n"
            "trade config get tushare_token            # 读取单个设置\n"
            "trade config set tushare_token abc123     # 写入设置 (DB)\n"
            "trade config doctor                       # 检查密钥/路径/备份配置\n"
            "trade config source list                  # 数据源列表 (同 trade data source list)\n"
            "trade config source enable BTC            # 启用数据源\n"
            "trade config watch list                   # 自选股列表\n"
            "trade config dag list                     # DAG 任务开关状态\n"
            "trade config dag enable kline_update      # 启用 DAG 节点\n"
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # Shared parent for --data-root
    _dr = argparse.ArgumentParser(add_help=False)
    _dr.add_argument("--data-root", default=str(default_data_root()))

    p_init = sub.add_parser("init", description="从 example 创建 config/trade.yaml (如果不存在)", parents=[_dr])
    p_init.add_argument("--force", action="store_true", help="覆盖已存在的 trade.yaml")

    p_path = sub.add_parser("path", description="显示已解析的路径 (repo_root / data_root / config)", parents=[_dr])
    p_path.add_argument("--json", action="store_true", dest="as_json")

    p_show = sub.add_parser("show", description="显示所有已持久化的设置 (DB + YAML + ENV 合并视图)", parents=[_dr])
    p_show.add_argument("--category", default=None, help="按 category 过滤: credentials/paths/general/...")
    p_show.add_argument("--show-secrets", action="store_true", help="显示密钥明文 (默认打码)")
    p_show.add_argument("--json", action="store_true", dest="as_json")

    p_get = sub.add_parser("get", description="读取单个设置", parents=[_dr])
    p_get.add_argument("key")
    p_get.add_argument("--show-secret", action="store_true")

    p_set = sub.add_parser("set", description="写入设置到 DB (key=value)", parents=[_dr])
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_set.add_argument("--category", default="general")
    p_set.add_argument("--type", choices=["string", "int", "float", "bool", "json"], default=None)

    p_unset = sub.add_parser("unset", description="删除设置", parents=[_dr])
    p_unset.add_argument("key")

    p_doctor = sub.add_parser("doctor", description="配置健康检查 (密钥/路径/写入权限/备份)", parents=[_dr])

    # source subcommand (write-ops: enable/disable/add/remove; list/show delegated but available)
    p_src = sub.add_parser("source", description="数据源启停/注册 (asset_registry)",
                           formatter_class=argparse.RawDescriptionHelpFormatter,
                           parents=[_dr])
    src_sub = p_src.add_subparsers(dest="src_cmd", required=True)

    p_src_list = src_sub.add_parser("list", description="列出所有数据源", parents=[_dr])
    p_src_list.add_argument("--class", dest="asset_class", default=None)
    p_src_list.add_argument("--venue", default=None)
    p_src_list.add_argument("--disabled", action="store_true")
    p_src_list.add_argument("--json", action="store_true", dest="as_json")

    p_src_show = src_sub.add_parser("show", description="查看单个数据源详情", parents=[_dr])
    p_src_show.add_argument("asset_id")
    p_src_show.add_argument("--json", action="store_true", dest="as_json")

    p_src_enable = src_sub.add_parser("enable", description="启用数据源", parents=[_dr])
    p_src_enable.add_argument("asset_id")

    p_src_disable = src_sub.add_parser("disable", description="停用数据源", parents=[_dr])
    p_src_disable.add_argument("asset_id")

    p_src_add = src_sub.add_parser("add", description="新增数据源", parents=[_dr])
    p_src_add.add_argument("--asset-id", required=True)
    p_src_add.add_argument("--class", dest="asset_class", required=True)
    p_src_add.add_argument("--symbol", required=True)
    p_src_add.add_argument("--venue", required=True)
    p_src_add.add_argument("--quote", default="USD")
    p_src_add.add_argument("--interval", default="1d")
    p_src_add.add_argument("--priority", type=int, default=5)
    p_src_add.add_argument("--batch-size", type=int, default=100)
    p_src_add.add_argument("--min-interval-ms", type=int, default=300)
    p_src_add.add_argument("--backfill-days", type=int, default=730)

    p_src_remove = src_sub.add_parser("remove", description="删除数据源 (不删除 parquet)", parents=[_dr])
    p_src_remove.add_argument("asset_id")
    p_src_remove.add_argument("--yes", action="store_true")

    # watch subcommand (watchlist)
    p_w = sub.add_parser("watch", description="自选股管理", parents=[_dr])
    w_sub = p_w.add_subparsers(dest="w_cmd", required=True)
    w_sub.add_parser("list", description="列出自选股", parents=[_dr])
    p_w_add = w_sub.add_parser("add", description="添加自选股", parents=[_dr])
    p_w_add.add_argument("symbol")
    p_w_add.add_argument("--note", default="")
    p_w_rm = w_sub.add_parser("remove", description="移除自选股", parents=[_dr])
    p_w_rm.add_argument("symbol")

    # dag subcommand (pipeline_dag toggles)
    p_dag = sub.add_parser("dag", description="DAG 任务开关管理", parents=[_dr])
    dag_sub = p_dag.add_subparsers(dest="dag_cmd", required=True)
    p_dag_list = dag_sub.add_parser("list", description="列出所有 DAG 节点及启用状态", parents=[_dr])
    p_dag_list.add_argument("--all", action="store_true", help="包含已禁用节点")
    p_dag_enable = dag_sub.add_parser("enable", description="启用 DAG 节点", parents=[_dr])
    p_dag_enable.add_argument("job_name")
    p_dag_disable = dag_sub.add_parser("disable", description="禁用 DAG 节点", parents=[_dr])
    p_dag_disable.add_argument("job_name")

    return parser


def _cmd_init(args) -> int:
    target = _config_yaml_path()
    example = _config_example_path()
    if target.exists() and not args.force:
        print(f"Config already exists: {target}")
        print("Use --force to overwrite.")
        return 1
    if not example.exists():
        print(f"Example config not found: {example}")
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(example, target)
    print(f"Created: {target}")
    print("Edit this file to set tushare_token, web port, etc.")
    return 0


def _cmd_path(args) -> int:
    repo = resolve_repo_path(".")
    data = Path(args.data_root)
    if not data.is_absolute():
        data = resolve_repo_path(data)
    cfg = _config_yaml_path()
    if args.as_json:
        print(json.dumps({
            "repo_root": str(repo),
            "data_root": str(data),
            "config_file": str(cfg),
            "config_exists": cfg.exists(),
        }, ensure_ascii=False, indent=2))
        return 0
    print(f"repo_root:   {repo}")
    print(f"data_root:   {data}")
    print(f"config_file: {cfg}  ({'exists' if cfg.exists() else 'missing; run: trade config init'})")
    return 0


def _cmd_show(args) -> int:
    db = _db(args.data_root)
    yaml_cfg = _load_yaml(_config_yaml_path())
    rows = db._conn.execute(
        "SELECT key, value, value_type, category, label FROM settings ORDER BY category, key"
    ).fetchall()
    db_settings: dict[str, dict] = {}
    for r in rows:
        if args.category and r["category"] != args.category:
            continue
        db_settings[r["key"]] = {
            "value": db._cast(r["value"], r["value_type"]),
            "source": "db",
            "category": r["category"],
            "label": r["label"],
        }
    yaml_flat = _flatten(yaml_cfg)
    merged: dict[str, dict] = dict(db_settings)
    for k, v in yaml_flat.items():
        if k not in merged and (not args.category or args.category == "yaml"):
            merged[k] = {"value": v, "source": "yaml", "category": "yaml", "label": ""}
    env_keys = ["TUSHARE_TOKEN", "ANTHROPIC_API_KEY", "TRADE_DATA_ROOT", "TRADE_CONFIG_FILE",
                "TRADE_NOTIFY_URL", "TRADE_RSSHUB_BASE_URL"]
    env_map = {k: os.environ.get(k, "") for k in env_keys if os.environ.get(k, "")}
    for k, v in env_map.items():
        key = f"env.{k}"
        if not args.category or args.category in ("env", "credentials"):
            merged[key] = {"value": v, "source": "env", "category": "env", "label": k}

    if args.as_json:
        out = {k: {"value": v["value"], "source": v["source"], "category": v["category"]}
               for k, v in merged.items()}
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0

    print(f"{'Key':<35} {'Source':<6} {'Category':<12} {'Value'}")
    print("-" * 100)
    for k in sorted(merged):
        v = merged[k]
        val = v["value"]
        if _sensitive(k) and not args.show_secrets:
            val = _mask(val)
        print(f"{k:<35} {v['source']:<6} {v['category']:<12} {val}")
    print()
    if not args.show_secrets:
        print("(secrets masked; use --show-secrets to reveal)")
    return 0


def _cmd_get(args) -> int:
    db = _db(args.data_root)
    val = db.get(args.key, None)
    if val is None:
        yaml_cfg = _flatten(_load_yaml(_config_yaml_path()))
        val = yaml_cfg.get(args.key)
    if val is None:
        print(f"(not set)")
        return 1
    if _sensitive(args.key) and not args.show_secret:
        print(_mask(val))
    else:
        print(val)
    return 0


def _coerce_value(raw: str, type_hint: str | None) -> Any:
    if type_hint == "int":
        return int(raw)
    if type_hint == "float":
        return float(raw)
    if type_hint == "bool":
        return raw.lower() in ("1", "true", "yes", "on")
    if type_hint == "json":
        return json.loads(raw)
    return raw


def _cmd_set(args) -> int:
    db = _db(args.data_root)
    val = _coerce_value(args.value, args.type)
    db.set(args.key, val, category=args.category)
    print(f"Set: {args.key} = {_mask(val) if _sensitive(args.key) else val}")
    return 0


def _cmd_unset(args) -> int:
    db = _db(args.data_root)
    db._conn.execute("DELETE FROM settings WHERE key = ?", (args.key,))
    db._conn.commit()
    print(f"Unset: {args.key}")
    return 0


def _cmd_doctor(args) -> int:
    db = _db(args.data_root)
    repo = resolve_repo_path(".")
    data = Path(args.data_root)
    if not data.is_absolute():
        data = resolve_repo_path(data)
    checks: list[tuple[str, str, str]] = []

    def check(name: str, ok: bool, detail: str = ""):
        checks.append((name, "OK" if ok else "WARN", detail))

    tushare = db.get("tushare_token") or os.environ.get("TUSHARE_TOKEN", "")
    check("tushare_token", bool(tushare), "set" if tushare else "missing; A-share features will fail")

    anthropic = db.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
    check("anthropic_api_key", bool(anthropic), "set" if anthropic else "optional; needed for LLM-based news analysis")

    cfg = _config_yaml_path()
    check("config_file", cfg.exists(), str(cfg))

    check("data_root_writable", data.exists() and os.access(data, os.W_OK), str(data))

    check("repo_root", repo.exists(), str(repo))

    notify_url = db.get("notify_url") or os.environ.get("TRADE_NOTIFY_URL", "")
    check("notify_webhook", bool(notify_url), "set" if notify_url else "optional; event notifications disabled")

    try:
        from scripts.backup import backup_doctor
        result = backup_doctor(args.data_root)
        ok = bool(result.get("enabled"))
        detail = f"backend={result.get('backend','?')} gdrive={result.get('google_drive_available', False)}"
        check("backup_driver", ok, detail)
    except Exception as e:
        check("backup_driver", False, f"unavailable: {type(e).__name__}")

    print(f"{'Check':<25} {'Status':<6} {'Detail'}")
    print("-" * 80)
    worst = 0
    for name, st, detail in checks:
        print(f"{name:<25} {st:<6} {detail}")
        if st == "WARN":
            worst = max(worst, 1)
    print()
    return worst


def _is_source_command(args) -> bool:
    return args.cmd == "source" or (hasattr(args, "command") and args.command in ("source", "sources"))


def _cmd_source(args) -> int:
    from trade_py.cli import data as data_cli
    src_argv: list[str] = ["source"]
    if args.src_cmd:
        src_argv.append(args.src_cmd)

    if args.src_cmd in ("list",):
        if args.asset_class:
            src_argv.extend(["--class", args.asset_class])
        if args.venue:
            src_argv.extend(["--venue", args.venue])
        if args.disabled:
            src_argv.append("--disabled")
        if args.as_json:
            src_argv.append("--json")
    elif args.src_cmd == "show":
        src_argv.append(args.asset_id)
        if args.as_json:
            src_argv.append("--json")
    elif args.src_cmd in ("enable", "disable", "remove"):
        src_argv.append(args.asset_id)
        if args.src_cmd == "remove" and args.yes:
            src_argv.append("--yes")
    elif args.src_cmd == "add":
        src_argv.extend([
            "--asset-id", args.asset_id,
            "--class", args.asset_class,
            "--symbol", args.symbol,
            "--venue", args.venue,
        ])
        if args.quote:
            src_argv.extend(["--quote", args.quote])
        if args.interval:
            src_argv.extend(["--interval", args.interval])
        src_argv.extend([
            "--priority", str(args.priority),
            "--batch-size", str(args.batch_size),
            "--min-interval-ms", str(args.min_interval_ms),
            "--backfill-days", str(args.backfill_days),
        ])

    src_argv.extend(["--data-root", str(args.data_root)])
    return data_cli.main(src_argv)


def _cmd_watch(args) -> int:
    db = _db(args.data_root)
    if args.w_cmd == "list":
        rows = db.watchlist_get_with_names()
        if not rows:
            print("(watchlist is empty)")
            return 0
        print(f"{'Symbol':<12} {'Name':<20} {'Note'}")
        print("-" * 50)
        for r in rows:
            print(f"{r['symbol']:<12} {(r.get('name') or ''):<20} {r.get('note','')}")
        return 0
    if args.w_cmd == "add":
        db.watchlist_add(args.symbol.upper(), args.note)
        print(f"Added to watchlist: {args.symbol.upper()}")
        return 0
    if args.w_cmd == "remove":
        db.watchlist_remove(args.symbol.upper())
        print(f"Removed from watchlist: {args.symbol.upper()}")
        return 0
    return 1


def _cmd_dag(args) -> int:
    db = _db(args.data_root)
    if args.dag_cmd == "list":
        rows = db.pipeline_dag_all(enabled_only=not args.all)
        print(f"{'Job':<28} {'Enabled':<8} {'Stage':<10} {'Schedule'}")
        print("-" * 75)
        for r in rows:
            en = "yes" if r["enabled"] else "NO"
            print(f"{r['job_name']:<28} {en:<8} {(r.get('stage') or ''):<10} {(r.get('schedule_expr') or '')}")
        return 0
    if args.dag_cmd == "enable":
        n = db.pipeline_dag_set_enabled_by_job(args.job_name, True)
        print(f"Enabled {n} DAG node(s): {args.job_name}")
        return 0
    if args.dag_cmd == "disable":
        n = db.pipeline_dag_set_enabled_by_job(args.job_name, False)
        print(f"Disabled {n} DAG node(s): {args.job_name}")
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if args.cmd == "init":
        return _cmd_init(args)
    if args.cmd == "path":
        return _cmd_path(args)
    if args.cmd == "show":
        return _cmd_show(args)
    if args.cmd == "get":
        return _cmd_get(args)
    if args.cmd == "set":
        return _cmd_set(args)
    if args.cmd == "unset":
        return _cmd_unset(args)
    if args.cmd == "doctor":
        return _cmd_doctor(args)
    if args.cmd == "source":
        return _cmd_source(args)
    if args.cmd == "watch":
        return _cmd_watch(args)
    if args.cmd == "dag":
        return _cmd_dag(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
