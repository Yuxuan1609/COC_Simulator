"""
TRPG 场景核心模块 —— 数据类、有向图、玩家、运行时世界、记忆管理。

从 notebook_simplified.ipynb 拆分，不包含任何 LLM 调用或 UI 逻辑。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple, Set, Callable, TYPE_CHECKING
if TYPE_CHECKING:
    from investigator.models import Investigator as InvestigatorType
from dataclasses import dataclass, field
from module_designer.dependency_graph import DependencyNode, DependencyEdge


# ═══════════════════════════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════════════════════════

def read_json_file(file_path: str) -> dict:
    with open(file_path, 'r', encoding='utf-8') as file:
        return json.load(file)


# ═══════════════════════════════════════════════════════════════
#  基础数据类
# ═══════════════════════════════════════════════════════════════

@dataclass
class Edge:
    target: str
    method: str          # 移动方式，如"步行通过车门"
    requirement: str = ""  # 通行前置条件（自然语言），如"需要先找到钥匙"

    def __repr__(self):
        return f"Edge({self.target}, '{self.method}')"


@dataclass
class Requirement:
    """前置条件 —— 执行交互或触发事件前需满足的条件"""
    ref_type: str      # "interaction" / "event" / "flag"
    ref_scene: str     # scene ID（或 event ID，当 ref_type 为 "event" 时）
    ref_name: str      # prerequisite name


@dataclass
class Interaction:
    """场景中可执行的动作（调查、鉴定、对话、决策等）"""
    type: str            # 调查 / 鉴定 / 搜索 / 急救 / 对话 / 决策 / 使用物品 / 策略 / 战斗 / 准备 / 事件
    name: str            # 动作名称
    trigger: str         # 触发条件描述
    result: str          # 执行结果（含线索信息）
    requirements: List[Requirement] = field(default_factory=list)   # 前置条件
    side_effects: list = field(default_factory=list)   # ItemGain | StatChange | SpawnEnemy | GrantWeapon | NPCStateChange

    def summary(self) -> str:
        return f"[{self.type}] {self.name}"


@dataclass
class ItemGain:
    """获得物品 —— 加入调查员 ItemManager"""
    item_name: str
    quantity: int = 1


@dataclass
class ConsumeItem:
    """消耗物品 —— 从调查员 ItemManager 移除"""
    item_name: str
    quantity: int = 1
    narrative: str = ""  # 消耗原因（可选）


@dataclass
class StatChange:
    """属性/状态变化。delta 为数值变化，narrative 描述难以量化的影响（恐惧、幻觉等）."""
    stat_name: str
    delta: int = 0
    narrative: str = ""


@dataclass
class SpawnEnemy:
    """生成敌人遭遇 —— 从 library 中实例化敌人"""
    enemy_ref: str       # 引用 library/enemies 中的敌人名
    scene: str           # 目标场景
    quantity: int = 1


@dataclass
class GrantWeapon:
    """授予武器 —— 从 library/weapons 中选取标准化武器"""
    weapon_ref: str      # 引用 library/weapons 中的武器名
    scene: str = ""      # 目标场景（空=当前场景）
    quantity: int = 1


@dataclass
class SceneWeapon:
    """武器放置 — 在场景中可被发现拾取的武器"""
    weapon_ref: str      # 引用 library/weapons 中的武器名
    scene: str           # 所在场景
    quantity: int = 1


@dataclass
class NPCStateChange:
    """NPC 状态变化 —— 更新 ScenarioWorld.npc_states"""
    npc_name: str
    new_state: str       # 如 "清醒"、"死亡"、"已对话"、"已离开"


@dataclass
class ActionResult:
    """交互/事件执行的统一返回类型"""
    success: bool
    message: str
    side_effects: list = field(default_factory=list)     # JSON 声明的确定性副作用
    suggested_flags: list = field(default_factory=list)   # LLM 建议（预留，本轮不实现）


@dataclass
class Entity:
    """Unified entity — interaction, auto_trigger, or event."""
    id: str                        # I1, AT1, E1
    entity_type: str               # "interaction" | "auto_trigger" | "event"
    name: str
    scene: str = ""                # empty for events
    type: str = ""                 # COC 45 skill name, "" = no check
    requirement: str = ""          # natural language
    trigger: str = ""              # when this fires
    result: str = ""               # may contain ##GRADED##, ##END_*, @markup
    side_effects: list[str] = field(default_factory=list)  # @markup strings
    graded_result: dict | None = None
    difficulty: str = ""           # None/regular/hard/extreme

    def summary(self) -> str:
        return f"[{self.type}] {self.name}"


# ═══════════════════════════════════════════════════════════════
#  @markup 解析器
# ═══════════════════════════════════════════════════════════════

_MARKUP_PATTERN = re.compile(
    r'@(spawn_enemy|grant_weapon|stat_change|item_gain|consume_item|npc_state_change)'
    r'\(([^)]*)\)'
)


def _parse_kwargs(kwargs_str: str) -> dict:
    """Parse key=value pairs from @markup arg string. Values may be quoted."""
    result = {}
    if not kwargs_str.strip():
        return result
    # Match key=value pairs, value can be quoted (single/double) or unquoted
    for match in re.findall(r'(\w+)\s*=\s*(?:"""([^"]*)"""|"([^"]*)"|\'([^\']*)\'|([^,)]+))', kwargs_str):
        key = match[0]
        value = match[1] or match[2] or match[3] or match[4]
        value = value.strip().rstrip(',')
        result[key] = value
    return result


