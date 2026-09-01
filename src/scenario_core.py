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
from config import COMMS_INTERVAL_MINUTES, WR0_ENABLED

from game.side_effects import (
    ItemGain, ConsumeItem, StatChange, SpawnEnemy, GrantWeapon, GrantSpell,
    SceneWeapon, NPCStateChange, NPCFollow,
    parse_markup, parse_markup_all,
)


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
    type: str
    name: str
    trigger: str
    result: str
    requirements: List[Requirement] = field(default_factory=list)
    side_effects: list = field(default_factory=list)

    def summary(self) -> str:
        return f"[{self.type}] {self.name}"


@dataclass
class ActionResult:
    """Movement action result."""
    success: bool
    message: str


def find_entity_by_id(world: 'ScenarioWorld', entity_id: str):
    """Shared entity lookup — scans scenes + events. Called by judge and keeper."""
    if entity_id in world.graph.events:
        return world.graph.events[entity_id]
    for node in world.graph.nodes.values():
        for e in node.interactions + node.auto_triggers:
            if e.id == entity_id:
                return e
    return None


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
    extra: dict | None = None      # time_range, etc.
    time_condition: str = ""      # JSON list of {"day": ">=N|<=N|N|ALL", "times": ["时段",...]}, e.g. [{"day":">=2","times":["夜间","早晨"]}]. [] = no constraint
    repeatable: bool = False      # F23: True = 完成后可再触发；默认 once

    def summary(self) -> str:
        return f"[{self.type}] {self.name}"

    @classmethod
    def from_dict(cls, data: dict, overrides: dict | None = None) -> "Entity":
        """统一工厂 — 从 dict 构造 Entity，覆盖所有构造点（8+ 处）。
        
        overrides: 可选，覆盖 data 中的特定字段（如 scene 需动态注入）。
        """
        d = dict(data)
        if overrides:
            d.update(overrides)
        return cls(
            id=d.get("id", ""),
            entity_type=d.get("entity_type", "interaction"),
            name=d.get("name", ""),
            scene=d.get("scene", ""),
            type=d.get("type", ""),
            requirement=d.get("requirement", ""),
            trigger=d.get("trigger", ""),
            result=d.get("result", ""),
            side_effects=list(d.get("side_effects", [])),
            graded_result=d.get("graded_result"),
            difficulty=d.get("difficulty", ""),
            extra=d.get("extra"),
            time_condition=d.get("time_condition", ""),
            repeatable=bool(d.get("repeatable", False)
                            or (d.get("extra") or {}).get("repeatable", False)),
        )


_GRADED_PATTERN = re.compile(r'^##GRADED##$')
_END_PATTERN = re.compile(r'##END_([^:]+):(.+?)##')


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
    match = _END_PATTERN.search(text)
    if match:
        return match.group(1), match.group(2)
    return None, None


_TIME_CONDITION_TIMES = {"凌晨", "早晨", "白天", "黄昏", "夜间"}


