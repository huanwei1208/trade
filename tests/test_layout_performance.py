from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from trade_py.cli import dev
from trade_py.devtools.layout_performance.capacity import (
    GIB,
    CapacityRefused,
    ValidationCapacity,
    prove_capacity_policy,
)
from trade_py.devtools.layout_performance.cli import run_layout_performance_cli
from trade_py.devtools.layout_performance.compare import compare_performance
from trade_py.devtools.layout_performance.evidence import (
    load_performance_evidence,
    render_evidence,
)
from trade_py.devtools.layout_performance.identity import (
    capture_source_tree_digest,
    runner_identity_digest,
)
from trade_py.devtools.layout_performance.models import (
    CapacityEvidence,
    IndexEvidence,
    MetricSummary,
    PerformanceEvidence,
    ProbeEvidence,
    RunnerIdentity,
    WebBuildEvidence,
)
from trade_py.devtools.layout_performance.probes import PROBE_NAMES
from trade_py.devtools.layout_performance.processes import (
    PerformanceProcessError,
    ProcessOutcome,
    run_process,
)
from trade_py.devtools.layout_performance.web import capture_web_build_evidence

REPO_ROOT = Path(__file__).resolve().parents[1]
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64


def _metric(samples: int, *, duration_ms: float = 20.0) -> MetricSummary:
    return MetricSummary.summarize(
        [duration_ms] * samples,
        peak_rss_bytes=32 * 1024 * 1024,
        module_count=100,
        module_digest=DIGEST_A,
    )


def _evidence(*, web_available: bool = True) -> PerformanceEvidence:
    runner_fields: dict[str, Any] = {
        "harness_digest": DIGEST_C,
        "runner_image": f"local:{DIGEST_B}",
        "platform": "test-linux",
        "machine": "x86_64",
        "cpu_count": 8,
        "memory_limit_bytes": 16 * GIB,
        "python_implementation": "CPython",
        "python_version": "3.14.0",
        "python_executable_digest": DIGEST_B,
        "uv_lock_digest": DIGEST_C,
        "frontend_lock_digest": DIGEST_A,
        "node_version": "v22.0.0",
        "npm_version": "11.0.0",
    }
    runner = RunnerIdentity(
        identity_digest=runner_identity_digest(runner_fields),
        **runner_fields,
    )
    web = WebBuildEvidence(
        available=web_available,
        root="trade_web/frontend",
        dependency_digest=DIGEST_A if web_available else None,
        cache_key=DIGEST_A if web_available else None,
        incremental_cache_key=DIGEST_B if web_available else None,
        no_change_cache_hit=web_available,
        cache_invalidated=web_available,
        no_change_ms=10.0 if web_available else None,
        cold_build_ms=1000.0 if web_available else None,
        incremental_build_ms=500.0 if web_available else None,
        cold_output_digest=DIGEST_C if web_available else None,
        no_change_output_digest=DIGEST_C if web_available else None,
        incremental_output_digest=DIGEST_B if web_available else None,
        cleanup_complete=True,
        unavailable_reason=None if web_available else "node_modules_not_selected",
    )
    capacity = CapacityEvidence(
        available_cpu_count=8,
        ordinary_worker_limit=4,
        heavy_job_limit=2,
        install_limit=2,
        rss_limit_bytes=8 * GIB,
        temp_limit_bytes=10 * GIB,
        queue_deadline_seconds=120,
        ordinary_observed_max=4,
        heavy_observed_max=2,
        install_observed_max=2,
        queue_refused=True,
        rss_refused=True,
        temp_refused=True,
        cleanup_timed_out=True,
        cleanup_survivors=0,
        cross_invocation_lease_claimed=False,
    )
    return PerformanceEvidence(
        generated_at="2026-07-27T12:00:00Z",
        source_commit="1" * 40,
        source_tree_digest=DIGEST_B,
        runner=runner,
        cold_processes=15,
        warmups=5,
        warm_samples=30,
        probes={name: ProbeEvidence(cold=_metric(15), warm=_metric(30)) for name in PROBE_NAMES},
        current_index=IndexEvidence(
            scale=1,
            source_count=10,
            source_bytes=1000,
            duration_ms=20.0,
            peak_rss_bytes=16 * 1024 * 1024,
            scan_count=1,
        ),
        synthetic_10x_index=IndexEvidence(
            scale=10,
            source_count=100,
            source_bytes=10_000,
            duration_ms=100.0,
            peak_rss_bytes=32 * 1024 * 1024,
            scan_count=1,
        ),
        web=web,
        capacity=capacity,
        bridge_count=0,
        bridge_cumulative_ms=0.0,
        duplicate_implementation_imports=0,
    )