def parse_markup(text: str):
    """Parse a single @function(args) markup string into a side effect dataclass."""
    match = _MARKUP_PATTERN.search(text)
    if not match:
        return None
    func_name = match.group(1)
    kwargs_str = match.group(2)
    kwargs = _parse_kwargs(kwargs_str)

    if func_name == "spawn_enemy":
        return SpawnEnemy(
            enemy_ref=kwargs.get("enemy_ref", ""),
            scene=kwargs.get("scene", ""),
            quantity=int(kwargs.get("quantity", 1)),
        )
    elif func_name == "grant_weapon":
        return GrantWeapon(
            weapon_ref=kwargs.get("weapon_ref", ""),
            scene=kwargs.get("scene", ""),
            quantity=int(kwargs.get("quantity", 1)),
        )
    elif func_name == "stat_change":
        delta_str = kwargs.get("delta", "0")
        try:
            delta = int(delta_str)
        except ValueError:
            delta = delta_str  # keep as string if it's a dice formula like "-1d4"
        return StatChange(
            stat_name=kwargs.get("stat_name", ""),
            delta=delta,
            narrative=kwargs.get("narrative", ""),
        )
    elif func_name == "item_gain":
        return ItemGain(
            item_name=kwargs.get("item_name", ""),
            quantity=int(kwargs.get("quantity", 1)),
        )
    elif func_name == "consume_item":
        return ConsumeItem(
            item_name=kwargs.get("item_name", ""),
            quantity=int(kwargs.get("quantity", 1)),
            narrative=kwargs.get("narrative", ""),
        )
    elif func_name == "npc_state_change":
        return NPCStateChange(
            npc_name=kwargs.get("npc_name", ""),
            new_state=kwargs.get("new_state", ""),
        )
    return None


def parse_markup_all(text: str) -> list:
    """Parse all @markup occurrences in a string."""
    results = []
    for match in _MARKUP_PATTERN.finditer(text):
        func_name = match.group(1)
        kwargs_str = match.group(2)
        kwargs = _parse_kwargs(kwargs_str)

        if func_name == "spawn_enemy":
            results.append(SpawnEnemy(
                enemy_ref=kwargs.get("enemy_ref", ""),
                scene=kwargs.get("scene", ""),
                quantity=int(kwargs.get("quantity", 1)),
            ))
        elif func_name == "grant_weapon":
            results.append(GrantWeapon(
                weapon_ref=kwargs.get("weapon_ref", ""),
                scene=kwargs.get("scene", ""),
                quantity=int(kwargs.get("quantity", 1)),
            ))
        elif func_name == "stat_change":
            delta_str = kwargs.get("delta", "0")
            try:
                delta = int(delta_str)
            except ValueError:
                delta = delta_str
            results.append(StatChange(
                stat_name=kwargs.get("stat_name", ""),
                delta=delta,
                narrative=kwargs.get("narrative", ""),
            ))
        elif func_name == "item_gain":
            results.append(ItemGain(
                item_name=kwargs.get("item_name", ""),
                quantity=int(kwargs.get("quantity", 1)),
            ))
        elif func_name == "consume_item":
            results.append(ConsumeItem(
                item_name=kwargs.get("item_name", ""),
                quantity=int(kwargs.get("quantity", 1)),
                narrative=kwargs.get("narrative", ""),
            ))
        elif func_name == "npc_state_change":
            results.append(NPCStateChange(
                npc_name=kwargs.get("npc_name", ""),
                new_state=kwargs.get("new_state", ""),
            ))
    return results

_GRADED_PATTERN = re.compile(r'^##GRADED##$')
_END_PATTERN = re.compile(r'^##END_([^:]+):(.+?)##')


def resolve_graded_result(entity: Entity, tier: str) -> str:
    """Resolve ##GRADED## result based on skill check tier.

    tier: "failure" | "regular" | "hard" | "extreme"
    """
    if not _GRADED_PATTERN.match(entity.result):
        return entity.result
    if not entity.graded_result:
        return entity.result
    key = f"on_{tier}"
    if key in entity.graded_result:
        return entity.graded_result[key]
    fallback_order = {
        "extreme": ["on_extreme", "on_hard", "on_regular", "on_failure"],
        "hard": ["on_hard", "on_regular", "on_failure", "on_extreme"],
        "regular": ["on_regular", "on_failure", "on_hard", "on_extreme"],
        "failure": ["on_failure", "on_regular", "on_hard", "on_extreme"],
    }
    for fb_key in fallback_order.get(tier, ["on_regular", "on_failure"]):
        if fb_key in entity.graded_result:
            return entity.graded_result[fb_key]
    return entity.result


def has_ending(text: str) -> tuple[str | None, str | None]:
    """Check if text contains an ending marker. Returns (ending_name, description) or (None, None)."""
    match = _END_PATTERN.match(text)
    if match:
        return match.group(1), match.group(2)
    return None, None



def _normalize_requirement(req):
    """兼容字符串格式的 requirement（LLM 可能生成 'flag:xxx' 或纯字符串）."""
    if isinstance(req, str):
        if req.startswith("flag:"):
            return Requirement(ref_type="flag", ref_scene="", ref_name=req[5:])
        return Requirement(ref_type="flag", ref_scene="", ref_name=req)
    if isinstance(req, dict):
        return Requirement(
            ref_type=req.get("ref_type", ""),
            ref_scene=req.get("ref_scene", ""),
            ref_name=req.get("ref_name", ""),
        )
    return Requirement(ref_type="", ref_scene="", ref_name="")


def _side_effect_to_dict(effect) -> dict:
    """将 side effect 实例序列化为 dict"""
    if isinstance(effect, ItemGain):
        return {"type": "item_gain", "item_name": effect.item_name, "quantity": effect.quantity}
    elif isinstance(effect, ConsumeItem):
        return {"type": "consume_item", "item_name": effect.item_name, "quantity": effect.quantity, "narrative": effect.narrative}
    elif isinstance(effect, StatChange):
        return {"type": "stat_change", "stat_name": effect.stat_name, "delta": effect.delta, "narrative": effect.narrative}
    elif isinstance(effect, SpawnEnemy):
        return {
            "type": "spawn_enemy",
            "enemy_ref": effect.enemy_ref,
            "scene": effect.scene,
            "quantity": effect.quantity,
        }
    elif isinstance(effect, GrantWeapon):
        return {"type": "grant_weapon", "weapon_ref": effect.weapon_ref, "scene": effect.scene, "quantity": effect.quantity}
    elif isinstance(effect, NPCStateChange):
        return {"type": "npc_state_change", "npc_name": effect.npc_name, "new_state": effect.new_state}
    return {}


