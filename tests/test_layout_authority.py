from __future__ import annotations

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from trade_py.devtools.layout import authority
from trade_py.devtools.layout.authority import (
    build_consumer_inventory,
    validate_authority_manifest,
)
from trade_py.devtools.layout.tree_index import (
    TreeIndexError,
    TreeIndexLimits,
    TreeIndexSession,
    read_regular_relative,
    scan_repository,
)
from trade_py.devtools.quality.config import QualityConfig
from trade_py.devtools.quality.models import GateMode, ScopeSelection
from trade_py.devtools.quality.planner import build_plan

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 27, 12, tzinfo=timezone.utc)
ACTIVATION_PLAN_DIGEST = "sha256:" + "a" * 64
MIGRATION_EVIDENCE_REF = "sha256:" + "b" * 64


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write(repo: Path, relative: str, content: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _manifest(authorities: list[dict[str, Any]] | None = None) -> str:
    lines = [
        "schema_version = 1",
        'rules_version = "layout-authority-v1"',
        'included_roots = ["src/trade", "trade_py"]',
        'foundation_modules = ["trade"]',
    ]
    if not authorities:
        lines.append("authorities = []")
        return "\n".join(lines) + "\n"
    for item in authorities:
        lines.extend(
            (
                "",
                "[[authorities]]",
                f'legacy_module = "{item["legacy_module"]}"',
                f'target_module = "{item["target_module"]}"',
                f'owner = "{item["owner"]}"',
                f'contract_generation = "{item["contract_generation"]}"',
                f'implementation_digest = "{item["implementation_digest"]}"',
                f'compatibility_direction = "{item["compatibility_direction"]}"',
                f'state = "{item["state"]}"',
            )
        )
        for key in ("activation_plan_digest", "migration_evidence_ref"):
            if value := item.get(key):
                lines.append(f"{key} = {json.dumps(value)}")
        lines.extend(("", "[authorities.consumer_inventory]"))
        inventory = item["consumer_inventory"]
        for key, value in inventory.items():
            if isinstance(value, str):
                lines.append(f"{key} = {json.dumps(value)}")
            elif isinstance(value, tuple):
                lines.append(f"{key} = {json.dumps(list(value))}")
            else:
                lines.append(f"{key} = {value}")
    return "\n".join(lines) + "\n"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "layout@example.invalid")
    _run_git(repo, "config", "user.name", "Layout Test")
    _write(repo, "src/trade/__init__.py", '"""Target package foundation."""\n')
    _write(repo, "trade_py/__init__.py", '"""Legacy package."""\n')
    _write(
        repo,
        "pyproject.toml",
        "[project]\n"
        'name = "layout-test"\n'
        'version = "0.0.0"\n'
        "\n"
        "[project.scripts]\n"
        'trade-py = "trade_py.cli.main:main"\n',
    )
    _write(repo, "layout-authority.toml", _manifest())
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "baseline")
    return repo


def _authority_row(
    repo: Path,
    *,
    legacy_module: str = "trade_py.sample",
    target_module: str = "trade.sample",
    owner: str = "datasets",
    state: str = "shadow_verified",
    generated_at: datetime = NOW,
) -> dict[str, Any]:
    initial = validate_authority_manifest(repo, observed_at=NOW)
    assert initial.findings
    assert {item.code for item in initial.findings} == {"layout.authority.target_unclassified"}
    assert initial.tree_index is not None
    target = next(
        entry
        for entry in initial.tree_index.entries
        if authority._module_name(entry.path) == target_module
    )
    inventory = build_consumer_inventory(
        repo,
        index=initial.tree_index,
        included_roots=("src/trade", "trade_py"),
        rules_digest=initial.tree_index.rules_digest,
        import_edges=initial.import_edges,
        selected_modules=(legacy_module, target_module),
        generated_at=generated_at,
    )
    row = {
        "legacy_module": legacy_module,
        "target_module": target_module,
        "owner": owner,
        "contract_generation": "dataset-contract-v1",
        "implementation_digest": target.source_digest,
        "compatibility_direction": "legacy_to_target",
        "state": state,
        "consumer_inventory": asdict(inventory),
    }
    if state != "inventoried":
        row["activation_plan_digest"] = ACTIVATION_PLAN_DIGEST
    if state in {"legacy_forwarding", "target_authoritative", "retireable"}:
        row["migration_evidence_ref"] = MIGRATION_EVIDENCE_REF
    return row


