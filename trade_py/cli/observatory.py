"""trade observatory — read-only BTC Observatory catalog operations (WP1).

Subcommands:
  trade observatory catalog rebuild [--dry-run] [--json]   full deterministic rebuild
  trade observatory catalog update  [--dry-run] [--json]   incremental (== full) update
  trade observatory catalog verify  [--json]               reconcile projection vs facts
  trade observatory catalog status  [--json]               show generation + staleness

The catalog is a rebuildable projection of immutable manifests/current/audits. Only
these explicit CLI/Operations commands write the projection; GET/SDK reads never do.
No provider network, no DB mutation, no data writes.
"""
from __future__ import annotations

import argparse
import json as _json
import sys

from trade_py.infra.settings.context import default_data_root
from trade_py.observatory.catalog import store


def _emit(payload: dict, as_json: bool) -> None:
    if as_json:
        print(_json.dumps(payload, indent=2, sort_keys=True))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def _catalog_main(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="trade observatory catalog")
    parser.add_argument("action", choices=["rebuild", "update", "verify", "status"])
    parser.add_argument("--data-root", default=str(default_data_root()))
    parser.add_argument("--dry-run", action="store_true", help="report only; write to a temp catalog")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    ns = parser.parse_args(args)

    if ns.action == "rebuild":
        payload = store.rebuild(ns.data_root, dry_run=ns.dry_run)
    elif ns.action == "update":
        payload = store.update(ns.data_root, dry_run=ns.dry_run)
    elif ns.action == "verify":
        payload = store.verify(ns.data_root)
    else:
        payload = store.status(ns.data_root)
    _emit(payload, ns.json)
    # verify/status of a stale catalog is informational, not a failure.
    return 0


def _research_main(args: list[str]) -> int:
    from trade_py.observatory.domain.vocab import ObservatoryError
    from trade_py.observatory.research import workflow

    parser = argparse.ArgumentParser(prog="trade observatory research btc")
    parser.add_argument("action", choices=["run", "import", "promote"])
    parser.add_argument("--data-root", default=str(default_data_root()))
    parser.add_argument("--hypothesis", default="H1")
    parser.add_argument("--snapshot-id", default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--bundle", default=None, help="notebook bundle path (import)")
    parser.add_argument("--research-run-id", default=None, help="exploratory run id (promote)")
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--commit", action="store_true", help="opposite of dry-run; perform the write")
    parser.add_argument("--json", action="store_true")
    ns = parser.parse_args(args)
    # Default to dry-run unless --commit is given (safe default for a write side).
    dry_run = not ns.commit
    try:
        if ns.action == "run":
            payload = workflow.run(
                ns.data_root, hypothesis=ns.hypothesis,
                snapshot_id=ns.snapshot_id, run_id=ns.run_id, dry_run=dry_run,
            )
        elif ns.action == "import":
            if not ns.bundle:
                print("error: --bundle is required for import", file=sys.stderr)
                return 2
            payload = workflow.import_notebook_bundle(ns.data_root, bundle_path=ns.bundle, dry_run=dry_run)
        else:
            if not ns.research_run_id:
                print("error: --research-run-id is required for promote", file=sys.stderr)
                return 2
            payload = workflow.promote(ns.data_root, research_run_id=ns.research_run_id, dry_run=dry_run)
    except ObservatoryError as exc:
        _emit(exc.to_payload(), ns.json)
        return 1
    _emit(payload, ns.json)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        prog="trade observatory",
        description="只读 BTC Observatory 目录/快照运维",
    )
    parser.add_argument(
        "group",
        choices=["catalog", "research"],
        metavar="<group>",
        help="catalog | research",
    )
    parser.add_argument("args", nargs=argparse.REMAINDER, metavar="...")
    if not args:
        parser.print_help()
        return 2
    ns = parser.parse_args(args)
    if ns.group == "catalog":
        return _catalog_main(ns.args)
    if ns.group == "research":
        return _research_main(ns.args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
