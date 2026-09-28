"""Consumer-inventory construction and immutable identity validation."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from trade_py.devtools.layout.dependencies import imports_module
from trade_py.devtools.layout.models import (
    AuthorityFinding,
    ConsumerInventoryRef,
    ImportEdge,
)
from trade_py.devtools.layout.tree_index import (
    SOURCE_EXCLUDED_NAME_PATTERNS,
    SOURCE_EXCLUDED_SEGMENTS,
    TreeIndex,
    TreeIndexError,
    read_regular_relative,
)

MAX_AUTHORITIES = 50
MAX_CONSUMERS = 500
MAX_INVENTORY_AGE = timedelta(hours=24)
_SCANNER_SOURCE_FILES = (
    "authority.py",
    "dependencies.py",
    "inventory.py",
    "models.py",
    "tree_index.py",
)
_INVENTORY_FIELDS = frozenset(
    {
        "schema_version",
        "source_commit",
        "tree_digest",
        "scanner_name",
        "scanner_version",
        "scanner_source_digest",
        "included_roots",
        "explicit_exclusions",
        "rules_digest",
        "generated_at",
        "max_age_seconds",
        "completeness_state",
        "production_module_count",
        "consumer_count",
        "unclassified_consumer_count",
        "entry_digest",
        "report_digest",
    }
)


def build_consumer_inventory(
    repo_root: Path,
    *,
    index: TreeIndex,
    included_roots: Iterable[str],
    rules_digest: str,
    import_edges: Iterable[ImportEdge],
    selected_modules: Iterable[str],
    generated_at: datetime,
    completeness_state: str = "complete",
    unclassified_consumer_count: int = 0,
    source_commit_value: str | None = None,
    scanner_source_digest_value: str | None = None,
) -> ConsumerInventoryRef:
    """Build a content-bound inventory reference for a prospective authority slice."""

    if generated_at.tzinfo is None:
        raise ValueError("generated_at must carry an explicit UTC offset")
    selected = tuple(sorted(set(selected_modules)))
    edges = tuple(
        sorted(
            (
                edge
                for edge in import_edges
                if any(imports_module(edge.imported, module) for module in selected)
            ),
            key=lambda item: (item.consumer, item.imported, item.path, item.line),
        )
    )
    if len(selected) > MAX_AUTHORITIES or len(edges) > MAX_CONSUMERS:
        completeness_state = "over_budget"
    rows = tuple(f"{edge.consumer}\0{edge.imported}\0{edge.path}\0{edge.line}" for edge in edges)
    entry_digest = digest_rows(rows)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "source_commit": source_commit_value or source_commit(repo_root),
        "tree_digest": index.tree_digest,
        "scanner_name": index.scanner_name,
        "scanner_version": index.scanner_version,
        "scanner_source_digest": scanner_source_digest_value or scanner_source_digest(),
        "included_roots": tuple(sorted(set(included_roots))),
        "explicit_exclusions": explicit_exclusions(),
        "rules_digest": rules_digest,
        "generated_at": generated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "max_age_seconds": int(MAX_INVENTORY_AGE.total_seconds()),
        "completeness_state": completeness_state,
        "production_module_count": len(selected),
        "consumer_count": len(edges),
        "unclassified_consumer_count": unclassified_consumer_count,
        "entry_digest": entry_digest,
    }
    return ConsumerInventoryRef(
        **payload,
        report_digest=canonical_digest(payload),
    )


def parse_inventory(
    payload: object,
    path: str,
    findings: list[AuthorityFinding],
) -> ConsumerInventoryRef | None:
    if not isinstance(payload, dict):
        findings.append(
            AuthorityFinding(
                "layout.authority.inventory_missing",
                path,
                None,
                "authority requires a consumer_inventory table",
            )
        )
        return None
    unknown = sorted(set(payload) - _INVENTORY_FIELDS)
    if unknown:
        findings.append(
            AuthorityFinding(
                "layout.authority.inventory_invalid",
                path,
                None,
                f"consumer inventory contains unknown fields: {unknown}",
            )
        )
        return None
    try:
        roots = payload["included_roots"]
        if not isinstance(roots, list) or not all(isinstance(item, str) for item in roots):
            raise TypeError("included_roots")
        exclusions = payload["explicit_exclusions"]
        if not isinstance(exclusions, list) or not all(
            isinstance(item, str) for item in exclusions
        ):
            raise TypeError("explicit_exclusions")
        return ConsumerInventoryRef(
            schema_version=_integer(payload, "schema_version"),
            source_commit=_text(payload, "source_commit"),
            tree_digest=_text(payload, "tree_digest"),
            scanner_name=_text(payload, "scanner_name"),
            scanner_version=_text(payload, "scanner_version"),
            scanner_source_digest=_text(payload, "scanner_source_digest"),
            included_roots=tuple(roots),
            explicit_exclusions=tuple(exclusions),
            rules_digest=_text(payload, "rules_digest"),
            generated_at=_text(payload, "generated_at"),
            max_age_seconds=_integer(payload, "max_age_seconds"),
            completeness_state=_text(payload, "completeness_state"),
            production_module_count=_integer(payload, "production_module_count"),
            consumer_count=_integer(payload, "consumer_count"),
            unclassified_consumer_count=_integer(payload, "unclassified_consumer_count"),
            entry_digest=_text(payload, "entry_digest"),
            report_digest=_text(payload, "report_digest"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        findings.append(
            AuthorityFinding(
                "layout.authority.inventory_invalid",
                path,
                None,
                f"consumer inventory is malformed: {exc}",
            )
        )
        return None


def source_commit_covers_current_sources(
    repo_root: Path,
    source_commit_value: str,
    included_roots: tuple[str, ...],
    *,
    deadline_at: float | None = None,
) -> bool:
    if len(source_commit_value) != 40 or any(
        character not in "0123456789abcdef" for character in source_commit_value
    ):
        return False
    timeout = _remaining_timeout(deadline_at)
    if timeout is None:
        return False
    try:
        ancestor = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "merge-base",
                "--is-ancestor",
                source_commit_value,
                "HEAD",
            ],
            capture_output=True,
            timeout=timeout,
        )
        if ancestor.returncode != 0:
            return False
        timeout = _remaining_timeout(deadline_at)
        if timeout is None:
            return False
        difference = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "diff",
                "--quiet",
                source_commit_value,
                "--",
                *included_roots,
            ],
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise TreeIndexError(
            "layout.index.timeout",
            "source commit coverage check exceeded its monotonic deadline",
        ) from exc
    except OSError as exc:
        raise TreeIndexError(
            "layout.authority.commit_unavailable",
            f"cannot validate inventory source commit: {exc}",
        ) from exc
    except subprocess.SubprocessError:
        return False
    return difference.returncode == 0


def parse_utc(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("generated_at must carry an explicit UTC offset")
    return parsed.astimezone(timezone.utc)


def canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def scanner_source_digest(*, deadline_at: float | None = None) -> str:
    source_root = Path(__file__).parent
    digest = hashlib.sha256()
    for name in _SCANNER_SOURCE_FILES:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(
            read_regular_relative(
                source_root,
                name,
                max_bytes=1024 * 1024,
                deadline_at=deadline_at,
            )
        )
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def explicit_exclusions() -> tuple[str, ...]:
    return tuple(
        (
            *(f"segment:{item}" for item in SOURCE_EXCLUDED_SEGMENTS),
            *(f"name:{item}" for item in SOURCE_EXCLUDED_NAME_PATTERNS),
        )
    )


def source_commit(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TreeIndexError(
            "layout.authority.commit_unavailable",
            f"cannot resolve source commit: {exc}",
        ) from exc
    commit = result.stdout.strip()
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise TreeIndexError("layout.authority.commit_invalid", "source commit is not a full SHA")
    return commit


def _remaining_timeout(deadline_at: float | None) -> float | None:
    if deadline_at is None:
        return 3.0
    remaining = deadline_at - time.monotonic()
    if remaining <= 0:
        return None
    return min(3.0, remaining)


def digest_rows(rows: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(row.encode("utf-8"))
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


def _text(payload: Mapping[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise TypeError(key)
    return value


def _integer(payload: Mapping[str, Any], key: str) -> int:
    value = payload[key]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TypeError(key)
    return value


__all__ = [
    "MAX_AUTHORITIES",
    "MAX_CONSUMERS",
    "MAX_INVENTORY_AGE",
    "build_consumer_inventory",
    "canonical_digest",
    "parse_inventory",
    "parse_utc",
    "source_commit_covers_current_sources",
]