@dataclass
class Node:
    node_id: str
    description: str = ""
    edges: List[Edge] = field(default_factory=list)     # from_here
    to_here: List[Edge] = field(default_factory=list)
    interactions: List[Entity] = field(default_factory=list)
    auto_triggers: List[Entity] = field(default_factory=list)
    encounters: list = field(default_factory=list)
    scene_weapons: list = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def get_interaction(self, name: str) -> Optional[Entity]:
        for e in self.interactions:
            if e.name == name:
                return e
        return None

    def get_auto_trigger(self, name: str) -> Optional[Entity]:
        for e in self.auto_triggers:
            if e.name == name:
                return e
        return None


@dataclass
class NodeRuntimeState:
    """Dynamic runtime state for each entity. Written by Judge, read by requirement parser."""
    completed: bool = False
    result_tier: str = ""          # "" | "fumble" | "failure" | "regular" | "hard" | "extreme"
    retries: int = 0
    escalated_difficulty: str = "" # "hard" | "extreme"


# ═══════════════════════════════════════════════════════════════
#  有向图
# ═══════════════════════════════════════════════════════════════

class DirectedGraph:
    """管理所有场景节点、边、动作及全局事件的图结构"""

    def __init__(self, scenes: dict = None, events: list = None):
        """
        scenes: scene_output_revised.json 格式的字典，键为车厢名
        events: res_event_revised.json 格式的列表
        """
        self.nodes: Dict[str, Node] = {}
        self.events: Dict[str, Entity] = {}
        if scenes:
            self.load_scenes(scenes)
        if events:
            self.load_events(events)

    # ── 加载 ──

    def load_scenes(self, data: dict):
        for node_id, node_info in data.items():
            interactions = []
            for inter in node_info.get("interactions", []):
                interactions.append(Entity(
                    id=inter["id"], entity_type="interaction",
                    name=inter["name"], scene=inter.get("scene", node_id),
                    type=inter.get("type", ""),
                    requirement=inter.get("requirement", ""),
                    trigger=inter.get("trigger", ""),
                    result=inter.get("result", ""),
                    side_effects=inter.get("side_effects", []),
                    graded_result=inter.get("graded_result"),
                    difficulty=inter.get("difficulty", ""),
                ))

            auto_triggers = []
            for at in node_info.get("auto_triggers", []):
                auto_triggers.append(Entity(
                    id=at["id"], entity_type="auto_trigger",
                    name=at["name"], scene=at.get("scene", node_id),
                    type=at.get("type", ""),
                    requirement=at.get("requirement", ""),
                    trigger=at.get("trigger", ""),
                    result=at.get("result", ""),
                    side_effects=at.get("side_effects", []),
                    graded_result=at.get("graded_result"),
                    difficulty=at.get("difficulty", ""),
                ))

            from_edges = [
                Edge(target=conn["target"], method=conn["method"],
                     requirement=conn.get("requirement", ""))
                for conn in node_info.get("from_here", [])
            ]
            to_edges = [
                Edge(target=conn.get("source", conn.get("target", "")),
                     method=conn["method"],
                     requirement=conn.get("requirement", ""))
                for conn in node_info.get("to_here", [])
            ]

            self.nodes[node_id] = Node(
                node_id=node_id,
                description=node_info.get("description", ""),
                edges=from_edges,
                to_here=to_edges,
                interactions=interactions,
                auto_triggers=auto_triggers,
                encounters=node_info.get("encounters", []),
                scene_weapons=node_info.get("scene_weapons", []),
                extra=node_info.get("extra", {}),
            )

    def load_events(self, data: list):
        for item in data:
            eid = item["id"]
            self.events[eid] = Entity(
                id=eid, entity_type="event",
                name=item["name"],
                type=item.get("type", ""),
                requirement=item.get("requirement", ""),
                trigger=item.get("trigger", ""),
                result=item.get("result", ""),
                side_effects=item.get("side_effects", []),
                graded_result=item.get("graded_result"),
                difficulty=item.get("difficulty", ""),
            )

    # ── 查询 ──

    def get_edges_from(self, node_id: str) -> List[Edge]:
        if node_id in self.nodes:
            return self.nodes[node_id].edges
        return []

    def get_interactions(self, node_id: str) -> List[Entity]:
        if node_id in self.nodes:
            return self.nodes[node_id].interactions
        return []

    def get_event(self, event_id: str) -> Optional[Entity]:
        return self.events.get(event_id)

    def get_all_event_ids(self) -> List[str]:
        return list(self.events.keys())

    # ── 修改 ──

    def remove_node(self, node_id: str):
        if node_id not in self.nodes:
            return
        del self.nodes[node_id]
        for nid, node in self.nodes.items():
            node.edges = [e for e in node.edges if e.target != node_id]
            node.to_here = [e for e in node.to_here if e.target != node_id]

    def remove_edge(self, source: str, target: str):
        if source in self.nodes:
            node = self.nodes[source]
            node.edges = [e for e in node.edges if e.target != target]
            if target in self.nodes:
                self.nodes[target].to_here = [
                    e for e in self.nodes[target].to_here if e.target != source
                ]

    def __repr__(self):
        result = f"DirectedGraph({len(self.nodes)} nodes, {len(self.events)} events)\n"
        for nid, node in self.nodes.items():
            exits = ", ".join(e.target for e in node.edges)
            interactions = len(node.interactions)
            result += f"  {nid}: {node.description[:40]}... → [{exits}] ({interactions} actions)\n"
        return result

    def to_dict(self) -> dict:
        nodes_dict = {}
        for nid, node in self.nodes.items():
            nodes_dict[nid] = {
                "node_id": node.node_id,
                "description": node.description,
                "edges": [{"target": e.target, "method": e.method, "requirement": e.requirement} for e in node.edges],
                "to_here": [{"target": e.target, "method": e.method, "requirement": e.requirement} for e in node.to_here],
                "interactions": [
                    {
                        "id": e.id, "entity_type": e.entity_type,
                        "name": e.name, "scene": e.scene, "type": e.type,
                        "requirement": e.requirement, "trigger": e.trigger,
                        "result": e.result,
                        "side_effects": e.side_effects,
                        "graded_result": e.graded_result,
                        "difficulty": e.difficulty,
                    }
                    for e in node.interactions
                ],
                "auto_triggers": [
                    {
                        "id": e.id, "entity_type": e.entity_type,
                        "name": e.name, "scene": e.scene, "type": e.type,
                        "requirement": e.requirement, "trigger": e.trigger,
                        "result": e.result,
                        "side_effects": e.side_effects,
                        "graded_result": e.graded_result,
                        "difficulty": e.difficulty,
                    }
                    for e in node.auto_triggers
                ],
                "encounters": node.encounters,
                "scene_weapons": node.scene_weapons,
                "extra": node.extra,
            }
        events_list = [
            {
                "id": e.id, "entity_type": e.entity_type,
                "name": e.name, "type": e.type,
                "requirement": e.requirement, "trigger": e.trigger,
                "result": e.result,
                "side_effects": e.side_effects,
                "graded_result": e.graded_result,
                "difficulty": e.difficulty,
            }
            for e in self.events.values()
        ]
        return {"nodes": nodes_dict, "events": events_list}

    @classmethod
    def from_dict(cls, data: dict) -> "DirectedGraph":
        """从 dict 重建 DirectedGraph（含 nodes 和 events）"""
        graph = cls()
        nodes_data = data.get("nodes", {})
        for nid, node_data in nodes_data.items():
            interactions = [
                Entity(
                    id=inter["id"],
                    entity_type=inter.get("entity_type", ""),
                    name=inter["name"],
                    scene=inter.get("scene", ""),
                    type=inter.get("type", ""),
                    requirement=inter.get("requirement", ""),
                    trigger=inter.get("trigger", ""),
                    result=inter.get("result", ""),
                    side_effects=inter.get("side_effects", []),
                    graded_result=inter.get("graded_result"),
                    difficulty=inter.get("difficulty", ""),
                )
                for inter in node_data.get("interactions", [])
            ]
            auto_triggers = [
                Entity(
                    id=at["id"],
                    entity_type=at.get("entity_type", ""),
                    name=at["name"],
                    scene=at.get("scene", ""),
                    type=at.get("type", ""),
                    requirement=at.get("requirement", ""),
                    trigger=at.get("trigger", ""),
                    result=at.get("result", ""),
                    side_effects=at.get("side_effects", []),
                    graded_result=at.get("graded_result"),
                    difficulty=at.get("difficulty", ""),
                )
                for at in node_data.get("auto_triggers", [])
            ]
            graph.nodes[nid] = Node(
                node_id=node_data["node_id"],
                description=node_data.get("description", ""),
                edges=[Edge(target=e["target"], method=e["method"],
                             requirement=e.get("requirement", "")) for e in node_data.get("edges", [])],
                to_here=[Edge(target=e["target"], method=e["method"],
                              requirement=e.get("requirement", "")) for e in node_data.get("to_here", [])],
                interactions=interactions,
                auto_triggers=auto_triggers,
                encounters=node_data.get("encounters", []),
                scene_weapons=node_data.get("scene_weapons", []),
                extra=node_data.get("extra", {}),
            )
        events_data = data.get("events", [])
        for ev_data in events_data:
            graph.events[ev_data["id"]] = Entity(
                id=ev_data["id"],
                entity_type=ev_data.get("entity_type", ""),
                name=ev_data["name"],
                type=ev_data.get("type", ""),
                requirement=ev_data.get("requirement", ""),
                trigger=ev_data.get("trigger", ""),
                result=ev_data.get("result", ""),
                side_effects=ev_data.get("side_effects", []),
                graded_result=ev_data.get("graded_result"),
                difficulty=ev_data.get("difficulty", ""),
            )
        return graph

