"""trade observatory — BTC Observatory catalog + research operations (WP1).

Subcommands:
  trade observatory catalog rebuild [--dry-run] [--json]   full deterministic rebuild
  trade observatory catalog update  [--dry-run] [--json]   incremental (== full) update
  trade observatory catalog verify  [--json]               reconcile projection vs facts
  trade observatory catalog status  [--json]               show generation + staleness
  trade observatory research run     [--commit] [--json]    run the H1 research workflow
  trade observatory research import  --bundle <p> [--commit] import a notebook bundle
  trade observatory research promote --research-run-id <id> promote an exploratory run

The catalog is a rebuildable projection of immutable manifests/current/audits.
GET/SDK reads never build the projection, but `catalog rebuild`/`catalog update`
DO write it, and `research {run,import,promote} --commit` performs the documented
write (the default is a dry-run that writes nothing). No provider network calls.
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


# Canonical capability_state -> strict `status` field. The strict gate reports a
# single status derived from the read-only capability classifier so that `status`
# and `verify` can never disagree with `capability_state`. `ready` is the only
# state that maps to `current` (exit 0); every other state fails closed.
_STRICT_STATUS = {
    "ready": "current",
    "catalog_missing": "missing",
    "catalog_stale": "stale",
    "catalog_corrupt": "corrupt",
}


def _strict_gate(action: str, data_root: str) -> int:
    """Emit the canonical machine-readable readiness gate and return its exit code.

    Strict mode is a deployment readiness gate consumed by machines, so it ALWAYS
    emits structured JSON (regardless of --json) and fails closed: exit 3 for
    catalog_missing/catalog_stale/catalog_corrupt, 0 only when the read-only
    capability classifier reports `ready`. The classifier is the single source of
    truth, so `status`/`verify` agree AND the emitted `status` is derived from
    `capability_state` — there is NO nested raw status/verify field that could
    contradict the canonical top-level contract.
    """

    cap = store.capability(data_root)
    state = cap["state"]
    ready = state == "ready"
    gate = {
        "action": action,
        "strict": True,
        "capability_state": state,
        # Defensive default is a fail-closed `corrupt`; the classifier only ever
        # returns one of the four mapped states, so the default is unreachable.
        "status": _STRICT_STATUS.get(state, "corrupt"),
        "ready": ready,
        "db_exists": cap["db_exists"],
        "generation_id": cap.get("generation_id"),
    }
    if cap.get("meta_mismatch"):
        gate["meta_mismatch"] = cap["meta_mismatch"]
    print(_json.dumps(gate, indent=2, sort_keys=True))
    return 0 if ready else 3


def _catalog_main(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="trade observatory catalog")
    parser.add_argument("action", choices=["rebuild", "update", "verify", "status"])
    parser.add_argument("--data-root", default=str(default_data_root()))
    parser.add_argument("--dry-run", action="store_true", help="report only; write to a temp catalog")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="deployment gate: status/verify exit non-zero unless the catalog is ready",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    ns = parser.parse_args(args)

    if ns.action == "rebuild":
        payload = store.rebuild(ns.data_root, dry_run=ns.dry_run)
    elif ns.action == "update":
        payload = store.update(ns.data_root, dry_run=ns.dry_run)
    elif ns.strict and ns.action in ("verify", "status"):
        # Strict status/verify is a machine deployment gate: the canonical
        # capability-derived contract is the ONLY output. Skip the human
        # verify()/status() payload entirely so nothing nested can contradict
        # the top-level capability_state/status.
        return _strict_gate(ns.action, ns.data_root)
    elif ns.action == "verify":
        payload = store.verify(ns.data_root)
    else:
        payload = store.status(ns.data_root)

    _emit(payload, ns.json)
    # Non-strict verify/status of a stale catalog is informational, not a failure.
    return 0


def _research_main(args: list[str], *, prog: str = "trade observatory research") -> int:
    from trade_py.observatory.domain.vocab import ObservatoryError
    from trade_py.observatory.research import workflow

    parser = argparse.ArgumentParser(prog=prog)
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


def research_btc_main(argv: list[str] | None = None) -> int:
    """Public entrypoint for `trade research btc {run,import,promote}`.

    Routes into the SAME reusable BTC research parser as
    `trade observatory research`, so workflow logic is defined once (plan §5.3).
    """

    args = list(argv) if argv is not None else sys.argv[1:]
    return _research_main(args, prog="trade research btc")


def main(argv: list[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        prog="trade observatory",
        description="BTC Observatory 目录/快照/研究运维 (catalog 只读投影; research 支持 --commit 写入)",
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
