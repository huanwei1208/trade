"""A-share sector knowledge graph for event propagation.

Encodes supply chain, policy linkage, and fund flow relationships
between 31 SW Level-1 industries. Used to propagate event signals
across related sectors.

Usage:
    graph = SectorGraph()
    results = graph.propagate("SW_Electronics", "semiconductor_policy", max_hop=2)
    for r in results:
        print(r.sector, r.score, r.path)
"""

from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from enum import IntEnum
from pathlib import Path
from typing import Optional


# ── Sector IDs (mirror SWIndustry C++ enum) ──────────────────────────────────

class SW(IntEnum):
    Agriculture = 0
    Mining = 1
    Chemical = 2
    Steel = 3
    NonFerrousMetal = 4
    Electronics = 5
    Auto = 6
    HouseholdAppliance = 7
    FoodBeverage = 8
    Textile = 9
    LightManufacturing = 10
    Medicine = 11
    Utilities = 12
    Transportation = 13
    RealEstate = 14
    Commerce = 15
    SocialService = 16
    Banking = 17
    NonBankFinancial = 18
    Construction = 19
    BuildingMaterial = 20
    MechanicalEquipment = 21
    Defense = 22
    Computer = 23
    Media = 24
    Telecom = 25
    Environment = 26
    ElectricalEquipment = 27
    Beauty = 28
    Coal = 29
    Petroleum = 30


SW_NAMES_ZH = {
    SW.Agriculture: "农林牧渔",
    SW.Mining: "采掘",
    SW.Chemical: "化工",
    SW.Steel: "钢铁",
    SW.NonFerrousMetal: "有色金属",
    SW.Electronics: "电子",
    SW.Auto: "汽车",
    SW.HouseholdAppliance: "家用电器",
    SW.FoodBeverage: "食品饮料",
    SW.Textile: "纺织服装",
    SW.LightManufacturing: "轻工制造",
    SW.Medicine: "医药生物",
    SW.Utilities: "公用事业",
    SW.Transportation: "交通运输",
    SW.RealEstate: "房地产",
    SW.Commerce: "商业贸易",
    SW.SocialService: "社会服务",
    SW.Banking: "银行",
    SW.NonBankFinancial: "非银金融",
    SW.Construction: "建筑装饰",
    SW.BuildingMaterial: "建筑材料",
    SW.MechanicalEquipment: "机械设备",
    SW.Defense: "国防军工",
    SW.Computer: "计算机",
    SW.Media: "传媒",
    SW.Telecom: "通信",
    SW.Environment: "环保",
    SW.ElectricalEquipment: "电气设备",
    SW.Beauty: "美容护理",
    SW.Coal: "煤炭",
    SW.Petroleum: "石油石化",
}


# ── Edge types ────────────────────────────────────────────────────────────────

RELATION_TYPES = [
    "upstream_supply",    # 上游供应：source是target的原材料/零部件供应商
    "downstream_demand",  # 下游需求：source是target的客户/下游应用场景
    "policy_linkage",     # 政策联动：受同一政策主题影响
    "competition",        # 竞争替代：同类产品/服务竞争
    "fund_rotation",      # 资金轮动：机构在两板块间切换
    "macro_exposure",     # 宏观因子暴露：对同一宏观因子（利率/汇率/PPI）的暴露相似
]


@dataclass
class SectorEdge:
    source: SW          # 事件发生板块
    target: SW          # 受传导影响板块
    relation: str       # edge type from RELATION_TYPES
    weight: float       # propagation strength [0, 1]
    direction: int      # +1 同向(利好传导利好), -1 反向(成本上升→下游受损)
    typical_days: int   # median propagation lag in trading days
    description: str = ""  # human-readable explanation in Chinese


@dataclass
class PropagationResult:
    sector: SW
    sector_name: str
    score: float        # adjusted propagation score (weight × direction)
    hop: int            # 1=direct, 2=second-order
    path: list[str]     # e.g. ["SW_NonFerrousMetal", "SW_Electronics"]
    relation: str       # relation type of the decisive edge
    typical_days: int   # expected propagation lag
    description: str = ""


