"""Frozen vocabulary and reason codes for the BTC Observatory.

These enums implement the WP0 frozen contracts (see
openspec/changes/btc-observatory-research-lab-v1/frozen_contracts.md). They are the
single source of truth for state axes, channels, and reason codes across the
domain, catalog, resolver, PIT, research, and Web layers. Downstream code MUST NOT
redefine these strings.
"""
from __future__ import annotations

from enum import Enum

MAPPING_POLICY_VERSION = "obs-map-v1"
RESOLVER_POLICY_VERSION = "obs-resolver-v1"
CATALOG_SCHEMA_VERSION = "obs-catalog-v1"
SERIALIZATION_VERSION = "obs-serial-v1"


class Channel(str, Enum):
    """Lifecycle channel (orthogonal to knowledge cut and revision policy)."""

    OBSERVED = "observed"
    EVALUATED_CANDIDATE = "evaluated_candidate"
    FORMAL = "formal"
    EXACT = "exact"


class KnowledgeMode(str, Enum):
    MARKET_AVAILABLE = "market_available"
    INSTALLATION_OBSERVED = "installation_observed"


class RevisionPolicy(str, Enum):
    AS_KNOWN = "as_known"
    LATEST_RESTATED = "latest_restated"


class AcquisitionState(str, Enum):
    NOT_ATTEMPTED = "not_attempted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    EMPTY = "empty"
    FAILED = "failed"
    ABANDONED = "abandoned"
    UNKNOWN = "unknown"


class QualityState(str, Enum):
    NOT_EVALUATED = "not_evaluated"
    ASSURED = "assured"
    DEGRADED = "degraded"
    INSUFFICIENT = "insufficient"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class LifecycleState(str, Enum):
    STAGED = "staged"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"
    UNKNOWN = "unknown"


class ResearchState(str, Enum):
    EXPLORATORY = "exploratory"
    ELIGIBLE = "eligible"
    CANDIDATE = "candidate"
    MONITORING = "monitoring"
    VALIDATED = "validated"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class FreshnessState(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


class CompatibilityState(str, Enum):
    COMPATIBLE = "compatible"
    CONTRACT_STALE = "contract_stale"
    REPLAY_MISMATCH = "replay_mismatch"
    UNKNOWN = "unknown"


class AvailabilityState(str, Enum):
    PRESENT = "present"
    MISSING = "missing"
    UNOBSERVED = "unobserved"
    UNKNOWN = "unknown"


class RevisionState(str, Enum):
    UNCHANGED = "unchanged"
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    UNKNOWN = "unknown"


class RenderRole(str, Enum):
    FORMAL_BASELINE = "formal_baseline"
    CANDIDATE_OVERLAP = "candidate_overlap"
    CANDIDATE_ONLY = "candidate_only"
    OBSERVED_OVERLAP = "observed_overlap"
    OBSERVED_ONLY = "observed_only"


class Purpose(str, Enum):
    MANUAL_OBSERVATION = "manual_observation"
    EXPLORATORY_RESEARCH = "exploratory_research"
    FORMAL_SYSTEM_CONSUMPTION = "formal_system_consumption"
    STRICT_RESEARCH = "strict_research"
    AUTOMATED_DECISION = "automated_decision"


class ReasonCode(str, Enum):
    """Frozen error/reason codes (WP0 frozen_contracts.md)."""

    SNAPSHOT_NOT_FOUND = "SNAPSHOT_NOT_FOUND"
    CURRENT_POINTER_INVALID = "CURRENT_POINTER_INVALID"
    ARTIFACT_HASH_MISMATCH = "ARTIFACT_HASH_MISMATCH"
    MANIFEST_INVALID = "MANIFEST_INVALID"
    CHANNEL_UNAVAILABLE = "CHANNEL_UNAVAILABLE"
    PIT_NOT_PROVEN = "PIT_NOT_PROVEN"
    DATASET_STALE = "DATASET_STALE"
    QUALITY_BLOCKED = "QUALITY_BLOCKED"
    RESEARCH_NOT_ELIGIBLE = "RESEARCH_NOT_ELIGIBLE"
    INVALID_SNAPSHOT_SELECTOR = "INVALID_SNAPSHOT_SELECTOR"
    COMPOSITE_NOT_DATASET = "COMPOSITE_NOT_DATASET"
    CATALOG_STALE = "CATALOG_STALE"
    RESTATED_NOT_PIT = "RESTATED_NOT_PIT"
    LEGACY_TIME_UNPROVEN = "LEGACY_TIME_UNPROVEN"


# Asset / provider identity (frozen — identity_map.md)
ASSET_ID = "crypto.BTC"
DISPLAY_SYMBOL = "BTC"
PRIMARY_PROVIDER = "okx"
PRIMARY_INSTRUMENT = "BTC-USDT"
SHADOW_PROVIDER = "binance"
SHADOW_INSTRUMENT = "BTCUSDT"
QUOTE = "USDT"
PRIMARY_INTERVAL = "1Dutc"
SHADOW_INTERVAL = "1d"


class ObservatoryError(Exception):
    """Base error carrying a frozen reason code, evidence refs, and retryability."""

    def __init__(
        self,
        reason_code: ReasonCode,
        message: str = "",
        *,
        evidence_refs: list[str] | None = None,
        retryable: bool = False,
        extra: dict | None = None,
    ) -> None:
        super().__init__(message or reason_code.value)
        self.reason_code = reason_code
        self.message = message or reason_code.value
        self.evidence_refs = list(evidence_refs or [])
        self.retryable = retryable
        self.extra = dict(extra or {})

    def to_payload(self) -> dict:
        payload = {
            "reason_codes": [self.reason_code.value],
            "message": self.message,
            "evidence_refs": self.evidence_refs,
            "retryable": self.retryable,
        }
        payload.update(self.extra)
        return payload
