"""Explicit CLI for package-layout performance evidence."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from trade_py.devtools.layout_performance.capture import (
    PerformanceCaptureError,
    capture_performance,
)
from trade_py.devtools.layout_performance.compare import compare_performance
from trade_py.devtools.layout_performance.evidence import (
    load_performance_evidence,
    render_evidence,
)
from trade_py.devtools.layout_performance.processes import (
    PerformanceProcessError,
    run_process,
)

DEFAULT_BASELINE = Path("tests/baselines/layout-performance.json")


def run_layout_performance_cli(args: argparse.Namespace) -> int:
    repo_root = _repo_root(Path.cwd())
    try:
        if args.performance_command == "capture":
            evidence = capture_performance(
                repo_root,
                node_modules=_optional_path(args.node_modules),
            )
            output = _resolve_path(repo_root, args.output)
            _write_atomic(output, render_evidence(evidence, baseline=True))
            print(
                json.dumps(
                    {
                        "schema_version": "trade.layout.performance-capture.v1",
                        "status": (
                            "pass" if evidence.web.available else "unavailable_prerequisite"
                        ),
                        "exit_code": 0 if evidence.web.available else 3,
                        "output": _relative_display(repo_root, output),
                        "source_commit": evidence.source_commit,
                        "runner_identity": evidence.runner.identity_digest,
                        "web_unavailable_reason": evidence.web.unavailable_reason,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0 if evidence.web.available else 3

        baseline_path = _resolve_path(repo_root, args.baseline)
        baseline = load_performance_evidence(baseline_path, baseline=True)
        _require_repository_bound_baseline(repo_root, baseline.source_commit)
        candidate = capture_performance(
            repo_root,
            node_modules=_optional_path(args.node_modules),
        )
        report = compare_performance(baseline, candidate)
        payload = report.to_dict()
        if args.output is not None:
            _write_atomic(
                _resolve_path(repo_root, args.output),
                json.dumps(
                    payload,
                    ensure_ascii=True,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n",
            )
        print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
        return report.exit_code
    except PerformanceCaptureError as exc:
        return _render_error(
            exc.code,
            exc.detail,
            completed_stages=exc.completed_stages,
            partial_evidence=exc.partial_evidence,
        )
    except PerformanceProcessError as exc:
        return _render_error(exc.code, exc.detail)
    except (OSError, TypeError, ValueError) as exc:
        return _render_error("layout.performance.tool_failure", str(exc))


def _render_error(
    code: str,
    detail: str,
    *,
    completed_stages: tuple[str, ...] = (),
    partial_evidence: dict[str, Any] | None = None,
) -> int:
    failure_class = (
        "capacity_refusal"
        if "capacity" in code
        else "unavailable_prerequisite"
        if "prerequisite" in code
        else "tool_failure"
    )
    exit_code = {
        "tool_failure": 2,
        "unavailable_prerequisite": 3,
        "capacity_refusal": 4,
    }[failure_class]
    print(
        json.dumps(
            {
                "schema_version": "trade.layout.performance-error.v1",
                "status": failure_class,
                "failure_class": failure_class,
                "exit_code": exit_code,
                "error": {
                    "code": code,
                    "detail": detail[:2048],
                },
                "completed_stages": list(completed_stages),
                "partial_evidence": partial_evidence or {},
            },
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    )
    return exit_code


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _repo_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "trade").is_file():
            return candidate
    raise ValueError("cannot find Trade repository root")


def _resolve_path(repo_root: Path, value: Path) -> Path:
    return value.resolve() if value.is_absolute() else (repo_root / value).resolve()


def _optional_path(value: Path | None) -> Path | None:
    return value.resolve() if value is not None else None


def _require_repository_bound_baseline(repo_root: Path, source_commit: str) -> None:
    run_process(
        ("git", "cat-file", "-e", f"{source_commit}^{{commit}}"),
        cwd=repo_root,
        timeout_seconds=5,
        output_limit_bytes=4096,
    )
    run_process(
        ("git", "merge-base", "--is-ancestor", source_commit, "HEAD"),
        cwd=repo_root,
        timeout_seconds=5,
        output_limit_bytes=4096,
    )


def _relative_display(repo_root: Path, path: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return "<external-output>"


__all__ = ["DEFAULT_BASELINE", "run_layout_performance_cli"]
