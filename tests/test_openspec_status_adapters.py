from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from trade_py.devtools.design_quality.policy import load_policy
from trade_py.devtools.openspec_status.errors import (
    WorkflowCollectionError,
    WorkflowError,
)
from trade_py.devtools.openspec_status.executor import (
    BoundedProcessExecutor,
    ProcessResult,
)
from trade_py.devtools.openspec_status.models import WorkflowLimits
from trade_py.devtools.openspec_status.native import collect_native_evidence
from trade_py.devtools.openspec_status.snapshot import capture_source_generation

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _write_change(repo: Path, name: str, *, governed: bool) -> Path:
    change = repo / "openspec" / "changes" / name
    change.mkdir(parents=True)
    (change / "proposal.md").write_text(f"proposal for {name}\n", encoding="utf-8")
    if governed:
        (change / "design-quality.toml").write_text(
            'schema_version = 1\npolicy_version = "v1"\n',
            encoding="utf-8",
        )
    return change


def _snapshot_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copytree(REPO_ROOT / "design-policy", repo / "design-policy")
    openspec = repo / "openspec"
    (openspec / "changes").mkdir(parents=True)
    (openspec / "config.yaml").write_text("schema: spec-driven\n", encoding="utf-8")
    _write_change(repo, "existing-governed", governed=True)
    _write_change(repo, "historical-change", governed=False)
    _write_change(repo, "marker-deleted", governed=True)
    _git(repo, "init", "-b", "master")
    _git(repo, "config", "user.email", "openspec@example.test")
    _git(repo, "config", "user.name", "OpenSpec Test")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "baseline")
    (repo / "openspec" / "changes" / "marker-deleted" / "design-quality.toml").unlink()
    new_change = _write_change(repo, "new-change", governed=True)
    (new_change / "ignored.bin").write_bytes(b"not allowlisted")
    return repo


def test_source_generation_resolves_governance_and_materializes_allowlist(
    tmp_path: Path,
) -> None:
    repo = _snapshot_repo(tmp_path)
    policy = load_policy(repo)

    generation = capture_source_generation(
        repo,
        executor=BoundedProcessExecutor(),
        deadline=time.monotonic() + 10,
        policy=policy,
        limits=WorkflowLimits(),
    )

    sources = {
        item.change: (item.required, item.source.value)
        for item in generation.governance.requirements
    }
    assert sources == {
        "existing-governed": (True, "existing_governed"),
        "historical-change": (False, "historical_exempt"),
        "marker-deleted": (True, "marker_deleted"),
        "new-change": (True, "new_change"),
    }
    assert generation.source.base_ref == "master"
    assert generation.source.git_head == generation.source.base_sha
    assert generation.source.snapshot_digest.startswith("sha256:")
    with generation.materialize() as materialized:
        materialized_path = materialized
        assert (materialized / "openspec" / "config.yaml").is_file()
        assert (materialized / "openspec" / "changes" / "new-change" / "proposal.md").is_file()
        assert not (materialized / "openspec" / "changes" / "new-change" / "ignored.bin").exists()
    assert not materialized_path.exists()
    generation.verify(policy)


def test_source_generation_detects_artifact_drift(tmp_path: Path) -> None:
    repo = _snapshot_repo(tmp_path)
    policy = load_policy(repo)
    generation = capture_source_generation(
        repo,
        executor=BoundedProcessExecutor(),
        deadline=time.monotonic() + 10,
        policy=policy,
        limits=WorkflowLimits(),
    )
    proposal = repo / "openspec" / "changes" / "new-change" / "proposal.md"
    proposal.write_text("changed after capture\n", encoding="utf-8")

    with pytest.raises(WorkflowCollectionError, match="changed"):
        generation.verify(policy)


