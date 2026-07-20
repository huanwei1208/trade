"""Safe worktree setup for the mandatory six-role consensus review."""

from __future__ import annotations

import argparse
import re
import subprocess
from datetime import datetime
from pathlib import Path

from trade_py.devtools.quality.scope import ScopeError, discover_repo_root

ROLES = {
    "1": "Reliability & Resilience — error handling, retries, idempotency, data loss, crash safety, locking",
    "2": "Performance & Scalability — throughput, QPS, memory, parquet I/O, bus congestion, pool sizing",
    "3": "Architecture & Design — module boundaries, meta-driven extensibility, plugin patterns, CLI cohesion",
    "4": "Data Quality & Validation — OHLCV validation, outlier detection, timestamps, cross-source reconciliation",
    "5": "Observability & Operability — CLI usability, logging, health commands, dashboard, alerting, audit trail",
    "6": "News/Sentiment & Future Integration — bus isolation for NLP, unstructured data, backpressure, embeddings",
}


def worktree_entries(repo_root: Path) -> dict[Path, str]:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git worktree list failed")
    entries: dict[Path, str] = {}
    path: Path | None = None
    branch = ""
    for line in (*result.stdout.splitlines(), ""):
        if line.startswith("worktree "):
            path = Path(line.removeprefix("worktree ")).resolve()
        elif line.startswith("branch "):
            branch = line.removeprefix("branch ").removeprefix("refs/heads/")
        elif not line and path is not None:
            entries[path] = branch
            path = None
            branch = ""
    return entries


def _review_context(args: argparse.Namespace) -> tuple[Path, Path, list[str]] | None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.slug):
        print(f"Invalid review slug: {args.slug!r}")
        return None
    selected = [role.strip() for role in args.roles.split(",") if role.strip()]
    invalid_roles = sorted(set(selected) - ROLES.keys())
    if invalid_roles:
        print(f"Invalid review roles: {','.join(invalid_roles)}")
        return None
    try:
        repo_root = discover_repo_root(Path.cwd())
        scope_path = (repo_root / args.scope).resolve()
        scope_path.relative_to(repo_root)
    except (ScopeError, ValueError) as exc:
        print(f"Invalid review scope: {exc}")
        return None
    return repo_root, scope_path, selected


def _ensure_worktree(repo_root: Path, slug: str) -> tuple[Path, str] | None:
    date_str = datetime.now().strftime("%Y%m%d")
    wt_path = repo_root.parent / f"trade-wt-review-{slug}"
    branch_name = f"wt/review-{slug}-{date_str}"
    try:
        entries = worktree_entries(repo_root)
    except RuntimeError as exc:
        print(f"Error inspecting worktrees: {exc}")
        return None
    if wt_path.exists():
        actual_branch = entries.get(wt_path.resolve())
        if actual_branch != branch_name:
            print(
                f"Existing path is not the expected review worktree: {wt_path} "
                f"(expected branch {branch_name}, found {actual_branch or 'unregistered'})"
            )
            return None
        assert actual_branch is not None
        print(f"Worktree already exists: {wt_path}")
        print(f"Branch: {actual_branch}")
        return wt_path, actual_branch
    result = subprocess.run(
        ["git", "worktree", "add", str(wt_path), "-b", branch_name],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"Error creating worktree: {result.stderr.strip()}")
        return None
    print(f"Created review worktree: {wt_path}")
    print(f"Branch: {branch_name}")
    return wt_path, branch_name


def run_review(args: argparse.Namespace) -> int:
    context = _review_context(args)
    if context is None:
        return 2
    repo_root, scope_path, selected = context
    worktree = _ensure_worktree(repo_root, args.slug)
    if worktree is None:
        return 2
    wt_path, _branch_name = worktree
    print("\n=== Multi-Agent Consensus Review Scaffolded ===\n")
    print("Launch 6 judge agents in parallel with these role prompts:\n")
    for role_id in selected:
        print(f"  Judge {role_id}: {ROLES[role_id]}")
    print(f"\nAll agents should review code at: {wt_path}")
    print(f"Scope: {scope_path.relative_to(repo_root)}\n")
    print("After all judges complete, synthesize consensus:")
    print("  - Unanimous (3+ judges) → P0, must fix before merge")
    print("  - Two-judge agreement → P1, high priority")
    print("  - Single-judge → evaluate on merit")
    print("  - Disagreements → one reconciliation round (max)")
    return 0
