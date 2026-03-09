from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ReadPolicy:
    cache_policy: str = "local_first"
    history_backfill_days: int = 3
    request_timeout_sec: float = 8.0
    max_attempts_per_read: int = 1
    strict_retry_on_anomaly: bool = True
    fallback_on_failure: bool = True
    mode: str = "blocking"


@dataclass
class BackfillReport:
    dataset: str
    key: str
    action: str = "hit_local"
    degraded: bool = False
    reason_code: str = ""
    local_range: str = ""
    missing_range: str = ""
    api_endpoint: str = ""
    api_calls_est: int = 0
    api_calls_actual: int = 0
    llm_provider: str = ""
    token_est: int = 0
    token_actual: int = 0
    cost_est_usd: float = 0.0
    duration_ms: int = 0
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds") + "Z")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