class _NativeExecutor(BoundedProcessExecutor):
    def __init__(
        self,
        names: tuple[str, ...],
        *,
        failed_status: str | None = None,
        unsupported_schema: str | None = None,
    ) -> None:
        super().__init__()
        self.names = names
        self.failed_status = failed_status
        self.unsupported_schema = unsupported_schema
        self._lock = threading.Lock()
        self.active_status = 0
        self.max_active_status = 0

    def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        deadline: float,
        timeout_seconds: float,
        output_limit_bytes: int,
        source: str,
        change: str | None = None,
        allowed_returncodes: frozenset[int] = frozenset({0}),
    ) -> ProcessResult:
        del cwd, deadline, timeout_seconds, output_limit_bytes, source, allowed_returncodes
        if argv == ("openspec", "list", "--json"):
            payload = {
                "changes": [
                    {
                        "name": name,
                        "completedTasks": 1,
                        "totalTasks": 2,
                        "lastModified": "2026-07-23T00:00:00.000Z",
                        "status": "in-progress",
                    }
                    for name in self.names
                ]
            }
            return _result(argv, payload)
        if argv[:2] == ("openspec", "validate"):
            payload = {
                "items": [
                    {
                        "id": name,
                        "type": "change",
                        "valid": True,
                        "issues": [],
                        "durationMs": 1,
                    }
                    for name in ((change,) if change else self.names)
                ],
                "summary": {},
                "version": "1.0",
            }
            return _result(argv, payload)
        if argv[:3] == ("openspec", "status", "--change"):
            name = argv[3]
            with self._lock:
                self.active_status += 1
                self.max_active_status = max(self.max_active_status, self.active_status)
            try:
                time.sleep(0.02)
                if name == self.failed_status:
                    raise WorkflowCollectionError(
                        WorkflowError(
                            code="workflow.process.exit",
                            source="openspec",
                            change=name,
                            message="status failed",
                            remediation="repair status",
                        )
                    )
                schema = "custom-schema" if name == self.unsupported_schema else "spec-driven"
                return _result(
                    argv,
                    {
                        "changeName": name,
                        "schemaName": schema,
                        "isComplete": True,
                        "applyRequires": ["tasks"],
                        "artifacts": [
                            {
                                "id": "tasks",
                                "outputPath": "tasks.md",
                                "status": "done",
                            }
                        ],
                    },
                )
            finally:
                with self._lock:
                    self.active_status -= 1
        raise AssertionError(f"unexpected command: {argv}")


def _result(argv: tuple[str, ...], payload: object) -> ProcessResult:
    return ProcessResult(
        argv=argv,
        returncode=0,
        stdout=json.dumps(payload).encode(),
        stderr=b"",
        duration_ms=1,
    )


@pytest.mark.parametrize("count", (10, 100))
def test_native_status_fanout_is_bounded_and_deterministic(tmp_path: Path, count: int) -> None:
    names = tuple(f"change-{index:03d}" for index in range(count))
    executor = _NativeExecutor(names)

    collection = collect_native_evidence(
        tmp_path,
        expected_names=names,
        requested_change=None,
        executor=executor,
        deadline=time.monotonic() + 10,
        limits=WorkflowLimits(),
    )

    assert tuple(sorted(collection.changes)) == names
    assert collection.errors == {}
    assert 1 < executor.max_active_status <= 4


def test_native_partial_status_failure_preserves_sibling(tmp_path: Path) -> None:
    names = ("change-a", "change-b")
    executor = _NativeExecutor(names, failed_status="change-b")

    collection = collect_native_evidence(
        tmp_path,
        expected_names=names,
        requested_change=None,
        executor=executor,
        deadline=time.monotonic() + 10,
        limits=WorkflowLimits(),
    )

    assert set(collection.changes) == {"change-a"}
    assert collection.errors["change-b"].code == "workflow.process.exit"


def test_unsupported_schema_preserves_only_schema_and_payload_digest(
    tmp_path: Path,
) -> None:
    executor = _NativeExecutor(("change-a",), unsupported_schema="change-a")

    collection = collect_native_evidence(
        tmp_path,
        expected_names=("change-a",),
        requested_change="change-a",
        executor=executor,
        deadline=time.monotonic() + 10,
        limits=WorkflowLimits(),
    )

    error = collection.errors["change-a"]
    assert error.code == "workflow.openspec.unsupported_schema"
    assert error.details["schema_name"] == "custom-schema"
    assert set(error.details) == {"schema_name", "payload_digest"}
    assert error.details["payload_digest"].startswith("sha256:")