def test_process_timeout_terminates_descendant_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    script = (
        "import pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid));"
        "time.sleep(30)"
    )

    with pytest.raises(PerformanceProcessError) as raised:
        run_process(
            (sys.executable, "-c", script),
            cwd=tmp_path,
            timeout_seconds=0.2,
        )

    assert raised.value.code == "layout.performance.process_timeout"
    child_pid = int(pid_file.read_text())
    deadline = time.monotonic() + 2
    while Path(f"/proc/{child_pid}").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not Path(f"/proc/{child_pid}").exists()


def test_process_timeout_terminates_detached_descendant_and_honors_deadline(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "detached.pid"
    script = (
        "import pathlib,subprocess,sys,time;"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],"
        "start_new_session=True);"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid));"
        "time.sleep(30)"
    )
    started = time.monotonic()

    with pytest.raises(PerformanceProcessError) as raised:
        run_process(
            (sys.executable, "-c", script),
            cwd=tmp_path,
            timeout_seconds=0.2,
        )

    assert raised.value.code == "layout.performance.process_timeout"
    assert time.monotonic() - started < 2
    child_pid = int(pid_file.read_text())
    deadline = time.monotonic() + 2
    while Path(f"/proc/{child_pid}").exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not Path(f"/proc/{child_pid}").exists()


def test_process_timeout_never_returns_shape_valid_partial_output(tmp_path: Path) -> None:
    with pytest.raises(PerformanceProcessError) as raised:
        run_process(
            (
                sys.executable,
                "-c",
                "import sys,time;sys.stdout.write('1'*40);sys.stdout.flush();time.sleep(30)",
            ),
            cwd=tmp_path,
            timeout_seconds=0.1,
        )

    assert raised.value.code == "layout.performance.process_timeout"


def test_process_refuses_output_explosion_and_cleans_group(tmp_path: Path) -> None:
    with pytest.raises(PerformanceProcessError) as raised:
        run_process(
            (
                sys.executable,
                "-c",
                "import sys,time;sys.stdout.write('x'*100000);sys.stdout.flush();time.sleep(30)",
            ),
            cwd=tmp_path,
            timeout_seconds=5,
            output_limit_bytes=1024,
        )

    assert raised.value.code == "layout.performance.process_output"


def test_process_rejects_residual_descendant_after_parent_exit(tmp_path: Path) -> None:
    with pytest.raises(PerformanceProcessError) as raised:
        run_process(
            (
                sys.executable,
                "-c",
                (
                    "import subprocess,sys;"
                    "subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])"
                ),
            ),
            cwd=tmp_path,
            timeout_seconds=5,
        )

    assert raised.value.code == "layout.performance.process_survivor"


def test_capacity_admission_refuses_worker_rss_and_temp_overflow() -> None:
    capacity = ValidationCapacity(
        available_cpu_count=2,
        available_memory_bytes=4 * GIB,
        queue_deadline_seconds=1,
    )

    with capacity.admit(
        "ordinary",
        timeout_seconds=0.1,
        rss_bytes=capacity.rss_limit_bytes,
    ):
        with pytest.raises(CapacityRefused):
            with capacity.admit(
                "heavy",
                timeout_seconds=0.01,
                rss_bytes=1,
            ):
                pass
    with pytest.raises(CapacityRefused):
        capacity.require_temp(capacity.temp_limit_bytes + 1)


