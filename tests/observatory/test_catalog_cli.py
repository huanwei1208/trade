"""WP1.4 observatory catalog CLI tests.

Also covers RA.1 (docs/27 Phase A): the real `./trade observatory` wrapper
dispatch, the read-only Catalog capability classifier, and the strict
deployment-gate mode for `status`/`verify`.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from trade_py.cli import observatory as observatory_cli
from trade_py.observatory.catalog import store
from tests.observatory.fixtures import build_observatory_fixture, build_legacy_run

REPO_ROOT = Path(__file__).resolve().parents[2]
TRADE_WRAPPER = REPO_ROOT / "trade"


def _run_trade(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    """Invoke the REAL ./trade wrapper (plan §5: not trade_py.cli.*.main directly)."""

    return subprocess.run(
        [str(TRADE_WRAPPER), *args],
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        timeout=timeout,
    )


@pytest.fixture()
def data_root(tmp_path):
    return str(build_observatory_fixture(tmp_path / "data")["data_root"])


def test_cli_rebuild_then_status(data_root, capsys):
    rc = observatory_cli.main(["catalog", "rebuild", "--data-root", data_root, "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["committed"] is True
    assert out["run_count"] >= 5

    rc = observatory_cli.main(["catalog", "status", "--data-root", data_root, "--json"])
    assert rc == 0
    status = json.loads(capsys.readouterr().out)
    assert status["db_exists"] is True
    assert status["verify"]["status"] == "current"


def test_cli_dry_run_does_not_commit(data_root, capsys):
    rc = observatory_cli.main(["catalog", "rebuild", "--data-root", data_root, "--dry-run", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert store.load_generation(data_root) is None


def test_cli_update_reports_stale_after_new_run(data_root, capsys):
    observatory_cli.main(["catalog", "rebuild", "--data-root", data_root, "--json"])
    capsys.readouterr()
    build_legacy_run(__import__("pathlib").Path(data_root), run_id="legacy_run_5555555555555555")
    rc = observatory_cli.main(["catalog", "verify", "--data-root", data_root, "--json"])
    assert rc == 0
    verify = json.loads(capsys.readouterr().out)
    assert verify["status"] == "stale"

    observatory_cli.main(["catalog", "update", "--data-root", data_root, "--json"])
    update = json.loads(capsys.readouterr().out)
    assert update["changed"] is True


def test_cli_no_args_prints_help_and_returns_2():
    rc = observatory_cli.main([])
    assert rc == 2


# ── RA.1: real ./trade wrapper dispatch (docs/27 Phase A, F10) ────────────────


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv required for ./trade wrapper")
def test_real_trade_wrapper_reaches_observatory_catalog_status(data_root):
    """`./trade observatory catalog status --json` reaches the Observatory parser.

    Baseline (F10): the bash wrapper printed "未知命令 'observatory'" and never
    dispatched. The real wrapper must now route into the catalog parser.
    """

    proc = _run_trade("observatory", "catalog", "status", "--data-root", data_root, "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["action"] == "status"
    assert "verify" in payload


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv required for ./trade wrapper")
def test_real_trade_wrapper_rejects_unknown_group_without_falling_through(data_root):
    """An unknown observatory group is a clean parser error, not a bash fallthrough."""

    proc = _run_trade("observatory", "bogus-group", "--data-root", data_root)
    assert proc.returncode != 0
    # The Observatory parser (not the bash "未知命令" path) handled it.
    assert "未知命令" not in proc.stdout
    assert "未知命令" not in proc.stderr


# ── RA.1: read-only Catalog capability classifier (does not build) ────────────


def test_capability_ready_after_rebuild(data_root):
    store.rebuild(data_root)
    cap = store.capability(data_root)
    assert cap["state"] == "ready"
    assert cap["db_exists"] is True


def test_capability_catalog_missing_before_build(data_root):
    cap = store.capability(data_root)
    assert cap["state"] == "catalog_missing"
    # Inspecting capability must NOT build the projection (read-only).
    assert store.load_generation(data_root) is None


def test_capability_catalog_stale_after_new_immutable_facts(data_root):
    store.rebuild(data_root)
    build_legacy_run(Path(data_root), run_id="legacy_run_7777777777777777")
    cap = store.capability(data_root)
    assert cap["state"] == "catalog_stale"
    # Still read-only: the stored generation is untouched by a capability probe.
    assert store.load_generation(data_root) is not None


def test_capability_catalog_corrupt_on_bad_sqlite(data_root):
    store.rebuild(data_root)
    db_path = Path(data_root) / "market" / "crypto" / "observatory" / "catalog.sqlite"
    db_path.write_bytes(b"not a sqlite database")
    cap = store.capability(data_root)
    assert cap["state"] == "catalog_corrupt"


# ── RA.1: strict deployment gate for status/verify ───────────────────────────


def test_strict_status_returns_nonzero_when_not_ready(data_root, capsys):
    # No catalog built yet -> strict status must fail closed (non-zero).
    rc = observatory_cli.main(["catalog", "status", "--data-root", data_root, "--strict", "--json"])
    capsys.readouterr()
    assert rc != 0


def test_strict_status_returns_zero_when_ready(data_root, capsys):
    observatory_cli.main(["catalog", "rebuild", "--data-root", data_root, "--json"])
    capsys.readouterr()
    rc = observatory_cli.main(["catalog", "status", "--data-root", data_root, "--strict", "--json"])
    capsys.readouterr()
    assert rc == 0


def test_nonstrict_status_stays_zero_when_not_ready(data_root, capsys):
    # Human/informational mode retains a non-strict zero exit for compatibility.
    rc = observatory_cli.main(["catalog", "status", "--data-root", data_root, "--json"])
    capsys.readouterr()
    assert rc == 0


def test_strict_verify_returns_nonzero_when_stale(data_root, capsys):
    observatory_cli.main(["catalog", "rebuild", "--data-root", data_root, "--json"])
    capsys.readouterr()
    build_legacy_run(Path(data_root), run_id="legacy_run_8888888888888888")
    rc = observatory_cli.main(["catalog", "verify", "--data-root", data_root, "--strict", "--json"])
    capsys.readouterr()
    assert rc != 0


# ── RA.1: fail-closed capability classifier (pointer + SQLite meta) ───────────


def _observatory_paths(data_root: str):
    base = Path(data_root) / "market" / "crypto" / "observatory"
    return base / "catalog.sqlite", base / "generation.json"


def test_read_generation_classifies_absent(data_root):
    status, payload = store.read_generation(data_root)
    assert status == "absent"
    assert payload is None


def test_capability_corrupt_on_malformed_pointer_with_db(data_root):
    """A DB with a non-JSON pointer is corrupt, never `catalog_missing`."""

    store.rebuild(data_root)
    _, gen_path = _observatory_paths(data_root)
    gen_path.write_text("this is not json", encoding="utf-8")
    status, _ = store.read_generation(data_root)
    assert status == "malformed"
    cap = store.capability(data_root)
    assert cap["state"] == "catalog_corrupt"


def test_capability_corrupt_on_wrong_type_pointer(data_root):
    """A JSON scalar/array pointer (wrong top-level type) is corrupt, not missing."""

    store.rebuild(data_root)
    _, gen_path = _observatory_paths(data_root)
    gen_path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    status, _ = store.read_generation(data_root)
    assert status == "malformed"
    # load_generation() stays traceback-free for the non-dict pointer.
    assert store.load_generation(data_root) is None
    assert store.capability(data_root)["state"] == "catalog_corrupt"


def test_capability_corrupt_on_wrong_field_type_pointer(data_root):
    """A pointer whose generation_id is the wrong type is corrupt, not incomplete."""

    store.rebuild(data_root)
    _, gen_path = _observatory_paths(data_root)
    stored = json.loads(gen_path.read_text(encoding="utf-8"))
    stored["generation_id"] = 12345  # wrong type (should be a non-empty string)
    gen_path.write_text(json.dumps(stored), encoding="utf-8")
    status, _ = store.read_generation(data_root)
    assert status == "malformed"
    assert store.capability(data_root)["state"] == "catalog_corrupt"


def test_capability_corrupt_on_incomplete_pointer(data_root):
    """A well-formed object missing required identity fields is corrupt."""

    store.rebuild(data_root)
    _, gen_path = _observatory_paths(data_root)
    stored = json.loads(gen_path.read_text(encoding="utf-8"))
    stored.pop("content_hash")
    gen_path.write_text(json.dumps(stored), encoding="utf-8")
    status, _ = store.read_generation(data_root)
    assert status == "incomplete"
    assert store.capability(data_root)["state"] == "catalog_corrupt"


def test_capability_corrupt_on_pointer_without_db(data_root):
    """A committed pointer whose SQLite projection is gone is corrupt, not missing."""

    store.rebuild(data_root)
    db_path, _ = _observatory_paths(data_root)
    db_path.unlink()
    cap = store.capability(data_root)
    assert cap["state"] == "catalog_corrupt"
    assert cap["db_exists"] is False


def test_capability_corrupt_on_sqlite_generation_id_mismatch(data_root):
    """F6: a DB whose catalog_meta.generation_id disagrees with the pointer must be
    corrupt, never `ready` — the read side cannot trust a DB the pointer disowns."""

    import sqlite3

    store.rebuild(data_root)
    db_path, _ = _observatory_paths(data_root)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE catalog_meta SET value = ? WHERE key = 'generation_id'",
            ("deadbeefdeadbeefdeadbeef",),
        )
        conn.commit()
    finally:
        conn.close()
    cap = store.capability(data_root)
    assert cap["state"] == "catalog_corrupt"
    assert cap.get("meta_mismatch") == "generation_id"


def test_capability_corrupt_on_sqlite_content_hash_mismatch(data_root):
    """A DB whose catalog_meta.content_hash drifts from the pointer is corrupt."""

    import sqlite3

    store.rebuild(data_root)
    db_path, _ = _observatory_paths(data_root)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("UPDATE catalog_meta SET value = ? WHERE key = 'content_hash'", ("0" * 64,))
        conn.commit()
    finally:
        conn.close()
    assert store.capability(data_root)["state"] == "catalog_corrupt"


def test_capability_corrupt_on_missing_required_table(data_root):
    """A SQLite file missing a required projection table fails the integrity probe."""

    import sqlite3

    store.rebuild(data_root)
    db_path, _ = _observatory_paths(data_root)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DROP TABLE releases")
        conn.commit()
    finally:
        conn.close()
    assert store.capability(data_root)["state"] == "catalog_corrupt"


# ── RA.1: strict deployment gate emits structured JSON + exit code matrix ─────


def test_strict_status_emits_structured_json_gate(data_root, capsys):
    """Strict mode always emits machine-readable JSON (even without --json)."""

    store.rebuild(data_root)
    rc = observatory_cli.main(["catalog", "status", "--data-root", data_root, "--strict"])
    gate = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert gate["strict"] is True
    assert gate["ready"] is True
    assert gate["capability_state"] == "ready"


def test_strict_status_exit3_on_corrupt(data_root, capsys):
    store.rebuild(data_root)
    db_path, _ = _observatory_paths(data_root)
    db_path.write_bytes(b"not a sqlite database")
    rc = observatory_cli.main(["catalog", "status", "--data-root", data_root, "--strict"])
    gate = json.loads(capsys.readouterr().out)
    assert rc == 3
    assert gate["capability_state"] == "catalog_corrupt"
    assert gate["ready"] is False


def test_strict_verify_exit3_on_malformed_pointer_does_not_traceback(data_root, capsys):
    store.rebuild(data_root)
    _, gen_path = _observatory_paths(data_root)
    gen_path.write_text("{ broken", encoding="utf-8")
    rc = observatory_cli.main(["catalog", "verify", "--data-root", data_root, "--strict"])
    gate = json.loads(capsys.readouterr().out)
    assert rc == 3
    assert gate["capability_state"] == "catalog_corrupt"


# ── RA.1: real ./trade subprocess status/verify matrix (F10 + F6/F14) ─────────


def _setup_missing(data_root: str) -> None:
    """No catalog built -> capability `catalog_missing` (db absent)."""


def _setup_ready(data_root: str) -> None:
    store.rebuild(data_root)


def _setup_stale(data_root: str) -> None:
    store.rebuild(data_root)
    # A new immutable run moves the live fingerprint ahead of the projection.
    build_legacy_run(Path(data_root), run_id="legacy_run_9999999999999999")


def _setup_corrupt(data_root: str) -> None:
    """F6: tamper the materialized SQLite generation_id so it disagrees with the
    pointer. The read side must fail closed (corrupt), never falsely `ready`."""

    import sqlite3

    store.rebuild(data_root)
    db_path = Path(data_root) / "market" / "crypto" / "observatory" / "catalog.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("UPDATE catalog_meta SET value = 'tampered_gen_id' WHERE key = 'generation_id'")
        conn.commit()
    finally:
        conn.close()


# (state id, setup, capability_state, canonical status, exit code, db_exists)
_STRICT_STATE_MATRIX = [
    ("missing", _setup_missing, "catalog_missing", "missing", 3, False),
    ("stale", _setup_stale, "catalog_stale", "stale", 3, True),
    ("corrupt", _setup_corrupt, "catalog_corrupt", "corrupt", 3, True),
    ("ready", _setup_ready, "ready", "current", 0, True),
]


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv required for ./trade wrapper")
@pytest.mark.parametrize("action", ["status", "verify"])
@pytest.mark.parametrize(
    ("state_id", "setup", "capability_state", "canonical_status", "exit_code", "db_exists"),
    _STRICT_STATE_MATRIX,
    ids=[row[0] for row in _STRICT_STATE_MATRIX],
)
def test_real_trade_strict_matrix(
    data_root, action, state_id, setup, capability_state, canonical_status, exit_code, db_exists
):
    """Real ./trade `catalog {status,verify} --strict` across all four states.

    For BOTH actions this asserts the exact exit code (0 only for ready, 3 for
    missing/stale/corrupt), a JSON stdout, the canonical capability_state/status
    pair, the correct db_exists, and no traceback. There is NO nested detail field
    that could contradict the canonical top-level status."""

    setup(data_root)
    proc = _run_trade("observatory", "catalog", action, "--data-root", data_root, "--strict")
    assert proc.returncode == exit_code, proc.stderr
    assert "Traceback" not in proc.stderr
    gate = json.loads(proc.stdout)
    assert gate["action"] == action
    assert gate["strict"] is True
    assert gate["capability_state"] == capability_state
    assert gate["status"] == canonical_status
    assert gate["ready"] is (exit_code == 0)
    assert gate["db_exists"] is db_exists
    # The canonical contract must not smuggle a nested raw status/verify field.
    assert "detail" not in gate
    assert "verify" not in gate


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv required for ./trade wrapper")
@pytest.mark.parametrize("action", ["status", "verify"])
def test_real_trade_strict_malformed_pointer_exit3(data_root, action):
    """`./trade observatory catalog {status,verify} --strict` fails closed (exit 3)
    on a malformed/wrong-type pointer and never tracebacks."""

    store.rebuild(data_root)
    gen_path = Path(data_root) / "market" / "crypto" / "observatory" / "generation.json"
    gen_path.write_text(json.dumps(42), encoding="utf-8")  # wrong top-level type
    proc = _run_trade("observatory", "catalog", action, "--data-root", data_root, "--strict")
    assert proc.returncode == 3, proc.stderr
    assert "Traceback" not in proc.stderr
    gate = json.loads(proc.stdout)
    assert gate["capability_state"] == "catalog_corrupt"
    assert gate["status"] == "corrupt"
    assert gate["ready"] is False
