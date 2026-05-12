"""
TRPG 场景核心模块 —— 数据类、有向图、玩家、运行时世界、记忆管理。

从 notebook_simplified.ipynb 拆分，不包含任何 LLM 调用或 UI 逻辑。
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple, Set, Callable, TYPE_CHECKING
if TYPE_CHECKING:
    from investigator.models import Investigator as InvestigatorType
from dataclasses import dataclass, field


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
    result: str          # 执行结果
    clue: Optional[str] = None         # 对玩家的提示
    requirements: List[Requirement] = field(default_factory=list)   # 前置条件
    side_effects: list = field(default_factory=list)   # FlagSet | ItemGain | StatChange

    def summary(self) -> str:
        return f"[{self.type}] {self.name}"


@dataclass
class FlagSet:
    """设置世界标记"""
    key: str
    value: bool = True


@dataclass
class ItemGain:
    """获得关键物品"""
    item_name: str


@dataclass
class StatChange:
    """
    属性变化（预留）
    - COC 规则下的 SAN/HP 变化涉及检定与鉴定大成功/失败规则
    - 当前仅做结构化记录，不自动修改 Investigator 状态
    """
    stat_name: str
    delta: int       # 正=回复，负=损失


@dataclass
class ActionResult:
    """交互/事件执行的统一返回类型"""
    success: bool
    message: str
    side_effects: list = field(default_factory=list)     # JSON 声明的确定性副作用
    suggested_flags: list = field(default_factory=list)   # LLM 建议（预留，本轮不实现）


def _parse_side_effect(data: dict):
    """从 dict 解析单个 side effect"""
    type_ = data.get("type", "")
    if type_ == "flag_set":
        return FlagSet(key=data["key"], value=data.get("value", True))
    elif type_ == "item_gain":
        return ItemGain(item_name=data["item_name"])
    elif type_ == "stat_change":
        return StatChange(stat_name=data["stat_name"], delta=data.get("delta", 0))
    return None


def _parse_side_effects(data: list) -> list:
    """从 list[dict] 解析 side effects"""
    result = []
    for d in data:
        parsed = _parse_side_effect(d)
        if parsed is not None:
            result.append(parsed)
    return result


def _side_effect_to_dict(effect) -> dict:
    """将 side effect 实例序列化为 dict"""
    if isinstance(effect, FlagSet):
        return {"type": "flag_set", "key": effect.key, "value": effect.value}
    elif isinstance(effect, ItemGain):
        return {"type": "item_gain", "item_name": effect.item_name}
    elif isinstance(effect, StatChange):
        return {"type": "stat_change", "stat_name": effect.stat_name, "delta": effect.delta}
    return {}


@dataclass
class GameEvent:
    """全局不可逆事件（来自 res_event_revised.json）"""
    event_id: str        # E1, E2, ...
    name: str            # 事件名称
    trigger: str         # 触发条件
    impact: str          # 不可逆影响（从 irreversible_impact 或 impact 键读取）
    requirements: List[Requirement] = field(default_factory=list)   # 前置条件


@dataclass
class Node:
    node_id: str
    description: str = ""
    edges: List[Edge] = field(default_factory=list)     # from_here —— 出边（可去往的地点）
    to_here: List[Edge] = field(default_factory=list)   # 入边（从哪些地点可来此）
    interactions: List[Interaction] = field(default_factory=list)

    def get_interaction(self, name: str) -> Optional[Interaction]:
        for inter in self.interactions:
            if inter.name == name:
                return inter
        return None


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
        self.events: Dict[str, GameEvent] = {}
        if scenes:
            self.load_scenes(scenes)
        if events:
            self.load_events(events)

    # ── 加载 ──

    def load_scenes(self, data: dict):
        """从 scene_output_resolved_revised.json 格式的字典加载场景"""
        for node_id, node_info in data.items():
            interactions = [
                Interaction(
                    type=inter["type"],
                    name=inter["name"],
                    trigger=inter.get("trigger", ""),
                    result=inter.get("result", ""),
                    clue=inter.get("clue"),
                    requirements=[
                        Requirement(
                            ref_type=req.get("ref_type", ""),
                            ref_scene=req.get("ref_scene", ""),
                            ref_name=req.get("ref_name", ""),
                        )
                        for req in inter.get("requirement", [])
                    ],
                )
                for inter in node_info.get("interactions", [])
            ]

            from_edges = [
                Edge(target=conn["target"], method=conn["method"])
                for conn in node_info.get("from_here", [])
            ]
            to_edges = [
                Edge(target=conn["source"], method=conn["method"])
                for conn in node_info.get("to_here", [])
            ]

            self.nodes[node_id] = Node(
                node_id=node_id,
                description=node_info.get("description", ""),
                edges=from_edges,
                to_here=to_edges,
                interactions=interactions,
            )

    def load_events(self, data: list):
        """从 res_event_resolved_revised.json 格式的列表加载全局事件"""
        for item in data:
            eid = item["id"]
            self.events[eid] = GameEvent(
                event_id=eid,
                name=item["name"],
                trigger=item.get("trigger", ""),
                impact=item.get("irreversible_impact", item.get("impact", "")),
                requirements=[
                    Requirement(
                        ref_type=req.get("ref_type", ""),
                        ref_scene=req.get("ref_scene", ""),
                        ref_name=req.get("ref_name", ""),
                    )
                    for req in item.get("requirement", [])
                ],
            )

    # ── 查询 ──

    def get_edges_from(self, node_id: str) -> List[Edge]:
        if node_id in self.nodes:
            return self.nodes[node_id].edges
        return []

    def get_interactions(self, node_id: str) -> List[Interaction]:
        if node_id in self.nodes:
            return self.nodes[node_id].interactions
        return []

    def get_event(self, event_id: str) -> Optional[GameEvent]:
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
                if not self.world.flags.get(req.ref_name, False):
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
                if not self.world.flags.get(req.ref_name, False):
                    unmet.append(req)
        return unmet

    def resolve_chain(self, requirements: List[Requirement]) -> List[Requirement]:
        """（桩）追踪传递依赖链，返回最深层的未满足前置条件。留待后续实现。"""
        return self.get_unmet(requirements)


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
                 background_story: str = ""):
        self.graph = graph
        self.current_location = start_node
        self.player: 'InvestigatorType | None' = None

        # 前置条件解析器
        self.requirement_resolver = RequirementResolver(self)

        # 背景故事（模组设定，供叙事阶段参考）
        self.background_story = background_story

        # 事件追踪
        self.triggered_events: Dict[str, bool] = {
            eid: False for eid in graph.get_all_event_ids()
        }

        # 每个场景已完成动作名
        self.completed_interactions: Dict[str, Set[str]] = {}

        # 任意世界标记
        self.flags: Dict[str, bool] = {}

        # 记忆管理器
        self.memory = MemoryManager()

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

    def get_available_interactions(self) -> List[Interaction]:
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

    def _are_requirements_met(self, interaction: Interaction) -> bool:
        """检查指定交互的所有前置条件是否已满足"""
        if not interaction.requirements:
            return True
        ok, _ = self.requirement_resolver.check(interaction.requirements)
        return ok

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
                 "clue": i.clue,
                 "requirements_met": self._are_requirements_met(i)}
                for i in interactions
            ],
            "triggered_events": [eid for eid, t in self.triggered_events.items() if t],
            "flags": dict(self.flags),
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

    # ── 交互 ──

    def execute_interaction(self, name: str) -> ActionResult:
        """
        执行当前场景的指定动作。检查前置条件，标记完成并返回结果文本。
        不检查事件 —— 事件触发由外部 LLM 调用链独立处理。
        """
        node = self._current_node()
        if not node:
            return ActionResult(False, "当前场景不存在。")
        interaction = node.get_interaction(name)
        if not interaction:
            available = ', '.join(i.name for i in node.interactions)
            return ActionResult(False, f"当前场景没有动作「{name}」。可用动作：{available or '无'}")

        # 检查前置条件
        if interaction.requirements:
            ok, msg = self.requirement_resolver.check(interaction.requirements)
            if not ok:
                return ActionResult(False, msg)

        loc = self.current_location
        if loc not in self.completed_interactions:
            self.completed_interactions[loc] = set()
        self.completed_interactions[loc].add(name)
        return ActionResult(
            True,
            f"【{interaction.type}】{interaction.name}：{interaction.result}",
            side_effects=list(interaction.side_effects),
        )

    # ── 事件（纯泛用）──

    def trigger_event(self, event_id: str) -> ActionResult:
        event = self.graph.get_event(event_id)
        if not event:
            return ActionResult(False, f"未知事件：{event_id}")
        if self.triggered_events.get(event_id, False):
            return ActionResult(False, f"事件「{event.name}」已经触发过。")

        # 检查前置条件
        if event.requirements:
            ok, msg = self.requirement_resolver.check(event.requirements)
            if not ok:
                return ActionResult(False, msg)

        self.triggered_events[event_id] = True
        return ActionResult(True, f"【事件触发】{event.name}\n{event.impact}")

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

    # ── 标记（纯泛用）──

    def set_flag(self, key: str, value: bool = True):
        self.flags[key] = value

    def get_flag(self, key: str) -> bool:
        return self.flags.get(key, False)

    def toggle_flag(self, key: str):
        self.flags[key] = not self.flags.get(key, False)

    def apply_world_update(self, abstract: str):
        """应用世界更新结果"""
        self.set_background(abstract)

    def apply_scene_update(self, description: str):
        node = self._current_node()
        if node:
            node.description = description

    def __repr__(self):
        events_on = sum(1 for v in self.triggered_events.values() if v)
        interactions_done = sum(len(s) for s in self.completed_interactions.values())
        return (
            f"ScenarioWorld(location={self.current_location}, "
            f"events={events_on}/{len(self.triggered_events)}, "
            f"interactions_done={interactions_done}, "
            f"flags={len(self.flags)}, "
            f"background={'set' if self.background_story else 'none'})"
        )


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