# ═══════════════════════════════════════════════════════════════
#  前置条件解析器
# ═══════════════════════════════════════════════════════════════

class RequirementResolver:
    """检查 interaction / event 的前置条件是否满足"""

    def __init__(self, world: 'ScenarioWorld'):
        self.world = world

    def check(self, requirements: List[Requirement]) -> Tuple[bool, str]:
        """返回 (True, '') 若全部满足，否则 (False, 缺失条件描述)"""
        for req in requirements:
            if req.ref_type == "interaction":
                done = self.world.completed_interactions.get(req.ref_scene, set())
                if req.ref_name not in done:
                    return False, f"行动失败！！！ \n 需要先完成「{req.ref_scene}」的「{req.ref_name}」"
            elif req.ref_type == "event":
                if not self.world.triggered_events.get(req.ref_scene, False):
                    event = self.world.graph.get_event(req.ref_scene)
                    event_name = event.name if event else req.ref_scene
                    return False, f"行动失败！！！需要先触发事件「{event_name}」"
            elif req.ref_type == "flag":
                state = self.world.runtime_state.get(req.ref_name)
                if not state or not state.completed:
                    return False, f"行动失败！！！需要满足条件「{req.ref_name}」"
        return True, ""

    def get_unmet(self, requirements: List[Requirement]) -> List[Requirement]:
        """返回未满足的前置条件列表"""
        unmet: List[Requirement] = []
        for req in requirements:
            if req.ref_type == "interaction":
                done = self.world.completed_interactions.get(req.ref_scene, set())
                if req.ref_name not in done:
                    unmet.append(req)
            elif req.ref_type == "event":
                if not self.world.triggered_events.get(req.ref_scene, False):
                    unmet.append(req)
            elif req.ref_type == "flag":
                state = self.world.runtime_state.get(req.ref_name)
                if not state or not state.completed:
                    unmet.append(req)
        return unmet

    def resolve_chain(self, requirements: List[Requirement]) -> List[Requirement]:
        """（桩）追踪传递依赖链，返回最深层的未满足前置条件。留待后续实现。"""
        return self.get_unmet(requirements)


# ═══════════════════════════════════════════════════════════════
#  Requirement string parser (AND/OR logic)
# ═══════════════════════════════════════════════════════════════

_ENTITY_ID_PATTERN = re.compile(r'^[IEA]+\d+[a-z]?$')


