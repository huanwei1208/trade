"""Categorical encoding and feature-map persistence."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def _events_maps_path(data_root: str) -> Path:
    return Path(data_root) / "events" / "feature_maps.json"


def _models_maps_path(data_root: str) -> Path:
    return Path(data_root) / "models" / "propagation" / "feature_maps.json"


def stable_code_map(values: pd.Series) -> dict[str, int]:
    """Build a deterministic string-to-int mapping from unique values."""
    items = sorted({str(v).strip() for v in values.fillna("").tolist() if str(v).strip()})
    return {name: idx + 1 for idx, name in enumerate(items)}


def encode_with_maps(df: pd.DataFrame, maps: dict[str, dict[str, int]]) -> pd.DataFrame:
    """Encode event_type and breadth columns to integer codes."""
    out = df.copy()
    event_map = maps.get("event_type", {})
    breadth_map = maps.get("breadth", {})
    out["event_type_code"] = (
        out.get("event_type", pd.Series([], dtype=object))
        .fillna("").astype(str).map(event_map).fillna(0).astype(int)
    )
    out["breadth_code"] = (
        out.get("breadth", pd.Series([], dtype=object))
        .fillna("").astype(str).map(breadth_map).fillna(0).astype(int)
    )
    return out


def save_feature_maps(data_root: str, maps: dict[str, dict[str, int]], *,
                      model_copy: bool = False) -> Path:
    path = _models_maps_path(data_root) if model_copy else _events_maps_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(maps, ensure_ascii=False, indent=2))
    return path


def load_feature_maps(data_root: str) -> dict[str, dict[str, int]]:
    for path in (_models_maps_path(data_root), _events_maps_path(data_root)):
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception as exc:
                logger.warning("failed to load feature maps from %s: %s", path, exc)
    return {"event_type": {}, "breadth": {}}
