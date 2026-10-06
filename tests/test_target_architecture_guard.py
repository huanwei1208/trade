from __future__ import annotations

from pathlib import Path

import pytest

from trade_py.devtools.architecture_guard import validate_architecture_baseline
from trade_py.devtools.target_architecture_guard import (
    COMPAT_ADAPTER_BOUNDARY,
    COMPAT_AGGREGATE_REEXPORT,
    DYNAMIC_IMPORT_UNRESOLVED,
    DYNAMIC_REEXPORT,
    KERNEL_DEPENDENCY,
    KERNEL_MODULE_ALLOWLIST,
    KERNEL_OWNER_VOCABULARY,
    PLATFORM_DEPENDENCY,
    PROCESSES_DEPENDENCY,
    RUNTIME_ADOPTION_FENCE,
    TARGET_LEGACY_DEPENDENCY,
    validate_target_architecture,
)


def _write(repo: Path, relative: str, text: str = "") -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _target_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    _write(repo, "src/trade/__init__.py")
    _write(repo, "src/trade/kernel/__init__.py")
    for module in ("digest", "envelope", "errors", "ids", "result", "time"):
        _write(repo, f"src/trade/kernel/{module}.py", "from __future__ import annotations\n")
    return repo


def _rule_ids(repo: Path) -> set[str]:
    return {finding.rule_id for finding in validate_target_architecture(repo)}


def test_guard_is_dormant_before_target_kernel_exists(tmp_path: Path) -> None:
    repo = tmp_path / "legacy"
    _write(repo, "trade_py/runtime.py", "target = input()\n__import__(target)\n")

    assert validate_target_architecture(repo) == ()


def test_current_repository_target_graph_passes() -> None:
    repo = Path(__file__).resolve().parents[1]

    assert validate_target_architecture(repo) == ()


@pytest.mark.parametrize(
    ("relative_path", "source", "expected_rule"),
    [
        ("src/trade/kernel/refs.py", "", KERNEL_MODULE_ALLOWLIST),
        ("src/trade/kernel/time.py", "import fastapi\n", KERNEL_DEPENDENCY),
        (
            "src/trade/kernel/time.py",
            "class DatasetSnapshot:\n    pass\n",
            KERNEL_OWNER_VOCABULARY,
        ),
        (
            "src/trade/platform/contracts/actor.py",
            "from trade.processes.contracts import ProcessId\n",
            PLATFORM_DEPENDENCY,
        ),
        (
            "src/trade/platform/contracts/actor.py",
            "from trade_py.bus import EventBus\n",
            TARGET_LEGACY_DEPENDENCY,
        ),
        (
            "src/trade/processes/contracts/process_view.py",
            "from trade.platform.persistence import Session\n",
            PROCESSES_DEPENDENCY,
        ),
        (
            "src/trade/processes/contracts/process_view.py",
            "from trade_web.backend.runtime import RuntimeCommandRunner\n",
            TARGET_LEGACY_DEPENDENCY,
        ),
        (
            "trade_py/compat/public_contracts.py",
            "from trade_py.compat.bus_contracts import map_event\n",
            COMPAT_AGGREGATE_REEXPORT,
        ),
        (
            "trade_py/compat/bus_contracts.py",
            "from trade_py.db.trade_db import TradeDB\n",
            COMPAT_ADAPTER_BOUNDARY,
        ),
        (
            "trade_py/bus/__init__.py",
            "from trade.platform.contracts import OperationReceipt\n",
            RUNTIME_ADOPTION_FENCE,
        ),
        (
            "trade_web/backend/runtime/resources.py",
            "from trade_py.compat.runtime_contracts import map_shutdown\n",
            RUNTIME_ADOPTION_FENCE,
        ),
    ],
)
def test_guard_rejects_forbidden_target_edges(
    tmp_path: Path,
    relative_path: str,
    source: str,
    expected_rule: str,
) -> None:
    repo = _target_repo(tmp_path)
    _write(repo, relative_path, source)

    assert expected_rule in _rule_ids(repo)


def test_permitted_process_and_owner_mapper_edges_pass(tmp_path: Path) -> None:
    repo = _target_repo(tmp_path)
    _write(repo, "src/trade/platform/__init__.py")
    _write(repo, "src/trade/platform/contracts/__init__.py")
    _write(
        repo,
        "src/trade/platform/contracts/operations.py",
        "from trade.kernel.ids import OpaqueId\n",
    )
    _write(repo, "src/trade/processes/__init__.py")
    _write(repo, "src/trade/processes/contracts/__init__.py")
    _write(
        repo,
        "src/trade/processes/contracts/process_view.py",
        "from trade.kernel.ids import OpaqueId\n"
        "from trade.platform.contracts.operations import OperationReceipt\n",
    )
    _write(repo, "trade_py/compat/__init__.py")
    _write(
        repo,
        "trade_py/compat/bus_contracts.py",
        "from trade.kernel.ids import OpaqueId\n"
        "from trade.platform.contracts.operations import OperationReceipt\n"
        "from trade_py.bus import EventBus\n",
    )
    _write(
        repo,
        "trade_py/compat/job_run_contracts.py",
        "from trade.processes.contracts.process_view import ProcessView\n"
        "from trade_py.db.trade_db import TradeDB\n",
    )
    _write(
        repo,
        "trade_py/compat/observatory_contracts.py",
        "from trade_py.observatory.domain.models import ArtifactRef\n",
    )
    _write(
        repo,
        "trade_py/compat/runtime_contracts.py",
        "from trade_web.backend.runtime.commands import RuntimeCommandRunner\n",
    )

    assert validate_target_architecture(repo) == ()