def _extract_entity_id(text: str) -> str | None:
    """Extract entity ID from a cleaned group string. Returns None if no ID found."""
    match = _ENTITY_ID_PATTERN.match(text)
    return match.group(0) if match else None


def parse_hard_requirement(hard: str, runtime_state: dict) -> bool:
    """Parse the hard portion of a requirement string.

    Format:
        and_group ("AND" and_group)*
        and_group = or_group ("OR" or_group)*
        or_group  = entity_id (after stripping parens/spaces)

    Returns True if ALL AND groups pass.
    An AND group passes if ANY of its OR groups passes.
    An OR group passes if its entity_id is completed in runtime_state.
    Groups with no recognizable entity ID pass automatically (graceful degradation
    for LLM-generated natural language that couldn't be fully structured).
    """
    if not hard or not hard.strip():
        return True

    # Step 1: split top-level AND (respecting parenthesized groups)
    and_parts = _split_top_level(hard, "AND")

    for and_group in and_parts:
        # Step 2: split secondary OR
        or_parts = _split_top_level(and_group, "OR")

        or_pass = False
        for or_group in or_parts:
            # Step 3: clean and extract entity ID
            cleaned = _clean_group(or_group)
            eid = _extract_entity_id(cleaned)

            if eid is None:
                # No recognizable ID → pass this group (LLM-generator grace)
                or_pass = True
                break

            state = runtime_state.get(eid)
            if state and state.completed:
                or_pass = True
                break

        if not or_pass:
            return False  # This AND group failed entirely

    return True  # All AND groups passed


def _split_top_level(text: str, sep: str) -> list[str]:
    """Split by separator but respect parenthesized groups as atomic units.

    e.g. "(I12a OR I12b) AND I1" split by AND → ["(I12a OR I12b)", "I1"]
    """
    # Strip balanced outer parentheses so that "(A OR B)" splits correctly
    text = text.strip()
    while text.startswith("(") and text.endswith(")"):
        inner = text[1:-1]
        if inner.count("(") == inner.count(")"):
            text = inner.strip()
        else:
            break

    parts = text.split(sep)
    result = []
    buf = []
    for part in parts:
        buf.append(part)
        joined = sep.join(buf)
        if joined.count("(") == joined.count(")"):
            result.append(joined.strip())
            buf = []
    if buf:
        result.append(sep.join(buf).strip())
    return [r for r in result if r]


def _clean_group(text: str) -> str:
    """Strip parentheses, spaces, and Chinese punctuation from a group."""
    return text.strip().strip("()（） \t")


# ═══════════════════════════════════════════════════════════════
#  场景世界（纯泛用运行时状态管理）
# ═══════════════════════════════════════════════════════════════

