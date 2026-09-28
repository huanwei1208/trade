"""Isolated Web build evidence for package-layout validation."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path, PurePosixPath

from trade_py.devtools.layout.tree_index import read_regular_relative
from trade_py.devtools.layout_performance.capacity import ValidationCapacity
from trade_py.devtools.layout_performance.models import WebBuildEvidence
from trade_py.devtools.layout_performance.processes import ProcessOutcome, run_process

WEB_ROOT = "trade_web/frontend"
WEB_BUILD_TIMEOUT_SECONDS = 15 * 60
MAX_TRACKED_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_WEB_SOURCE_FILE_BYTES = 8 * 1024 * 1024
MAX_WEB_OUTPUT_BYTES = 2 * 1024 * 1024 * 1024
MAX_WEB_OUTPUT_FILES = 100_000

ProcessRunner = Callable[..., ProcessOutcome]


def capture_web_build_evidence(
    repo_root: Path,
    *,
    node_modules: Path | None,
    capacity: ValidationCapacity,
    temp_parent: Path | None = None,
    process_runner: ProcessRunner = run_process,
) -> WebBuildEvidence:
    """Build one selected Web root without writing to the checkout."""

    source_root = repo_root.resolve() / WEB_ROOT
    unavailable = _unavailable_reason(source_root, node_modules)
    if unavailable is not None:
        return _unavailable(unavailable)
    assert node_modules is not None
    tracked_files = _tracked_web_files(repo_root.resolve(), process_runner)
    if not tracked_files:
        return _unavailable("tracked_web_source_empty")

    with capacity.admit(
        "heavy",
        timeout_seconds=capacity.queue_deadline_seconds,
        rss_bytes=2 * 1024 * 1024 * 1024,
        temp_bytes=2 * 1024 * 1024 * 1024,
    ):
        temporary = tempfile.TemporaryDirectory(
            prefix="trade-layout-web-",
            dir=temp_parent,
        )
        temporary_path = Path(temporary.name)
        evidence: WebBuildEvidence | None = None
        try:
            work_root = temporary_path / "frontend"
            _copy_tracked_source(repo_root.resolve(), work_root, tracked_files)
            dependency_bytes = _tree_size(node_modules.resolve())
            if dependency_bytes > MAX_WEB_OUTPUT_BYTES:
                return _unavailable("node_modules_exceeds_temp_budget")
            shutil.copytree(
                node_modules.resolve(),
                work_root / "node_modules",
                symlinks=True,
                ignore_dangling_symlinks=True,
            )
            dependency_digest = _dependency_digest(node_modules.resolve())
            toolchain_identity = _toolchain_identity(node_modules.resolve(), process_runner)
            cache_key = _source_cache_key(
                work_root,
                tracked_files,
                dependency_digest=dependency_digest,
                toolchain_identity=toolchain_identity,
            )
            environment = _build_environment(temporary_path)
            cold = _run_build(
                work_root,
                environment,
                process_runner,
            )
            cold_digest = _tree_digest(work_root / "dist")

            key_after_cold = _source_cache_key(
                work_root,
                tracked_files,
                dependency_digest=dependency_digest,
                toolchain_identity=toolchain_identity,
            )
            no_change = _run_build(
                work_root,
                environment,
                process_runner,
            )
            no_change_digest = _tree_digest(work_root / "dist")
            no_change_cache_hit = cache_key == key_after_cold and cold_digest == no_change_digest
            if not no_change_cache_hit or cold_digest != no_change_digest:
                raise RuntimeError("no-change Web cache identity is inconsistent")

            mutation_target = _mutation_target(tracked_files)
            target = work_root / mutation_target
            with target.open("ab") as stream:
                stream.write(_mutation_bytes(mutation_target))
            incremental_key = _source_cache_key(
                work_root,
                tracked_files,
                dependency_digest=dependency_digest,
                toolchain_identity=toolchain_identity,
            )
            incremental = _run_build(
                work_root,
                environment,
                process_runner,
            )
            incremental_digest = _tree_digest(work_root / "dist")
            if incremental_digest == cold_digest:
                raise RuntimeError("source mutation did not change the Web output manifest")

            evidence = WebBuildEvidence(
                available=True,
                root=WEB_ROOT,
                dependency_digest=dependency_digest,
                cache_key=cache_key,
                incremental_cache_key=incremental_key,
                no_change_cache_hit=no_change_cache_hit,
                cache_invalidated=incremental_key != cache_key,
                no_change_ms=no_change.duration_ms,
                cold_build_ms=cold.duration_ms,
                incremental_build_ms=incremental.duration_ms,
                cold_output_digest=cold_digest,
                no_change_output_digest=no_change_digest,
                incremental_output_digest=incremental_digest,
                cleanup_complete=False,
                unavailable_reason=None,
            )
        finally:
            temporary.cleanup()
    assert evidence is not None
    return replace(evidence, cleanup_complete=not temporary_path.exists())


def _unavailable_reason(source_root: Path, node_modules: Path | None) -> str | None:
    if not source_root.is_dir():
        return "web_root_missing"
    if node_modules is None:
        return "node_modules_not_selected"
    dependency_root = node_modules.resolve()
    if not dependency_root.is_dir():
        return "node_modules_missing"
    required = (
        dependency_root / ".bin" / "tsc",
        dependency_root / ".bin" / "vite",
    )
    if any(not item.exists() for item in required):
        return "node_modules_incomplete"
    if shutil.which("node") is None or shutil.which("npm") is None:
        return "node_toolchain_missing"
    return None


def _unavailable(reason: str) -> WebBuildEvidence:
    return WebBuildEvidence(
        available=False,
        root=WEB_ROOT,
        dependency_digest=None,
        cache_key=None,
        incremental_cache_key=None,
        no_change_cache_hit=False,
        cache_invalidated=False,
        no_change_ms=None,
        cold_build_ms=None,
        incremental_build_ms=None,
        cold_output_digest=None,
        no_change_output_digest=None,
        incremental_output_digest=None,
        cleanup_complete=True,
        unavailable_reason=reason,
    )


def _tracked_web_files(repo_root: Path, process_runner: ProcessRunner) -> tuple[str, ...]:
    outcome = process_runner(
        ("git", "ls-files", "-z", "--", WEB_ROOT),
        cwd=repo_root,
        timeout_seconds=10,
        output_limit_bytes=MAX_TRACKED_OUTPUT_BYTES,
    )
    values: list[str] = []
    prefix = f"{WEB_ROOT}/"
    for raw in outcome.stdout.split(b"\0"):
        if not raw:
            continue
        value = raw.decode("utf-8", "strict")
        if not value.startswith(prefix):
            raise RuntimeError(f"Git returned a file outside {WEB_ROOT}: {value}")
        relative = value.removeprefix(prefix)
        path = PurePosixPath(relative)
        if (
            path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or "node_modules" in path.parts
            or "dist" in path.parts
        ):
            raise RuntimeError(f"unsafe tracked Web path: {value}")
        values.append(path.as_posix())
    if len(values) != len(set(values)):
        raise RuntimeError("Git returned duplicate Web paths")
    return tuple(sorted(values))


def _copy_tracked_source(
    repo_root: Path,
    work_root: Path,
    tracked_files: tuple[str, ...],
) -> None:
    source_root = repo_root / WEB_ROOT
    for relative in tracked_files:
        content = read_regular_relative(
            source_root,
            relative,
            max_bytes=MAX_WEB_SOURCE_FILE_BYTES,
        )
        target = work_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        source_mode = (source_root / relative).stat(follow_symlinks=False).st_mode
        if source_mode & stat.S_IXUSR:
            target.chmod(target.stat().st_mode | stat.S_IXUSR)


def _run_build(
    work_root: Path,
    environment: dict[str, str],
    process_runner: ProcessRunner,
) -> ProcessOutcome:
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError("npm became unavailable during Web validation")
    outcome = process_runner(
        (npm, "run", "build"),
        cwd=work_root,
        timeout_seconds=WEB_BUILD_TIMEOUT_SECONDS,
        output_limit_bytes=4 * 1024 * 1024,
        env=environment,
        rss_limit_bytes=2 * 1024 * 1024 * 1024,
        temp_limit_bytes=MAX_WEB_OUTPUT_BYTES,
        temp_root=work_root / "dist",
    )
    if outcome.timed_out:
        raise RuntimeError(f"Web build exceeded {WEB_BUILD_TIMEOUT_SECONDS} seconds")
    if outcome.cleanup_survivors:
        raise RuntimeError("Web build left residual processes")
    return outcome


def _build_environment(temporary_path: Path) -> dict[str, str]:
    home = temporary_path / "home"
    cache = temporary_path / "npm-cache"
    home.mkdir()
    cache.mkdir()
    return {
        **os.environ,
        "CI": "1",
        "HOME": str(home),
        "NPM_CONFIG_AUDIT": "false",
        "NPM_CONFIG_CACHE": str(cache),
        "NPM_CONFIG_FUND": "false",
        "NPM_CONFIG_OFFLINE": "true",
        "NO_UPDATE_NOTIFIER": "1",
    }


def _source_cache_key(
    work_root: Path,
    tracked_files: tuple[str, ...],
    *,
    dependency_digest: str,
    toolchain_identity: tuple[str, str, str],
) -> str:
    digest = hashlib.sha256()
    digest.update(f"root:{WEB_ROOT}\n".encode())
    digest.update(f"lock:{dependency_digest}\n".encode())
    for name, version in zip(("node", "npm", "vite"), toolchain_identity, strict=True):
        digest.update(f"{name}:{version}\n".encode())
    for relative in tracked_files:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update((work_root / relative).read_bytes())
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _toolchain_identity(
    dependency_root: Path,
    process_runner: ProcessRunner,
) -> tuple[str, str, str]:
    node = shutil.which("node")
    npm = shutil.which("npm")
    vite = dependency_root / ".bin" / "vite"
    if node is None or npm is None or not vite.is_file():
        raise RuntimeError("selected Web toolchain is incomplete")
    return (
        _version((node, "--version"), process_runner),
        _version((npm, "--version"), process_runner),
        _version((str(vite), "--version"), process_runner),
    )


def _version(argv: tuple[str, ...], process_runner: ProcessRunner) -> str:
    outcome = process_runner(
        argv,
        cwd=Path.cwd(),
        timeout_seconds=10,
        output_limit_bytes=4096,
    )
    value = outcome.stdout.decode("utf-8", "strict").strip()
    if not value or len(value) > 128:
        raise RuntimeError(f"{Path(argv[0]).name} returned an invalid version")
    return value


def _mutation_target(tracked_files: tuple[str, ...]) -> str:
    if "index.html" in tracked_files:
        return "index.html"
    candidates = tuple(
        item
        for item in tracked_files
        if item.startswith("src/")
        and item.endswith((".js", ".jsx", ".ts", ".tsx"))
        and not item.endswith(".d.ts")
        and "/test/" not in item
        and ".test." not in item
    )
    if not candidates:
        raise RuntimeError("Web source has no cache-invalidation target")
    return candidates[0]


def _mutation_bytes(relative: str) -> bytes:
    if relative.endswith(".html"):
        return b"\n<!-- trade-layout-cache-invalidation-probe -->\n"
    return b'\nconsole.info("trade-layout-cache-invalidation-probe");\n'


def _tree_size(root: Path) -> int:
    total = 0
    count = 0
    for parent, directories, files in os.walk(root, followlinks=False):
        directories.sort()
        files.sort()
        for name in files:
            count += 1
            if count > MAX_WEB_OUTPUT_FILES:
                raise RuntimeError("Web dependency tree exceeds its file-count budget")
            path = Path(parent) / name
            if path.is_symlink():
                continue
            metadata = path.stat(follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError(f"Web dependency entry is not regular: {path.name}")
            total += metadata.st_size
            if total > MAX_WEB_OUTPUT_BYTES:
                return total
    return total


def _dependency_digest(root: Path) -> str:
    lock = root / ".package-lock.json"
    if not lock.is_file():
        raise RuntimeError("selected node_modules has no .package-lock.json")
    return f"sha256:{hashlib.sha256(lock.read_bytes()).hexdigest()}"


def _tree_digest(root: Path) -> str:
    if not root.is_dir():
        raise RuntimeError("Web build did not produce dist/")
    digest = hashlib.sha256()
    total = 0
    count = 0
    for parent, directories, files in os.walk(root, followlinks=False):
        directories.sort()
        files.sort()
        for name in files:
            count += 1
            if count > MAX_WEB_OUTPUT_FILES:
                raise RuntimeError("Web output exceeds its file-count budget")
            path = Path(parent) / name
            metadata = path.stat(follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError(f"Web output entry is not regular: {path.name}")
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_WEB_OUTPUT_BYTES:
                        raise RuntimeError("Web output exceeds its byte budget")
                    digest.update(chunk)
            digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


__all__ = [
    "WEB_BUILD_TIMEOUT_SECONDS",
    "WEB_ROOT",
    "capture_web_build_evidence",
]
