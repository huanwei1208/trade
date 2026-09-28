"""Read-only module-authority and consumer-inventory validation."""

from __future__ import annotations

import ast
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from trade_py.devtools.layout.dependencies import (
    forwarder_optional_dependency_findings,
    is_inert_foundation,
    is_target_module,
    is_thin_forwarder,
    module_escape_findings,
    module_name,
)
from trade_py.devtools.layout.dependencies import (
    import_edges as collect_import_edges,
)
from trade_py.devtools.layout.inventory import (
    MAX_AUTHORITIES,
    MAX_CONSUMERS,
    MAX_INVENTORY_AGE,
    build_consumer_inventory,
    canonical_digest,
    parse_inventory,
    parse_utc,
    scanner_source_digest,
    source_commit_covers_current_sources,
)
from trade_py.devtools.layout.models import (
    AuthorityFinding,
    AuthorityReport,
    ConsumerInventoryRef,
    ImportEdge,
    ModuleAuthorityRef,
)
from trade_py.devtools.layout.tree_index import (
    DEFAULT_LIMITS,
    SOURCE_EXCLUDED_NAME_PATTERNS,
    SOURCE_EXCLUDED_SEGMENTS,
    SOURCE_SUFFIXES,
    TreeEntry,
    TreeIndex,
    TreeIndexError,
    read_regular_relative,
    scan_repository,
)
from trade_py.devtools.toml_compat import tomllib

MANIFEST_FILENAME = "layout-authority.toml"
MANIFEST_SCHEMA_VERSION = 1
RULES_VERSION = "layout-authority-v1"
MAX_MANIFEST_BYTES = 256 * 1024
_INCLUDED_ROOTS = ("src/trade", "trade_py")
_AUTHORITY_STATES = frozenset(
    {
        "inventoried",
        "prepared",
        "shadow_verified",
        "legacy_forwarding",
        "target_authoritative",
        "retireable",
    }
)
_OWNERS = frozenset(
    {
        "bootstrap",
        "capture",
        "datasets",
        "decision_support",
        "interfaces",
        "kernel",
        "platform",
        "processes",
        "studies",
    }
)
_MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "rules_version",
        "included_roots",
        "foundation_modules",
        "authorities",
    }
)
_AUTHORITY_FIELDS = frozenset(
    {
        "activation_plan_digest",
        "legacy_module",
        "migration_evidence_ref",
        "target_module",
        "owner",
        "contract_generation",
        "implementation_digest",
        "compatibility_direction",
        "state",
        "consumer_inventory",
    }
)
_DIGEST_PREFIX = "sha256:"
_PLANNED_STATES = frozenset(
    {
        "prepared",
        "shadow_verified",
        "legacy_forwarding",
        "target_authoritative",
        "retireable",
    }
)
_COMPLETED_STATES = frozenset(
    {
        "legacy_forwarding",
        "target_authoritative",
        "retireable",
    }
)
_APPROVED_PROJECT_SCRIPTS = {"trade-py": "trade_py.cli.main:main"}


@dataclass(frozen=True)
class _Manifest:
    included_roots: tuple[str, ...]
    foundation_modules: frozenset[str]
    rules_digest: str
    authorities: tuple[Mapping[str, Any], ...]