class ScenarioWorld:
    """
    纯泛用的运行时状态管理器 —— 不包含任何具体场景或事件的硬编码逻辑。
    所有智能判断（动作解析、事件触发、叙事生成）由外部 LLM 调用链完成。

    管理内容：
    - 当前位置、调查员
    - 背景故事（模组设定）
    - 已触发事件（不可逆）
    - 已完成动作（每个场景独立追踪）
    - 世界标记（任意条件标记）
    """

    def __init__(self, graph: DirectedGraph, start_node: str,
                 background_story: str = "",
                 wr0_enabled: bool = False,
                 enemy_library: Any = None,
                 weapon_library: Any = None):
        self.graph = graph
        self.current_location = start_node
        self.player: 'InvestigatorType | None' = None

        # 背景故事（模组设定，供叙事阶段参考）
        self.background_story = background_story
        self.wr0_enabled = wr0_enabled

        # 事件追踪
        self.triggered_events: Dict[str, bool] = {
            eid: False for eid in graph.get_all_event_ids()
        }

        # 每个场景已完成动作名
        self.completed_interactions: Dict[str, Set[str]] = {}

        # L2 dependency graph + per-entity runtime state (replaces flags)
        self.runtime_state: Dict[str, NodeRuntimeState] = {}
        self.dependency_graph: Dict[str, Any] = {}


        # 记忆管理器
        self.memory = MemoryManager()

        # NPC 运行时状态
        self.npc_states: Dict[str, str] = {}

        # Weapon tracking
        self.scene_weapons: dict[str, list[SceneWeapon]] = {}
        self.weapon_library: Any = weapon_library

        # Enemy tracking
        if enemy_library is not None:
            from game.enemy_manager import EnemyManager
            self.enemy_manager = EnemyManager(enemy_library)
        else:
            self.enemy_manager = None

    # ── Dependency graph & runtime state ──

    def load_dependency_graph(self, dep_graph: dict):
        """Load L2 dependency graph into runtime-ready structures."""
        self.dependency_graph = dep_graph
        nodes = dep_graph.get("nodes", {})
        for eid in nodes:
            if eid not in self.runtime_state:
                self.runtime_state[eid] = NodeRuntimeState()

    def get_runtime_state(self, entity_id: str) -> NodeRuntimeState:
        """Get or create runtime state for an entity."""
        if entity_id not in self.runtime_state:
            self.runtime_state[entity_id] = NodeRuntimeState()
        return self.runtime_state[entity_id]

    def get_incoming_edges(self, entity_id: str) -> list[dict]:
        """Get all edges where source == entity_id (what entity_id depends on)."""
        edges = self.dependency_graph.get("edges", [])
        return [e for e in edges if e.get("source") == entity_id]

    def check_edge_requirements(self, entity_id: str) -> tuple[bool, str]:
        """Check if all incoming dependency edges for entity_id are satisfied.

        Returns (met: bool, reason: str).
        Each edge is an AND condition: ALL edges must pass.
        OR logic is handled by requirement string parsing (parse_hard_requirement).
        """
        edges = self.get_incoming_edges(entity_id)
        if not edges:
            return True, ""

        for edge in edges:
            target_id = edge.get("target", "")
            condition = edge.get("condition", "completed")
            target_state = self.get_runtime_state(target_id)

            if condition == "success":
                if target_state.result_tier not in ("regular", "hard", "extreme"):
                    return False, f"需要成功完成「{target_id}」"
            elif condition == "completed":
                if not target_state.completed:
                    return False, f"需要先完成「{target_id}」"
            elif condition == "fail":
                if target_state.result_tier not in ("failure", "fumble"):
                    return False, f"需要「{target_id}」结果为失败"
            elif condition == "Uncompleted":
                if target_state.completed:
                    return False, f"需要「{target_id}」未完成"

        return True, ""

    # ── 背景故事 ──

    def set_background(self, text: str):
        """设置/更新背景故事"""
        self.background_story = text

    # ── 调查员 ──

    def set_player(self, player: 'InvestigatorType'):
        """设置调查员角色。接受 investigator.Investigator 实例。"""
        self.player = player

    def load_player(self, path: str):
        """从 JSON 文件加载调查员"""
        from investigator.serialization import from_json
        self.player = from_json(path)

    # ── 查询：场景信息 ──

    def _current_node(self) -> Optional[Node]:
        return self.graph.nodes.get(self.current_location)

    def get_current_description(self) -> str:
        node = self._current_node()
        return node.description if node else "未知地点"

    def get_possible_exits(self) -> List[Edge]:
        return self.graph.get_edges_from(self.current_location)

    def get_available_interactions(self) -> list[Entity]:
        """未完成的在前，已完成的在后"""
        node = self._current_node()
        if not node:
            return []
        done = self.completed_interactions.get(self.current_location, set())
        incomplete = [i for i in node.interactions if i.name not in done]
        complete = [i for i in node.interactions if i.name in done]
        return incomplete + complete

    def is_interaction_completed(self, interaction_name: str) -> bool:
        done = self.completed_interactions.get(self.current_location, set())
        return interaction_name in done

    def _are_requirements_met(self, entity) -> bool:
        """Check if entity prerequisites are satisfied via runtime_state.
        For '||' separated requirements, only checks the hard part (before ||)."""
        if hasattr(entity, 'requirement'):
            req = entity.requirement
            if not req or not req.strip():
                return True
            hard = req.split("||", 1)[0].strip() if "||" in req else req.strip()
            if not hard:
                return True
            return parse_hard_requirement(hard, self.runtime_state)
        return True

    # ── 场景摘要（确定性、泛用格式化）──

    def get_scene_summary(self) -> str:
        """
        返回当前场景的完整摘要。同一世界状态多次调用返回相同结果。
        包括：描述 + 可移动方向 + 可执行动作 + 已触发事件
        """
        node = self._current_node()
        if not node:
            return "【未知地点】无可用信息。"

        lines = [
            f"══════ {self.current_location} ══════",
            f"描述：{node.description}",
            "",
        ]

        exits = self.get_possible_exits()
        lines.append("═══ 可移动方向 ═══")
        if exits:
            for i, e in enumerate(exits, 1):
                lines.append(f"  {i}. → {e.target}：{e.method}")
        else:
            lines.append("  （无路可走）")

        interactions = self.get_available_interactions()
        done = self.completed_interactions.get(self.current_location, set())
        available = [i for i in interactions if i.name not in done]
        completed = [i for i in interactions if i.name in done]

        lines.append("")
        lines.append("═══ 可执行动作 ═══")
        if available:
            for i, inter in enumerate(available, 1):
                hint = " [需要前置]" if not self._are_requirements_met(inter) else ""
                lines.append(f"  {i}. {inter.summary()}{hint} —— {inter.trigger}")
        else:
            lines.append("  （无新增可执行动作）")
        if completed:
            lines.append(f"  已完成：{', '.join(i.name for i in completed)}")

        active = self.get_active_event_effects()
        if active:
            lines.append("")
            lines.append("═══ 当前已触发事件 ═══")
            for name, impact in active:
                lines.append(f"  ◆ {name}")
                lines.append(f"    影响：{impact}")

        return "\n".join(lines)

    def get_scene_info(self) -> dict:
        """当前场景的结构化信息字典，供编程使用"""
        node = self._current_node()
        if not node:
            return {"location": self.current_location, "error": "unknown location"}
        exits = self.get_possible_exits()
        interactions = self.get_available_interactions()
        done = self.completed_interactions.get(self.current_location, set())
        return {
            "location": self.current_location,
            "description": node.description,
            "exits": [{"target": e.target, "method": e.method} for e in exits],
            "interactions": [
                {"type": i.type, "name": i.name, "trigger": i.trigger,
                 "completed": i.name in done,
                 "requirements_met": self._are_requirements_met(i)}
                for i in interactions
            ],
            "triggered_events": [eid for eid, t in self.triggered_events.items() if t],
        }

    # ── 移动 ──

    def move(self, target: str) -> ActionResult:
        if self.player is None:
            return ActionResult(False, "尚未设置角色")
        possible = {e.target: e for e in self.get_possible_exits()}
        if target not in possible:
            available = ', '.join(e.target for e in self.get_possible_exits())
            return ActionResult(False, f"无法从{self.current_location}前往{target}。可前往：{available or '无'}")
        self.current_location = target
        return ActionResult(True, f"你来到了{target}。{self.get_current_description()}")

    def is_event_triggered(self, event_id: str) -> bool:
        return self.triggered_events.get(event_id, False)

    def get_active_event_effects(self) -> List[Tuple[str, str]]:
        results = []
        for eid, triggered in self.triggered_events.items():
            if triggered:
                event = self.graph.get_event(eid)
                if event:
                    results.append((event.name, event.impact))
        return results


    # ── NPC 运行时状态 ──

    def set_npc_state(self, npc_name: str, state: str):
        """更新 NPC 运行时状态"""
        self.npc_states[npc_name] = state

    def get_npc_state(self, npc_name: str) -> str:
        """查询 NPC 运行时状态"""
        return self.npc_states.get(npc_name, "未知")

    def apply_world_update(self, abstract: str):
        """应用世界更新结果"""
        self.set_background(abstract)

    def apply_scene_update(self, description: str):
        node = self._current_node()
        if node:
            node.description = description

    def to_dict(self) -> dict:
        """序列化运行时世界状态（含被修改的 node descriptions）"""
        modified_descriptions = {}
        for nid, node in self.graph.nodes.items():
            modified_descriptions[nid] = node.description

        runtime_state_serialized = {}
        for eid, s in self.runtime_state.items():
            runtime_state_serialized[eid] = {
                "completed": s.completed,
                "result_tier": s.result_tier,
                "retries": s.retries,
                "escalated_difficulty": s.escalated_difficulty,
            }

        return {
            "current_location": self.current_location,
            "triggered_events": dict(self.triggered_events),
            "completed_interactions": {
                k: list(v) for k, v in self.completed_interactions.items()
            },
            "runtime_state": runtime_state_serialized,
            "dependency_graph": self.dependency_graph,
            "background_story": self.background_story,
            "modified_descriptions": modified_descriptions,
            "npc_states": dict(self.npc_states),
            "wr0_enabled": self.wr0_enabled,
        }

    @classmethod
    def from_dict(cls, data: dict, graph: "DirectedGraph") -> "ScenarioWorld":
        """从 dict + graph 恢复运行时世界状态"""
        world = cls(graph, data["current_location"])
        world.triggered_events = data.get("triggered_events", {})
        world.completed_interactions = {
            k: set(v) for k, v in data.get("completed_interactions", {}).items()
        }
        world.background_story = data.get("background_story", "")
        world.npc_states = data.get("npc_states", {})
        world.wr0_enabled = data.get("wr0_enabled", False)
        world.dependency_graph = data.get("dependency_graph", {})
        # 恢复 runtime_state
        for eid, sdata in data.get("runtime_state", {}).items():
            world.runtime_state[eid] = NodeRuntimeState(
                completed=sdata.get("completed", False),
                result_tier=sdata.get("result_tier", ""),
                retries=sdata.get("retries", 0),
                escalated_difficulty=sdata.get("escalated_difficulty", ""),
            )
        # 恢复被修改的 node descriptions
        for nid, desc in data.get("modified_descriptions", {}).items():
            if nid in graph.nodes:
                graph.nodes[nid].description = desc
        world.memory = MemoryManager.from_dict(data.get("memory", {}))
        return world

    def save_state(self, path: str):
        """全量快照存档（图 + 世界 + 记忆 + 调查员快照）"""
        from investigator.serialization import to_dict as inv_to_dict
        from datetime import datetime
        import os

        data = {
            "version": 1,
            "timestamp": datetime.now().isoformat(),
            "graph": self.graph.to_dict(),
            "world": self.to_dict(),
            "memory": self.memory.to_dict(),
            "player_snapshot": inv_to_dict(self.player) if self.player else None,
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load_state(cls, path: str) -> "ScenarioWorld":
        """从存档恢复（自包含，不需要外部传 graph）"""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if data.get("version") != 1:
            raise ValueError(f"不支持的存档版本: {data.get('version')}")
        graph = DirectedGraph.from_dict(data["graph"])
        world_data = data["world"]
        world_data["memory"] = data.get("memory", {})
        world = cls.from_dict(world_data, graph)
        # 恢复调查员
        ps = data.get("player_snapshot")
        if ps is not None:
            from investigator.serialization import from_dict as inv_from_dict
            world.player = inv_from_dict(ps)
        return world

    def __repr__(self):
        events_on = sum(1 for v in self.triggered_events.values() if v)
        interactions_done = sum(len(s) for s in self.completed_interactions.values())
        return (
            f"ScenarioWorld(location={self.current_location}, "
            f"events={events_on}/{len(self.triggered_events)}, "
            f"interactions_done={interactions_done}, "
            f"background={'set' if self.background_story else 'none'})"
        )


def apply_side_effects(world: 'ScenarioWorld', side_effects: list) -> list:
    """Apply side effect dataclass instances to the world. Returns human-readable summaries."""
    msgs = []
    for effect in side_effects:
        if isinstance(effect, ItemGain):
            world.memory.note_item(effect.item_name)
            if world.player and hasattr(world.player, 'item_manager'):
                world.player.item_manager.add(
                    effect.item_name, quantity=effect.quantity
                )
                qty_str = f" x{effect.quantity}" if effect.quantity > 1 else ""
                msgs.append(f"[获得物品] {effect.item_name}{qty_str}（已加入背包）")
            else:
                msgs.append(f"[获得物品] {effect.item_name}")
        elif isinstance(effect, ConsumeItem):
            consumed = False
            if world.player and hasattr(world.player, 'item_manager'):
                im = world.player.item_manager
                if im.has(effect.item_name) and im.get(effect.item_name).quantity >= effect.quantity:
                    im.remove(effect.item_name, effect.quantity)
                    consumed = True
                else:
                    try:
                        from llm import call_deepseek
                        from prompts import build_consume_item_fuzzy_prompt
                        held = im.describe()
                        if held and held != "（未持有物品）":
                            prompt = build_consume_item_fuzzy_prompt(
                                target=effect.item_name,
                                quantity=effect.quantity,
                                held_items=held,
                            )
                            result = call_deepseek(
                                prompt, json_mode=True, model="deepseek-v4-flash",
                                system="你是 COC 7th KP 助理。",
                                fallback_schema={"matched": False, "item_name": "", "reason": ""},
                            )
                            if isinstance(result, str):
                                import json as _json
                                result = _json.loads(result)
                            if result.get("matched") and result.get("item_name"):
                                matched_name = result["item_name"]
                                if im.has(matched_name):
                                    im.remove(matched_name, effect.quantity)
                                    consumed = True
                    except Exception:
                        pass
            if consumed:
                msgs.append(f"[消耗物品] {effect.item_name} x{effect.quantity}")
            else:
                msgs.append(f"[消耗物品] {effect.item_name} x{effect.quantity}（未找到匹配物品）")
        elif isinstance(effect, SpawnEnemy):
            target_scene = effect.scene or world.current_location
            if world.enemy_manager:
                instance = world.enemy_manager.spawn(
                    effect.enemy_ref, target_scene, effect.quantity
                )
                msgs.append(
                    f"[生成敌人] {effect.enemy_ref} x{effect.quantity} "
                    f"在 {target_scene} ({instance.instance_id})"
                )
            else:
                msgs.append(
                    f"[生成敌人] {effect.enemy_ref} x{effect.quantity} 在 {target_scene}"
                )
        elif isinstance(effect, GrantWeapon):
            target_scene = effect.scene or world.current_location
            sw = SceneWeapon(
                weapon_ref=effect.weapon_ref,
                scene=target_scene,
                quantity=effect.quantity,
            )
            if target_scene not in world.scene_weapons:
                world.scene_weapons[target_scene] = []
            world.scene_weapons[target_scene].append(sw)
            world.memory.note_item(effect.weapon_ref)
            msgs.append(f"[武器放置] {effect.weapon_ref} x{effect.quantity} 在 {target_scene}")
        elif isinstance(effect, NPCStateChange):
            world.set_npc_state(effect.npc_name, effect.new_state)
            msgs.append(f"[NPC状态] {effect.npc_name} -> {effect.new_state}")
        elif isinstance(effect, StatChange):
            if world.player:
                new_val, detail = world.player.modify_stat(effect.stat_name, effect.delta)
                msgs.append(f"[属性变化] {detail}")
                # Apply narrative description via LLM if present
                if effect.narrative and hasattr(world.player, 'personal_description'):
                    try:
                        from llm import call_deepseek
                        from prompts import build_stat_narrative_prompt
                        prompt = build_stat_narrative_prompt(
                            inv_desc=world.player.personal_description or world.player.appearance or "",
                            stat_name=effect.stat_name,
                            delta=str(effect.delta),
                            narrative=effect.narrative,
                        )
                        result = call_deepseek(
                            prompt, json_mode=True, model="deepseek-v4-flash",
                            system="你是 COC 7th KP 助理，负责更新调查员描述。",
                            fallback_schema={"description": world.player.personal_description or ""},
                        )
                        if isinstance(result, str):
                            import json as _json
                            result = _json.loads(result)
                        new_desc = result.get("description", "")
                        if new_desc and new_desc != (world.player.personal_description or ""):
                            world.player.personal_description = new_desc
                            msgs.append(f"[描述更新] {effect.stat_name} 变化影响了外貌/心理描述")
                    except Exception:
                        pass  # Narrative modification is best-effort
            else:
                sign = '+' if (isinstance(effect.delta, (int, float)) and effect.delta > 0) else ''
                msgs.append(f"[属性变化] {effect.stat_name} {sign}{effect.delta}（无调查员，未应用）")
    return msgs


# ═══════════════════════════════════════════════════════════════
#  分层记忆管理器
# ═══════════════════════════════════════════════════════════════

class MemoryManager:
    """分层记忆管理器 —— 近期原始记录 + 远期压缩摘要 + 关键发现追踪"""

    def __init__(self, max_raw: int = 5):
        self.raw_history: List[Dict] = []       # 近期原始记录（未压缩）
        self.summary: str = ""                   # 远期压缩摘要
        self.max_raw = max_raw                   # 触发压缩的原始记录数阈值

        # 关键发现（独立存储，不会被压缩丢失）
        self.visited: List[str] = []             # 到访场景（按顺序）
        self.key_items: List[str] = []           # 获得的关键物品
        self.turn: int = 0                       # 回合计数

    # ── 记录 ──

    def add_record(self, user_input: str, action: str, target: Optional[str],
                   result: str, location: str = "", success: bool = True):
        """添加一条交互记录"""
        self.turn += 1
        self.raw_history.append({
            "turn": self.turn,
            "location": location,
            "user_input": user_input,
            "action": action,
            "target": target,
            "result": result,
            "success": success,
        })
        if location and location not in self.visited:
            self.visited.append(location)

    def note_item(self, item: str):
        """记录获得的关键物品（不会被压缩丢失）"""
        self.key_items.append(item)

    # ── 压缩 ──

    def should_compress(self) -> bool:
        """原始记录超过阈值时需压缩"""
        return len(self.raw_history) > self.max_raw

    def compress(self, llm_call: Callable[[str], str]):
        """
        将超出阈值的旧记录压缩进摘要。
        llm_call: 接受 prompt 返回压缩文本的函数。
        """
        if len(self.raw_history) <= self.max_raw:
            return

        to_compress = self.raw_history
        self.raw_history = []

        history_text = ""
        for rec in to_compress:
            history_text += (
                f"[T{rec['turn']}][{rec['location']}] "
                f"{rec['user_input']} → {rec['result']}\n"
            )

        prompt = f"""将以下TRPG游戏记录压缩为简洁摘要，保留：
- 玩家行动轨迹（经过哪些场景）
- 与NPC的对话和情报
- 获得的关键物品
- 基于已有摘要合并加入新记录的内容，必要的话进行缩写
用第三人称流畅中文，不超过2000字。

已有摘要：{self.summary or '（无）'}

新记录：
{history_text}"""

        new_summary = llm_call(prompt)
        self.summary = new_summary
    # ── 上下文输出 ──

    def get_context(self) -> str:
        """构建完整上下文字符串，供 prompt 使用"""
        parts = []

        if self.summary:
            parts.append(f"【历史摘要】\n{self.summary}")

        if self.visited:
            parts.append(f"【已探索】{' → '.join(self.visited)}")

        if self.key_items:
            parts.append(f"【物品】{', '.join(self.key_items)}")

        if self.raw_history:
            recent = "\n".join([
                f"  T{rec['turn']}[{rec['location']}]: {rec['user_input']} → {rec['result']}"
                for rec in self.raw_history
            ])
            parts.append(f"【近期行动】\n{recent}")

        return "\n\n".join(parts) if parts else ""

    def to_dict(self) -> dict:
        return {
            "raw_history": self.raw_history,
            "summary": self.summary,
            "visited": self.visited,
            "key_items": self.key_items,
            "turn": self.turn,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryManager":
        mm = cls(max_raw=data.get("max_raw", 5))
        mm.raw_history = data.get("raw_history", [])
        mm.summary = data.get("summary", "")
        mm.visited = data.get("visited", [])
        mm.key_items = data.get("key_items", [])
        mm.turn = data.get("turn", 0)
        return mm