def _commit_authorities(repo: Path, rows: list[dict[str, Any]]) -> None:
    _write(repo, "layout-authority.toml", _manifest(rows))
    _run_git(repo, "add", "layout-authority.toml")
    _run_git(repo, "commit", "-m", "authority")


def _commit_authority(repo: Path, row: dict[str, Any]) -> None:
    _commit_authorities(repo, [row])


def _codes(repo: Path, **kwargs: Any) -> set[str]:
    return {item.code for item in validate_authority_manifest(repo, **kwargs).findings}


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_repository_foundation_manifest_is_read_only_and_valid() -> None:
    report = validate_authority_manifest(REPO_ROOT)

    assert report.ok
    assert report.exit_code == 0
    assert report.authorities == ()
    assert report.tree_index is not None
    assert report.tree_index.partition(("src/trade",))
    assert all(
        not item.path.startswith(("tests/", "data/", "trade_web/"))
        for item in report.tree_index.entries
    )


def test_explicit_session_builds_one_index_for_multiple_partitions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    calls = 0
    real_scan = authority.scan_repository

    def recording_scan(*args: Any, **kwargs: Any):
        nonlocal calls
        calls += 1
        return real_scan(*args, **kwargs)

    monkeypatch.setattr("trade_py.devtools.layout.tree_index.scan_repository", recording_scan)
    session = TreeIndexSession(
        repo,
        ("src/trade", "trade_py"),
        "sha256:" + "1" * 64,
    )

    assert session.index().partition(("src/trade",))
    assert session.index().partition(("trade_py",))
    assert calls == 1


def test_session_concurrency_scans_once_and_new_session_invalidates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    calls = 0
    real_scan = authority.scan_repository

    def recording_scan(*args: Any, **kwargs: Any):
        nonlocal calls
        calls += 1
        time.sleep(0.05)
        return real_scan(*args, **kwargs)

    monkeypatch.setattr("trade_py.devtools.layout.tree_index.scan_repository", recording_scan)
    session = TreeIndexSession(repo, ("src/trade", "trade_py"), "sha256:" + "1" * 64)

    with ThreadPoolExecutor(max_workers=4) as executor:
        indexes = tuple(executor.map(lambda _value: session.index(), range(8)))

    assert calls == 1
    assert all(item is indexes[0] for item in indexes)

    _write(repo, "trade_py/__init__.py", '"""Changed legacy package."""\n')
    assert session.index() is indexes[0]

    changed = TreeIndexSession(
        repo,
        ("src/trade", "trade_py"),
        "sha256:" + "1" * 64,
    ).index()
    assert calls == 2
    assert changed.tree_digest != indexes[0].tree_digest


