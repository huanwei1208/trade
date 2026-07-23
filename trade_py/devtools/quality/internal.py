"""Read-only checks implemented with the Python standard library."""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tokenize
from pathlib import Path

from trade_py.devtools.quality.toml_compat import tomllib


def _paths(values: list[str]) -> list[str]:
    return values[1:] if values and values[0] == "--" else values


def _python_syntax(paths: list[str]) -> int:
    failed = False
    for raw in paths:
        path = Path(raw)
        try:
            source = path.read_bytes()
            compile(source, str(path), "exec", dont_inherit=True)
        except (OSError, SyntaxError, ValueError) as exc:
            failed = True
            print(f"{raw}: {exc}", file=sys.stderr)
    return int(failed)


def _config_parse(paths: list[str]) -> int:
    failed = False
    for raw in paths:
        path = Path(raw)
        try:
            if path.suffix.lower() == ".json":
                json.loads(path.read_text(encoding="utf-8"))
            elif path.suffix.lower() == ".toml" or path.name == "uv.lock":
                with path.open("rb") as handle:
                    tomllib.load(handle)
        except (OSError, UnicodeError, ValueError) as exc:
            failed = True
            print(f"{raw}: {exc}", file=sys.stderr)
    return int(failed)


def _text_hygiene(paths: list[str]) -> int:
    failed = False
    for raw in paths:
        path = Path(raw)
        try:
            data = path.read_bytes()
        except OSError as exc:
            failed = True
            print(f"{raw}: {exc}", file=sys.stderr)
            continue
        if b"\0" in data:
            failed = True
            print(f"{raw}: NUL byte in owned text source", file=sys.stderr)
            continue
        if data and not data.endswith(b"\n"):
            failed = True
            print(f"{raw}: missing final newline", file=sys.stderr)
        for line_number, line in enumerate(data.splitlines(), 1):
            if line.endswith((b" ", b"\t")):
                failed = True
                print(f"{raw}:{line_number}: trailing whitespace", file=sys.stderr)
    return int(failed)


_PYTHON_SUPPRESSIONS = (
    (re.compile(r"#\s*ruff:\s*noqa\b", re.IGNORECASE), "file-wide Ruff noqa"),
    (
        re.compile(r"#\s*(?:type:\s*ignore|pyright:\s*ignore)(?!\s*\[)", re.IGNORECASE),
        "unscoped type ignore",
    ),
)
_ESLINT_SUPPRESSION = re.compile(r"eslint-disable(?:\s*(?:--.*)?)?$", re.IGNORECASE)
_NOLINT_SUPPRESSION = re.compile(r"\bNOLINT\b(?!\s*\()")
_TYPECHECK_DISABLED = re.compile(r"typeCheckingMode\s*=\s*[\"']off[\"']", re.IGNORECASE)


def _python_comments(text: str) -> list[tuple[int, str]]:
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        return [
            (token.start[0], token.string) for token in tokens if token.type == tokenize.COMMENT
        ]
    except (IndentationError, tokenize.TokenError):
        return []


def _line_comments(text: str) -> list[tuple[int, str]]:
    comments: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        starts = [index for marker in ("//", "/*") if (index := line.find(marker)) >= 0]
        if starts:
            comments.append((line_number, line[min(starts) :]))
    return comments


def _suppression_audit(paths: list[str]) -> int:
    failed = False
    for raw in paths:
        path = Path(raw)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        findings: list[tuple[int, str]] = []
        if path.suffix.lower() in {".py", ".pyi"}:
            for line_number, comment in _python_comments(text):
                findings.extend(
                    (line_number, label)
                    for pattern, label in _PYTHON_SUPPRESSIONS
                    if pattern.search(comment)
                )
        else:
            for line_number, comment in _line_comments(text):
                if _ESLINT_SUPPRESSION.search(comment):
                    findings.append((line_number, "unscoped ESLint disable"))
                if _NOLINT_SUPPRESSION.search(comment):
                    findings.append((line_number, "unscoped NOLINT"))
        if path.suffix.lower() == ".toml":
            findings.extend(
                (line_number, "disabled project type checking")
                for line_number, line in enumerate(text.splitlines(), 1)
                if _TYPECHECK_DISABLED.search(line)
            )
        for line_number, label in findings:
            failed = True
            print(
                f"{raw}:{line_number}: {label}; use an exact rule/scope with reason, owner, and expiry",
                file=sys.stderr,
            )
    return int(failed)


def _dependency_name(requirement: str) -> str:
    return re.split(r"[<>=!~\[]", requirement, maxsplit=1)[0].strip().lower()


def _lock_consistency(_paths: list[str]) -> int:
    failed = False
    pyproject = Path("pyproject.toml")
    uv_lock = Path("uv.lock")
    if pyproject.exists() and uv_lock.exists():
        with pyproject.open("rb") as handle:
            project = tomllib.load(handle)
        with uv_lock.open("rb") as handle:
            lock = tomllib.load(handle)
        dev = project.get("project", {}).get("optional-dependencies", {}).get("dev", [])
        locked = {str(package.get("name", "")).lower() for package in lock.get("package", [])}
        missing = sorted(
            _dependency_name(str(item)) for item in dev if _dependency_name(str(item)) not in locked
        )
        if missing:
            failed = True
            print(f"uv.lock is missing dev dependencies: {', '.join(missing)}", file=sys.stderr)

    package_path = Path("trade_web/frontend/package.json")
    package_lock_path = Path("trade_web/frontend/package-lock.json")
    if package_path.exists() and package_lock_path.exists():
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package_lock = json.loads(package_lock_path.read_text(encoding="utf-8"))
        expected = package.get("devDependencies", {})
        actual = package_lock.get("packages", {}).get("", {}).get("devDependencies", {})
        if expected != actual:
            failed = True
            print(
                "package-lock.json root devDependencies do not match package.json", file=sys.stderr
            )
    return int(failed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trade-quality-internal")
    parser.add_argument(
        "command",
        choices=(
            "python-syntax",
            "config-parse",
            "text-hygiene",
            "suppression-audit",
            "lock-consistency",
        ),
    )
    parser.add_argument("paths", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    paths = _paths(args.paths)
    if args.command == "python-syntax":
        return _python_syntax(paths)
    if args.command == "config-parse":
        return _config_parse(paths)
    if args.command == "text-hygiene":
        return _text_hygiene(paths)
    if args.command == "suppression-audit":
        return _suppression_audit(paths)
    return _lock_consistency(paths)


if __name__ == "__main__":
    raise SystemExit(main())
