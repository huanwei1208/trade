"""US event types must not disturb the A-share or crypto pipelines.

Two invariants are load-bearing and easy to break by accident:

1. feature_builder uses list(EventType).index() as a model feature, so the
   position of every pre-existing label must never move.
2. The A-share prompt must stay byte-identical to what it was before US
   types existed, or previously-enriched articles stop being comparable to
   newly-enriched ones.
"""

from __future__ import annotations

import json

from trade_py.data.news.edgar import ITEM_8K_EVENT_TYPES
from trade_py.db.event_db import (
    EVENT_TYPES_BY_MARKET,
    EventType,
    event_types_for_market,
)
from trade_py.intelligence.clients.base import (
    SYSTEM_PROMPT,
    USER_TEMPLATE,
    BaseLLMClient,
)

# The taxonomy exactly as it stood before US types were appended.
LEGACY_ORDER = [
    "semiconductor_policy", "new_energy_policy", "real_estate_easing",
    "real_estate_tightening", "rate_cut", "rate_hike", "commodity_surge",
    "commodity_slump", "defense_spending_up", "macro_recovery",
    "macro_slowdown", "geopolitical_risk", "earnings_beat", "earnings_miss",
    "merger_acquisition", "regulatory_tightening", "supply_disruption",
    "etf_approval", "etf_rejection", "hack_exploit", "exchange_bankruptcy",
    "exchange_listing", "exchange_delisting", "regulation_ban",
    "protocol_upgrade", "halving", "defi_exploit", "stablecoin_depeg",
    "institutional_adoption", "other",
]


def test_existing_enum_indices_are_frozen() -> None:
    """New labels append only; feature_builder indexes by position."""
    values = [e.value for e in EventType]
    assert values[:len(LEGACY_ORDER)] == LEGACY_ORDER
    # and spot-check the property the feature actually depends on
    for i, name in enumerate(LEGACY_ORDER):
        assert list(EventType).index(EventType(name)) == i


def test_us_labels_are_appended_after_other() -> None:
    values = [e.value for e in EventType]
    assert values.index("other") == len(LEGACY_ORDER) - 1
    assert "officer_change" in values[len(LEGACY_ORDER):]


class _Probe(BaseLLMClient):
    """Captures the prompt instead of calling a model."""

    def __init__(self, market=None):
        super().__init__(market=market)
        self.seen = None

    def _call_llm(self, prompt):
        self.seen = prompt
        return json.dumps({"sentiment_score": 0.0, "event_type": "other"}), 0, 0


def _prompt_for(market):
    c = _Probe(market=market)
    c.RATE_LIMIT_DELAY = 0
    c.analyze("t", "x")
    return c, c.seen


def test_default_prompt_is_unchanged_by_us_work() -> None:
    """No market given -> the historical A-share prompt, full taxonomy."""
    c, prompt = _prompt_for(None)
    assert c.system_prompt == SYSTEM_PROMPT
    assert "分析以下A股市场新闻" in prompt
    expected = USER_TEMPLATE.format(
        market_label="A股市场", title="t", text="x",
        event_types=json.dumps([e.value for e in EventType], ensure_ascii=False))
    assert prompt == expected


def test_cn_market_offers_no_us_or_crypto_labels() -> None:
    c, prompt = _prompt_for("cn")
    assert c.system_prompt == SYSTEM_PROMPT          # same framing as before
    assert "分析以下A股市场新闻" in prompt
    labels = set(EVENT_TYPES_BY_MARKET["cn"])
    assert "officer_change" not in labels and "halving" not in labels
    assert "semiconductor_policy" in labels and "other" in labels


def test_us_market_gets_us_framing_and_labels() -> None:
    c, prompt = _prompt_for("us")
    assert "美股市场" in c.system_prompt
    assert "分析以下美股市场新闻" in prompt
    labels = set(EVENT_TYPES_BY_MARKET["us"])
    assert {"officer_change", "buyback", "product_launch"} <= labels
    # A-share policy labels and crypto labels have no business here
    assert "semiconductor_policy" not in labels and "halving" not in labels
    # the summary stays Chinese: same reader
    assert "30字以内中文摘要" in prompt


def test_unknown_market_falls_back_to_full_taxonomy() -> None:
    assert event_types_for_market(None) == [e.value for e in EventType]
    assert event_types_for_market("jp") == [e.value for e in EventType]


def test_every_market_vocabulary_is_valid_and_has_other() -> None:
    valid = {e.value for e in EventType}
    for market, labels in EVENT_TYPES_BY_MARKET.items():
        assert set(labels) <= valid, market
        assert labels[-1] == "other", market
        assert len(labels) == len(set(labels)), market


def test_8k_item_map_targets_real_event_types() -> None:
    valid = {e.value for e in EventType}
    assert set(ITEM_8K_EVENT_TYPES.values()) <= valid
    # every mapped label must be offerable to the US prompt too, so filings
    # and news share one vocabulary
    assert set(ITEM_8K_EVENT_TYPES.values()) <= set(EVENT_TYPES_BY_MARKET["us"])