# ── Sector graph ──────────────────────────────────────────────────────────────

# All edges encoding A-share supply chain domain knowledge
# Weight scale: 0.9=very strong, 0.7=strong, 0.5=moderate, 0.3=weak
_EDGES: list[SectorEdge] = [
    # ── 上游原材料 → 工业制造 ─────────────────────────────────────────────────
    SectorEdge(SW.NonFerrousMetal, SW.Electronics,        "upstream_supply",   0.75, +1, 8,
               "稀土/铜/铝是半导体、PCB等电子产品核心原材料"),
    SectorEdge(SW.NonFerrousMetal, SW.Auto,               "upstream_supply",   0.65, +1, 10,
               "铜/铝/锂是汽车（尤其新能源车）关键材料"),
    SectorEdge(SW.NonFerrousMetal, SW.ElectricalEquipment,"upstream_supply",   0.80, +1, 7,
               "锂/钴/镍是动力电池核心，稀土是永磁电机核心"),
    SectorEdge(SW.NonFerrousMetal, SW.MechanicalEquipment,"upstream_supply",   0.45, +1, 12,
               "铜/铝是机械设备常用金属材料"),
    SectorEdge(SW.NonFerrousMetal, SW.Defense,            "upstream_supply",   0.55, +1, 15,
               "钛/特种合金是国防航空航天核心材料"),
    SectorEdge(SW.Coal,            SW.Utilities,          "upstream_supply",   0.75, +1, 5,
               "煤炭是火电发电主要燃料，煤价直接影响电力成本"),
    SectorEdge(SW.Coal,            SW.Steel,              "upstream_supply",   0.70, +1, 7,
               "焦煤是炼钢关键原料"),
    SectorEdge(SW.Coal,            SW.Chemical,           "upstream_supply",   0.55, +1, 10,
               "煤化工：煤炭是合成氨/甲醇等化工品原料"),
    SectorEdge(SW.Petroleum,       SW.Chemical,           "upstream_supply",   0.85, +1, 5,
               "石油/天然气是化工品最重要上游原料（乙烯/丙烯/PTA等）"),
    SectorEdge(SW.Petroleum,       SW.Transportation,     "upstream_supply",   0.55, +1, 3,
               "燃油价格直接影响航运/航空运营成本"),
    SectorEdge(SW.Petroleum,       SW.Auto,               "upstream_supply",   0.35, -1, 5,
               "油价上涨促进新能源车替代，传统燃油车需求承压"),
    SectorEdge(SW.Steel,           SW.Construction,       "upstream_supply",   0.75, +1, 8,
               "螺纹钢/型钢是建筑施工核心原料"),
    SectorEdge(SW.Steel,           SW.BuildingMaterial,   "upstream_supply",   0.55, +1, 8,
               "钢材是门窗/钢结构建材原料"),
    SectorEdge(SW.Steel,           SW.MechanicalEquipment,"upstream_supply",   0.65, +1, 10,
               "钢铁是机械设备主要结构材料"),
    SectorEdge(SW.Steel,           SW.Auto,               "upstream_supply",   0.55, +1, 10,
               "汽车用钢（含高强钢）是钢铁重要下游"),
    SectorEdge(SW.Mining,          SW.Steel,              "upstream_supply",   0.70, +1, 7,
               "铁矿石是炼铁炼钢核心原料"),
    SectorEdge(SW.Mining,          SW.NonFerrousMetal,    "upstream_supply",   0.65, +1, 7,
               "铜/铝/锌矿是有色金属上游资源"),
    SectorEdge(SW.Chemical,        SW.Agriculture,        "upstream_supply",   0.55, +1, 10,
               "化肥/农药是农业生产必需品"),
    SectorEdge(SW.Chemical,        SW.Medicine,           "upstream_supply",   0.50, +1, 15,
               "原料药/化学中间体是医药工业关键投入"),
    SectorEdge(SW.Chemical,        SW.Auto,               "upstream_supply",   0.45, +1, 12,
               "工程塑料/橡胶是汽车零部件重要材料"),
    SectorEdge(SW.Chemical,        SW.ElectricalEquipment,"upstream_supply",   0.45, +1, 10,
               "电池电解液/隔膜等化工材料是新能源核心"),
    SectorEdge(SW.Electronics,     SW.Computer,           "upstream_supply",   0.55, +1, 10,
               "芯片/存储/显示面板等电子元器件是计算机核心部件"),
    SectorEdge(SW.Electronics,     SW.Telecom,            "upstream_supply",   0.50, +1, 12,
               "基站/通信设备使用大量电子器件"),
    SectorEdge(SW.Electronics,     SW.Auto,               "upstream_supply",   0.45, +1, 12,
               "汽车电子化提升（智能驾驶/座舱）"),
    SectorEdge(SW.Electronics,     SW.Media,              "upstream_supply",   0.30, +1, 15,
               "显示屏/存储是传媒终端硬件基础"),

    # ── 下游需求传导 ──────────────────────────────────────────────────────────
    SectorEdge(SW.RealEstate,      SW.Construction,       "downstream_demand", 0.85, +1, 5,
               "房地产开工直接带动建筑施工需求"),
    SectorEdge(SW.RealEstate,      SW.BuildingMaterial,   "downstream_demand", 0.80, +1, 7,
               "房地产竣工带动水泥/玻璃/防水等建材需求"),
    SectorEdge(SW.RealEstate,      SW.HouseholdAppliance, "downstream_demand", 0.70, +1, 10,
               "房屋交付带动家电购置需求（白电尤其明显）"),
    SectorEdge(SW.RealEstate,      SW.Commerce,           "downstream_demand", 0.40, +1, 15,
               "房产交易带动家居/家具/装修商业需求"),
    SectorEdge(SW.RealEstate,      SW.LightManufacturing, "downstream_demand", 0.35, +1, 15,
               "装修带动轻工制造（家具/灯饰等）需求"),

    # ── 政策联动 ──────────────────────────────────────────────────────────────
    SectorEdge(SW.Banking,         SW.NonBankFinancial,   "policy_linkage",    0.70, +1, 3,
               "金融监管政策同步影响银行和非银（证券/保险/信托）"),
    SectorEdge(SW.Banking,         SW.RealEstate,         "policy_linkage",    0.65, +1, 5,
               "按揭利率/房贷政策联动：地产宽松伴随银行信贷放松"),
    SectorEdge(SW.NonBankFinancial,SW.Banking,            "policy_linkage",    0.60, +1, 3,
               "资本市场政策同时影响券商和银行"),
    SectorEdge(SW.Defense,         SW.ElectricalEquipment,"policy_linkage",    0.65, +1, 10,
               "国防信息化/电子化采购拉动电气/电子设备"),
    SectorEdge(SW.Defense,         SW.MechanicalEquipment,"policy_linkage",    0.55, +1, 10,
               "军工装备采购含大量精密机械制造需求"),
    SectorEdge(SW.Defense,         SW.Computer,           "policy_linkage",    0.50, +1, 12,
               "信息化国防对国产操作系统/安全计算需求"),
    SectorEdge(SW.Medicine,        SW.SocialService,      "policy_linkage",    0.50, +1, 8,
               "医疗体制改革同步影响医院/养老等社会服务"),
    SectorEdge(SW.Utilities,       SW.Environment,        "policy_linkage",    0.55, +1, 8,
               "电力转型/双碳政策联动环保行业"),
    SectorEdge(SW.ElectricalEquipment, SW.Auto,           "policy_linkage",    0.65, +1, 8,
               "新能源政策同时利好动力电池和新能源整车"),
    SectorEdge(SW.ElectricalEquipment, SW.Environment,    "policy_linkage",    0.45, +1, 10,
               "储能/光伏政策联动绿色环保概念"),
    SectorEdge(SW.Computer,        SW.Media,              "policy_linkage",    0.40, +1, 12,
               "数字经济/互联网监管政策同步影响科技与传媒"),
    SectorEdge(SW.Computer,        SW.Telecom,            "policy_linkage",    0.45, +1, 8,
               "数字基础设施投资联动计算机和通信"),

    # ── 资金轮动 ──────────────────────────────────────────────────────────────
    # Growth style rotation (when growth in favor)
    SectorEdge(SW.Electronics,     SW.Computer,           "fund_rotation",     0.55, +1, 2,
               "成长风格资金在科技板块内部快速轮动"),
    SectorEdge(SW.Computer,        SW.Electronics,        "fund_rotation",     0.55, +1, 2,
               "TMT板块资金内轮动"),
    SectorEdge(SW.Electronics,     SW.Defense,            "fund_rotation",     0.40, +1, 3,
               "高端制造资金轮动"),
    SectorEdge(SW.Defense,         SW.ElectricalEquipment,"fund_rotation",     0.45, +1, 3,
               "成长/高端制造资金轮动"),
    # Value style rotation (when value in favor)
    SectorEdge(SW.Banking,         SW.Utilities,          "fund_rotation",     0.45, +1, 3,
               "高股息价值风格资金轮动"),
    SectorEdge(SW.Banking,         SW.Coal,               "fund_rotation",     0.40, +1, 3,
               "红利板块内资金轮动（银行→煤炭高股息）"),
    SectorEdge(SW.Coal,            SW.Petroleum,          "fund_rotation",     0.50, +1, 2,
               "能源板块资金轮动"),
    SectorEdge(SW.Petroleum,       SW.Coal,               "fund_rotation",     0.50, +1, 2,
               "能源板块资金轮动"),
    # Cyclical rotation
    SectorEdge(SW.Steel,           SW.NonFerrousMetal,    "fund_rotation",     0.55, +1, 2,
               "顺周期大宗商品板块内轮动"),
    SectorEdge(SW.NonFerrousMetal, SW.Mining,             "fund_rotation",     0.50, +1, 2,
               "资源板块资金轮动"),

    # ── 宏观因子暴露 ──────────────────────────────────────────────────────────
    SectorEdge(SW.Banking,         SW.RealEstate,         "macro_exposure",    0.55, +1, 5,
               "对利率因子同向暴露（降息均利好）"),
    SectorEdge(SW.Utilities,       SW.Banking,            "macro_exposure",    0.40, +1, 5,
               "高股息板块对无风险利率暴露相似"),
    SectorEdge(SW.Steel,           SW.Chemical,           "macro_exposure",    0.50, +1, 5,
               "对PPI因子同向暴露（PPI上行同时利好）"),
    SectorEdge(SW.Mining,          SW.NonFerrousMetal,    "macro_exposure",    0.60, +1, 3,
               "对大宗商品价格因子同向暴露"),
    SectorEdge(SW.Agriculture,     SW.FoodBeverage,       "macro_exposure",    0.45, -1, 8,
               "农产品价格上涨→食饮成本压力（反向暴露）"),
    SectorEdge(SW.Petroleum,       SW.Transportation,     "macro_exposure",    0.50, -1, 3,
               "油价上涨→航运/航空成本压力"),

    # ── 竞争替代 ──────────────────────────────────────────────────────────────
    SectorEdge(SW.Auto,            SW.Transportation,     "competition",       0.35, -1, 20,
               "新能源车渗透→公共交通/共享出行部分替代"),
    SectorEdge(SW.ElectricalEquipment, SW.Coal,           "competition",       0.40, -1, 30,
               "新能源发电替代煤电（长期结构性压力）"),
    SectorEdge(SW.ElectricalEquipment, SW.Petroleum,      "competition",       0.35, -1, 30,
               "电动化替代燃油（长期）"),
]