def validate_authority_manifest(
    repo_root: Path,
    *,
    manifest_name: str = MANIFEST_FILENAME,
    candidate_paths: Iterable[str] = (),
    observed_at: datetime | None = None,
) -> AuthorityReport:
    """Validate the immutable package authority declaration without importing it."""

    findings: list[AuthorityFinding] = []
    root = repo_root.resolve()
    deadline = time.monotonic() + DEFAULT_LIMITS.deadline_seconds
    try:
        manifest = _load_manifest(root, manifest_name, deadline_at=deadline)
        index = scan_repository(
            root,
            included_roots=manifest.included_roots,
            rules_digest=manifest.rules_digest,
            candidate_paths=candidate_paths,
            deadline_at=deadline,
        )
        scanner_digest = scanner_source_digest(deadline_at=deadline)
    except (TreeIndexError, ValueError, tomllib.TOMLDecodeError) as exc:
        code = exc.code if isinstance(exc, TreeIndexError) else "layout.authority.manifest_invalid"
        return AuthorityReport(
            tree_index=None,
            findings=(AuthorityFinding(code, manifest_name, None, str(exc)),),
            authorities=(),
            import_edges=(),
        )
    try:
        findings.extend(_package_metadata_findings(root, deadline_at=deadline))
    except (TreeIndexError, ValueError, tomllib.TOMLDecodeError) as exc:
        findings.append(
            AuthorityFinding(
                "layout.authority.package_metadata_invalid",
                "pyproject.toml",
                None,
                str(exc),
            )
        )

    entries_by_module: dict[str, TreeEntry] = {}
    for entry in index.entries:
        module = module_name(entry.path)
        if module is None:
            continue
        previous = entries_by_module.get(module)
        if previous is not None:
            findings.append(
                AuthorityFinding(
                    "layout.authority.duplicate_module_path",
                    entry.path,
                    None,
                    f"logical module {module} is also provided by {previous.path}",
                )
            )
            continue
        entries_by_module[module] = entry
    import_edges: list[ImportEdge] = []
    trees: dict[str, ast.Module] = {}
    for module, entry in sorted(entries_by_module.items()):
        try:
            _check_deadline(deadline)
            source = read_regular_relative(
                root,
                entry.path,
                max_bytes=entry.source_bytes,
                deadline_at=deadline,
            )
            tree = ast.parse(source, filename=entry.path)
        except (SyntaxError, UnicodeDecodeError, TreeIndexError) as exc:
            findings.append(
                AuthorityFinding(
                    "layout.authority.source_invalid",
                    entry.path,
                    getattr(exc, "lineno", None),
                    f"cannot parse indexed source: {exc}",
                )
            )
            continue
        trees[module] = tree
        import_edges.extend(collect_import_edges(module, entry.path, tree))
        findings.extend(module_escape_findings(module, entry.path, tree))

    authorities: list[ModuleAuthorityRef] = []
    if len(manifest.authorities) > MAX_AUTHORITIES:
        findings.append(
            AuthorityFinding(
                "layout.authority.module_budget",
                manifest_name,
                None,
                f"{len(manifest.authorities)} authorities exceed the limit of {MAX_AUTHORITIES}",
            )
        )
    now = observed_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        return AuthorityReport(
            tree_index=index,
            findings=(
                AuthorityFinding(
                    "layout.authority.observation_time_invalid",
                    manifest_name,
                    None,
                    "observed_at must carry an explicit UTC offset",
                ),
            ),
            authorities=(),
            import_edges=tuple(import_edges),
        )
    rows = manifest.authorities if len(manifest.authorities) <= MAX_AUTHORITIES else ()
    try:
        commit_coverage = _inventory_commit_coverage(
            rows,
            repo_root=root,
            included_roots=manifest.included_roots,
            manifest_name=manifest_name,
            deadline_at=deadline,
            findings=findings,
        )
        for row in rows:
            _check_deadline(deadline)
            authority, row_findings = _validate_authority_row(
                row,
                repo_root=root,
                manifest=manifest,
                index=index,
                entries_by_module=entries_by_module,
                import_edges=import_edges,
                observed_at=now,
                manifest_name=manifest_name,
                scanner_digest=scanner_digest,
                commit_coverage=commit_coverage,
            )
            findings.extend(row_findings)
            if authority is not None:
                authorities.append(authority)
    except TreeIndexError as exc:
        findings.append(
            AuthorityFinding(
                exc.code,
                manifest_name,
                None,
                exc.detail,
            )
        )

    findings.extend(
        _cross_authority_findings(
            authorities,
            trees=trees,
            entries_by_module=entries_by_module,
            foundation_modules=manifest.foundation_modules,
        )
    )
    return AuthorityReport(
        tree_index=index,
        findings=tuple(
            sorted(
                findings,
                key=lambda item: (item.path, item.line or -1, item.code, item.detail),
            )
        ),
        authorities=tuple(sorted(authorities, key=lambda item: item.target_module)),
        import_edges=tuple(
            sorted(import_edges, key=lambda item: (item.consumer, item.imported, item.line))
        ),
    )