def test_capacity_proof_is_process_local_and_leaves_no_children() -> None:
    evidence = prove_capacity_policy(
        ValidationCapacity(
            available_cpu_count=4,
            available_memory_bytes=4 * GIB,
        )
    )

    assert evidence.ordinary_worker_limit == 2
    assert evidence.ordinary_observed_max <= 2
    assert evidence.heavy_observed_max <= 2
    assert evidence.install_observed_max <= 2
    assert evidence.queue_refused
    assert evidence.rss_refused
    assert evidence.temp_refused
    assert evidence.cleanup_timed_out
    assert evidence.cleanup_survivors == 0
    assert not evidence.cross_invocation_lease_claimed


def test_evidence_round_trip_rejects_unknown_duplicate_and_non_finite_json(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(render_evidence(_evidence(), baseline=True), encoding="utf-8")

    assert load_performance_evidence(baseline, baseline=True) == _evidence()

    payload = json.loads(baseline.read_text())
    payload["unknown"] = True
    baseline.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="fields differ"):
        load_performance_evidence(baseline, baseline=True)

    baseline.write_text(
        render_evidence(_evidence(), baseline=True).replace(
            '"bridge_count": 0,',
            '"bridge_count": 0,\n  "bridge_count": 1,',
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        load_performance_evidence(baseline, baseline=True)

    baseline.write_text('{"schema_version": NaN}', encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite"):
        load_performance_evidence(baseline, baseline=True)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload["runner"].__setitem__("platform", "forged-linux"),
            "identity_digest",
        ),
        (
            lambda payload: payload["probes"]["root_help"]["cold"].__setitem__("p95_ms", 1.0),
            "p95_ms does not match",
        ),
        (
            lambda payload: payload["synthetic_10x_index"].__setitem__("source_bytes", 9999),
            "source bytes must be exactly 10x",
        ),
        (
            lambda payload: payload.__setitem__("source_tree_digest", "forged"),
            "source_tree_digest must be a canonical",
        ),
    ],
)
def test_evidence_rejects_forged_identity_metric_and_index(
    tmp_path: Path,
    mutate: Any,
    message: str,
) -> None:
    path = tmp_path / "forged.json"
    payload = _evidence().to_dict(baseline=True)
    mutate(payload)
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_performance_evidence(path, baseline=True)


