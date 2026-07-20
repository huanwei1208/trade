from __future__ import annotations

import builtins
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict, cast, get_type_hints

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


class CliProbePayload(TypedDict):
    code: int
    loaded: list[str]
    stdout: str
    stderr: str


_CLI_PROBE = r"""
import contextlib
import io
import json
import sys

from trade_py.cli.main import main

stdout = io.StringIO()
stderr = io.StringIO()
with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
    try:
        code = main(sys.argv[1:])
    except SystemExit as exc:
        code = exc.code

print(json.dumps({
    "code": code,
    "loaded": sorted(name for name in sys.modules if name.startswith("trade_py") or name == "pandas"),
    "stdout": stdout.getvalue(),
    "stderr": stderr.getvalue(),
}))
"""


def _probe_cli(*argv: str) -> CliProbePayload:
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(REPO_ROOT) if not pythonpath else f"{REPO_ROOT}{os.pathsep}{pythonpath}"
    result = subprocess.run(
        [sys.executable, "-c", _CLI_PROBE, *argv],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return cast(CliProbePayload, json.loads(result.stdout))


def test_root_help_does_not_import_command_domains() -> None:
    payload = _probe_cli("--help")

    assert payload["code"] == 0
    assert not any(name.startswith("trade_py.cli.data") for name in payload["loaded"])
    assert not any(name.startswith("trade_py.cli.run") for name in payload["loaded"])
    assert "trade_py.db.trade_db" not in payload["loaded"]
    assert "pandas" not in payload["loaded"]


def test_data_help_imports_only_selected_domain() -> None:
    payload = _probe_cli("data", "--help")

    assert payload["code"] == 0
    assert "trade_py.cli.data" in payload["loaded"]
    assert "trade_py.cli.run" not in payload["loaded"]
    assert "trade_py.evaluation.service" not in payload["loaded"]
    assert "trade_py.jobs" not in payload["loaded"]
    assert "pandas" not in payload["loaded"]


def test_quality_plan_does_not_import_settings_or_db() -> None:
    payload = _probe_cli("dev", "check", "--show-plan", "--path", "does-not-exist")

    assert payload["code"] == 0
    assert "trade_py.cli.dev" in payload["loaded"]
    assert "trade_py.infra.settings" not in payload["loaded"]
    assert "trade_py.db.trade_db" not in payload["loaded"]
    assert "pandas" not in payload["loaded"]


def test_runtime_help_does_not_load_db_jobs_or_write_requested_root(tmp_path: Path) -> None:
    data_root = tmp_path / "runtime-data"

    run_payload = _probe_cli("run", "--help", "--data-root", str(data_root))
    eval_payload = _probe_cli(
        "research",
        "evaluate",
        "--help",
        "--data-root",
        str(data_root),
    )

    assert run_payload["code"] == 0
    assert "trade_py.cli.run" in run_payload["loaded"]
    assert "trade_py.db.trade_db" not in run_payload["loaded"]
    assert "trade_py.jobs" not in run_payload["loaded"]
    assert "trade_py.bus" not in run_payload["loaded"]

    assert eval_payload["code"] == 0
    assert "trade_py.cli.evaluate" in eval_payload["loaded"]
    assert "trade_py.evaluation.service" not in eval_payload["loaded"]
    assert "trade_py.db.trade_db" not in eval_payload["loaded"]
    assert not data_root.exists()


def test_root_dispatch_imports_only_selected_module(monkeypatch: pytest.MonkeyPatch) -> None:
    from trade_py.cli import main as main_cli

    imported: list[str] = []
    received: list[list[str]] = []

    def fake_import(name: str):
        imported.append(name)
        return SimpleNamespace(main=lambda argv: received.append(argv) or 17)

    monkeypatch.setattr(main_cli, "_import_domain", fake_import)

    assert main_cli.main(["data", "kline", "status"]) == 17
    assert imported == ["data"]
    assert received == [["kline", "status"]]


@pytest.mark.parametrize("group", ["model", "factor", "evaluate"])
def test_research_route_is_canonical_but_legacy_route_warns(
    group: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from trade_py.cli import evaluate, factor, model, research

    modules = {"model": model, "factor": factor, "evaluate": evaluate}

    with pytest.raises(SystemExit) as canonical_exit:
        research.main([group, "--help"])
    canonical = capsys.readouterr()

    assert canonical_exit.value.code == 0
    assert f"usage: trade research {group}" in canonical.out
    assert "DeprecationWarning" not in canonical.err

    with pytest.raises(SystemExit) as legacy_exit:
        modules[group].main(["--help"])
    legacy = capsys.readouterr()

    assert legacy_exit.value.code == 0
    assert f"usage: trade {group}" in legacy.out
    assert "DeprecationWarning" in legacy.err


def test_runtime_type_hints_resolve_after_lazy_imports() -> None:
    from trade_py.cli import evaluate, kg

    assert get_type_hints(evaluate._render_source)["outcome"] is not None
    assert get_type_hints(kg._candidate_rows_for_review)["db"] is not None


def test_kline_settings_import_failure_is_not_silently_downgraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from trade_py.cli import data

    real_import = builtins.__import__

    def fail_settings_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "trade_py.db.settings_db":
            raise ModuleNotFoundError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fail_settings_import)

    with pytest.raises(ModuleNotFoundError):
        data._resolve_kline_start("unused", None)


def test_main_module_supports_direct_help_execution() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "trade_py" / "cli" / "main.py"), "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert "usage: trade" in result.stdout
