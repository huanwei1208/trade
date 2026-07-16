from __future__ import annotations

import json
from typing import Any

from trade_py.data.operations.contracts import OperationResult


def _print_json(result: OperationResult) -> None:
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str))


def print_status(result: OperationResult, *, as_json: bool = False, detail: bool = False) -> int:
    if as_json:
        _print_json(result)
        return result.exit_code

    evidence = result.evidence
    print(
        f"data status={result.status} observed={str(result.observed).lower()} "
        f"elapsed={result.elapsed_ms}ms root={evidence.get('data_root')}"
    )
    profiles = evidence.get("profiles") or {}
    print("profiles: " + "  ".join(
        f"{name}={payload.get('status', 'unknown')}" for name, payload in profiles.items()
    ))
    artifacts = evidence.get("artifacts") or {}
    visible = [
        f"{name}:{item.get('files', 0)}"
        for name, item in artifacts.items()
        if item.get("files") or detail
    ]
    print("parquet files: " + ("  ".join(visible) if visible else "none observed"))
    database = evidence.get("database") or {}
    print(
        f"database: observed={str(bool(database.get('observed'))).lower()} "
        f"assets={sum(int(row.get('total') or 0) for row in database.get('assets') or [])}"
    )
    btc = evidence.get("btc") or {}
    print(
        f"btc assurance: observed={str(bool(btc.get('observed'))).lower()} "
        f"run_id={btc.get('run_id') or '-'}"
    )
    if detail:
        for name, profile in profiles.items():
            for step in profile.get("steps") or []:
                print(
                    f"  {name}/{step['step_id']}: {step['status']} "
                    f"completed={step.get('completed_at') or '-'}"
                )
        for error in evidence.get("errors") or []:
            print(f"  error: {error}")
    return result.exit_code


def print_check(result: OperationResult, *, as_json: bool = False, detail: bool = False) -> int:
    if as_json:
        _print_json(result)
        return result.exit_code

    counts = result.evidence.get("counts") or {}
    print(
        f"data {result.operation} profile={result.profile} status={result.status} "
        f"files={result.evidence.get('checked_files', 0)} elapsed={result.elapsed_ms}ms "
        f"pass={counts.get('pass', 0)} warn={counts.get('warn', 0)} "
        f"fail={counts.get('fail', 0)} unknown={counts.get('unknown', 0)}"
    )
    items: list[dict[str, Any]] = list(result.evidence.get("items") or [])
    selected = items if detail else [item for item in items if item.get("status") != "pass"]
    for item in selected[:100 if detail else 20]:
        print(f"  {item.get('status', 'unknown'):<7} {item.get('name')}: {item.get('detail')}")
    if len(selected) > (100 if detail else 20):
        print(f"  ... {len(selected) - (100 if detail else 20)} more; rerun with --json")
    return result.exit_code


def print_update(result: OperationResult, *, as_json: bool = False) -> int:
    if as_json:
        _print_json(result)
        return result.exit_code

    print(
        f"data update profile={result.profile} v{result.profile_version} "
        f"status={result.status} dry_run={str(result.dry_run).lower()} "
        f"run_id={result.run_id or '-'} elapsed={result.elapsed_ms}ms"
    )
    for index, step in enumerate(result.steps, start=1):
        print(
            f"  {index}. {step.step_id:<16} {step.status:<11} "
            f"job={step.job_name} {step.summary}"
        )
    if result.evidence.get("error"):
        print(f"  error: {result.evidence['error']}")
    return result.exit_code