def _load_manifest(
    root: Path,
    manifest_name: str,
    *,
    deadline_at: float,
) -> _Manifest:
    content = read_regular_relative(
        root,
        manifest_name,
        max_bytes=MAX_MANIFEST_BYTES,
        deadline_at=deadline_at,
    )
    payload = tomllib.loads(content.decode("utf-8"))
    unknown = sorted(set(payload) - _MANIFEST_FIELDS)
    if unknown:
        raise ValueError(f"layout authority manifest contains unknown fields: {unknown}")
    if payload.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("layout authority manifest requires schema_version = 1")
    if payload.get("rules_version") != RULES_VERSION:
        raise ValueError(f"layout authority manifest requires rules_version = {RULES_VERSION!r}")
    roots = _string_tuple(payload, "included_roots")
    if tuple(sorted(roots)) != tuple(sorted(_INCLUDED_ROOTS)):
        raise ValueError(
            "included_roots must contain only the approved src/trade and trade_py source roots"
        )
    foundations = frozenset(_string_tuple(payload, "foundation_modules"))
    if foundations != {"trade"}:
        raise ValueError("foundation_modules must contain only the inert top-level trade package")
    authorities = payload.get("authorities", [])
    if not isinstance(authorities, list) or not all(isinstance(item, dict) for item in authorities):
        raise ValueError("authorities must be an array of tables")
    rules_payload = {
        "rules_version": RULES_VERSION,
        "included_roots": roots,
        "foundation_modules": tuple(sorted(foundations)),
        "source_suffixes": SOURCE_SUFFIXES,
        "excluded_segments": SOURCE_EXCLUDED_SEGMENTS,
        "excluded_name_patterns": SOURCE_EXCLUDED_NAME_PATTERNS,
    }
    return _Manifest(
        included_roots=roots,
        foundation_modules=foundations,
        rules_digest=canonical_digest(rules_payload),
        authorities=tuple(authorities),
    )