def test_tree_index_is_deterministic_across_root_order(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/zeta.py", "VALUE = 1\n")
    _write(repo, "trade_py/alpha.py", "VALUE = 2\n")
    _run_git(repo, "add", ".")

    first = scan_repository(
        repo,
        included_roots=("src/trade", "trade_py"),
        rules_digest="sha256:" + "1" * 64,
    )
    second = scan_repository(
        repo,
        included_roots=("trade_py", "src/trade"),
        rules_digest="sha256:" + "1" * 64,
    )

    assert first == second
    assert tuple(item.path for item in first.entries) == tuple(
        sorted(item.path for item in first.entries)
    )
    assert first.excluded_segments == tuple(sorted(first.excluded_segments))


def test_git_timeout_terminates_descendant_process_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    tools = tmp_path / "tools"
    tools.mkdir()
    child_pid_path = tmp_path / "child.pid"
    fake_git = tools / "git"
    fake_git.write_text(
        f"#!/bin/sh\nsleep 30 &\necho $! > {child_pid_path}\nsleep 30\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tools}{os.pathsep}{os.environ['PATH']}")

    with pytest.raises(TreeIndexError) as raised:
        scan_repository(
            repo,
            included_roots=("src/trade", "trade_py"),
            rules_digest="sha256:" + "1" * 64,
            limits=TreeIndexLimits(deadline_seconds=0.1),
        )

    assert raised.value.code == "layout.index.timeout"
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2
    while _pid_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not _pid_exists(child_pid)


def test_successful_git_parent_exit_still_terminates_background_descendant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    tools = tmp_path / "tools"
    tools.mkdir()
    child_pid_path = tmp_path / "child.pid"
    fake_git = tools / "git"
    fake_git.write_text(
        f"#!/bin/sh\nsleep 30 </dev/null >/dev/null 2>&1 &\necho $! > {child_pid_path}\nexit 0\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tools}{os.pathsep}{os.environ['PATH']}")

    index = scan_repository(
        repo,
        included_roots=("src/trade", "trade_py"),
        rules_digest="sha256:" + "1" * 64,
        limits=TreeIndexLimits(deadline_seconds=1),
    )

    assert index.entries == ()
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2
    while _pid_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not _pid_exists(child_pid)


def test_untracked_target_candidate_is_not_hidden_by_git_index(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/hidden.py", "VALUE = 1\n")

    without_candidate = validate_authority_manifest(repo, observed_at=NOW)
    with_candidate = validate_authority_manifest(
        repo,
        candidate_paths=("src/trade/hidden.py",),
        observed_at=NOW,
    )

    assert without_candidate.ok
    assert "layout.authority.target_unclassified" in {item.code for item in with_candidate.findings}


def test_manifest_rejects_unapproved_roots_and_unknown_fields(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    manifest = _manifest().replace(
        'included_roots = ["src/trade", "trade_py"]',
        'included_roots = ["src/trade", "trade_py", "data"]',
    )
    _write(repo, "layout-authority.toml", manifest + 'unexpected = "value"\n')
    _write(repo, "data/poison.py", "this is not valid Python\n")

    report = validate_authority_manifest(repo, observed_at=NOW)

    assert report.tree_index is None
    assert report.exit_code == 1
    assert {item.code for item in report.findings} == {"layout.authority.manifest_invalid"}


def test_duplicate_logical_module_paths_are_rejected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(repo, "src/trade/sample/__init__.py", "VALUE = 2\n")
    _run_git(repo, "add", ".")

    assert "layout.authority.duplicate_module_path" in _codes(repo, observed_at=NOW)


@pytest.mark.parametrize(
    ("content", "code"),
    (
        ("from trade_py.sample import VALUE\n", "layout.authority.reverse_dependency"),
        (
            'import sys\nsys.modules["trade.alias"] = sys.modules[__name__]\n',
            "layout.authority.sys_modules_alias",
        ),
        (
            'import sys\nsys.modules.update({"trade.alias": sys.modules[__name__]})\n',
            "layout.authority.sys_modules_alias",
        ),
        ('__path__ = ["../trade_py"]\n', "layout.authority.path_extension"),
        (
            "import pkgutil\n__path__ = pkgutil.extend_path(__path__, __name__)\n",
            "layout.authority.path_extension",
        ),
    ),
)
def test_target_namespace_escape_is_rejected(
    tmp_path: Path,
    content: str,
    code: str,
) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/escaped.py", content)

    report = validate_authority_manifest(
        repo,
        candidate_paths=("src/trade/escaped.py",),
        observed_at=NOW,
    )

    assert report.exit_code == 1
    assert code in {item.code for item in report.findings}


def test_optional_transport_cannot_leak_into_lower_layer(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/datasets/domain/rule.py", "import mcp.client\n")

    assert "layout.authority.optional_dependency_leak" in _codes(
        repo,
        candidate_paths=("src/trade/datasets/domain/rule.py",),
        observed_at=NOW,
    )


@pytest.mark.parametrize("segment", ("domain", "use_cases", "compat"))
@pytest.mark.parametrize("dependency", ("mcp.client", "plugins.registry", "remote_worker.client"))
def test_optional_transport_is_rejected_from_every_lower_layer(
    tmp_path: Path,
    segment: str,
    dependency: str,
) -> None:
    repo = _repo(tmp_path)
    path = f"src/trade/datasets/{segment}/rule.py"
    _write(repo, path, f"import {dependency}\n")

    assert "layout.authority.optional_dependency_leak" in _codes(
        repo,
        candidate_paths=(path,),
        observed_at=NOW,
    )


@pytest.mark.parametrize(
    "content",
    (
        'import importlib\nimportlib.import_module("mcp.client")\n',
        'import importlib as loader\nloader.import_module("plugins.registry")\n',
        'from importlib import import_module as load\nload("remote_worker.client")\n',
        '__import__("mcp.client")\n',
        'import importlib.util\nimportlib.util.find_spec("plugins.registry")\n',
        ('from importlib.util import find_spec as locate\nlocate("remote_worker.client")\n'),
        ('from importlib import util as loader_util\nloader_util.find_spec("mcp.client")\n'),
        ('import importlib\nload = importlib.import_module\nload("plugins.registry")\n'),
        (
            "from importlib import import_module\n"
            "load = import_module\n"
            "load_again = load\n"
            'load_again("remote_worker.client")\n'
        ),
        (
            "from importlib import import_module\n"
            'tuple(map(import_module, ("json", "mcp.client")))\n'
        ),
        ('from importlib import import_module\npool.map(import_module, ("plugins.registry",))\n'),
    ),
)
def test_dynamic_optional_transport_is_rejected_from_lower_layer(
    tmp_path: Path,
    content: str,
) -> None:
    repo = _repo(tmp_path)
    path = "src/trade/datasets/domain/rule.py"
    _write(repo, path, content)

    report = validate_authority_manifest(
        repo,
        candidate_paths=(path,),
        observed_at=NOW,
    )

    assert "layout.authority.optional_dependency_leak" in {item.code for item in report.findings}
    assert any(
        edge.imported in {"mcp.client", "plugins.registry", "remote_worker.client"}
        for edge in report.import_edges
    )


def test_unresolved_dynamic_import_fails_closed_in_lower_layer(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    path = "src/trade/datasets/use_cases/load.py"
    _write(
        repo,
        path,
        "import importlib\ndef load(name: str):\n    return importlib.import_module(name)\n",
    )

    assert "layout.authority.dynamic_import_unresolved" in _codes(
        repo,
        candidate_paths=(path,),
        observed_at=NOW,
    )


def test_dynamic_legacy_import_is_rejected_from_target_module(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    path = "src/trade/datasets/domain/rule.py"
    _write(repo, path, 'from importlib import import_module\nimport_module("trade_py.sample")\n')

    assert "layout.authority.reverse_dependency" in _codes(
        repo,
        candidate_paths=(path,),
        observed_at=NOW,
    )


@pytest.mark.parametrize(
    "metadata",
    (
        (
            "[project]\n"
            'name = "layout-test"\n'
            'version = "0.0.0"\n'
            "\n"
            "[project.scripts]\n"
            'trade-py = "trade_py.cli.main:main"\n'
            'trade-plugin = "trade.plugins:main"\n'
        ),
        (
            "[project]\n"
            'name = "layout-test"\n'
            'version = "0.0.0"\n'
            "\n"
            "[project.scripts]\n"
            'trade-py = "trade_py.cli.main:main"\n'
            "\n"
            '[project.entry-points."trade.plugins"]\n'
            'sample = "trade.plugins.sample:Plugin"\n'
        ),
    ),
)
def test_unapproved_package_entry_points_are_rejected(
    tmp_path: Path,
    metadata: str,
) -> None:
    repo = _repo(tmp_path)
    _write(repo, "pyproject.toml", metadata)

    assert "layout.authority.entry_point_unapproved" in _codes(repo, observed_at=NOW)


def test_relative_import_is_included_in_consumer_inventory(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(repo, "src/trade/nested/consumer.py", "from .. import sample\n")
    _write(repo, "trade_py/sample.py", "VALUE = 1\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "sample sources")

    row = _authority_row(repo)

    assert row["consumer_inventory"]["consumer_count"] == 1


def test_valid_shadow_authority_binds_current_sources_and_inventory(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(repo, "trade_py/sample.py", "VALUE = 1\n")
    _run_git(repo, "add", "src/trade/sample.py", "trade_py/sample.py")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo)
    _commit_authority(repo, row)

    report = validate_authority_manifest(repo, observed_at=NOW + timedelta(hours=1))

    assert report.ok
    assert len(report.authorities) == 1
    assert report.authorities[0].consumer_inventory.completeness_state == "complete"


@pytest.mark.parametrize(
    "state",
    ("prepared", "shadow_verified", "legacy_forwarding", "target_authoritative", "retireable"),
)
def test_planned_authority_requires_activation_plan_lineage(
    tmp_path: Path,
    state: str,
) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    legacy_source = (
        "from trade.sample import VALUE\n"
        if state in {"legacy_forwarding", "target_authoritative", "retireable"}
        else "VALUE = 1\n"
    )
    _write(repo, "trade_py/sample.py", legacy_source)
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo, state=state)
    row.pop("activation_plan_digest")
    _commit_authority(repo, row)

    assert "layout.authority.activation_plan_missing" in _codes(
        repo,
        observed_at=NOW + timedelta(hours=1),
    )


@pytest.mark.parametrize(
    "state",
    ("legacy_forwarding", "target_authoritative", "retireable"),
)
def test_terminal_authority_requires_migration_evidence(
    tmp_path: Path,
    state: str,
) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(repo, "trade_py/sample.py", "from trade.sample import VALUE\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo, state=state)
    row.pop("migration_evidence_ref")
    _commit_authority(repo, row)

    assert "layout.authority.migration_evidence_missing" in _codes(
        repo,
        observed_at=NOW + timedelta(hours=1),
    )


@pytest.mark.parametrize("state", ("prepared", "shadow_verified"))
def test_nonterminal_authority_rejects_terminal_evidence(
    tmp_path: Path,
    state: str,
) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(repo, "trade_py/sample.py", "VALUE = 1\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo, state=state)
    row["migration_evidence_ref"] = MIGRATION_EVIDENCE_REF
    _commit_authority(repo, row)

    assert "layout.authority.lineage_premature" in _codes(
        repo,
        observed_at=NOW + timedelta(hours=1),
    )


def test_inventoried_authority_rejects_activation_lineage(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(repo, "trade_py/sample.py", "VALUE = 1\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo, state="inventoried")
    row["activation_plan_digest"] = ACTIVATION_PLAN_DIGEST
    _commit_authority(repo, row)

    assert "layout.authority.lineage_premature" in _codes(
        repo,
        observed_at=NOW + timedelta(hours=1),
    )


def test_authority_lineage_requires_complete_sha256_digest(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(repo, "trade_py/sample.py", "VALUE = 1\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo)
    row["activation_plan_digest"] = "sha256:not-a-digest"
    _commit_authority(repo, row)

    assert "layout.authority.lineage_invalid" in _codes(
        repo,
        observed_at=NOW + timedelta(hours=1),
    )


@pytest.mark.parametrize(
    "state",
    ("legacy_forwarding", "target_authoritative", "retireable"),
)
def test_valid_terminal_authority_binds_plan_and_migration_evidence(
    tmp_path: Path,
    state: str,
) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(repo, "trade_py/sample.py", "from trade.sample import VALUE\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo, state=state)
    _commit_authority(repo, row)

    report = validate_authority_manifest(repo, observed_at=NOW + timedelta(hours=1))

    assert report.ok
    assert report.authorities[0].activation_plan_digest == ACTIVATION_PLAN_DIGEST
    assert report.authorities[0].migration_evidence_ref == MIGRATION_EVIDENCE_REF


def test_owner_partitions_are_deterministic(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    for name in ("alpha", "beta"):
        _write(repo, f"src/trade/{name}.py", f'NAME = "{name}"\n')
        _write(repo, f"trade_py/{name}.py", f'NAME = "{name}"\n')
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "authority sources")
    rows = [
        _authority_row(
            repo,
            legacy_module="trade_py.beta",
            target_module="trade.beta",
            owner="studies",
        ),
        _authority_row(
            repo,
            legacy_module="trade_py.alpha",
            target_module="trade.alpha",
            owner="capture",
        ),
    ]
    _commit_authorities(repo, rows)

    report = validate_authority_manifest(repo, observed_at=NOW + timedelta(hours=1))

    assert report.ok
    assert tuple(owner for owner, _items in report.partition_by_owner()) == (
        "capture",
        "studies",
    )
    assert tuple(
        item.target_module for _owner, items in report.partition_by_owner() for item in items
    ) == ("trade.alpha", "trade.beta")


def test_duplicate_legacy_and_target_authority_is_rejected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(repo, "trade_py/sample.py", "VALUE = 1\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo)
    _commit_authorities(repo, [row, row])

    codes = _codes(repo, observed_at=NOW + timedelta(hours=1))

    assert "layout.authority.duplicate_legacy" in codes
    assert "layout.authority.duplicate_target" in codes


def test_forwarding_authority_requires_one_direct_inert_hop(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(repo, "trade_py/sample.py", "from trade.sample import VALUE\nVALUE += 1\n")
    _run_git(repo, "add", "src/trade/sample.py", "trade_py/sample.py")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo, state="legacy_forwarding")
    _commit_authority(repo, row)

    assert "layout.authority.forwarder_not_thin" in _codes(
        repo,
        observed_at=NOW + timedelta(hours=1),
    )


def test_forwarder_cannot_import_optional_transport(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(
        repo,
        "trade_py/sample.py",
        "from trade.sample import VALUE\nimport mcp.client\n",
    )
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo, state="legacy_forwarding")
    _commit_authority(repo, row)

    codes = _codes(repo, observed_at=NOW + timedelta(hours=1))

    assert "layout.authority.optional_dependency_leak" in codes
    assert "layout.authority.forwarder_not_thin" in codes


@pytest.mark.parametrize(
    "dynamic_line",
    (
        'importlib.import_module("mcp.client")',
        'load("plugins.registry")',
        'tuple(map(load, ("remote_worker.client",)))',
    ),
)
def test_forwarder_cannot_dynamically_import_optional_transport(
    tmp_path: Path,
    dynamic_line: str,
) -> None:
    repo = _repo(tmp_path)
    loader_import = (
        "import importlib\n"
        if dynamic_line.startswith("importlib.")
        else "from importlib import import_module as load\n"
    )
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(
        repo,
        "trade_py/sample.py",
        f"from trade.sample import VALUE\n{loader_import}{dynamic_line}\n",
    )
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo, state="legacy_forwarding")
    _commit_authority(repo, row)

    codes = _codes(repo, observed_at=NOW + timedelta(hours=1))

    assert "layout.authority.optional_dependency_leak" in codes
    assert "layout.authority.forwarder_not_thin" in codes


def test_forwarder_unresolved_dynamic_import_fails_closed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(
        repo,
        "trade_py/sample.py",
        "from importlib import import_module\n"
        "from trade.sample import VALUE\n"
        "def load(name: str):\n"
        "    return import_module(name)\n",
    )
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo, state="legacy_forwarding")
    _commit_authority(repo, row)

    codes = _codes(repo, observed_at=NOW + timedelta(hours=1))

    assert "layout.authority.dynamic_import_unresolved" in codes
    assert "layout.authority.forwarder_not_thin" in codes


@pytest.mark.parametrize(
    "probe",
    (
        "import trade_py.sample as old; import trade.sample as new",
        "import trade.sample as new; import trade_py.sample as old",
        (
            "from concurrent.futures import ThreadPoolExecutor\n"
            "import importlib\n"
            "with ThreadPoolExecutor(max_workers=2) as pool:\n"
            "    old, new = tuple(pool.map(importlib.import_module, "
            "('trade_py.sample', 'trade.sample')))"
        ),
    ),
)
def test_valid_forwarder_initializes_target_once_and_preserves_identity(
    tmp_path: Path,
    probe: str,
) -> None:
    repo = _repo(tmp_path)
    _write(
        repo,
        "src/trade/sample.py",
        "import builtins\n"
        "builtins._layout_init_count = getattr(builtins, '_layout_init_count', 0) + 1\n"
        "REGISTRY = object()\n"
        "HANDLER = object()\n"
        "RESOURCE = object()\n",
    )
    _write(
        repo,
        "trade_py/sample.py",
        "from trade.sample import HANDLER, REGISTRY, RESOURCE\n",
    )
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo, state="legacy_forwarding")
    _commit_authority(repo, row)

    report = validate_authority_manifest(repo, observed_at=NOW + timedelta(hours=1))
    result = subprocess.run(
        [
            os.environ.get("PYTHON", "python"),
            "-c",
            (
                f"{probe}\n"
                "import builtins\n"
                "assert old.REGISTRY is new.REGISTRY\n"
                "assert old.HANDLER is new.HANDLER\n"
                "assert old.RESOURCE is new.RESOURCE\n"
                "assert builtins._layout_init_count == 1\n"
            ),
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTHONPATH": f"{repo / 'src'}{os.pathsep}{repo}",
        },
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert report.ok
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        (
            lambda row: row["consumer_inventory"].__setitem__("completeness_state", "tool_failed"),
            "layout.authority.inventory_incomplete",
        ),
        (
            lambda row: row["consumer_inventory"].__setitem__("tree_digest", "sha256:" + "0" * 64),
            "layout.authority.inventory_stale",
        ),
        (
            lambda row: row["consumer_inventory"].__setitem__(
                "scanner_source_digest", "sha256:" + "0" * 64
            ),
            "layout.authority.inventory_stale",
        ),
        (
            lambda row: row["consumer_inventory"].__setitem__("rules_digest", "sha256:" + "0" * 64),
            "layout.authority.inventory_stale",
        ),
        (
            lambda row: row["consumer_inventory"].__setitem__(
                "explicit_exclusions", ["segment:invented"]
            ),
            "layout.authority.inventory_stale",
        ),
        (
            lambda row: row["consumer_inventory"].__setitem__("unclassified_consumer_count", 1),
            "layout.authority.inventory_unclassified",
        ),
    ),
)
def test_incomplete_or_stale_inventory_is_rejected(
    tmp_path: Path,
    mutation: Any,
    code: str,
) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(repo, "trade_py/sample.py", "VALUE = 1\n")
    _run_git(repo, "add", "src/trade/sample.py", "trade_py/sample.py")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo)
    mutation(row)
    _commit_authority(repo, row)

    assert code in _codes(repo, observed_at=NOW + timedelta(hours=1))


def test_inventory_age_boundary_is_exact(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(repo, "trade_py/sample.py", "VALUE = 1\n")
    _run_git(repo, "add", "src/trade/sample.py", "trade_py/sample.py")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo)
    _commit_authority(repo, row)

    assert "layout.authority.inventory_expired" not in _codes(
        repo,
        observed_at=NOW + timedelta(hours=24),
    )
    assert "layout.authority.inventory_expired" in _codes(
        repo,
        observed_at=NOW + timedelta(hours=24, microseconds=1),
    )


def test_inventory_from_the_future_is_rejected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(repo, "trade_py/sample.py", "VALUE = 1\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo, generated_at=NOW + timedelta(seconds=1))
    _commit_authority(repo, row)

    assert "layout.authority.inventory_time_invalid" in _codes(repo, observed_at=NOW)


def test_authority_module_budget_refuses_without_partial_admission(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(repo, "trade_py/sample.py", "VALUE = 1\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo)
    _commit_authorities(repo, [row for _index in range(authority.MAX_AUTHORITIES + 1)])

    report = validate_authority_manifest(repo, observed_at=NOW + timedelta(hours=1))

    assert "layout.authority.module_budget" in {item.code for item in report.findings}
    assert report.authorities == ()


def test_consumer_budget_refuses_without_sampling(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(repo, "trade_py/sample.py", "VALUE = 1\n")
    _write(
        repo,
        "trade_py/consumers.py",
        "\n".join(
            f"import trade.sample as sample_{index}" for index in range(authority.MAX_CONSUMERS + 1)
        )
        + "\n",
    )
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo)
    assert row["consumer_inventory"]["consumer_count"] == authority.MAX_CONSUMERS + 1
    assert row["consumer_inventory"]["completeness_state"] == "over_budget"
    _commit_authority(repo, row)

    codes = _codes(repo, observed_at=NOW + timedelta(hours=1))

    assert "layout.authority.consumer_budget" in codes
    assert "layout.authority.inventory_incomplete" in codes


def test_missing_or_unknown_owner_is_rejected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(repo, "trade_py/sample.py", "VALUE = 1\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "sample sources")
    missing = _authority_row(repo)
    missing_manifest = _manifest([missing]).replace('owner = "datasets"\n', "")
    _write(repo, "layout-authority.toml", missing_manifest)
    assert "layout.authority.field_missing" in _codes(repo, observed_at=NOW)

    unknown = dict(missing)
    unknown["owner"] = "observatory"
    _write(repo, "layout-authority.toml", _manifest([unknown]))
    assert "layout.authority.owner_invalid" in _codes(repo, observed_at=NOW)


def test_source_path_and_file_budgets_fail_closed(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    with pytest.raises(TreeIndexError) as path_error:
        scan_repository(
            repo,
            included_roots=("src/trade", "trade_py"),
            rules_digest="sha256:" + "1" * 64,
            limits=TreeIndexLimits(max_paths=1),
        )
    with pytest.raises(TreeIndexError) as file_error:
        scan_repository(
            repo,
            included_roots=("src/trade", "trade_py"),
            rules_digest="sha256:" + "1" * 64,
            limits=TreeIndexLimits(max_file_bytes=1),
        )

    assert path_error.value.code == "layout.index.path_budget"
    assert file_error.value.code == "layout.index.file_budget"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO fixture requires POSIX")
def test_source_reader_rejects_fifo_without_waiting_for_writer(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    source = repo / "trade_py" / "__init__.py"
    source.unlink()
    os.mkfifo(source)

    started = time.monotonic()
    with pytest.raises(TreeIndexError) as blocked:
        read_regular_relative(
            repo,
            "trade_py/__init__.py",
            max_bytes=1024,
            deadline_at=time.monotonic() + 1,
        )
    elapsed = time.monotonic() - started

    assert blocked.value.code == "layout.index.unsafe_source"
    assert elapsed < 1.0


def test_many_authorities_share_one_source_commit_coverage_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/trade/sample.py", "VALUE = 1\n")
    _write(repo, "trade_py/sample.py", "VALUE = 1\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "sample sources")
    row = _authority_row(repo)
    _commit_authorities(repo, [row for _index in range(authority.MAX_AUTHORITIES)])
    real_run = subprocess.run
    calls: list[tuple[str, ...]] = []

    def recording_run(command: list[str], *args: Any, **kwargs: Any):
        calls.append(tuple(command))
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(
        "trade_py.devtools.layout.inventory.subprocess.run",
        recording_run,
    )

    report = validate_authority_manifest(repo, observed_at=NOW + timedelta(hours=1))

    assert len(calls) == 2
    assert [command[3] for command in calls] == ["merge-base", "diff"]
    assert "layout.authority.inventory_commit_stale" not in {item.code for item in report.findings}


def test_layout_contributor_runs_only_for_check_and_relevant_scope(tmp_path: Path) -> None:
    relevant = ScopeSelection(
        repo_root=str(tmp_path),
        base_ref="master",
        base_sha="a" * 40,
        head_sha="b" * 40,
        files=("src/trade/new.py", "trade_py/unrelated.py"),
        delta_files=("src/trade/new.py", "trade_py/unrelated.py"),
        fingerprint="f" * 64,
    )
    unrelated = ScopeSelection(
        repo_root=str(tmp_path),
        base_ref="master",
        base_sha="a" * 40,
        head_sha="b" * 40,
        files=("docs/readme.md",),
        delta_files=("docs/readme.md",),
        fingerprint="f" * 64,
    )
    legacy_only = ScopeSelection(
        repo_root=str(tmp_path),
        base_ref="master",
        base_sha="a" * 40,
        head_sha="b" * 40,
        files=("trade_py/datasets/source.py",),
        delta_files=("trade_py/datasets/source.py",),
        fingerprint="f" * 64,
    )

    check = build_plan(relevant, mode=GateMode.CHECK, config=QualityConfig())
    fix = build_plan(relevant, mode=GateMode.FIX, config=QualityConfig())
    docs = build_plan(unrelated, mode=GateMode.CHECK, config=QualityConfig())
    legacy = build_plan(legacy_only, mode=GateMode.CHECK, config=QualityConfig())

    step = next(item for item in check.steps if item.check_id == "layout.authority")
    assert step.argv[-4:] == (
        "--candidate",
        "src/trade/new.py",
        "--candidate",
        "trade_py/unrelated.py",
    )
    legacy_step = next(item for item in legacy.steps if item.check_id == "layout.authority")
    assert legacy_step.argv[-2:] == ("--candidate", "trade_py/datasets/source.py")
    assert all(item.check_id != "layout.authority" for item in fix.steps)
    assert all(item.check_id != "layout.authority" for item in docs.steps)


def test_cli_report_is_machine_readable_and_no_business_modules_are_loaded(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from trade_py.devtools.layout import cli

    monkeypatch.chdir(REPO_ROOT)
    code = cli.main(["--repo-root", "."])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["schema_version"] == "trade.layout.authority-report.v1"
    assert payload["status"] == "PASS"
    assert payload["authorities"] == []
    assert payload["index"]["source_count"] > 0
