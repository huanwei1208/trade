"""Historical event database for event propagation ML pipeline.

An HistoricalEvent records a structured market event extracted from news,
covering event type, magnitude, actor type, and affected sectors.
Events are stored in Parquet and loaded on demand for training/inference.

Usage:
    db = EventDatabase("data/events")
    db.add(HistoricalEvent(...))
    db.save()
    all_events = db.events
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, asdict
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ── Event type taxonomy (mirrors plan Section 4.3) ────────────────────────────

class EventType(str, Enum):
    semiconductor_policy  = "semiconductor_policy"   # 半导体/电子政策支持
    new_energy_policy     = "new_energy_policy"      # 新能源/双碳政策
    real_estate_easing    = "real_estate_easing"     # 地产宽松政策
    real_estate_tightening= "real_estate_tightening" # 地产收紧政策
    rate_cut              = "rate_cut"               # 降息/宽货币
    rate_hike             = "rate_hike"              # 加息/紧货币
    commodity_surge       = "commodity_surge"        # 大宗商品价格大涨
    commodity_slump       = "commodity_slump"        # 大宗商品价格大跌
    defense_spending_up   = "defense_spending_up"    # 国防军费增加
    macro_recovery        = "macro_recovery"         # 宏观经济复苏
    macro_slowdown        = "macro_slowdown"         # 宏观经济下行
    geopolitical_risk     = "geopolitical_risk"      # 地缘政治/贸易摩擦
    earnings_beat         = "earnings_beat"          # 业绩超预期
    earnings_miss         = "earnings_miss"          # 业绩低于预期
    merger_acquisition    = "merger_acquisition"     # 并购重组
    regulatory_tightening = "regulatory_tightening"  # 监管收紧（互联网/教育等）
    supply_disruption     = "supply_disruption"      # 供应链中断
    other                 = "other"                  # 其他


class ActorType(str, Enum):
    """Market actor personality archetypes (Section 4.3C of the plan)."""
    trump_style     = "trump_style"      # 高波动/零和博弈/意外冲击
    dovish_central  = "dovish_central"   # 鸽派央行/数据驱动/渐进
    hawkish_central = "hawkish_central"  # 鹰派央行/通胀优先
    china_policy    = "china_policy"     # 中国政策型/长期战略/突然纠偏
    elon_style      = "elon_style"       # 社媒驱动/信念投资/高波动
    corporate_mgmt  = "corporate_mgmt"   # 普通企业管理层
    regulator       = "regulator"        # 监管机构（SEC/CSRC等）
    unknown         = "unknown"


# ── Risk score per actor (used as feature in Group A) ─────────────────────────

ACTOR_RISK_SCORES: dict[ActorType, float] = {
    ActorType.trump_style:     0.90,  # 极高不确定性
    ActorType.dovish_central:  0.25,
    ActorType.hawkish_central: 0.45,
    ActorType.china_policy:    0.55,
    ActorType.elon_style:      0.80,
    ActorType.corporate_mgmt:  0.30,
    ActorType.regulator:       0.50,
    ActorType.unknown:         0.40,
}


# ── HistoricalEvent dataclass ─────────────────────────────────────────────────

@dataclass
class HistoricalEvent:
    """A structured market event extracted from news or filings.

    Fields match the training sample structure described in plan Section 4.2.
    """
    event_date:      date          # Date the event was published/occurred
    event_type:      EventType     # Taxonomy label
    magnitude:       float         # LLM-scored event strength [0, 1]
    actor_type:      ActorType     # Who triggered the event
    primary_sector:  str           # Primary affected SW sector (e.g. "SW_Electronics")
    breadth:         str           # "stock", "sector", "market"
    sentiment_score: float         # LLM sentiment [-1, +1]
    news_volume:     int           # Number of articles on this event date
    summary:         str           # 1-2 sentence summary
    source_url:      str = ""      # Reference news URL
    # Derived / cached at build time
    actor_risk_score: float = 0.0
    event_id: str = ""             # SHA1 hash of (date + type + primary_sector)

    def __post_init__(self) -> None:
        if isinstance(self.event_type, str):
            self.event_type = EventType(self.event_type)
        if isinstance(self.actor_type, str):
            self.actor_type = ActorType(self.actor_type)
        if not self.actor_risk_score:
            self.actor_risk_score = ACTOR_RISK_SCORES.get(self.actor_type, 0.40)
        if not self.event_id:
            key = f"{self.event_date}|{self.event_type.value}|{self.primary_sector}"
            self.event_id = hashlib.sha1(key.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["event_date"]  = self.event_date.isoformat()
        d["event_type"]  = self.event_type.value
        d["actor_type"]  = self.actor_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "HistoricalEvent":
        d = dict(d)
        d["event_date"]  = date.fromisoformat(str(d["event_date"]))
        d["event_type"]  = EventType(d["event_type"])
        d["actor_type"]  = ActorType(d["actor_type"])
        return cls(**d)


# ── EventDatabase ─────────────────────────────────────────────────────────────

class EventDatabase:
    """Persistent store of HistoricalEvent records backed by Parquet.

    Layout:
        {data_root}/events/historical_events.parquet
    """

    _PARQUET_FILE = "historical_events.parquet"

    def __init__(self, data_root: str | Path) -> None:
        self._root = Path(data_root) / "events"
        self._events: list[HistoricalEvent] = []
        self._loaded = False

    # ── I/O ───────────────────────────────────────────────────────────────────

    def load(self) -> None:
        """Load events from Parquet into memory."""
        path = self._root / self._PARQUET_FILE
        if not path.exists():
            logger.info("EventDatabase: no file at %s, starting empty", path)
            self._loaded = True
            return
        df = pd.read_parquet(path)
        self._events = [HistoricalEvent.from_dict(row) for _, row in df.iterrows()]
        self._loaded = True
        logger.info("EventDatabase: loaded %d events from %s", len(self._events), path)

    def save(self) -> None:
        """Persist all events to Parquet."""
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / self._PARQUET_FILE
        if not self._events:
            logger.warning("EventDatabase: no events to save")
            return
        df = pd.DataFrame([e.to_dict() for e in self._events])
        df = df.drop_duplicates(subset=["event_id"], keep="last")
        df.to_parquet(path, index=False)
        logger.info("EventDatabase: saved %d events to %s", len(df), path)

    # ── Mutation ──────────────────────────────────────────────────────────────

    def add(self, event: HistoricalEvent) -> None:
        """Add or replace an event (matched by event_id)."""
        if not self._loaded:
            self.load()
        existing_ids = {e.event_id for e in self._events}
        if event.event_id in existing_ids:
            self._events = [e for e in self._events if e.event_id != event.event_id]
        self._events.append(event)

    def add_many(self, events: list[HistoricalEvent]) -> None:
        for e in events:
            self.add(e)

    # ── Queries ───────────────────────────────────────────────────────────────

    @property
    def events(self) -> list[HistoricalEvent]:
        if not self._loaded:
            self.load()
        return list(self._events)

    def filter(
        self,
        event_type:  Optional[EventType] = None,
        start_date:  Optional[date] = None,
        end_date:    Optional[date] = None,
        sector:      Optional[str] = None,
        min_magnitude: float = 0.0,
    ) -> list[HistoricalEvent]:
        """Filter events by optional criteria."""
        if not self._loaded:
            self.load()
        result = self._events
        if event_type is not None:
            result = [e for e in result if e.event_type == event_type]
        if start_date is not None:
            result = [e for e in result if e.event_date >= start_date]
        if end_date is not None:
            result = [e for e in result if e.event_date <= end_date]
        if sector is not None:
            result = [e for e in result if e.primary_sector == sector]
        if min_magnitude > 0.0:
            result = [e for e in result if e.magnitude >= min_magnitude]
        return result

    def to_dataframe(self) -> pd.DataFrame:
        """Return all events as a DataFrame."""
        if not self._loaded:
            self.load()
        if not self._events:
            return pd.DataFrame()
        return pd.DataFrame([e.to_dict() for e in self._events])

    def __len__(self) -> int:
        if not self._loaded:
            self.load()
        return len(self._events)

    def __repr__(self) -> str:
        return f"EventDatabase(n={len(self)}, root={self._root})"


# ── LLM extraction helper ─────────────────────────────────────────────────────

def extract_event_from_claude(result, article_date: date, source_url: str = "",
                               news_volume: int = 1) -> Optional[HistoricalEvent]:
    """Convert a ClaudeClient analysis result into a HistoricalEvent.

    Args:
        result: ClaudeClient.SentimentResult object
        article_date: Publication date
        source_url: Original article URL
        news_volume: Number of related articles on that day

    Returns:
        HistoricalEvent or None if event_type is 'other' with low magnitude
    """
    # Map Claude's free-form event_type to our taxonomy
    event_type_map = {
        "semiconductor": EventType.semiconductor_policy,
        "chip":          EventType.semiconductor_policy,
        "new_energy":    EventType.new_energy_policy,
        "ev":            EventType.new_energy_policy,
        "real_estate":   EventType.real_estate_easing,
        "property":      EventType.real_estate_easing,
        "rate_cut":      EventType.rate_cut,
        "rate_hike":     EventType.rate_hike,
        "commodity":     EventType.commodity_surge,
        "defense":       EventType.defense_spending_up,
        "macro":         EventType.macro_recovery,
        "geopolitical":  EventType.geopolitical_risk,
        "trade":         EventType.geopolitical_risk,
        "earnings":      EventType.earnings_beat,
        "acquisition":   EventType.merger_acquisition,
        "regulatory":    EventType.regulatory_tightening,
    }

    raw_type = getattr(result, "event_type", "other").lower()
    event_type = EventType.other
    for key, val in event_type_map.items():
        if key in raw_type:
            event_type = val
            break

    magnitude = float(getattr(result, "event_magnitude", 0.5))
    if event_type == EventType.other and magnitude < 0.4:
        return None

    sectors = getattr(result, "affected_sectors", [])
    primary_sector = f"SW_{sectors[0]}" if sectors else "SW_Unknown"

    return HistoricalEvent(
        event_date=article_date,
        event_type=event_type,
        magnitude=magnitude,
        actor_type=ActorType.unknown,
        primary_sector=primary_sector,
        breadth="sector" if sectors else "market",
        sentiment_score=float(getattr(result, "sentiment_score", 0.0)),
        news_volume=news_volume,
        summary=getattr(result, "summary", ""),
        source_url=source_url,
    )
