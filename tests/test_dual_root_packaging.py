from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import TypedDict

REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_INFO_FILES = frozenset({"METADATA", "RECORD", "WHEEL", "entry_points.txt", "top_level.txt"})
MAX_DIST_INFO_MEMBER_BYTES = 65_536
MAX_DIST_INFO_BYTES = 262_144
MAX_WHEEL_OVERHEAD_BYTES = 524_288


@dataclass(frozen=True)
class SourceMember:
    source: Path
    relative_source: Path


@dataclass(frozen=True)
class WheelEvidence:
    wheel_name: str
    wheel_sha256: str
    member_count: int
    python_member_count: int
    source_python_bytes: int
    dist_info_bytes: int
    total_uncompressed_bytes: int
    wheel_bytes: int


class ImportProbe(TypedDict):
    modules: dict[str, str]
    sys_path: list[str]


def _clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "__PYVENV_LAUNCHER__"):
        environment.pop(name, None)
    environment["UV_OFFLINE"] = "1"
    environment["UV_PYTHON_DOWNLOADS"] = "never"
    return environment


def _run(
    argv: list[str],
    *,
    cwd: Path,
    environment: dict[str, str] | None = None,
    timeout: float = 120,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        env=environment or _clean_environment(),
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _has_symlink_component(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return True
    return False


def _source_members(repo_root: Path) -> dict[str, SourceMember]:
    roots = (
        (repo_root / "trade_py", PurePosixPath("trade_py")),
        (repo_root / "scripts", PurePosixPath("scripts")),
        (repo_root / "src" / "trade", PurePosixPath("trade")),
    )
    members: dict[str, SourceMember] = {}
    for source_root, wheel_root in roots:
        assert source_root.is_dir(), f"missing package root: {source_root}"
        assert not source_root.is_symlink(), f"package root cannot be a symlink: {source_root}"
        for source in sorted(source_root.rglob("*.py")):
            assert not _has_symlink_component(source, source_root), (
                f"packaged source cannot traverse a symlink: {source}"
            )
            member = (
                wheel_root / PurePosixPath(source.relative_to(source_root).as_posix())
            ).as_posix()
            assert member not in members, f"duplicate wheel member mapping: {member}"
            members[member] = SourceMember(
                source=source,
                relative_source=source.relative_to(repo_root),
            )
    return members


def _copy_build_input(
    repo_root: Path,
    build_root: Path,
    members: dict[str, SourceMember],
) -> None:
    shutil.copy2(repo_root / "pyproject.toml", build_root / "pyproject.toml")
    for source_member in members.values():
        destination = build_root / source_member.relative_source
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_member.source, destination)


def _normalized_member(name: str) -> str:
    assert "\\" not in name, f"wheel member uses a backslash: {name}"
    member = PurePosixPath(name)
    assert not member.is_absolute(), f"wheel member is absolute: {name}"
    assert all(part not in {"", ".", ".."} for part in member.parts), (
        f"wheel member is not normalized: {name}"
    )
    return member.as_posix()


def _verify_record(archive: zipfile.ZipFile, inventory: set[str], record_name: str) -> None:
    rows = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))))
    assert len(rows) == len(inventory)
    assert {row[0] for row in rows} == inventory
    for name, encoded_digest, encoded_size in rows:
        if name == record_name:
            assert encoded_digest == ""
            assert encoded_size == ""
            continue
        content = archive.read(name)
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        assert encoded_digest == f"sha256={digest}"
        assert encoded_size == str(len(content))


def _inspect_wheel(wheel: Path, members: dict[str, SourceMember]) -> WheelEvidence:
    with zipfile.ZipFile(wheel) as archive:
        infos = archive.infolist()
        names = [_normalized_member(info.filename) for info in infos]
        assert len(names) == len(set(names)), "wheel contains duplicate member names"
        assert all(not info.is_dir() for info in infos), (
            "wheel contains an unexpected directory entry"
        )

        source_names = set(members)
        non_source_names = set(names) - source_names
        dist_info_roots = {name.split("/", 1)[0] for name in non_source_names}
        assert len(dist_info_roots) == 1
        dist_info_root = dist_info_roots.pop()
        assert dist_info_root.startswith("trade_py-")
        assert dist_info_root.endswith(".dist-info")

        expected_dist_info = {f"{dist_info_root}/{basename}" for basename in DIST_INFO_FILES}
        expected_inventory = source_names | expected_dist_info
        assert set(names) == expected_inventory

        source_python_bytes = 0
        for member, source_member in members.items():
            source_bytes = source_member.source.read_bytes()
            assert archive.read(member) == source_bytes, f"source byte mismatch: {member}"
            source_python_bytes += len(source_bytes)

        dist_info_sizes = {name: archive.getinfo(name).file_size for name in expected_dist_info}
        assert all(size <= MAX_DIST_INFO_MEMBER_BYTES for size in dist_info_sizes.values())
        dist_info_bytes = sum(dist_info_sizes.values())
        assert dist_info_bytes <= MAX_DIST_INFO_BYTES

        total_uncompressed_bytes = sum(info.file_size for info in infos)
        assert total_uncompressed_bytes <= source_python_bytes + MAX_DIST_INFO_BYTES
        assert wheel.stat().st_size <= source_python_bytes + MAX_WHEEL_OVERHEAD_BYTES

        metadata = archive.read(f"{dist_info_root}/METADATA").decode("utf-8")
        assert "\nName: trade-py\n" in f"\n{metadata}"
        assert archive.read(f"{dist_info_root}/entry_points.txt").decode("utf-8") == (
            "[console_scripts]\ntrade-py = trade_py.cli.main:main\n"
        )
        assert archive.read(f"{dist_info_root}/top_level.txt").decode("utf-8") == (
            "scripts\ntrade\ntrade_py\n"
        )
        _verify_record(archive, expected_inventory, f"{dist_info_root}/RECORD")

    return WheelEvidence(
        wheel_name=wheel.name,
        wheel_sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),
        member_count=len(names),
        python_member_count=len(members),
        source_python_bytes=source_python_bytes,
        dist_info_bytes=dist_info_bytes,
        total_uncompressed_bytes=total_uncompressed_bytes,
        wheel_bytes=wheel.stat().st_size,
    )


