"""Immutable records emitted by the package-layout authority guard."""

from __future__ import annotations

from dataclasses import dataclass

from trade_py.devtools.layout.tree_index import TreeIndex

INFRASTRUCTURE_FINDINGS = frozenset(
    {
        "layout.authority.commit_unavailable",
        "layout.authority.commit_invalid",
        "layout.index.cleanup_failed",
        "layout.index.output_budget",
        "layout.index.timeout",
        "layout.index.tool_failure",
    }
)


@dataclass(frozen=True)
class AuthorityFinding:
    code: str
    path: str
    line: int | None
    detail: str


@dataclass(frozen=True)
class ImportEdge:
    consumer: str
    imported: str
    path: str
    line: int


@dataclass(frozen=True)
class ConsumerInventoryRef:
    schema_version: int
    source_commit: str
    tree_digest: str
    scanner_name: str
    scanner_version: str
    scanner_source_digest: str
    included_roots: tuple[str, ...]
    explicit_exclusions: tuple[str, ...]
    rules_digest: str
    generated_at: str
    max_age_seconds: int
    completeness_state: str
    production_module_count: int
    consumer_count: int
    unclassified_consumer_count: int
    entry_digest: str
    report_digest: str


@dataclass(frozen=True)
class ModuleAuthorityRef:
    legacy_module: str
    target_module: str
    owner: str
    contract_generation: str
    implementation_digest: str
    compatibility_direction: str
    state: str
    activation_plan_digest: str | None
    migration_evidence_ref: str | None
    consumer_inventory: ConsumerInventoryRef


@dataclass(frozen=True)
class AuthorityReport:
    tree_index: TreeIndex | None
    findings: tuple[AuthorityFinding, ...]
    authorities: tuple[ModuleAuthorityRef, ...]
    import_edges: tuple[ImportEdge, ...]

    @property
    def ok(self) -> bool:
        return not self.findings

    @property
    def exit_code(self) -> int:
        if not self.findings:
            return 0
        if any(item.code in INFRASTRUCTURE_FINDINGS for item in self.findings):
            return 2
        return 1

    def partition_by_owner(self) -> tuple[tuple[str, tuple[ModuleAuthorityRef, ...]], ...]:
        partitions: dict[str, list[ModuleAuthorityRef]] = {}
        for item in self.authorities:
            partitions.setdefault(item.owner, []).append(item)
        return tuple(
            (
                owner,
                tuple(sorted(items, key=lambda item: (item.target_module, item.legacy_module))),
            )
            for owner, items in sorted(partitions.items())
        )


__all__ = [
    "AuthorityFinding",
    "AuthorityReport",
    "ConsumerInventoryRef",
    "ImportEdge",
    "ModuleAuthorityRef",
]
