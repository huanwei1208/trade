"""Feed / source quality scoring utilities."""

from __future__ import annotations

META_SCORE_WEIGHTS: dict[str, float] = {
    "officialness": 0.30,
    "authority": 0.25,
    "quality": 0.20,
    "coverage": 0.15,
    "value": 0.10,
}


def meta_score(meta: dict) -> float:
    """Compute a 0-100 quality score from a source metadata dict."""
    total = 0.0
    for key, w in META_SCORE_WEIGHTS.items():
        v = float(meta.get(key, 0.0))
        total += max(0.0, min(5.0, v)) * w
    return round(total / 5.0 * 100.0, 1)