def _validate_authority_row(
    row: Mapping[str, Any],
    *,
    repo_root: Path,
    manifest: _Manifest,
    index: TreeIndex,
    entries_by_module: Mapping[str, TreeEntry],
    import_edges: Iterable[ImportEdge],
    observed_at: datetime,
    manifest_name: str,
    scanner_digest: str,
    commit_coverage: Mapping[str, bool],
) -> tuple[ModuleAuthorityRef | None, list[AuthorityFinding]]:
    findings: list[AuthorityFinding] = []
    unknown = sorted(set(row) - _AUTHORITY_FIELDS)
    if unknown:
        findings.append(
            AuthorityFinding(
                "layout.authority.field_unknown",
                manifest_name,
                None,
                f"authority contains unknown fields: {unknown}",
            )
        )
    required = (
        "legacy_module",
        "target_module",
        "owner",
        "contract_generation",
        "implementation_digest",
        "compatibility_direction",
        "state",
    )
    values: dict[str, str] = {}
    for key in required:
        value = row.get(key)
        if not isinstance(value, str) or not value.strip():
            findings.append(
                AuthorityFinding(
                    "layout.authority.field_missing",
                    manifest_name,
                    None,
                    f"authority field {key!r} must be a non-empty string",
                )
            )
        else:
            values[key] = value
    if findings:
        return None, findings
    if values["owner"] not in _OWNERS:
        findings.append(
            AuthorityFinding(
                "layout.authority.owner_invalid",
                manifest_name,
                None,
                f"unknown semantic owner: {values['owner']}",
            )
        )
    if values["state"] not in _AUTHORITY_STATES:
        findings.append(
            AuthorityFinding(
                "layout.authority.state_invalid",
                manifest_name,
                None,
                f"unknown authority state: {values['state']}",
            )
        )
    if values["compatibility_direction"] != "legacy_to_target":
        findings.append(
            AuthorityFinding(
                "layout.authority.direction_invalid",
                manifest_name,
                None,
                "compatibility_direction must be legacy_to_target",
            )
        )
    activation_plan_digest = _optional_digest(
        row.get("activation_plan_digest"),
        "activation_plan_digest",
        manifest_name,
        findings,
    )
    migration_evidence_ref = _optional_digest(
        row.get("migration_evidence_ref"),
        "migration_evidence_ref",
        manifest_name,
        findings,
    )
    state = values["state"]
    if state == "inventoried" and (
        activation_plan_digest is not None or migration_evidence_ref is not None
    ):
        findings.append(
            AuthorityFinding(
                "layout.authority.lineage_premature",
                manifest_name,
                None,
                "inventoried authority cannot claim activation or migration evidence",
            )
        )
    if state in _PLANNED_STATES and activation_plan_digest is None:
        findings.append(
            AuthorityFinding(
                "layout.authority.activation_plan_missing",
                manifest_name,
                None,
                f"authority state {state} requires an immutable activation-plan digest",
            )
        )
    if state in _COMPLETED_STATES and migration_evidence_ref is None:
        findings.append(
            AuthorityFinding(
                "layout.authority.migration_evidence_missing",
                manifest_name,
                None,
                f"authority state {state} requires terminal migration evidence",
            )
        )
    if state in {"prepared", "shadow_verified"} and migration_evidence_ref is not None:
        findings.append(
            AuthorityFinding(
                "layout.authority.lineage_premature",
                manifest_name,
                None,
                f"authority state {state} cannot claim terminal migration evidence",
            )
        )
    if not (
        values["legacy_module"] == "trade_py" or values["legacy_module"].startswith("trade_py.")
    ):
        findings.append(
            AuthorityFinding(
                "layout.authority.namespace_invalid",
                manifest_name,
                None,
                f"legacy module must remain under trade_py: {values['legacy_module']}",
            )
        )
    if not is_target_module(values["target_module"]):
        findings.append(
            AuthorityFinding(
                "layout.authority.namespace_invalid",
                manifest_name,
                None,
                f"target module must be under trade: {values['target_module']}",
            )
        )
    legacy_entry = entries_by_module.get(values["legacy_module"])
    if legacy_entry is None:
        findings.append(
            AuthorityFinding(
                "layout.authority.legacy_missing",
                manifest_name,
                None,
                f"legacy module is not indexed: {values['legacy_module']}",
            )
        )
    target_entry = entries_by_module.get(values["target_module"])
    if target_entry is None:
        findings.append(
            AuthorityFinding(
                "layout.authority.target_missing",
                manifest_name,
                None,
                f"target module is not indexed: {values['target_module']}",
            )
        )
    elif target_entry.source_digest != values["implementation_digest"]:
        findings.append(
            AuthorityFinding(
                "layout.authority.implementation_stale",
                target_entry.path,
                None,
                "implementation digest does not match the indexed target source",
            )
        )
    inventory_payload = row.get("consumer_inventory")
    inventory = parse_inventory(inventory_payload, manifest_name, findings)
    if inventory is None:
        return None, findings
    try:
        generated_at = parse_utc(inventory.generated_at)
    except ValueError as exc:
        findings.append(
            AuthorityFinding(
                "layout.authority.inventory_invalid",
                manifest_name,
                None,
                str(exc),
            )
        )
        return None, findings
    expected = build_consumer_inventory(
        repo_root,
        index=index,
        included_roots=manifest.included_roots,
        rules_digest=manifest.rules_digest,
        import_edges=import_edges,
        selected_modules=(values["legacy_module"], values["target_module"]),
        generated_at=generated_at,
        completeness_state=inventory.completeness_state,
        unclassified_consumer_count=inventory.unclassified_consumer_count,
        source_commit_value=inventory.source_commit,
        scanner_source_digest_value=scanner_digest,
    )
    expected_payload = {
        key: value for key, value in expected.__dict__.items() if key != "report_digest"
    }
    expected_payload["source_commit"] = inventory.source_commit
    expected = ConsumerInventoryRef(
        **expected_payload,
        report_digest=canonical_digest(expected_payload),
    )
    # The commit is repository-specific and supplied by the immutable record.
    if inventory != expected:
        findings.append(
            AuthorityFinding(
                "layout.authority.inventory_stale",
                manifest_name,
                None,
                "consumer inventory does not match the current scanner, tree, rules or imports",
            )
        )
    age = observed_at.astimezone(timezone.utc) - generated_at
    if age < timedelta(0):
        findings.append(
            AuthorityFinding(
                "layout.authority.inventory_time_invalid",
                manifest_name,
                None,
                "consumer inventory generation time is after the observation time",
            )
        )
    elif age > MAX_INVENTORY_AGE:
        findings.append(
            AuthorityFinding(
                "layout.authority.inventory_expired",
                manifest_name,
                None,
                "consumer inventory is older than 24 hours",
            )
        )
    if inventory.completeness_state != "complete":
        findings.append(
            AuthorityFinding(
                "layout.authority.inventory_incomplete",
                manifest_name,
                None,
                f"consumer inventory is {inventory.completeness_state}, not complete",
            )
        )
    if inventory.unclassified_consumer_count:
        findings.append(
            AuthorityFinding(
                "layout.authority.inventory_unclassified",
                manifest_name,
                None,
                (
                    f"consumer inventory contains "
                    f"{inventory.unclassified_consumer_count} unclassified consumers"
                ),
            )
        )
    if not commit_coverage.get(inventory.source_commit, False):
        findings.append(
            AuthorityFinding(
                "layout.authority.inventory_commit_stale",
                manifest_name,
                None,
                "inventory source commit is missing or its governed source roots differ",
            )
        )
    if inventory.consumer_count > MAX_CONSUMERS:
        findings.append(
            AuthorityFinding(
                "layout.authority.consumer_budget",
                manifest_name,
                None,
                f"{inventory.consumer_count} consumers exceed the limit of {MAX_CONSUMERS}",
            )
        )
    return (
        ModuleAuthorityRef(
            legacy_module=values["legacy_module"],
            target_module=values["target_module"],
            owner=values["owner"],
            contract_generation=values["contract_generation"],
            implementation_digest=values["implementation_digest"],
            compatibility_direction=values["compatibility_direction"],
            state=values["state"],
            activation_plan_digest=activation_plan_digest,
            migration_evidence_ref=migration_evidence_ref,
            consumer_inventory=inventory,
        ),
        findings,
    )


