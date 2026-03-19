"""Factor definitions: column names, metadata, defaults."""
from __future__ import annotations

FEATURE_COLS: list[str] = [
    "hop", "kg_score", "magnitude", "confidence",
    "event_type_code", "breadth_code", "news_volume", "decay_factor", "max_hop",
    "industry", "market", "window_score", "net_sentiment",
    "bf_net_sentiment", "bf_event_strength", "bf_policy_intensity", "bf_entity_density",
    "bf_novelty", "bf_volume_burst", "bf_cross_source_confirmation", "bf_noise_penalty",
    "tech_rsi_14", "tech_macd_hist", "tech_macd_cross",
    "tech_kdj_k", "tech_kdj_d", "tech_kdj_j", "tech_kdj_cross",
    "tech_ma_gap_5_20", "tech_price_vs_ma20", "tech_volatility_20d", "tech_volume_ratio_5_20",
]

FACTOR_DEFINITIONS: dict[str, dict[str, str]] = {
    "hop":                          {"factor_type": "event",      "description": "Event propagation hop count."},
    "kg_score":                     {"factor_type": "graph",      "description": "KG propagation score for the event-symbol pair."},
    "magnitude":                    {"factor_type": "event",      "description": "Event magnitude inferred from article cluster."},
    "confidence":                   {"factor_type": "event",      "description": "Event extraction confidence."},
    "event_type_code":              {"factor_type": "event",      "description": "Encoded event type."},
    "breadth_code":                 {"factor_type": "event",      "description": "Encoded event breadth."},
    "news_volume":                  {"factor_type": "sentiment",  "description": "News article volume backing the event."},
    "decay_factor":                 {"factor_type": "graph",      "description": "Template decay factor used during propagation."},
    "max_hop":                      {"factor_type": "graph",      "description": "Maximum hop allowed for the event template."},
    "industry":                     {"factor_type": "instrument", "description": "Instrument industry code."},
    "market":                       {"factor_type": "instrument", "description": "Instrument market code."},
    "window_score":                 {"factor_type": "window",     "description": "Window quality score from the timing scorer."},
    "net_sentiment":                {"factor_type": "sentiment",  "description": "Canonical net sentiment score."},
    "bf_net_sentiment":             {"factor_type": "sentiment",  "description": "Base-factor net sentiment score."},
    "bf_event_strength":            {"factor_type": "sentiment",  "description": "Base-factor event strength."},
    "bf_policy_intensity":          {"factor_type": "sentiment",  "description": "Base-factor policy intensity."},
    "bf_entity_density":            {"factor_type": "sentiment",  "description": "Base-factor entity density."},
    "bf_novelty":                   {"factor_type": "sentiment",  "description": "Base-factor novelty score."},
    "bf_volume_burst":              {"factor_type": "sentiment",  "description": "Base-factor article volume burst."},
    "bf_cross_source_confirmation": {"factor_type": "sentiment",  "description": "Base-factor cross-source confirmation."},
    "bf_noise_penalty":             {"factor_type": "sentiment",  "description": "Base-factor noise penalty."},
    "tech_rsi_14":                  {"factor_type": "technical",  "description": "14-day RSI."},
    "tech_macd_hist":               {"factor_type": "technical",  "description": "MACD histogram."},
    "tech_macd_cross":              {"factor_type": "technical",  "description": "MACD cross direction."},
    "tech_kdj_k":                   {"factor_type": "technical",  "description": "KDJ K line."},
    "tech_kdj_d":                   {"factor_type": "technical",  "description": "KDJ D line."},
    "tech_kdj_j":                   {"factor_type": "technical",  "description": "KDJ J line."},
    "tech_kdj_cross":               {"factor_type": "technical",  "description": "KDJ cross direction."},
    "tech_ma_gap_5_20":             {"factor_type": "technical",  "description": "5d versus 20d moving-average gap."},
    "tech_price_vs_ma20":           {"factor_type": "technical",  "description": "Spot price relative to 20d moving average."},
    "tech_volatility_20d":          {"factor_type": "technical",  "description": "20-day realized volatility."},
    "tech_volume_ratio_5_20":       {"factor_type": "technical",  "description": "5d volume divided by 20d volume."},
}

TECHNICAL_DEFAULTS: dict[str, float] = {
    "tech_rsi_14": 50.0, "tech_macd_hist": 0.0, "tech_macd_cross": 0.0,
    "tech_kdj_k": 50.0,  "tech_kdj_d": 50.0,    "tech_kdj_j": 50.0, "tech_kdj_cross": 0.0,
    "tech_ma_gap_5_20": 0.0, "tech_price_vs_ma20": 0.0,
    "tech_volatility_20d": 0.0, "tech_volume_ratio_5_20": 1.0,
}

GOLD_DEFAULTS: dict[str, float] = {
    "bf_net_sentiment": 0.0, "bf_event_strength": 0.0, "bf_policy_intensity": 0.0,
    "bf_entity_density": 0.0, "bf_novelty": 1.0, "bf_volume_burst": 0.0,
    "bf_cross_source_confirmation": 0.0, "bf_noise_penalty": 1.0,
}

FACTOR_TYPE_MAP: dict[str, str] = {
    name: spec["factor_type"]
    for name, spec in FACTOR_DEFINITIONS.items()
}


def factor_registry_rows() -> list[dict]:
    return [
        {
            "factor_name": name,
            "factor_type": FACTOR_DEFINITIONS.get(name, {}).get("factor_type", "model_feature"),
            "factor_layer": "feature_store",
            "description": FACTOR_DEFINITIONS.get(name, {}).get("description", name),
            "source": "factors",
        }
        for name in FEATURE_COLS
    ]
