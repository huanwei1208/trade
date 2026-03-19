"""Compatibility shim — all logic has moved to trade_py/factors/.

This module re-exports the full public API so existing callers are unaffected.
Prefer importing directly from ``trade_py.factors`` in new code.
"""
from __future__ import annotations

# Re-export everything that callers may import from this module.
from trade_py.factors.definitions import (  # noqa: F401
    FEATURE_COLS,
    FACTOR_DEFINITIONS,
    FACTOR_TYPE_MAP,
    TECHNICAL_DEFAULTS,
    GOLD_DEFAULTS,
    factor_registry_rows,
)
from trade_py.factors.encoder import (  # noqa: F401
    stable_code_map as _stable_code_map,
    encode_with_maps as _encode_with_maps,
    save_feature_maps,
    load_feature_maps,
)
from trade_py.factors.technical import (  # noqa: F401
    compute_technical_factors as _compute_technical_factors,
    merge_technical_factors as _merge_technical_factors,
)
from trade_py.factors.materializer import (  # noqa: F401
    build_training_feature_frame,
    materialize_inference_factors,
)
from trade_py.factors.inference_bridge import sync_signal_predictions  # noqa: F401