def _inventory_commit_coverage(
    rows: Iterable[Mapping[str, Any]],
    *,
    repo_root: Path,
    included_roots: tuple[str, ...],
    manifest_name: str,
    deadline_at: float,
    findings: list[AuthorityFinding],
) -> Mapping[str, bool]:
    commits = {
        source_commit_value
        for row in rows
        if isinstance((inventory := row.get("consumer_inventory")), dict)
        and isinstance((source_commit_value := inventory.get("source_commit")), str)
    }
    if len(commits) > 1:
        findings.append(
            AuthorityFinding(
                "layout.authority.inventory_commit_conflict",
                manifest_name,
                None,
                "all authority inventories in one manifest must bind one source commit",
            )
        )
        return {commit: False for commit in commits}
    if not commits:
        return {}
    commit = next(iter(commits))
    return {
        commit: source_commit_covers_current_sources(
            repo_root,
            commit,
            included_roots,
            deadline_at=deadline_at,
        )
    }


def _check_deadline(deadline_at: float) -> None:
    if time.monotonic() >= deadline_at:
        raise TreeIndexError(
            "layout.index.timeout",
            "Module authority validation exceeded its monotonic deadline",
        )


def _package_metadata_findings(
    repo_root: Path,
    *,
    deadline_at: float,
) -> list[AuthorityFinding]:
    content = read_regular_relative(
        repo_root,
        "pyproject.toml",
        max_bytes=MAX_MANIFEST_BYTES,
        deadline_at=deadline_at,
    )
    payload = tomllib.loads(content.decode("utf-8"))
    project = payload.get("project")
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml requires a project table")
    findings: list[AuthorityFinding] = []
    scripts = project.get("scripts")
    if scripts != _APPROVED_PROJECT_SCRIPTS:
        findings.append(
            AuthorityFinding(
                "layout.authority.entry_point_unapproved",
                "pyproject.toml",
                None,
                "project.scripts must preserve only the reviewed trade-py console entry point",
            )
        )
    entry_points = project.get("entry-points")
    if entry_points not in (None, {}):
        findings.append(
            AuthorityFinding(
                "layout.authority.entry_point_unapproved",
                "pyproject.toml",
                None,
                "plugin, MCP and remote-worker entry-point groups require a strict-approved child",
            )
        )
    return findings