def check_time_condition(time_condition: str, day: int, time_of_day: str) -> bool:
    """Check if current game time satisfies entity's time_condition.

    time_condition format: JSON array of {"day": ">=N|<=N|N|ALL", "times": ["时段",...]},
    or []/"" for no constraint.

    Returns True if no constraint or any entry matches (OR logic within array).
    Each entry is AND between day condition and times check.
    """
    if not time_condition or time_condition == "[]":
        return True
    try:
        entries = json.loads(time_condition)
    except (json.JSONDecodeError, TypeError):
        return True  # malformed -> allow
    if not isinstance(entries, list) or not entries:
        return True
    for entry in entries:
        day_str = entry.get("day", "ALL") if isinstance(entry, dict) else "ALL"
        times = entry.get("times", ["ALL"]) if isinstance(entry, dict) else ["ALL"]
        # check day
        if day_str != "ALL":
            if day_str.startswith(">="):
                if day < int(day_str[2:]):
                    continue
            elif day_str.startswith("<="):
                if day > int(day_str[2:]):
                    continue
            else:
                if day != int(day_str):
                    continue
        # check times
        times_set = set(times)
        if "ALL" not in times_set and time_of_day not in times_set:
            continue
        return True
    return False



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
    elif isinstance(effect, NPCFollow):
        return {"type": "npc_follow", "npc_name": effect.npc_name, "follow": effect.follow}
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
                interactions.append(Entity.from_dict(inter, overrides={
                    "entity_type": "interaction",
                    "scene": inter.get("scene", node_id),
                }))

            auto_triggers = []
            for at in node_info.get("auto_triggers", []):
                auto_triggers.append(Entity.from_dict(at, overrides={
                    "entity_type": "auto_trigger",
                    "scene": at.get("scene", node_id),
                }))

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
            self.events[eid] = Entity.from_dict(item, overrides={
                "entity_type": "event",
            })

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
                        "extra": e.extra,
                        "time_condition": e.time_condition,
                        "repeatable": e.repeatable,
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
                        "extra": e.extra,
                        "time_condition": e.time_condition,
                        "repeatable": e.repeatable,
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
                "extra": e.extra,
                "time_condition": e.time_condition,
                "repeatable": e.repeatable,
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
                Entity.from_dict(inter)
                for inter in node_data.get("interactions", [])
            ]
            auto_triggers = [
                Entity.from_dict(at)
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
            graph.events[ev_data["id"]] = Entity.from_dict(ev_data, overrides={
                "entity_type": "event",
            })
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

_ENTITY_ID_PATTERN = re.compile(r'^[A-Z][A-Z0-9_]+[a-z]?$')


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

    # Sentinel keywords that always evaluate to False
    if hard.strip().upper() in ("NEVER_TRIGGER", "NEVER"):
        return False

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
                 wr0_enabled: bool = WR0_ENABLED,
                 enemy_library: Any = None,
                 weapon_library: Any = None,
                 boss_library: Any = None,
                 boss_encounters: list | None = None,
                 npc_profiles: dict | None = None,
                 item_library: Any = None,
                 spell_library: Any = None):
        from game.clock import GameClock
        from game.enemy_manager import EnemyManager
        from game.npc_manager import NPCManager
        from game.boss_manager import BossManager

        self.graph = graph
        self.current_location = start_node
        self.player: 'InvestigatorType | None' = None
        self.background_story = background_story
        self.wr0_enabled = wr0_enabled

        # 子系统
        self.clock = GameClock()
        self.memory = MemoryManager()
        self.chronicle = WorldChronicle()
        self.enemies = EnemyManager(enemy_library) if enemy_library else None
        self.npcs = NPCManager()
        if npc_profiles:
            self.npcs.init_from_profiles(npc_profiles)
        self._npc_profiles = npc_profiles or {}
        self.load_warnings: list[str] = []
        self.bosses = BossManager(boss_library, boss_encounters or []) if boss_library else None

        # 本体状态
        self.scene_weapons: dict[str, list[SceneWeapon]] = {}
        self.weapon_library = weapon_library
        self.item_library = item_library      # 统一资源层：物品库（可选，init_game 注入）
        self.spell_library = spell_library    # 统一资源层：法术库
        self._mp_regen_acc = 0        # MP 恢复分钟累计器(时间钩子)
        self.san_seen_sources: set[str] = set()   # F9: 目睹 SAN 全局去重(入档)
        self._insanity_llm = None   # F5 疯狂文本生成器（Task 2 由 game_loop 注入）
        self.clues: list = []
        self.narrative_memory: list = []

        # 从 graph nodes 加载 L2 定义的 scene_weapons → world.scene_weapons
        for node_id, node in graph.nodes.items():
            if node.scene_weapons:
                self.scene_weapons[node_id] = [
                    SceneWeapon(
                        weapon_ref=sw["weapon_ref"],
                        scene=node_id,
                        quantity=sw.get("quantity", 1),
                    )
                    for sw in node.scene_weapons
                ]
        self.time_costs: dict = {}
        self.comms_interval: int = COMMS_INTERVAL_MINUTES
        self.npc_states: dict[str, str] = {}

        self.triggered_events: Dict[str, bool] = {
            eid: False for eid in graph.get_all_event_ids()
        }
        self.completed_interactions: Dict[str, Set[str]] = {}

        self.runtime_state: Dict[str, NodeRuntimeState] = {}
        self.dependency_graph: Dict[str, Any] = {}

    # ── 向后兼容属性 — 代理到 clock ──

    @property
    def game_time(self) -> int:
        return self.clock.game_time

    @property
    def day(self) -> int:
        return self.clock.day

    @property
    def hour(self) -> int:
        return self.clock.hour

    @property
    def time_of_day(self) -> str:
        return self.clock.time_of_day

    @property
    def time_context(self) -> str:
        return self.clock.time_context

    @time_context.setter
    def time_context(self, value: str):
        self.clock.time_context = value

    def advance_time(self, minutes: int):
        old_day = self.clock.day
        self.clock.advance_time(minutes)
        # Auto-inject time flags into runtime_state
        # (先清旧 day:/time: flag 防长期局累积进 prompt/存档 -- ISSUES B2)
        current = self.clock.get_time_flags()
        for prefix in ("day:", "time:"):
            stale = [k for k in self.runtime_state
                     if k.startswith(prefix) and k not in current]
            for k in stale:
                del self.runtime_state[k]
        for flag, value in current.items():
            state = self.get_runtime_state(flag)
            state.completed = value
        # 时间钩子(2026-08-21 spec §2.2/§4)
        self._tick_time_effects(minutes)
        self._apply_daily_recovery(old_day)

    def _tick_time_effects(self, minutes: int):
        """MP 恢复(余数累计) + timed_effects 过期清除。"""
        import logging
        from investigator.rules import get_game_config
        logger = logging.getLogger("scenario_core")
        p = self.player
        if p is None:
            return
        # MP 恢复:分钟累计器攒 60 回 1 点/点每小时恢复率
        cfg = get_game_config()
        per_hour = int(cfg["mp_recovery_per_hour"])
        if p.derived.MP >= p.derived.MP_MAX:
            self._mp_regen_acc = 0
        else:
            self._mp_regen_acc = getattr(self, "_mp_regen_acc", 0) + max(0, minutes)
            if per_hour > 0 and self._mp_regen_acc >= 60:
                gain = (self._mp_regen_acc // 60) * per_hour
                self._mp_regen_acc -= (self._mp_regen_acc // 60) * 60
                before = p.derived.MP
                p.derived.MP = min(p.derived.MP_MAX, p.derived.MP + gain)
                if p.derived.MP != before:
                    logger.info("[time] MP 恢复 %d -> %d", before, p.derived.MP)
        # timed 过期清除(记录被清除的 id)
        now = self.clock.game_time
        expired = [t for t in getattr(p, "timed_effects", [])
                   if t.get("expire_at", 0) <= now]
        if expired:
            p.timed_effects = [t for t in p.timed_effects
                               if t.get("expire_at", 0) > now]
            for t in expired:
                logger.info("[time] timed 效果过期: %s", t.get("id"))

    def _apply_daily_recovery(self, old_day: int):
        """F8：跨日界恢复结算（速率 game_config 集中参数）。"""
        if not self.player:
            return
        days = self.clock.day - old_day
        if days <= 0:
            return
        from investigator.rules import get_game_config
        cfg = get_game_config()
        hp_rate = cfg.get("hp_recovery_per_day", 1)
        san_rate = cfg.get("san_recovery_per_day", 0)
        d = self.player.derived
        if hp_rate:
            d.HP = min(d.HP_MAX, d.HP + hp_rate * days)
        if san_rate:
            d.SAN = min(d.SAN_MAX, d.SAN + san_rate * days)

    def set_insanity_llm(self, llm_call):
        """注入疯狂文本生成器 callable(prompt)->str。None=回退固定文案。"""
        self._insanity_llm = llm_call

    def on_san_loss(self, loss: int, source: str = "") -> dict:
        """F5 疯狂判定钩子：所有 SAN 损失出口统一汇入（S3-P2 spec §1）。
        返回 {"temporary": bool, "indefinite": bool} 供调用方追加叙事。"""
        import logging
        result = {"temporary": False, "indefinite": False}
        p = self.player
        if p is None or loss <= 0:
            return result
        ins = p.insanity
        day = self.clock.day
        if ins.get("san_day") != day:  # 惰性跨日清零
            ins["san_lost_today"] = 0
            ins["san_day"] = day
            ins["san_at_day_start"] = p.derived.SAN
        ins["san_lost_today"] = int(ins.get("san_lost_today", 0)) + loss
        if loss >= 5 and not ins.get("temporary"):
            ok, msg, tier = p.check_skill("INT")
            if not ok:
                ins["temporary"] = self._gen_insanity_text("临时疯狂", source)
                result["temporary"] = True
                logging.getLogger("scenario_core").info(
                    "[F5] 临时疯狂触发（单次损失 %d，%s）", loss, source)
        start = int(ins.get("san_at_day_start", 0) or 0)
        if (start and not ins.get("indefinite")
                and ins["san_lost_today"] >= max(1, start // 5)):
            ins["indefinite"] = self._gen_insanity_text("总结性疯狂", source)
            result["indefinite"] = True
            logging.getLogger("scenario_core").info(
                "[F5] 总结性疯狂触发（当日累计 %d/%d）", ins["san_lost_today"], start)
        return result

    def _gen_insanity_text(self, kind: str, source: str) -> str:
        """LLM 现场生成（Task 2 注入）；未注入时回退固定文案。"""
        import logging
        if self._insanity_llm is None:
            return f"（{kind}）"
        try:
            p = self.player
            prompt = (f"调查员{p.name}因{source or '理智冲击'}陷入{kind}。"
                      f"用不超过 60 字中文描述其疯狂表现（如幻觉/偏执/歇斯底里），只写表现本身。")
            text = (self._insanity_llm(prompt) or "").strip()
            return text[:100] if text else f"（{kind}）"
        except Exception:
            logging.getLogger("scenario_core").warning(
                "[F5] 疯狂文本生成失败，回退固定文案", exc_info=True)
            return f"（{kind}）"

    def get_time_flags(self) -> dict:
        return self.clock.get_time_flags()

    @property
    def enemy_manager(self):
        """向后兼容 — 代理到 self.enemies。"""
        return self.enemies

    @enemy_manager.setter
    def enemy_manager(self, value):
        self.enemies = value

    # ── Dependency graph & runtime state ──

    def load_dependency_graph(self, dep_graph: dict):
        """Load L2 dependency graph into runtime-ready structures."""
        self.dependency_graph = dep_graph
        nodes = dep_graph.get("nodes", {})
        for eid in nodes:
            if eid not in self.runtime_state:
                self.runtime_state[eid] = NodeRuntimeState()
        self._register_boss_nodes()

    def _register_boss_nodes(self):
        """Register boss encounter IDs in dependency_graph and runtime_state
        so other entities can reference them as dependencies."""
        if not self.bosses:
            return
        for enc in self.bosses._encounters:
            boss_id = enc.get("id", "")
            if not boss_id:
                continue
            if "nodes" not in self.dependency_graph:
                self.dependency_graph["nodes"] = {}
            if boss_id not in self.dependency_graph["nodes"]:
                self.dependency_graph["nodes"][boss_id] = {
                    "entity_id": boss_id,
                    "entity_type": "boss",
                    "name": enc.get("description", "")[:40]
                }
            if boss_id not in self.runtime_state:
                self.runtime_state[boss_id] = NodeRuntimeState()

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
            target_state = self.get_runtime_state(target_id)

            if not target_state.completed:
                return False, f"需要先完成「{target_id}」"

        return True, ""

    def mark_completed(self, entity_id: str, tier: str = ""):
        """Mark entity as completed in runtime state with optional result tier."""
        state = self.get_runtime_state(entity_id)
        state.completed = True
        if tier:
            state.result_tier = tier

    def is_entity_completed(self, entity_id: str) -> bool:
        """Check if entity is completed. Checks runtime_state first, falls back to triggered_events."""
        state = self.runtime_state.get(entity_id)
        if state and state.completed:
            return True
        return self.triggered_events.get(entity_id, False)

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

    def are_entity_requirements_met(self, entity) -> bool:
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
                hint = " [需要前置]" if not self.are_entity_requirements_met(inter) else ""
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
                 "requirements_met": self.are_entity_requirements_met(i)}
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
        # O3 — Move restriction: use same flow as entity requirements
        edge = possible[target]
        if edge.requirement and edge.requirement.strip():
            # Split hard (entity IDs + AND/OR) from soft (natural language after ||)
            # Soft part evaluated by Parse (LLM) — only hard part checked here
            parts = edge.requirement.split("||", 1)
            hard = parts[0].strip()
            if hard and not parse_hard_requirement(hard, self.runtime_state):
                return ActionResult(
                    False,
                    f"前往{target}的条件未满足({edge.requirement})"
                )
        self.current_location = target
        # Sync following NPCs to new location
        if hasattr(self, 'npcs') and self.npcs:
            self.npcs.sync_followers(target)
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

    def build_snapshot(self) -> dict:
        """Pure data assembly — single source of truth for all prompt builders."""
        return {
            "location": self.current_location,
            "description": self.get_current_description(),
            "exits": [
                {"target": e.target, "method": e.method}
                for e in self.get_possible_exits()
            ],
            "time": self.clock.to_dict(),
            "player": self.player.build_snapshot() if self.player else {},
            "npcs_in_scene": self.npcs.get_in_scene_snapshot(self.current_location),
            "enemies_in_scene": (
                self.enemies.get_active_in_scene_snapshot(self.current_location)
                if self.enemies else []
            ),
            "boss_active": self.bosses.active_snapshot() if self.bosses else None,
            "scene_weapons": [
                {"weapon_ref": sw.weapon_ref, "quantity": sw.quantity}
                for sw in self.scene_weapons.get(self.current_location, [])
            ],
            "runtime": {
                "completed": [
                    eid for eid, s in self.runtime_state.items() if s.completed
                ],
                "triggered_events": [
                    eid for eid, t in self.triggered_events.items() if t
                ],
            },
            "narrative_memory": [
                f"{e['turn_range']}：{e['notes']}"
                for e in getattr(self, "narrative_memory", [])
            ],
        }

    def distill_narrative_memory(self, llm_call, max_entries: int = 5):
        """F25：把 memory.raw_history 蒸馏为一条叙事要点（伏笔/基调/NPC 关系），
        入 narrative_memory（5 条滚动）。与 memory.compress 同点触发、先蒸后压。"""
        records = list(self.memory.raw_history)
        if not records:
            return
        history_text = "\n".join(
            f"[T{r['turn']}][{r['location']}] {r['user_input']} → {r['result']}"
            for r in records)
        prompt = f"""将以下 TRPG 近期回合记录蒸馏为一条「叙事要点」，供叙事者长期记忆。
保留：未回收的伏笔 / 情绪基调变化 / NPC 关系变化 / 对玩家承诺过的后续。
只写要点本身，不超过 250 字中文，不要复述行动流水。

记录：
{history_text}"""
        notes = (llm_call(prompt) or "").strip()[:250]
        if not notes:
            return
        first, last = records[0]["turn"], records[-1]["turn"]
        self.narrative_memory.append(
            {"turn_range": f"T{first}-T{last}", "notes": notes})
        del self.narrative_memory[:-max_entries]

    # ── NPC 运行时状态 ──

    def set_npc_state(self, npc_name: str, state: str):
        self.npcs.set_state(npc_name, state)

    def get_npc_state(self, npc_name: str) -> str:
        npc = self.npcs.get(npc_name)
        return npc.state if npc else "未知"

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
            "clock": self.clock.to_dict(),
            "enemies": self.enemies.to_dict() if self.enemies else None,
            "npcs": self.npcs.to_dict() if hasattr(self, 'npcs') else {},
            "bosses": self.bosses.to_dict() if self.bosses else None,
            "scene_weapons": {
                scene: [{"weapon_ref": sw.weapon_ref, "quantity": sw.quantity}
                        for sw in weps]
                for scene, weps in self.scene_weapons.items()
            },
            "memory": self.memory.to_dict(),
            "chronicle": self.chronicle.to_dict(),
            "san_seen_sources": sorted(self.san_seen_sources),
            "clues": list(getattr(self, "clues", [])),
            "narrative_memory": list(getattr(self, "narrative_memory", [])),
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
        world.chronicle = WorldChronicle.from_dict(data.get("chronicle", {}))
        world.san_seen_sources = set(data.get("san_seen_sources", []))
        world.clues = list(data.get("clues", []))
        world.narrative_memory = list(data.get("narrative_memory", []))
        # 恢复 clock（无外部依赖）
        clock_data = data.get("clock")
        if clock_data:
            from game.clock import GameClock
            world.clock = GameClock.from_dict(clock_data)
        return world

    def save_state(self, path: str, extra_meta: dict | None = None):
        """全量快照存档（图 + 世界 + 记忆 + 调查员快照）。version 2。"""
        from investigator.serialization import to_dict as inv_to_dict
        from datetime import datetime
        import os

        data = {
            "version": 2,
            "timestamp": datetime.now().isoformat(),
            "graph": self.graph.to_dict(),
            "world": self.to_dict(),
            "memory": self.memory.to_dict(),
            "player_snapshot": inv_to_dict(self.player) if self.player else None,
            "_meta": extra_meta or {},
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load_state(cls, path: str, enemy_lib=None, boss_lib=None,
                   npc_profiles: dict | None = None) -> "ScenarioWorld":
        """从存档恢复。库由调用方（当前会话）透传——库是模组资产，不入档。
        结构性损坏 raise；单条引用失败/库缺失 → 跳过 + load_warnings。"""
        import logging
        log = logging.getLogger("scenario_core.load")
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if data.get("version") not in (1, 2):
            raise ValueError(f"不支持的存档版本: {data.get('version')}")
        graph = DirectedGraph.from_dict(data["graph"])
        world_data = data["world"]
        world_data["memory"] = data.get("memory", {})
        world = cls.from_dict(world_data, graph)
        world.load_warnings = []
        if npc_profiles is not None:
            world._npc_profiles = npc_profiles

        def _warn(msg):
            log.warning(msg)
            world.load_warnings.append(msg)

        enemies_data = world_data.get("enemies")
        if enemies_data:
            if enemy_lib is None:
                _warn("存档含敌人数据但当前会话无敌人库，敌人状态未恢复")
            else:
                from game.enemy_manager import EnemyManager
                try:
                    world.enemies = EnemyManager.from_dict(enemies_data, enemy_lib)
                except Exception as e:
                    _warn(f"敌人状态恢复失败（{e}），敌人状态未恢复")
        npcs_data = world_data.get("npcs")
        if npcs_data:
            from game.npc_manager import NPCManager
            try:
                world.npcs = NPCManager()
                world.npcs.from_dict(npcs_data, world._npc_profiles)
            except Exception as e:
                _warn(f"NPC 状态恢复失败（{e}）")
        bosses_data = world_data.get("bosses")
        if bosses_data:
            if boss_lib is None:
                _warn("存档含 Boss 数据但当前会话无 Boss 库，Boss 状态未恢复")
            else:
                from game.boss_manager import BossManager
                try:
                    world.bosses = BossManager.from_dict(bosses_data, boss_lib)
                except Exception as e:
                    _warn(f"Boss 状态恢复失败（{e}）")
        scene_weapons_data = world_data.get("scene_weapons", {})
        for scene, weps in scene_weapons_data.items():
            world.scene_weapons[scene] = [
                SceneWeapon(weapon_ref=w["weapon_ref"], scene=scene, quantity=w.get("quantity", 1))
                for w in weps
            ]
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


def apply_side_effects(world: 'ScenarioWorld', side_effects: list,
                       npc_events: list | None = None,
                       direct_weapon_callback=None) -> list:
    """Apply side effect dataclass instances to the world. Returns human-readable summaries.
    
    Args:
        world: ScenarioWorld instance
        side_effects: list of side effect dataclass instances
        npc_events: optional list to append NPC follow events (keeper path)
        direct_weapon_callback: optional callable(weapon_ref) for direct weapon grants (keeper path)
    """
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
                        from config_llm import LLM_FLASH_MODEL
                        from prompts import build_consume_item_fuzzy_prompt
                        held = im.describe()
                        if held and held != "（未持有物品）":
                            prompt = build_consume_item_fuzzy_prompt(
                                target=effect.item_name,
                                quantity=effect.quantity,
                                held_items=held,
                            )
                            result = call_deepseek(
                                prompt, json_mode=True, model=LLM_FLASH_MODEL,
                                system="你是 COC 7th KP 助理。",
                                fallback_schema={"matched": False, "material": "", "reason": ""},
                            )
                            if isinstance(result, str):
                                import json as _json
                                result = _json.loads(result)
                            matched_name = result.get("material") or result.get("item_name") or ""
                            if result.get("matched") and matched_name:
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
                try:
                    instance = world.enemy_manager.spawn(
                        effect.enemy_ref, target_scene, effect.quantity
                    )
                    msgs.append(
                        f"[生成敌人] {effect.enemy_ref} x{effect.quantity} "
                        f"在 {target_scene} ({instance.instance_id})"
                    )
                except KeyError:
                    msgs.append(
                        f"[生成敌人] 失败：敌人库中不存在「{effect.enemy_ref}」（已跳过）"
                    )
            else:
                msgs.append(
                    f"[生成敌人] {effect.enemy_ref} x{effect.quantity} 在 {target_scene}"
                )
        elif isinstance(effect, GrantSpell):
            lib = getattr(world, "spell_library", None)
            spell = lib.get(effect.spell_ref) if lib else None
            if spell is None:
                msgs.append(f"[获得法术失败] {effect.spell_ref}（法术库中不存在，已跳过）")
            else:
                if world.player and effect.spell_ref not in world.player.known_spells:
                    world.player.known_spells.append(effect.spell_ref)
                msgs.append(f"[获得法术] {spell.name}")
        elif isinstance(effect, GrantWeapon):
            target_scene = effect.scene or world.current_location
            if not effect.scene or not effect.scene.strip():
                # scene 为空：直接授予调查员
                if direct_weapon_callback:
                    direct_weapon_callback(effect.weapon_ref)
                    msgs.append(f"[武器授予] {effect.weapon_ref} x{effect.quantity} 直接授予调查员（待确认）")
                else:
                    # fallback: 放置到当前场景
                    if target_scene not in world.scene_weapons:
                        world.scene_weapons[target_scene] = []
                    world.scene_weapons[target_scene].append(SceneWeapon(
                        weapon_ref=effect.weapon_ref, scene=target_scene, quantity=effect.quantity))
                    world.memory.note_item(effect.weapon_ref)
                    msgs.append(f"[武器放置] {effect.weapon_ref} x{effect.quantity} 在 {target_scene}")
            else:
                sw = SceneWeapon(weapon_ref=effect.weapon_ref, scene=target_scene, quantity=effect.quantity)
                if target_scene not in world.scene_weapons:
                    world.scene_weapons[target_scene] = []
                world.scene_weapons[target_scene].append(sw)
                world.memory.note_item(effect.weapon_ref)
                msgs.append(f"[武器放置] {effect.weapon_ref} x{effect.quantity} 在 {target_scene}")
        elif isinstance(effect, NPCStateChange):
            world.npcs.set_state(effect.npc_name, effect.new_state)
            msgs.append(f"[NPC状态] {effect.npc_name} -> {effect.new_state}")
        elif isinstance(effect, NPCFollow):
            world.npcs.set_following(effect.npc_name, effect.follow)
            status = "开始跟随" if effect.follow else "停止跟随"
            msgs.append(f"[NPC跟随] {effect.npc_name} {status}")
            if npc_events is not None:
                npc_events.append(f"{effect.npc_name} {status}你")
        elif isinstance(effect, StatChange):
            if world.player:
                before_san = world.player.derived.SAN
                new_val, detail = world.player.modify_stat(effect.stat_name, effect.delta)
                msgs.append(f"[属性变化] {detail}")
                if effect.stat_name.strip().upper() == "SAN":
                    loss = before_san - world.player.derived.SAN
                    if loss > 0:
                        trig = world.on_san_loss(loss, "事件冲击")
                        if trig["temporary"] or trig["indefinite"]:
                            kind_text = (world.player.insanity.get("temporary")
                                         if trig["temporary"]
                                         else world.player.insanity.get("indefinite"))
                            msgs.append(f"[疯狂] {kind_text}")
                # Apply narrative description via LLM if present
                if effect.narrative and hasattr(world.player, 'personal_description'):
                    try:
                        from llm import call_deepseek
                        from config_llm import LLM_FLASH_MODEL
                        from prompts import build_stat_narrative_prompt
                        prompt = build_stat_narrative_prompt(
                            inv_desc=world.player.personal_description or world.player.appearance or "",
                            stat_name=effect.stat_name,
                            delta=str(effect.delta),
                            narrative=effect.narrative,
                        )
                        result = call_deepseek(
                            prompt, json_mode=True, model=LLM_FLASH_MODEL,
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


# ═══════════════════════════════════════════════════════════════
#  U2 WorldChronicle —— 世界状态摘要层（LLM 饲料，本期消费者=Author）
# ═══════════════════════════════════════════════════════════════

from collections import deque as _deque


class WorldChronicle:
    """滚动编年史：events(窗口15) + entity_results(截断100) + patches(append-only)。
    facts 不存储——render 时从 world 实时采集。
    events_summary 为 LLM 蒸馏预留字段（本期不接线，见 spec §5）。"""

    EVENTS_WINDOW = 15
    INPUT_MAX = 60
    TEXT_MAX = 100

    def __init__(self):
        self.events: _deque = _deque(maxlen=self.EVENTS_WINDOW)
        self.entity_results: dict[str, str] = {}
        self.patches: list[dict] = []
        self.events_summary: str = ""
        self._boss_seen_spawned: set[str] = set()   # boss diff 基准（入档防读档重报）
        self._boss_seen_dead: set[str] = set()

    # ── 生产者 ──

    def record_turn(self, turn_number: int, raw_input: str, result, world) -> None:
        """每回合末由 game_loop 调用。result 为 keeper TurnResult。"""
        entry = {"turn": turn_number, "input": (raw_input or "")[:self.INPUT_MAX]}
        brief = getattr(result, "brief", None)
        outcomes = brief.action_outcomes if brief else []
        if outcomes:
            entry["intent"] = outcomes[0].intent.action
            ents = {o.entity_id: (o.skill_tier or ("ok" if o.success else "fail"))
                    for o in outcomes if o.entity_id}
            if ents:
                entry["entities"] = ents
            for o in outcomes:
                if o.entity_id and o.entity_type == "interaction" and o.message:
                    self.entity_results[o.entity_id] = o.message[:self.TEXT_MAX]
        ats = [o.entity_id for o in outcomes if o.entity_type == "auto_trigger"]
        if ats:
            entry["at"] = ats
        spawns = [f"{se.enemy_ref}×{getattr(se, 'quantity', 1)}"
                  for o in outcomes
                  for se in (getattr(o, "side_effects", None) or [])
                  if type(se).__name__ == "SpawnEnemy"]
        if spawns:
            entry["spawn"] = spawns
        pend = getattr(result, "pending_interaction", None)
        if pend:
            entry["pending"] = pend.kind
        ci = getattr(result, "combat_init", None)
        if ci and ci.enemies:
            entry["combat"] = ["start(" + ",".join(
                getattr(e, "enemy_ref", "?") for e in ci.enemies) + ")"]
        ending = getattr(result, "ending", None)
        if ending:
            entry["ending"] = getattr(ending, "name", "") or str(ending)
        npc_events = getattr(result, "npc_events", None)
        if npc_events:
            entry["npc"] = [n[:40] for n in npc_events]
        boss_ev = self._diff_boss(world)
        if boss_ev:
            entry["boss"] = boss_ev
        self.events.append(entry)

    def _diff_boss(self, world) -> list[str]:
        """对 world.bosses 做增量 diff：新 engage / 新 defeated。逻辑同 llm_player._collect_mech_line。"""
        bosses = getattr(world, "bosses", None)
        if not bosses:
            return []
        events = []
        spawned = set(getattr(bosses, "_spawned_boss_ids", set()) or set())
        for bid in sorted(spawned - self._boss_seen_spawned):
            events.append(f"engage({bid})")
        self._boss_seen_spawned |= spawned
        enemies = getattr(world, "enemies", None)
        dead = set()
        for bid in spawned:
            iid = getattr(bosses, "_instance_ids", {}).get(bid)
            inst = enemies.get_by_id(iid) if (iid and enemies) else None
            if inst is not None and getattr(inst, "status", "") in ("dead", "defeated"):
                dead.add(bid)
        for bid in sorted(dead - self._boss_seen_dead):
            events.append(f"defeated({bid})")
        self._boss_seen_dead |= dead
        return events

    def record_combat_end(self, outcome: str, world) -> None:
        """战斗结算后由 keeper.complete_combat_turn 调用：标注当回合 combat_end，
        并同回合补 boss defeated diff（战斗在 record_turn 之后结算）。"""
        if not self.events:
            return
        e = self.events[-1]
        e["combat_end"] = outcome
        boss_ev = self._diff_boss(world)
        if boss_ev:
            e.setdefault("boss", []).extend(boss_ev)

    def record_patch(self, turn: int, level: str, entity_ids: list[str],
                     new_scenes: list[str], justification: str) -> None:
        self.patches.append({
            "turn": turn, "level": level, "entity_ids": list(entity_ids),
            "new_scenes": list(new_scenes),
            "justification": (justification or "")[:self.TEXT_MAX],
        })

    # ── LLM 蒸馏预留（本期不接线，spec §5）──

    def compress_events(self, llm_call) -> None:
        """将较旧事件蒸馏进 events_summary。接口预留，本期不实现。"""
        raise NotImplementedError("LLM 蒸馏为预留接口，本期不接线")

    # ── 消费者渲染 ──

    def render_for_author(self, world) -> str:
        parts = ["【世界真值】"]
        parts.append(f"  位置: {world.current_location}"
                     f"（已到访: {'→'.join(world.memory.visited) or '无'}）")
        parts.append(f"  时间: 第{world.clock.day + 1}天 {world.clock.time_of_day}"
                     f"（累计{world.clock.game_time}分钟）")
        p = world.player
        if p:
            weapons = "、".join(w.name for w in p.weapons) or "无"
            key_items = "、".join(getattr(world.memory, "key_items", [])) or "无"
            spells = "、".join(getattr(p, "known_spells", [])) or "无"
            timed = "；".join(
                f"{t.get('description', '')}（剩{max(0, t.get('expire_at', 0) - world.clock.game_time)}分钟）"
                for t in getattr(p, "timed_effects", [])
                if t.get("description"))
            timed_part = f" | 生效中: {timed}" if timed else ""
            parts.append(f"  玩家: HP {p.derived.HP}/{p.derived.HP_MAX} "
                         f"SAN {p.derived.SAN}/{p.derived.SAN_MAX} "
                         f"MP {p.derived.MP}/{getattr(p.derived, 'MP_MAX', '?')} "
                         f"LUCK {p.stats.LUCK} | 武器: {weapons}"
                         f" | 物品: {key_items} | 法术: {spells}{timed_part}")
        if world.enemies:
            for inst in world.enemies._instances.values():
                parts.append(f"  敌人: {inst.enemy_ref}@{inst.scene} "
                             f"状态={inst.status} flags={inst.flags}")
        bosses = getattr(world, "bosses", None)
        if bosses:
            spawned = getattr(bosses, "_spawned_boss_ids", set())
            iids = getattr(bosses, "_instance_ids", {})
            for bid in sorted(spawned):
                iid = iids.get(bid)
                inst = world.enemies.get_by_id(iid) if (world.enemies and iid) else None
                if inst is not None:
                    phase = getattr(inst, "_current_phase", "") or "—"
                    parts.append(f"  Boss: {bid}@{inst.scene} "
                                 f"状态={inst.status} 阶段={phase}")
                else:
                    parts.append(f"  Boss: {bid} 状态=已开战（实例缺失）")
            for enc in getattr(bosses, "_encounters", []):
                bid = enc.get("id", enc.get("boss_ref", "?"))
                if bid not in spawned:
                    parts.append(f"  Boss: {bid}@{enc.get('scene', '')} 未遭遇")
        if world.npcs:
            following = {n.name for n in world.npcs.get_following()}
            for name in world.npcs.all_names():
                npc = world.npcs.get(name)
                follow_mark = " [跟随中]" if name in following else ""
                parts.append(f"  NPC: {name}@{npc.scene} "
                             f"状态={npc.state}{follow_mark}")
        done = {eid: s for eid, s in world.runtime_state.items() if s.completed}
        if done:
            parts.append("  已完成实体:")
            for eid, s in done.items():
                result_text = self.entity_results.get(eid, "")
                line = f"    {eid}: {s.result_tier or 'ok'}"
                if result_text:
                    line += f" | {result_text}"
                parts.append(line)
        if world.scene_weapons:
            for scene, weps in world.scene_weapons.items():
                if weps:
                    parts.append(f"  场景武器: {scene} 剩余 "
                                 + "、".join(w.weapon_ref for w in weps))
        if self.patches:
            parts.append("【已注入内容】")
            for pt in self.patches:
                ids = "、".join(pt["entity_ids"]) or "（无实体）"
                scenes = "、".join(pt["new_scenes"])
                line = f"  T{pt['turn']} [{pt['level']}] {ids}"
                if scenes:
                    line += f" 新场景:{scenes}"
                parts.append(line)
        if self.events_summary:
            parts.append("【远期摘要】")
            parts.append(f"  {self.events_summary}")
        parts.append("【编年史】")
        for e in self.events:
            parts.append("  " + self._render_event(e))
        return "\n".join(parts)

    @staticmethod
    def _render_event(e: dict) -> str:
        segs = [f"T{e['turn']}", f'in="{e["input"]}"']
        for key, label in (("intent", "intent"), ("pending", "pending"),
                           ("move", "move"), ("standoff", "standoff"),
                           ("ending", "ending")):
            if e.get(key):
                segs.append(f"{label}={e[key]}")
        if e.get("entities"):
            segs.append("entities=" + ",".join(
                f"{k}:{v}" for k, v in e["entities"].items()))
        for key, label in (("at", "at"), ("spawn", "spawn"), ("boss", "boss"),
                           ("combat", "combat"), ("npc", "npc")):
            if e.get(key):
                segs.append(f"{label}={','.join(str(x) for x in e[key])}")
        if e.get("combat_end"):
            segs.append(f"combat=end({e['combat_end']})")
        return " | ".join(segs)

    # ── 序列化 ──

    def to_dict(self) -> dict:
        return {
            "events": list(self.events),
            "entity_results": dict(self.entity_results),
            "patches": list(self.patches),
            "events_summary": self.events_summary,
            "boss_seen_spawned": sorted(self._boss_seen_spawned),
            "boss_seen_dead": sorted(self._boss_seen_dead),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorldChronicle":
        c = cls()
        c.events = _deque(data.get("events", []), maxlen=cls.EVENTS_WINDOW)
        c.entity_results = dict(data.get("entity_results", {}))
        c.patches = list(data.get("patches", []))
        c.events_summary = data.get("events_summary", "")
        c._boss_seen_spawned = set(data.get("boss_seen_spawned", []))
        c._boss_seen_dead = set(data.get("boss_seen_dead", []))
        return c