# ── Event type → primary sector mapping ──────────────────────────────────────
# Each event type maps to a list of (sector, impact_score) pairs
# where impact_score > 0 = positive for sector, < 0 = negative
EVENT_SECTOR_MAPPING: dict[str, list[tuple[SW, float]]] = {
    "semiconductor_policy": [          # 半导体/电子政策支持
        (SW.Electronics, +0.90),
        (SW.Computer, +0.70),
        (SW.NonFerrousMetal, +0.60),   # 稀土
        (SW.Defense, +0.55),
        (SW.ElectricalEquipment, +0.50),
        (SW.MechanicalEquipment, +0.40),
    ],
    "new_energy_policy": [             # 新能源/双碳政策
        (SW.ElectricalEquipment, +0.90),
        (SW.Auto, +0.75),              # 新能源车
        (SW.NonFerrousMetal, +0.70),   # 锂/钴/镍/稀土
        (SW.Chemical, +0.50),          # 电解液/隔膜材料
        (SW.Environment, +0.50),
        (SW.Coal, -0.50),              # 煤电替代压力
        (SW.Petroleum, -0.35),
    ],
    "real_estate_easing": [            # 地产宽松政策
        (SW.RealEstate, +0.90),
        (SW.Construction, +0.80),
        (SW.BuildingMaterial, +0.75),
        (SW.Banking, +0.60),
        (SW.HouseholdAppliance, +0.60),
        (SW.Steel, +0.50),
        (SW.Commerce, +0.40),
    ],
    "real_estate_tightening": [        # 地产收紧政策
        (SW.RealEstate, -0.85),
        (SW.Construction, -0.70),
        (SW.BuildingMaterial, -0.65),
        (SW.Banking, -0.45),
        (SW.HouseholdAppliance, -0.50),
        (SW.Steel, -0.40),
    ],
    "rate_cut": [                      # 降息/宽货币
        (SW.Banking, +0.55),
        (SW.NonBankFinancial, +0.65),
        (SW.RealEstate, +0.70),
        (SW.Utilities, +0.50),
        (SW.ElectricalEquipment, +0.40),
    ],
    "rate_hike": [                     # 加息/紧货币
        (SW.Banking, +0.30),           # 利差扩大
        (SW.NonBankFinancial, -0.30),
        (SW.RealEstate, -0.65),
        (SW.Utilities, -0.40),
        (SW.Computer, -0.45),          # 高估值成长股折现率上升
        (SW.ElectricalEquipment, -0.40),
    ],
    "commodity_surge": [               # 大宗商品价格大涨
        (SW.NonFerrousMetal, +0.85),
        (SW.Coal, +0.80),
        (SW.Mining, +0.75),
        (SW.Petroleum, +0.80),
        (SW.Steel, +0.70),
        (SW.Chemical, +0.50),
        (SW.Auto, -0.35),              # 成本压力
        (SW.ElectricalEquipment, -0.30),
        (SW.MechanicalEquipment, -0.30),
    ],
    "commodity_slump": [               # 大宗商品价格大跌
        (SW.NonFerrousMetal, -0.80),
        (SW.Coal, -0.75),
        (SW.Mining, -0.70),
        (SW.Petroleum, -0.75),
        (SW.Steel, -0.65),
        (SW.Chemical, -0.45),
        (SW.Auto, +0.30),              # 成本减轻受益
        (SW.ElectricalEquipment, +0.25),
    ],
    "defense_spending_up": [           # 国防军费增加
        (SW.Defense, +0.90),
        (SW.ElectricalEquipment, +0.65),
        (SW.MechanicalEquipment, +0.60),
        (SW.Computer, +0.55),
        (SW.NonFerrousMetal, +0.40),
    ],
    "macro_recovery": [                # 宏观经济复苏
        (SW.Banking, +0.60),
        (SW.Steel, +0.55),
        (SW.NonFerrousMetal, +0.55),
        (SW.Auto, +0.60),
        (SW.HouseholdAppliance, +0.55),
        (SW.Commerce, +0.50),
        (SW.Transportation, +0.50),
        (SW.RealEstate, +0.45),
    ],
    "macro_slowdown": [                # 宏观经济下行
        (SW.FoodBeverage, +0.30),      # 防御
        (SW.Medicine, +0.25),
        (SW.Utilities, +0.20),
        (SW.Banking, -0.40),
        (SW.Steel, -0.55),
        (SW.Auto, -0.45),
        (SW.RealEstate, -0.50),
    ],
    "geopolitical_risk": [             # 地缘政治/贸易摩擦
        (SW.Defense, +0.80),
        (SW.Computer, +0.50),          # 国产替代
        (SW.Electronics, +0.45),       # 自主可控
        (SW.Agriculture, +0.40),       # 粮食安全
        (SW.Telecom, +0.40),
        (SW.Transportation, -0.35),    # 贸易量下降
    ],
}