def _optional_digest(
    value: object,
    name: str,
    path: str,
    findings: list[AuthorityFinding],
) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value.startswith(_DIGEST_PREFIX)
        or len(value) != len(_DIGEST_PREFIX) + 64
    ):
        findings.append(
            AuthorityFinding(
                "layout.authority.lineage_invalid",
                path,
                None,
                f"{name} must be a complete SHA-256 digest",
            )
        )
        return None
    suffix = value.removeprefix(_DIGEST_PREFIX)
    try:
        int(suffix, 16)
    except ValueError:
        findings.append(
            AuthorityFinding(
                "layout.authority.lineage_invalid",
                path,
                None,
                f"{name} must be a complete SHA-256 digest",
            )
        )
        return None
    return value


def _cross_authority_findings(
    authorities: Iterable[ModuleAuthorityRef],
    *,
    trees: Mapping[str, ast.Module],
    entries_by_module: Mapping[str, TreeEntry],
    foundation_modules: frozenset[str],
) -> list[AuthorityFinding]:
    findings: list[AuthorityFinding] = []
    items = tuple(authorities)
    targets: dict[str, ModuleAuthorityRef] = {}
    legacies: dict[str, ModuleAuthorityRef] = {}
    legacy_modules = {item.legacy_module for item in items}
    for item in items:
        if item.target_module in targets:
            entry = entries_by_module.get(item.target_module)
            findings.append(
                AuthorityFinding(
                    "layout.authority.duplicate_target",
                    entry.path if entry else MANIFEST_FILENAME,
                    None,
                    f"multiple authority records claim {item.target_module}",
                )
            )
        targets[item.target_module] = item
        if item.legacy_module in legacies:
            entry = entries_by_module.get(item.legacy_module)
            findings.append(
                AuthorityFinding(
                    "layout.authority.duplicate_legacy",
                    entry.path if entry else MANIFEST_FILENAME,
                    None,
                    f"multiple authority records claim {item.legacy_module}",
                )
            )
        legacies[item.legacy_module] = item
        if item.target_module in legacy_modules:
            findings.append(
                AuthorityFinding(
                    "layout.authority.forwarder_chain",
                    MANIFEST_FILENAME,
                    None,
                    f"authority chain is more than one hop at {item.target_module}",
                )
            )
        if item.state in {"legacy_forwarding", "target_authoritative", "retireable"}:
            legacy_tree = trees.get(item.legacy_module)
            legacy_entry = entries_by_module.get(item.legacy_module)
            if (
                legacy_tree is not None
                and legacy_entry is not None
                and not is_thin_forwarder(legacy_tree, item.target_module)
            ):
                findings.append(
                    AuthorityFinding(
                        "layout.authority.forwarder_not_thin",
                        legacy_entry.path,
                        None,
                        "compatibility module contains behavior or does not delegate directly",
                    )
                )
            if legacy_tree is not None and legacy_entry is not None:
                findings.extend(
                    forwarder_optional_dependency_findings(
                        item.legacy_module,
                        legacy_entry.path,
                        legacy_tree,
                        target_module=item.target_module,
                    )
                )

    for module, entry in entries_by_module.items():
        if not is_target_module(module):
            continue
        if module in foundation_modules:
            tree = trees.get(module)
            if tree is None or not is_inert_foundation(tree):
                findings.append(
                    AuthorityFinding(
                        "layout.authority.foundation_not_inert",
                        entry.path,
                        None,
                        "the additive foundation may contain only a module docstring",
                    )
                )
            continue
        if module in targets:
            continue
        findings.append(
            AuthorityFinding(
                "layout.authority.target_unclassified",
                entry.path,
                None,
                f"target module has no immutable authority record: {module}",
            )
        )
    return findings


_module_name = module_name


def _string_tuple(payload: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise ValueError(f"{key} must be a non-empty string array")
    return tuple(value)


__all__ = [
    "AuthorityFinding",
    "AuthorityReport",
    "ConsumerInventoryRef",
    "ImportEdge",
    "MANIFEST_FILENAME",
    "ModuleAuthorityRef",
    "build_consumer_inventory",
    "validate_authority_manifest",
]
