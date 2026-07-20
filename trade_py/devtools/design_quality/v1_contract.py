"""Pure validation primitives shared across the design report v1 trust boundary."""

from __future__ import annotations

import re
from datetime import date

EXCEPTION_EXPIRING_WINDOW_DAYS = 14

_RULE_ID_RE = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")


def is_rule_id(value: object) -> bool:
    return isinstance(value, str) and bool(_RULE_ID_RE.fullmatch(value))


def is_substantive_reason(value: object) -> bool:
    if not isinstance(value, str) or len(value.strip()) < 12:
        return False
    normalized = re.sub(r"[\s._/-]+", " ", value.strip().lower())
    return normalized not in {"n a", "na", "none", "not applicable", "no"}


def exception_state(expires: date, effective_date: date) -> str:
    if expires < effective_date:
        return "expired"
    if (expires - effective_date).days <= EXCEPTION_EXPIRING_WINDOW_DAYS:
        return "expiring"
    return "applied"
