from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from datetime import date
from pathlib import Path

import pytest

from trade_py.devtools.design_quality.governance import (
    GovernanceRequirement,
    GovernanceRequirementSource,
    GovernanceResolution,
)
from trade_py.devtools.design_quality.policy import load_policy
from trade_py.devtools.design_quality.report_binding import ReportBinding
from trade_py.devtools.openspec_status import design as design_adapter
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
from trade_py.devtools.quality.executor import DesignBatchValidation

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

    errors = generation.verify(policy)

    assert errors["new-change"].code == "workflow.snapshot.changed"
    assert errors["new-change"].change == "new-change"


def test_source_generation_detects_active_scope_drift(tmp_path: Path) -> None:
    repo = _snapshot_repo(tmp_path)
    policy = load_policy(repo)
    generation = capture_source_generation(
        repo,
        executor=BoundedProcessExecutor(),
        deadline=time.monotonic() + 10,
        policy=policy,
        limits=WorkflowLimits(),
    )
    _write_change(repo, "added-during-collection", governed=True)

    with pytest.raises(WorkflowCollectionError) as raised:
        generation.verify(policy)

    assert raised.value.error.code == "workflow.snapshot.scope_changed"


def test_source_generation_detects_git_head_drift(tmp_path: Path) -> None:
    repo = _snapshot_repo(tmp_path)
    policy = load_policy(repo)
    generation = capture_source_generation(
        repo,
        executor=BoundedProcessExecutor(),
        deadline=time.monotonic() + 10,
        policy=policy,
        limits=WorkflowLimits(),
    )
    unrelated = repo / "unrelated.txt"
    unrelated.write_text("changed Git generation\n", encoding="utf-8")
    _git(repo, "add", "unrelated.txt")
    _git(repo, "commit", "-m", "move head without openspec changes")

    with pytest.raises(WorkflowCollectionError) as raised:
        generation.verify(policy)

    assert raised.value.error.code == "workflow.git.provenance"


def test_source_generation_rejects_temporary_snapshot_mutation(tmp_path: Path) -> None:
    repo = _snapshot_repo(tmp_path)
    policy = load_policy(repo)
    generation = capture_source_generation(
        repo,
        executor=BoundedProcessExecutor(),
        deadline=time.monotonic() + 10,
        policy=policy,
        limits=WorkflowLimits(),
    )

    with pytest.raises(WorkflowCollectionError) as raised:
        with generation.materialize() as materialized:
            proposal = materialized / "openspec" / "changes" / "new-change" / "proposal.md"
            proposal.write_text("native mutation\n", encoding="utf-8")

    assert raised.value.error.code == "workflow.snapshot.temporary_changed"


class _NativeExecutor(BoundedProcessExecutor):
    def __init__(
        self,
        names: tuple[str, ...],
        *,
        failed_status: str | None = None,
        unsupported_schema: str | None = None,
        malformed_validation: str | None = None,
        validation_returncode: int | None = None,
        validation_summary: object | None = None,
        validation_names: tuple[str, ...] | None = None,
        omit_zero_spec_summary: bool = False,
        status_padding_bytes: int = 0,
    ) -> None:
        super().__init__()
        self.names = names
        self.failed_status = failed_status
        self.unsupported_schema = unsupported_schema
        self.malformed_validation = malformed_validation
        self.validation_returncode = validation_returncode
        self.validation_summary = validation_summary
        self.validation_names = validation_names
        self.omit_zero_spec_summary = omit_zero_spec_summary
        self.status_padding_bytes = status_padding_bytes
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
            selected = (change,) if change else self.names
            validation_names = (
                self.validation_names if self.validation_names is not None else selected
            )
            failed = int(self.malformed_validation in selected)
            payload = {
                "items": [
                    {
                        "id": name,
                        "type": "change",
                        "valid": ("not-a-boolean" if name == self.malformed_validation else True),
                        "issues": [],
                        "durationMs": 1,
                    }
                    for name in validation_names
                ],
                "summary": (
                    self.validation_summary
                    if self.validation_summary is not None
                    else _validation_summary(
                        items=len(validation_names),
                        passed=len(validation_names) - failed,
                        failed=failed,
                        include_spec=not self.omit_zero_spec_summary,
                    )
                ),
                "version": "1.0",
            }
            result = _result(argv, payload)
            return ProcessResult(
                argv=result.argv,
                returncode=(
                    self.validation_returncode
                    if self.validation_returncode is not None
                    else int(failed > 0)
                ),
                stdout=result.stdout,
                stderr=result.stderr,
                duration_ms=result.duration_ms,
            )
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
                        **(
                            {"padding": "x" * self.status_padding_bytes}
                            if self.status_padding_bytes
                            else {}
                        ),
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


def _validation_summary(
    *,
    items: int,
    passed: int,
    failed: int,
    include_spec: bool = True,
) -> dict[str, object]:
    counts = {"items": items, "passed": passed, "failed": failed}
    by_type = {"change": counts}
    if include_spec:
        by_type["spec"] = {"items": 0, "passed": 0, "failed": 0}
    return {
        "totals": counts,
        "byType": by_type,
    }


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


def test_native_single_change_accepts_omitted_zero_spec_summary(tmp_path: Path) -> None:
    executor = _NativeExecutor(
        ("change-a",),
        omit_zero_spec_summary=True,
    )

    collection = collect_native_evidence(
        tmp_path,
        expected_names=("change-a",),
        requested_change="change-a",
        executor=executor,
        deadline=time.monotonic() + 10,
        limits=WorkflowLimits(),
    )

    assert set(collection.changes) == {"change-a"}
    assert collection.errors == {}


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