# ── Core graph class ──────────────────────────────────────────────────────────

class SectorGraph:
    """A-share sector relationship graph with event propagation."""

    def __init__(self, edges: Optional[list[SectorEdge]] = None,
                 event_mapping: Optional[dict] = None):
        self._edges = edges or _EDGES
        self._event_mapping = event_mapping or EVENT_SECTOR_MAPPING

        # Build adjacency: source → list of (target, edge)
        self._adj: dict[SW, list[tuple[SW, SectorEdge]]] = {}
        for e in self._edges:
            self._adj.setdefault(e.source, []).append((e.target, e))

    # ── Propagation ──────────────────────────────────────────────────────────

    def propagate(self,
                  trigger_sector: SW,
                  trigger_score: float = 1.0,
                  max_hop: int = 2,
                  decay: float = 0.6) -> list[PropagationResult]:
        """BFS propagation from a triggered sector.

        Args:
            trigger_sector: The sector where the event occurs.
            trigger_score: Magnitude of the event signal (+/-).
            max_hop: Maximum propagation hops.
            decay: Score multiplier per hop (0.6 = 40% decay each hop).

        Returns:
            List of PropagationResult sorted by |score| descending.
        """
        results: dict[SW, PropagationResult] = {}
        # BFS queue: (sector, accumulated_score, hop, path, relation, days)
        queue: list[tuple[SW, float, int, list[str], str, int]] = [
            (trigger_sector, trigger_score, 0, [f"SW_{trigger_sector.name}"], "", 0)
        ]
        visited: dict[SW, int] = {trigger_sector: 0}

        while queue:
            sector, score, hop, path, rel, days = queue.pop(0)
            if hop > 0:  # Don't include the trigger sector itself
                if sector not in results or abs(score) > abs(results[sector].score):
                    results[sector] = PropagationResult(
                        sector=sector,
                        sector_name=SW_NAMES_ZH.get(sector, sector.name),
                        score=round(score, 4),
                        hop=hop,
                        path=path.copy(),
                        relation=rel,
                        typical_days=days,
                    )

            if hop >= max_hop:
                continue

            for target, edge in self._adj.get(sector, []):
                new_score = score * edge.weight * edge.direction * (decay ** hop)
                new_hop = hop + 1
                # Only re-explore if new score is stronger
                if target in visited and visited[target] <= new_hop:
                    if target in results and abs(new_score) <= abs(results[target].score):
                        continue
                visited[target] = new_hop
                new_path = path + [f"SW_{target.name}"]
                queue.append((target, new_score, new_hop, new_path,
                              edge.relation, edge.typical_days))

        return sorted(results.values(), key=lambda r: abs(r.score), reverse=True)

    def propagate_event(self,
                        event_type: str,
                        max_hop: int = 2) -> list[PropagationResult]:
        """Propagate a named event type across the graph.

        Args:
            event_type: Key in EVENT_SECTOR_MAPPING (e.g., 'semiconductor_policy').
            max_hop: Max propagation hops.

        Returns:
            All affected sectors sorted by |score|.
        """
        if event_type not in self._event_mapping:
            raise ValueError(f"Unknown event type '{event_type}'. "
                             f"Available: {list(self._event_mapping.keys())}")

        primary = self._event_mapping[event_type]
        all_results: dict[SW, PropagationResult] = {}

        for sector, impact in primary:
            # Add primary as hop=1 results
            if sector not in all_results or abs(impact) > abs(all_results[sector].score):
                all_results[sector] = PropagationResult(
                    sector=sector,
                    sector_name=SW_NAMES_ZH.get(sector, sector.name),
                    score=round(impact, 4),
                    hop=1,
                    path=[f"event:{event_type}", f"SW_{sector.name}"],
                    relation="primary",
                    typical_days=0,
                )
            # Propagate secondary (hop+1)
            secondary = self.propagate(sector, impact, max_hop=max_hop - 1)
            for r in secondary:
                r2 = PropagationResult(
                    sector=r.sector,
                    sector_name=r.sector_name,
                    score=r.score,
                    hop=r.hop + 1,
                    path=[f"event:{event_type}"] + r.path,
                    relation=r.relation,
                    typical_days=r.typical_days,
                )
                if r2.sector not in all_results or abs(r2.score) > abs(all_results[r2.sector].score):
                    all_results[r2.sector] = r2

        return sorted(all_results.values(), key=lambda r: abs(r.score), reverse=True)

    def get_related_symbols(self,
                            event_type: str,
                            instruments: list,  # list of Instrument-like objects
                            max_hop: int = 2,
                            min_score: float = 0.15) -> list[dict]:
        """Get symbols affected by an event, with propagation scores.

        Args:
            event_type: Named event type.
            instruments: List of objects with .symbol and .industry (int or SW).
            max_hop: Max propagation depth.
            min_score: Minimum |score| to include.

        Returns:
            List of dicts sorted by |score| desc, each with:
            symbol, score, sector_name, hop, typical_days, path
        """
        propagation = self.propagate_event(event_type, max_hop=max_hop)
        affected_sectors: dict[SW, PropagationResult] = {
            r.sector: r for r in propagation if abs(r.score) >= min_score
        }

        results = []
        for inst in instruments:
            ind = inst.industry if isinstance(inst.industry, SW) else SW(int(inst.industry))
            if ind in affected_sectors:
                pr = affected_sectors[ind]
                results.append({
                    "symbol": inst.symbol,
                    "name": getattr(inst, "name", ""),
                    "score": pr.score,
                    "sector": pr.sector_name,
                    "hop": pr.hop,
                    "typical_days": pr.typical_days,
                    "path": " -> ".join(pr.path),
                    "relation": pr.relation,
                })

        return sorted(results, key=lambda x: abs(x["score"]), reverse=True)

    def available_events(self) -> list[str]:
        return list(self._event_mapping.keys())

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize to dict (for JSON export, C++ loading)."""
        nodes = []
        for sw in SW:
            nodes.append({
                "id": f"SW_{sw.name}",
                "sw_code": int(sw),
                "name_zh": SW_NAMES_ZH.get(sw, sw.name),
                "name_en": sw.name,
            })

        edges = []
        for e in self._edges:
            edges.append({
                "source": f"SW_{e.source.name}",
                "target": f"SW_{e.target.name}",
                "relation": e.relation,
                "weight": e.weight,
                "direction": e.direction,
                "typical_days": e.typical_days,
                "description": e.description,
            })

        event_mappings = {}
        for event, sectors in self._event_mapping.items():
            event_mappings[event] = [
                {"sector": f"SW_{s.name}", "score": sc}
                for s, sc in sectors
            ]

        return {
            "version": "1.0",
            "nodes": nodes,
            "edges": edges,
            "event_mappings": event_mappings,
        }

    def save(self, path: str | Path) -> None:
        """Save graph to JSON file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> "SectorGraph":
        """Load graph from JSON file."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        # Rebuild from JSON
        sw_by_id = {f"SW_{sw.name}": sw for sw in SW}
        edges = []
        for e in data.get("edges", []):
            src = sw_by_id.get(e["source"])
            tgt = sw_by_id.get(e["target"])
            if src is None or tgt is None:
                continue
            edges.append(SectorEdge(
                source=src,
                target=tgt,
                relation=e["relation"],
                weight=float(e["weight"]),
                direction=int(e["direction"]),
                typical_days=int(e["typical_days"]),
                description=e.get("description", ""),
            ))

        event_mapping = {}
        for event, sectors in data.get("event_mappings", {}).items():
            event_mapping[event] = [
                (sw_by_id[s["sector"]], float(s["score"]))
                for s in sectors
                if s["sector"] in sw_by_id
            ]

        return cls(edges=edges, event_mapping=event_mapping)
