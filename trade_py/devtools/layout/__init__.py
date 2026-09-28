"""Read-only package-layout evidence and architecture guards."""

from trade_py.devtools.layout.authority import (
    AuthorityFinding,
    AuthorityReport,
    ConsumerInventoryRef,
    ImportEdge,
    ModuleAuthorityRef,
    build_consumer_inventory,
    validate_authority_manifest,
)
from trade_py.devtools.layout.tree_index import (
    TreeEntry,
    TreeIndex,
    TreeIndexError,
    TreeIndexLimits,
    TreeIndexSession,
    scan_repository,
)

__all__ = [
    "AuthorityFinding",
    "AuthorityReport",
    "ConsumerInventoryRef",
    "ImportEdge",
    "ModuleAuthorityRef",
    "TreeEntry",
    "TreeIndex",
    "TreeIndexError",
    "TreeIndexLimits",
    "TreeIndexSession",
    "build_consumer_inventory",
    "scan_repository",
    "validate_authority_manifest",
]
