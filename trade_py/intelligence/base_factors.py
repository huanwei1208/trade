"""Deterministic sentiment/event extraction used as the always-on base layer."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, asdict


_POSITIVE_TERMS = (
    "利好", "提振", "回暖", "改善", "增长", "上调", "超预期", "突破", "创新高",
    "签约", "中标", "扩产", "增持", "回购", "盈利", "景气", "扶持", "宽松",
)
_NEGATIVE_TERMS = (
    "利空", "下滑", "恶化", "收紧", "处罚", "亏损", "减持", "暴跌", "风险",
    "违约", "停产", "断供", "裁员", "调查", "问询", "诉讼", "制裁", "下修",
)
_POLICY_TERMS = (
    "政策", "国务院", "发改委", "证监会", "工信部", "财政部", "央行", "货币政策",
    "专项债", "补贴", "扶持", "监管", "征求意见", "指导意见", "工作方案",
)
_URGENT_TERMS = (
    "突发", "紧急", "立即", "立刻", "今日起", "今晚", "停牌", "复牌", "暴雷",
    "停产", "事故", "处罚", "暂停", "闪崩",
)
_CLICKBAIT_TERMS = (
    "炸裂", "疯传", "刷屏", "必看", "震惊", "速看", "重磅", "突发大消息",
)
_EVENT_RULES = (
    ("rate_cut", ("降息", "降准", "降贷款利率", "宽松", "流动性投放")),
    ("rate_hike", ("加息", "上调利率", "紧缩", "缩表")),
    ("semiconductor_policy", ("半导体", "芯片", "集成电路", "算力芯片")),
    ("new_energy_policy", ("新能源", "光伏", "储能", "锂电", "风电", "双碳")),
    ("real_estate_easing", ("楼市新政", "地产宽松", "降低首付", "取消限购", "稳地产")),
    ("real_estate_tightening", ("地产收紧", "房住不炒", "调控升级")),
    ("commodity_surge", ("涨价", "提价", "价格上涨", "创阶段新高")),
    ("commodity_slump", ("跌价", "价格下跌", "价格回落")),
    ("defense_spending_up", ("军费", "国防预算", "军工订单")),
    ("geopolitical_risk", ("贸易摩擦", "关税", "冲突", "地缘政治", "出口限制")),
    ("earnings_beat", ("业绩预增", "业绩超预期", "净利润增长", "扭亏为盈")),
    ("earnings_miss", ("业绩预减", "业绩不及预期", "由盈转亏", "亏损扩大")),
    ("merger_acquisition", ("并购", "收购", "重组", "资产注入")),
    ("regulatory_tightening", ("监管趋严", "处罚", "问询函", "立案", "整治")),
    ("supply_disruption", ("停产", "断供", "供应链中断", "罢工", "事故停工")),
)
_SECTOR_RULES = {
    "SW_Electronics": ("半导体", "芯片", "消费电子", "电子元件", "面板"),
    "SW_Computer": ("人工智能", "算力", "软件", "云计算", "数据中心", "网络安全"),
    "SW_Telecom": ("通信", "5g", "运营商", "光模块"),
    "SW_ElectricalEquipment": ("新能源", "储能", "锂电", "风电", "光伏", "充电桩"),
    "SW_Auto": ("汽车", "整车", "智能驾驶", "车企"),
    "SW_RealEstate": ("地产", "楼市", "房企", "住宅"),
    "SW_BuildingMaterial": ("水泥", "建材", "玻璃", "装修材料"),
    "SW_NonFerrousMetal": ("铜", "铝", "稀土", "黄金", "有色"),
    "SW_Petroleum": ("原油", "油气", "石油", "天然气"),
    "SW_Chemical": ("化工", "纯碱", "农药", "化纤"),
    "SW_Banking": ("银行", "信贷", "存款", "贷款"),
    "SW_NonBankFinancial": ("券商", "保险", "基金", "资本市场", "ipo"),
    "SW_Defense": ("军工", "国防", "导弹", "航空装备"),
    "SW_FoodBeverage": ("白酒", "食品饮料", "啤酒", "乳业"),
    "SW_Medicine": ("医药", "创新药", "集采", "药企", "医疗器械"),
    "SW_Agriculture": ("农业", "养殖", "种业", "农产品"),
}
_MARKET_WIDE_TERMS = ("全市场", "a股", "市场整体", "股市", "全行业", "宏观")
_MACRO_POSITIVE = ("复苏", "改善", "回升", "企稳", "回暖")
_MACRO_NEGATIVE = ("下行", "走弱", "衰退", "疲软", "承压")
_TOKEN_RE = re.compile(r"[A-Za-z]{2,}|\d+|[\u4e00-\u9fff]{2,}")


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _count_hits(text: str, terms: tuple[str, ...]) -> int:
    if not text:
        return 0
    return sum(text.count(term) for term in terms)


def _tokenize(text: str) -> set[str]:
    return {tok.lower() for tok in _TOKEN_RE.findall(text or "") if tok}


def _overlap_ratio(title: str, text: str) -> float:
    title_tokens = _tokenize(title)
    if not title_tokens:
        return 0.0
    body_tokens = _tokenize(text)
    if not body_tokens:
        return 0.0
    return len(title_tokens & body_tokens) / max(1, len(title_tokens))


def _sentiment_label(score: float) -> str:
    if score >= 0.15:
        return "positive"
    if score <= -0.15:
        return "negative"
    return "neutral"


def _deduce_event_type(text: str, score: float, policy_signal: bool) -> str:
    for event_type, terms in _EVENT_RULES:
        if any(term in text for term in terms):
            if event_type == "commodity_surge" and score < 0:
                return "commodity_slump"
            if event_type == "earnings_beat" and score < 0:
                return "earnings_miss"
            if event_type == "real_estate_easing" and score < 0:
                return "real_estate_tightening"
            return event_type
    if policy_signal:
        if any(term in text for term in _SECTOR_RULES["SW_Electronics"]):
            return "semiconductor_policy"
        if any(term in text for term in _SECTOR_RULES["SW_ElectricalEquipment"]):
            return "new_energy_policy"
        if any(term in text for term in _SECTOR_RULES["SW_RealEstate"]):
            return "real_estate_easing" if score >= 0 else "real_estate_tightening"
    if any(term in text for term in _MACRO_POSITIVE):
        return "macro_recovery"
    if any(term in text for term in _MACRO_NEGATIVE):
        return "macro_slowdown"
    return "other"


@dataclass
class BaseSemanticResult:
    sentiment_score: float = 0.0
    sentiment_label: str = "neutral"
    event_type: str = "other"
    event_magnitude: float = 0.0
    affected_sectors: list[str] | None = None
    key_entities: list[str] | None = None
    summary: str = ""
    confidence: float = 0.0
    policy_signal: bool = False
    market_impact_scope: str = "individual"
    time_sensitivity: str = "short_term"
    event_chain: str = ""
    entity_density: float = 0.0
    novelty_score: float = 1.0
    noise_score: float = 0.0

    def __post_init__(self) -> None:
        if self.affected_sectors is None:
            self.affected_sectors = []
        if self.key_entities is None:
            self.key_entities = []

    def to_dict(self) -> dict:
        return asdict(self)


def analyze_article(
    title: str,
    text: str,
    *,
    source: str = "",
    symbols: list[str] | None = None,
    symbol_sectors: list[str] | None = None,
    title_frequency: int = 1,
) -> BaseSemanticResult:
    combined = f"{title} {text}".strip()
    normalized = combined.lower()
    symbols = sorted(set(symbols or []))
    symbol_sectors = sorted(set(symbol_sectors or []))

    positive_hits = _count_hits(combined, _POSITIVE_TERMS)
    negative_hits = _count_hits(combined, _NEGATIVE_TERMS)
    policy_hits = _count_hits(combined, _POLICY_TERMS)
    urgent_hits = _count_hits(combined, _URGENT_TERMS)
    clickbait_hits = _count_hits(combined, _CLICKBAIT_TERMS)

    raw_sent = positive_hits - negative_hits
    sentiment_score = math.tanh(raw_sent / 3.0)
    if "下调" in combined or "收紧" in combined or "处罚" in combined:
        sentiment_score = min(sentiment_score, -0.25)
    if "超预期" in combined or "回购" in combined or "增持" in combined:
        sentiment_score = max(sentiment_score, 0.25)

    policy_signal = policy_hits > 0
    event_type = _deduce_event_type(normalized, sentiment_score, policy_signal)

    keyword_sectors = [
        sector
        for sector, aliases in _SECTOR_RULES.items()
        if any(alias.lower() in normalized for alias in aliases)
    ]
    affected_sectors = sorted(set(symbol_sectors + keyword_sectors)) or ["SW_Unknown"]

    if any(term in normalized for term in _MARKET_WIDE_TERMS) or len(affected_sectors) >= 3:
        scope = "market"
    elif len(affected_sectors) >= 1 or policy_signal:
        scope = "sector"
    else:
        scope = "individual"

    if urgent_hits > 0 or any(term in normalized for term in ("停产", "停牌", "处罚", "断供")):
        sensitivity = "immediate"
    elif policy_signal or event_type in {"earnings_beat", "earnings_miss", "merger_acquisition"}:
        sensitivity = "short_term"
    else:
        sensitivity = "medium_long"

    novelty_score = _clip(1.0 / max(1, title_frequency), 0.15, 1.0)
    entity_density = _clip((len(symbols) + len(affected_sectors)) / 5.0, 0.0, 1.0)
    title_body_overlap = _overlap_ratio(title, text)
    noise_score = _clip(
        (0.45 * (1.0 - novelty_score))
        + (0.2 * min(clickbait_hits, 2) / 2.0)
        + (0.2 * (1.0 - entity_density))
        + (0.15 * (1.0 - title_body_overlap)),
        0.0,
        1.0,
    )

    magnitude = _clip(
        0.2
        + 0.25 * abs(sentiment_score)
        + 0.15 * min(urgent_hits, 2) / 2.0
        + 0.15 * (1.0 if policy_signal else 0.0)
        + 0.1 * (1.0 if scope == "market" else 0.6 if scope == "sector" else 0.3)
        + 0.15 * entity_density
        - 0.15 * noise_score,
        0.0,
        1.0,
    )

    confidence = _clip(
        0.35
        + 0.15 * (1.0 if event_type != "other" else 0.0)
        + 0.1 * (1.0 if policy_signal else 0.0)
        + 0.15 * entity_density
        + 0.1 * title_body_overlap
        + 0.05 * novelty_score
        - 0.2 * noise_score,
        0.05,
        0.95,
    )

    summary = (title or text or "").strip()
    if len(summary) > 40:
        summary = summary[:40]

    return BaseSemanticResult(
        sentiment_score=round(float(sentiment_score), 4),
        sentiment_label=_sentiment_label(sentiment_score),
        event_type=event_type,
        event_magnitude=round(float(magnitude), 4),
        affected_sectors=affected_sectors,
        key_entities=symbols[:8],
        summary=summary,
        confidence=round(float(confidence), 4),
        policy_signal=policy_signal,
        market_impact_scope=scope,
        time_sensitivity=sensitivity,
        event_chain="",
        entity_density=round(float(entity_density), 4),
        novelty_score=round(float(novelty_score), 4),
        noise_score=round(float(noise_score), 4),
    )
