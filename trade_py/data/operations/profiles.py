from __future__ import annotations

from trade_py.data.operations.contracts import DataProfile, OperationStep


CORE_STEPS = (
    OperationStep("kline", "kline_update", "A-share daily K-line incremental sync", {"mode": "incremental"}),
    OperationStep("index", "market_index", "Market and sector index sync", {}),
    OperationStep("fund-flow", "fund_flow_update", "Fund-flow incremental sync", {}),
    OperationStep("northbound", "northbound", "Northbound capital-flow sync", {}),
)

CRYPTO_STEPS = (
    OperationStep(
        "btc-assurance",
        "crypto_btc_fetch",
        "BTC assurance-gated OKX/Binance sync",
        {"canonical_writer": "btc_assurance"},
    ),
    OperationStep(
        "crypto-assets",
        "asset_batch_ingest",
        "Generic non-BTC crypto asset sync",
        {"asset_class": "crypto", "exclude_symbols": ["BTC"]},
    ),
)

EXTENDED_STEPS = (
    OperationStep("fundamental", "fundamental", "A-share fundamental sync", {}),
    OperationStep("macro", "macro", "China macro dataset sync", {}),
)

PROFILES: dict[str, DataProfile] = {
    "core": DataProfile(
        "core",
        1,
        "Daily structured A-share market data",
        CORE_STEPS,
    ),
    "crypto": DataProfile(
        "crypto",
        1,
        "BTC assurance plus generic non-BTC crypto data",
        CRYPTO_STEPS,
    ),
    "all": DataProfile(
        "all",
        1,
        "All initial structured-data profiles (news/sentiment excluded)",
        CORE_STEPS + CRYPTO_STEPS + EXTENDED_STEPS,
    ),
}


def get_profile(name: str) -> DataProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"unknown data profile {name!r}; choose core, crypto, or all") from exc