_IMPORT_PROBE = """
import importlib
import json
import sys

payload = {
    "modules": {
        name: str(importlib.import_module(name).__file__)
        for name in sys.argv[1:]
    },
    "sys_path": sys.path,
}
print(json.dumps(payload, sort_keys=True))
"""


def _probe_imports(
    python: Path,
    *,
    cwd: Path,
    modules: tuple[str, ...],
) -> ImportProbe:
    result = _run(
        [str(python), "-c", _IMPORT_PROBE, *modules],
        cwd=cwd,
        environment=_clean_environment(),
    )
    return json.loads(result.stdout)


def _create_venv(uv: str, python: Path, destination: Path) -> Path:
    _run(
        [
            uv,
            "venv",
            "--no-project",
            "--offline",
            "--no-python-downloads",
            "--python",
            str(python),
            str(destination),
        ],
        cwd=destination.parent,
    )
    return destination / "bin" / "python"


def test_dual_root_source_editable_and_wheel_contract(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv is not None, "uv is required for the packaging contract"
    locked_python = Path(sys.executable)
    members = _source_members(REPO_ROOT)
    assert "trade_py/__init__.py" in members
    assert "scripts/__init__.py" in members
    assert "trade/__init__.py" in members

    source_trade_py = _probe_imports(
        locked_python,
        cwd=REPO_ROOT,
        modules=("trade_py",),
    )
    assert Path(source_trade_py["modules"]["trade_py"]).resolve() == (
        REPO_ROOT / "trade_py" / "__init__.py"
    )
    source_trade = _probe_imports(
        locked_python,
        cwd=REPO_ROOT / "src",
        modules=("trade",),
    )
    assert Path(source_trade["modules"]["trade"]).resolve() == REPO_ROOT / "src/trade/__init__.py"

    build_root = tmp_path / "source"
    build_root.mkdir()
    _copy_build_input(REPO_ROOT, build_root, members)

    wheel_dir = tmp_path / "wheel"
    _run(
        [
            uv,
            "build",
            "--wheel",
            "--offline",
            "--no-python-downloads",
            "--no-create-gitignore",
            "--out-dir",
            str(wheel_dir),
            str(build_root),
        ],
        cwd=tmp_path,
    )
    wheels = tuple(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, found: {wheels}"
    wheel = wheels[0]
    evidence = _inspect_wheel(wheel, members)

    editable_python = _create_venv(uv, locked_python, tmp_path / "editable-venv")
    _run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(editable_python),
            "--offline",
            "--no-deps",
            "--no-python-downloads",
            "--editable",
            str(build_root),
        ],
        cwd=tmp_path,
    )
    editable = _probe_imports(
        editable_python,
        cwd=tmp_path,
        modules=("trade_py", "trade"),
    )
    assert Path(editable["modules"]["trade_py"]).resolve() == build_root / "trade_py/__init__.py"
    assert Path(editable["modules"]["trade"]).resolve() == build_root / "src/trade/__init__.py"

    wheel_python = _create_venv(uv, locked_python, tmp_path / "wheel-venv")
    _run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(wheel_python),
            "--offline",
            "--no-index",
            "--no-deps",
            "--no-build",
            "--no-python-downloads",
            str(wheel),
        ],
        cwd=tmp_path,
    )
    installed = _probe_imports(
        wheel_python,
        cwd=tmp_path,
        modules=("trade_py", "trade"),
    )
    for module in ("trade_py", "trade"):
        module_path = Path(installed["modules"][module]).resolve()
        assert module_path.is_relative_to((tmp_path / "wheel-venv").resolve())
        assert not module_path.is_relative_to(REPO_ROOT.resolve())
    installed_sys_path = tuple(Path(entry).resolve() for entry in installed["sys_path"] if entry)
    assert REPO_ROOT.resolve() not in installed_sys_path
    assert build_root.resolve() not in installed_sys_path

    locked_environment = _clean_environment()
    locked_environment["UV_NO_SYNC"] = "1"
    locked_environment["UV_PROJECT_ENVIRONMENT"] = str(locked_python.parent.parent)
    root_help = _run(
        [str(REPO_ROOT / "trade"), "--help"],
        cwd=REPO_ROOT,
        environment=locked_environment,
    )
    assert "trade run" in root_help.stdout
    console_help = _run(
        [str(locked_python.with_name("trade-py")), "--help"],
        cwd=tmp_path,
        environment=locked_environment,
    )
    assert "usage:" in console_help.stdout

    print(json.dumps(asdict(evidence), sort_keys=True))
