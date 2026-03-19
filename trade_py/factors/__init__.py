"""factors — structured factor layer for the EBRT pipeline.

Public API:
    FEATURE_COLS, FACTOR_DEFINITIONS, TECHNICAL_DEFAULTS, factor_registry_rows()
    FactorType, FactorMeta, FACTOR_REGISTRY, composite_trust_weights()
    build_training_feature_frame(data_root) → (df, maps, trust_weights)
    materialize_inference_factors(data_root, date_str)
    sync_signal_predictions(data_root, date_str)
    update_utility_trust(data_root, lookback_days=60)
    compute_factor_ic(data_root, lookback_days=60)
"""
from trade_py.factors.definitions import (  # noqa: F401
    FEATURE_COLS,
    FACTOR_DEFINITIONS,
    FACTOR_TYPE_MAP,
    TECHNICAL_DEFAULTS,
    GOLD_DEFAULTS,
    factor_registry_rows,
)
from trade_py.factors.registry import (  # noqa: F401
    FactorType,
    FactorMeta,
    FACTOR_REGISTRY,
    composite_trust_weights,
    load_registry_from_db,
)
from trade_py.factors.materializer import (  # noqa: F401
    build_training_feature_frame,
    materialize_inference_factors,
)
from trade_py.factors.inference_bridge import sync_signal_predictions  # noqa: F401
from trade_py.factors.trust_update import (  # noqa: F401
    update_utility_trust,
    compute_factor_ic,
)