@pytest.mark.parametrize(
    ("source", "imported_symbol"),
    [
        (
            "from trade.platform import contracts as platform_contracts\n",
            "trade.platform.contracts",
        ),
        ("from .compat import runtime_contracts\n", "trade_py.compat.runtime_contracts"),
        (
            "import importlib\nimportlib.import_module('trade.processes.contracts')\n",
            "trade.processes.contracts",
        ),
        (
            "loader = __import__\nloader('trade_py.compat.bus_contracts')\n",
            "trade_py.compat.bus_contracts",
        ),
    ],
)
def test_static_aliased_relative_and_literal_dynamic_imports_are_guarded(
    tmp_path: Path,
    source: str,
    imported_symbol: str,
) -> None:
    repo = _target_repo(tmp_path)
    _write(repo, "trade_py/runtime.py", source)

    findings = validate_target_architecture(repo)

    assert any(
        finding.rule_id == RUNTIME_ADOPTION_FENCE
        and finding.path == "trade_py/runtime.py"
        and imported_symbol in finding.message
        for finding in findings
    )


@pytest.mark.parametrize(
    "source",
    [
        "import importlib\nname = input()\nimportlib.import_module(name)\n",
        "name = input()\n__import__(name)\n",
        "import importlib\nloader = importlib.import_module\nloader(input())\n",
        "import importlib\nloader = getattr(importlib, 'import_module')\nloader(input())\n",
    ],
)
def test_unresolved_dynamic_imports_fail_closed(tmp_path: Path, source: str) -> None:
    repo = _target_repo(tmp_path)
    _write(repo, "trade_web/backend/runtime/lifespan.py", source)

    findings = validate_target_architecture(repo)

    assert DYNAMIC_IMPORT_UNRESOLVED in {finding.rule_id for finding in findings}
    assert any(
        finding.path == "trade_web/backend/runtime/lifespan.py"
        and "<module>" in finding.message
        and "edge" in finding.message
        for finding in findings
    )


def test_current_cli_loader_exact_finite_legacy_allowlist_passes(tmp_path: Path) -> None:
    repo = _target_repo(tmp_path)
    current = Path(__file__).resolve().parents[1] / "trade_py" / "cli" / "main.py"
    _write(repo, "trade_py/cli/main.py", current.read_text(encoding="utf-8"))

    assert validate_target_architecture(repo) == ()


def test_cli_loader_cannot_expand_to_target_contracts(tmp_path: Path) -> None:
    repo = _target_repo(tmp_path)
    _write(
        repo,
        "trade_py/cli/main.py",
        "import importlib\n"
        "canonical_domains = [('run', 'run', 'run'), ('target', 'trade.platform', 'bad')]\n"
        "legacy_domains = []\n"
        "def _import_domain(name: str):\n"
        "    return importlib.import_module(f'trade_py.cli.{name}')\n",
    )

    assert DYNAMIC_IMPORT_UNRESOLVED in _rule_ids(repo)


@pytest.mark.parametrize(
    "source",
    [
        "def __getattr__(name: str):\n"
        "    import importlib\n"
        "    return importlib.import_module(name)\n",
        "import importlib\nname = input()\nglobals()[name] = importlib.import_module(name)\n",
        "import importlib\nname = input()\nglobals().update({name: importlib.import_module(name)})\n",
    ],
)
def test_dynamic_package_reexports_fail_closed(tmp_path: Path, source: str) -> None:
    repo = _target_repo(tmp_path)
    _write(repo, "trade_py/package/__init__.py", source)

    assert DYNAMIC_REEXPORT in _rule_ids(repo)


def test_package_level_compat_adapter_reexport_is_rejected(tmp_path: Path) -> None:
    repo = _target_repo(tmp_path)
    _write(
        repo,
        "trade_py/compat/__init__.py",
        "from trade_py.compat.runtime_contracts import map_shutdown\n",
    )
    _write(repo, "trade_py/compat/runtime_contracts.py", "def map_shutdown():\n    return None\n")

    assert RUNTIME_ADOPTION_FENCE in _rule_ids(repo)


def test_legacy_baseline_facade_merges_target_findings(tmp_path: Path) -> None:
    repo = _target_repo(tmp_path)
    _write(repo, "src/trade/kernel/refs.py")

    report = validate_architecture_baseline(repo)

    assert KERNEL_MODULE_ALLOWLIST in {finding.rule_id for finding in report.findings}
