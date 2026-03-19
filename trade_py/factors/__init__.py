"""factors — structured factor layer for the EBRT pipeline.

Public API (mirrors propagation_runtime for backward compatibility):
    FEATURE_COLS
    FACTOR_DEFINITIONS
    TECHNICAL_DEFAULTS
    factor_registry_rows()
    build_training_feature_frame(data_root)
    materialize_inference_factors(data_root, date_str)
    sync_signal_predictions(data_root, date_str)
"""
from trade_py.factors.definitions import (  # noqa: F401
    FEATURE_COLS,
    FACTOR_DEFINITIONS,
    FACTOR_TYPE_MAP,
    TECHNICAL_DEFAULTS,
    GOLD_DEFAULTS,
    factor_registry_rows,
)
from trade_py.factors.materializer import (  # noqa: F401
    build_training_feature_frame,
    materialize_inference_factors,
)
from trade_py.factors.inference_bridge import sync_signal_predictions  # noqa: F401