def test_source_tree_digest_binds_tracked_and_untracked_source(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    source = repo / "trade_py" / "domain.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(("git", "init", "-q"), cwd=repo, check=True)
    subprocess.run(("git", "add", "--", "trade_py/domain.py"), cwd=repo, check=True)
    initial = capture_source_tree_digest(repo)

    source.write_text("VALUE = 2\n", encoding="utf-8")
    modified = capture_source_tree_digest(repo)
    untracked = repo / "trade_py" / "new_rule.py"
    untracked.write_text("ENABLED = True\n", encoding="utf-8")
    with_untracked = capture_source_tree_digest(repo)

    assert modified != initial
    assert with_untracked != modified


def test_committed_baseline_contains_the_complete_reviewed_matrix() -> None:
    baseline = load_performance_evidence(
        REPO_ROOT / "tests" / "baselines" / "layout-performance.json",
        baseline=True,
    )

    assert baseline.cold_processes == 15
    assert baseline.warmups == 5
    assert baseline.warm_samples == 30
    assert set(baseline.probes) == set(PROBE_NAMES)
    assert all(item.cold.sample_count == 15 for item in baseline.probes.values())
    assert all(item.warm.sample_count == 30 for item in baseline.probes.values())
    assert baseline.current_index.scan_count == 1
    assert baseline.synthetic_10x_index.scan_count == 1
    assert baseline.synthetic_10x_index.source_count >= baseline.current_index.source_count * 10
    assert baseline.web.available
    assert baseline.web.no_change_cache_hit
    assert baseline.web.cache_invalidated
    assert baseline.web.cleanup_complete
    assert baseline.capacity.queue_refused
    assert baseline.capacity.rss_refused
    assert baseline.capacity.temp_refused
    assert baseline.capacity.cleanup_timed_out
    assert baseline.capacity.cleanup_survivors == 0
    assert not baseline.capacity.cross_invocation_lease_claimed


def test_comparator_distinguishes_pass_regression_and_unavailable() -> None:
    baseline = _evidence()
    passing = compare_performance(baseline, baseline)
    assert passing.status == "pass"
    assert passing.failure_class == "none"
    assert passing.exit_code == 0

    slow_metric = _metric(15, duration_ms=100.0)
    regressed = replace(
        baseline,
        probes={
            **baseline.probes,
            "root_help": ProbeEvidence(cold=slow_metric, warm=_metric(30)),
        },
    )
    regression = compare_performance(baseline, regressed)
    assert regression.status == "regression"
    assert regression.exit_code == 1
    assert "layout.performance.root_help.cold.p95" in regression.violations

    unavailable = compare_performance(baseline, _evidence(web_available=False))
    assert unavailable.status == "unavailable_prerequisite"
    assert unavailable.exit_code == 3
    assert "layout.performance.web.unavailable_prerequisite" in unavailable.violations

    dependency_mismatch = replace(
        baseline,
        web=replace(baseline.web, dependency_digest=DIGEST_B),
    )
    mismatched = compare_performance(baseline, dependency_mismatch)
    assert mismatched.status == "regression"
    assert "layout.performance.web.dependency_mismatch" in mismatched.violations

    module_mismatch = replace(
        baseline,
        probes={
            **baseline.probes,
            "root_help": ProbeEvidence(
                cold=replace(baseline.probes["root_help"].cold, module_digest=DIGEST_B),
                warm=baseline.probes["root_help"].warm,
            ),
        },
    )
    changed_modules = compare_performance(baseline, module_mismatch)
    assert changed_modules.status == "regression"
    assert "layout.performance.root_help.cold.module_identity" in changed_modules.violations


def test_evidence_integrity_requires_capacity_proofs() -> None:
    incomplete = replace(
        _evidence(),
        capacity=replace(
            _evidence().capacity,
            ordinary_observed_max=0,
            rss_refused=False,
        ),
    )

    with pytest.raises(ValueError, match="capacity proof"):
        compare_performance(_evidence(), incomplete)


def test_web_evidence_uses_temporary_root_and_invalidates_source_key(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    frontend = repo / "trade_web" / "frontend"
    app = frontend / "src" / "App.tsx"
    app.parent.mkdir(parents=True)
    app.write_text("export const value = 1;\n", encoding="utf-8")
    (frontend / "index.html").write_text("<main>Trade</main>\n", encoding="utf-8")
    (frontend / "package.json").write_text('{"scripts":{"build":"fake"}}\n', encoding="utf-8")
    node_modules = tmp_path / "node_modules"
    (node_modules / ".bin").mkdir(parents=True)
    (node_modules / ".bin" / "tsc").write_text("", encoding="utf-8")
    (node_modules / ".bin" / "vite").write_text("", encoding="utf-8")
    (node_modules / ".bin" / "vite").chmod(0o755)
    (node_modules / ".package-lock.json").write_text('{"lockfileVersion":3}\n')
    source_before = app.read_bytes()
    build_roots: list[Path] = []

    def fake_runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        **_kwargs: Any,
    ) -> ProcessOutcome:
        if argv[:2] == ("git", "ls-files"):
            stdout = (
                b"trade_web/frontend/index.html\0"
                b"trade_web/frontend/package.json\0"
                b"trade_web/frontend/src/App.tsx\0"
            )
        elif "--version" in argv:
            stdout = b"test-version\n"
        else:
            build_roots.append(cwd)
            output = cwd / "dist" / "asset.js"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(
                (cwd / "index.html").read_bytes() + (cwd / "src" / "App.tsx").read_bytes()
            )
            stdout = b""
        return ProcessOutcome(
            stdout=stdout,
            stderr=b"",
            returncode=0,
            duration_ms=25.0,
            timed_out=False,
            cleanup_survivors=0,
        )

    evidence = capture_web_build_evidence(
        repo,
        node_modules=node_modules,
        capacity=ValidationCapacity(
            available_cpu_count=4,
            available_memory_bytes=8 * GIB,
        ),
        temp_parent=tmp_path,
        process_runner=fake_runner,
    )

    assert evidence.available
    assert evidence.root == "trade_web/frontend"
    assert evidence.dependency_digest is not None
    assert evidence.no_change_cache_hit
    assert evidence.cache_invalidated
    assert evidence.cache_key != evidence.incremental_cache_key
    assert evidence.cold_output_digest == evidence.no_change_output_digest
    assert evidence.incremental_output_digest != evidence.cold_output_digest
    assert evidence.cleanup_complete
    assert len(build_roots) == 3
    assert all(root != frontend for root in build_roots)
    assert app.read_bytes() == source_before
    assert not tuple(tmp_path.glob("trade-layout-web-*"))


def test_web_evidence_rejects_stale_incremental_output(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    frontend = repo / "trade_web" / "frontend"
    app = frontend / "src" / "App.tsx"
    app.parent.mkdir(parents=True)
    app.write_text("export const value = 1;\n", encoding="utf-8")
    (frontend / "index.html").write_text("<main>Trade</main>\n", encoding="utf-8")
    (frontend / "package.json").write_text('{"scripts":{"build":"fake"}}\n', encoding="utf-8")
    node_modules = tmp_path / "node_modules"
    (node_modules / ".bin").mkdir(parents=True)
    (node_modules / ".bin" / "tsc").write_text("", encoding="utf-8")
    (node_modules / ".bin" / "vite").write_text("", encoding="utf-8")
    (node_modules / ".bin" / "vite").chmod(0o755)
    (node_modules / ".package-lock.json").write_text('{"lockfileVersion":3}\n')

    def stale_runner(
        argv: tuple[str, ...],
        *,
        cwd: Path,
        **_kwargs: Any,
    ) -> ProcessOutcome:
        if argv[:2] == ("git", "ls-files"):
            stdout = (
                b"trade_web/frontend/index.html\0"
                b"trade_web/frontend/package.json\0"
                b"trade_web/frontend/src/App.tsx\0"
            )
        elif "--version" in argv:
            stdout = b"test-version\n"
        else:
            output = cwd / "dist" / "asset.js"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("stale", encoding="utf-8")
            stdout = b""
        return ProcessOutcome(
            stdout=stdout,
            stderr=b"",
            returncode=0,
            duration_ms=25.0,
            timed_out=False,
            cleanup_survivors=0,
        )

    with pytest.raises(RuntimeError, match="did not change"):
        capture_web_build_evidence(
            repo,
            node_modules=node_modules,
            capacity=ValidationCapacity(
                available_cpu_count=4,
                available_memory_bytes=8 * GIB,
            ),
            temp_parent=tmp_path,
            process_runner=stale_runner,
        )


def test_process_enforces_measured_temp_usage(tmp_path: Path) -> None:
    temp_root = tmp_path / "owned-output"
    temp_root.mkdir()

    with pytest.raises(PerformanceProcessError) as raised:
        run_process(
            (
                sys.executable,
                "-c",
                (
                    "import pathlib,time;"
                    f"pathlib.Path({str(temp_root / 'large.bin')!r}).write_bytes(b'x'*4096);"
                    "time.sleep(.2)"
                ),
            ),
            cwd=tmp_path,
            timeout_seconds=2,
            temp_limit_bytes=1024,
            temp_root=temp_root,
        )

    assert raised.value.code == "layout.performance.capacity_temp"


def test_root_help_module_census_comes_from_measured_cli_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from trade_py.devtools.layout_performance import worker
    from trade_py.devtools.layout_performance.worker import run_probe

    monkeypatch.setattr(worker, "_module_identity", lambda: (1, DIGEST_A))
    payload = run_probe("root_help", samples=1, warmups=0)

    assert isinstance(payload["module_count"], int)
    assert payload["module_count"] > 100
    assert isinstance(payload["module_digest"], str)
    assert payload["module_digest"].startswith("sha256:")
    assert payload["module_digest"] != DIGEST_A


def test_web_evidence_reports_unavailable_prerequisite_without_running(
    tmp_path: Path,
) -> None:
    frontend = tmp_path / "trade_web" / "frontend"
    frontend.mkdir(parents=True)

    evidence = capture_web_build_evidence(
        tmp_path,
        node_modules=None,
        capacity=ValidationCapacity(),
    )

    assert not evidence.available
    assert evidence.unavailable_reason == "node_modules_not_selected"
    assert evidence.cleanup_complete


def test_dev_parser_keeps_performance_harness_lazy() -> None:
    before = set(sys.modules)
    args = dev.make_parser().parse_args(
        ["layout-performance", "verify", "--baseline", "baseline.json"]
    )
    loaded = set(sys.modules) - before

    assert args.cmd == "layout-performance"
    assert args.performance_command == "verify"
    assert args.baseline == Path("baseline.json")
    assert not any(name.startswith("trade_py.devtools.layout_performance") for name in loaded)


def test_cli_classifies_capture_failure_and_preserves_completed_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from trade_py.devtools.layout_performance.capture import PerformanceCaptureError

    monkeypatch.chdir(REPO_ROOT)

    def fail_capture(*_args: Any, **_kwargs: Any) -> PerformanceEvidence:
        raise PerformanceCaptureError(
            "layout.performance.process_cleanup",
            "child process remained",
            completed_stages=("runner_identity", "startup_probes"),
            partial_evidence={"source_commit": "1" * 40},
        )

    monkeypatch.setattr(
        "trade_py.devtools.layout_performance.cli.capture_performance",
        fail_capture,
    )
    args = dev.make_parser().parse_args(
        ["layout-performance", "capture", "--output", str(tmp_path / "baseline.json")]
    )

    code = run_layout_performance_cli(args)
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["status"] == "tool_failure"
    assert payload["completed_stages"] == ["runner_identity", "startup_probes"]
    assert payload["partial_evidence"]["source_commit"] == "1" * 40
    assert not (tmp_path / "baseline.json").exists()


def test_verify_rejects_baseline_commit_outside_repository_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = replace(_evidence(), source_commit="f" * 40)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(render_evidence(baseline, baseline=True), encoding="utf-8")
    monkeypatch.chdir(REPO_ROOT)
    args = dev.make_parser().parse_args(
        ["layout-performance", "verify", "--baseline", str(baseline_path)]
    )

    code = run_layout_performance_cli(args)
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["failure_class"] == "tool_failure"
    assert payload["error"]["code"] == "layout.performance.process_exit"


def test_process_failure_does_not_expose_child_output_or_inherited_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "sk-review-secret-123"
    monkeypatch.setenv("TRADE_REVIEW_TOKEN", secret)

    with pytest.raises(PerformanceProcessError) as raised:
        run_process(
            (
                sys.executable,
                "-c",
                (
                    "import os,sys;"
                    "sys.stderr.write(os.environ.get('TRADE_REVIEW_TOKEN','not-inherited'));"
                    "raise SystemExit(9)"
                ),
            ),
            cwd=tmp_path,
            timeout_seconds=2,
        )

    assert raised.value.code == "layout.performance.process_exit"
    assert secret not in raised.value.detail
    assert "not-inherited" not in raised.value.detail


def test_top_level_route_uses_frozen_no_sync(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
    fake_uv.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"

    result = subprocess.run(
        [str(REPO_ROOT / "trade"), "dev", "layout-performance", "verify"],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout.splitlines()[:4] == ["run", "--frozen", "--no-sync", "python"]
    assert result.stdout.splitlines()[-3:] == ["dev", "layout-performance", "verify"]
