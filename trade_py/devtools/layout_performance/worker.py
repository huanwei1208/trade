"""Single-process package-layout performance probes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

Probe = Callable[[], object]
_REPO_ROOT = Path(__file__).resolve().parents[3]
_LAST_COMMAND_MODULE_IDENTITY: tuple[int, str] | None = None


def _root_help() -> int:
    return _command_probe(
        (str(_REPO_ROOT / "trade"), "help"),
        _REPO_ROOT,
    )


def _console_help() -> int:
    executable = Path(sys.executable).with_name("trade-py")
    if not executable.is_file():
        raise RuntimeError("installed trade-py console is unavailable")
    return _command_probe(
        (str(executable), "--help"),
        _REPO_ROOT,
    )


def _domain_help() -> int:
    from trade_py.cli.main import main

    try:
        return main(["research", "--help"])
    except SystemExit as exc:
        if not isinstance(exc.code, int):
            raise RuntimeError("domain help returned a non-integer exit") from exc
        return exc.code


def _import_trade() -> object:
    import trade

    return trade


def _import_trade_web() -> object:
    import trade_web

    return trade_web


def _factory_construct() -> object:
    from trade_web.backend.app import create_app

    return create_app()


_PROBES: dict[str, Probe] = {
    "console_help": _console_help,
    "domain_help": _domain_help,
    "factory_construct": _factory_construct,
    "import_trade": _import_trade,
    "import_trade_web": _import_trade_web,
    "root_help": _root_help,
}


def _module_identity() -> tuple[int, str]:
    names = tuple(sorted(sys.modules))
    payload = "\n".join(names).encode("utf-8")
    return len(names), f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _rss_bytes() -> int:
    proc_peak = _linux_peak_rss()
    own = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    children = int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
    if proc_peak is not None:
        multiplier = 1 if own >= proc_peak // 4 else 1024
        own_bytes = max(proc_peak, own * multiplier)
        children_bytes = children * multiplier
    elif sys.platform == "darwin":
        own_bytes = own
        children_bytes = children
    else:
        own_bytes = own * 1024
        children_bytes = children * 1024
    return max(own_bytes, children_bytes)


def _linux_peak_rss() -> int | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        rows = Path("/proc/self/status").read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError):
        return None
    for row in rows:
        if not row.startswith("VmHWM:"):
            continue
        fields = row.split()
        if len(fields) == 3 and fields[2] == "kB" and fields[1].isdigit():
            return int(fields[1]) * 1024
    return None


def run_probe(name: str, samples: int, warmups: int) -> dict[str, object]:
    global _LAST_COMMAND_MODULE_IDENTITY
    _LAST_COMMAND_MODULE_IDENTITY = None
    probe = _PROBES[name]
    sys.stdout.flush()
    sys.stderr.flush()
    old_stdout = os.dup(1)
    old_stderr = os.dup(2)
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        for _index in range(warmups):
            probe()
        durations: list[float] = []
        for _index in range(samples):
            started = time.monotonic_ns()
            probe()
            durations.append((time.monotonic_ns() - started) / 1_000_000)
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os.dup2(old_stdout, 1)
        os.dup2(old_stderr, 2)
        os.close(old_stdout)
        os.close(old_stderr)
        os.close(devnull)
    module_count, module_digest = _LAST_COMMAND_MODULE_IDENTITY or _module_identity()
    return {
        "durations_ms": durations,
        "peak_rss_bytes": _rss_bytes(),
        "module_count": module_count,
        "module_digest": module_digest,
    }


def run_index(repo_root: Path, roots: tuple[str, ...]) -> dict[str, object]:
    from trade_py.devtools.layout.tree_index import TreeIndexLimits, scan_repository

    started = time.monotonic_ns()
    index = scan_repository(
        repo_root,
        included_roots=roots,
        rules_digest="sha256:" + "1" * 64,
        limits=TreeIndexLimits(max_source_bytes=64 * 1024 * 1024),
    )
    return {
        "source_count": len(index.entries),
        "source_bytes": index.source_bytes,
        "duration_ms": (time.monotonic_ns() - started) / 1_000_000,
        "peak_rss_bytes": _rss_bytes(),
        "scan_count": 1,
    }


def _command_probe(argv: tuple[str, ...], cwd: Path) -> int:
    global _LAST_COMMAND_MODULE_IDENTITY
    with tempfile.TemporaryDirectory(prefix="trade-layout-module-report-") as temporary:
        probe_root = Path(temporary)
        report_path = probe_root / "modules.json"
        (probe_root / "sitecustomize.py").write_text(
            _module_report_sitecustomize(),
            encoding="utf-8",
        )
        process = subprocess.run(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
            env={
                **os.environ,
                "PIP_NO_INDEX": "1",
                "PYTHONPATH": str(probe_root),
                "PYTHONDONTWRITEBYTECODE": "1",
                "TRADE_LAYOUT_MODULE_REPORT": str(report_path),
                "UV_FROZEN": "1",
                "UV_NO_SYNC": "1",
                "UV_OFFLINE": "1",
            },
        )
        if process.returncode == 0:
            _LAST_COMMAND_MODULE_IDENTITY = _read_module_report(report_path)
    if process.returncode != 0:
        raise RuntimeError(f"probe command exited {process.returncode}")
    return process.returncode


def _module_report_sitecustomize() -> str:
    return (
        "import atexit,hashlib,json,os,sys\n"
        "def _trade_layout_module_report():\n"
        "    target=os.environ.get('TRADE_LAYOUT_MODULE_REPORT')\n"
        "    if not target:return\n"
        "    names=tuple(sorted(sys.modules))\n"
        "    digest=hashlib.sha256('\\n'.join(names).encode('utf-8')).hexdigest()\n"
        "    with open(target,'w',encoding='utf-8') as stream:\n"
        "        json.dump({'module_count':len(names),"
        "'module_digest':'sha256:'+digest},stream,sort_keys=True,separators=(',',':'))\n"
        "atexit.register(_trade_layout_module_report)\n"
    )


def _read_module_report(path: Path) -> tuple[int, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("measured CLI did not produce a module report") from exc
    if not isinstance(payload, dict) or set(payload) != {"module_count", "module_digest"}:
        raise RuntimeError("measured CLI module report fields differ")
    count = payload.get("module_count")
    digest = payload.get("module_digest")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise RuntimeError("measured CLI module count is invalid")
    if (
        not isinstance(digest, str)
        or len(digest) != 71
        or not digest.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in digest[7:])
    ):
        raise RuntimeError("measured CLI module digest is invalid")
    return count, digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trade-layout-performance-worker")
    subparsers = parser.add_subparsers(dest="command", required=True)
    probe_parser = subparsers.add_parser("probe")
    probe_parser.add_argument("--probe", choices=tuple(sorted(_PROBES)), required=True)
    probe_parser.add_argument("--samples", type=int, required=True)
    probe_parser.add_argument("--warmups", type=int, required=True)
    index_parser = subparsers.add_parser("index")
    index_parser.add_argument("--repo-root", type=Path, required=True)
    index_parser.add_argument("--root", action="append", required=True)
    args = parser.parse_args(argv)
    if args.command == "index":
        print(
            json.dumps(
                run_index(args.repo_root, tuple(args.root)),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    if args.samples < 1 or args.warmups < 0:
        parser.error("samples must be positive and warmups non-negative")
    payload = run_probe(args.probe, args.samples, args.warmups)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