def test_native_malformed_validation_preserves_sibling(tmp_path: Path) -> None:
    names = ("change-a", "change-b")
    executor = _NativeExecutor(names, malformed_validation="change-b")

    collection = collect_native_evidence(
        tmp_path,
        expected_names=names,
        requested_change=None,
        executor=executor,
        deadline=time.monotonic() + 10,
        limits=WorkflowLimits(),
    )

    assert set(collection.changes) == {"change-a"}
    assert collection.errors["change-b"].code == "workflow.openspec.shape"
    assert collection.errors["change-b"].change == "change-b"


@pytest.mark.parametrize(
    ("validation_names", "affected"),
    (
        (("change-a",), "change-b"),
        (("change-a", "change-b", "change-b"), "change-b"),
    ),
)
def test_native_missing_or_duplicate_validation_preserves_sibling(
    tmp_path: Path,
    validation_names: tuple[str, ...],
    affected: str,
) -> None:
    names = ("change-a", "change-b")
    executor = _NativeExecutor(names, validation_names=validation_names)

    collection = collect_native_evidence(
        tmp_path,
        expected_names=names,
        requested_change=None,
        executor=executor,
        deadline=time.monotonic() + 10,
        limits=WorkflowLimits(),
    )

    assert set(collection.changes) == {"change-a"}
    assert collection.errors[affected].code == "workflow.openspec.shape"
    assert collection.errors[affected].change == affected


@pytest.mark.parametrize(
    ("summary", "returncode"),
    (
        (_validation_summary(items=2, passed=1, failed=1), 0),
        (_validation_summary(items=2, passed=2, failed=0), 1),
        (_validation_summary(items=1, passed=1, failed=0), 0),
        ({}, 0),
    ),
)
def test_native_validation_rejects_summary_or_returncode_contradiction(
    tmp_path: Path,
    summary: object,
    returncode: int,
) -> None:
    names = ("change-a", "change-b")
    executor = _NativeExecutor(
        names,
        validation_returncode=returncode,
        validation_summary=summary,
    )

    with pytest.raises(WorkflowCollectionError) as raised:
        collect_native_evidence(
            tmp_path,
            expected_names=names,
            requested_change=None,
            executor=executor,
            deadline=time.monotonic() + 10,
            limits=WorkflowLimits(),
        )

    assert raised.value.error.code == "workflow.openspec.shape"
    assert raised.value.error.change is None


def test_native_aggregate_output_budget_fails_closed(tmp_path: Path) -> None:
    names = tuple(f"change-{index:03d}" for index in range(10))
    executor = _NativeExecutor(names, status_padding_bytes=512)

    with pytest.raises(WorkflowCollectionError) as raised:
        collect_native_evidence(
            tmp_path,
            expected_names=names,
            requested_change=None,
            executor=executor,
            deadline=time.monotonic() + 10,
            limits=WorkflowLimits(
                native_output_bytes=2048,
                report_output_bytes=4096,
            ),
        )

    assert raised.value.error.code == "workflow.openspec.aggregate_output_limit"
    assert raised.value.error.change is None


def test_design_malformed_report_preserves_sibling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    names = ("change-a", "change-b")
    requirements = GovernanceResolution(
        tuple(
            GovernanceRequirement(
                change=name,
                required=True,
                source=GovernanceRequirementSource.NEW_CHANGE,
                live=True,
            )
            for name in names
        )
    )
    binding = ReportBinding(
        governance_status="GOVERNED",
        artifact_digest=f"sha256:{'1' * 64}",
        profiles=("core",),
        artifacts=(),
        total_bytes=0,
    )
    monkeypatch.setattr(
        design_adapter,
        "load_report_bindings",
        lambda *_args, **_kwargs: {name: binding for name in names},
    )
    monkeypatch.setattr(
        design_adapter,
        "validate_design_batch_payload",
        lambda *_args, **_kwargs: DesignBatchValidation(
            envelope_error=None,
            report_errors={"change-b": "report digest is invalid"},
        ),
    )
    executor = _DesignExecutor(names)

    collection = design_adapter.collect_design_evidence(
        tmp_path,
        names,
        requirements,
        evaluation_date=date(2026, 7, 23),
        executor=executor,
        deadline=time.monotonic() + 10,
        policy=load_policy(REPO_ROOT),
        limits=WorkflowLimits(),
    )

    assert set(collection.evidence) == {"change-a"}
    assert collection.evidence["change-a"].report["change"] == "change-a"
    assert collection.errors["change-b"].code == "workflow.design_quality.invalid"
    assert collection.errors["change-b"].change == "change-b"


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


class _DesignExecutor(BoundedProcessExecutor):
    def __init__(self, names: tuple[str, ...]) -> None:
        super().__init__()
        self.names = names

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
        del cwd, deadline, timeout_seconds, output_limit_bytes, source, change
        assert 0 in allowed_returncodes
        assert "--parent-managed-process-group" in argv
        return _result(
            argv,
            {
                "schema_version": "trade.design.batch.v1",
                "exit_code": 0,
                "reports": [{"change": name} for name in self.names],
                "errors": [],
                "summary": {
                    "changes": len(self.names),
                    "passed": len(self.names),
                    "failed": 0,
                    "not_governed": 0,
                    "errors": 0,
                },
            },
        )
