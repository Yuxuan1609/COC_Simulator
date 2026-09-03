"""NPC dataclass + NPCManager — NPC 全量管理（对话/态度/跟随/状态）"""
from __future__ import annotations
from dataclasses import dataclass, field
import re

from config import NPC_MEMORY_CAP

_STRIP = re.compile(
    r'\s*@(spawn_enemy|grant_weapon|grant_spell|stat_change|item_gain|consume_item|npc_state_change|npc_follow|env_change|attitude_change)'
    r'\([^)]*\)'
)


@dataclass
class NPC:
    name: str
    role: str = ""
    personality_notes: str = ""
    appearance: str = ""
    what_they_can_do: str = ""
    interaction_triggers: list[str] = field(default_factory=list)
    can_follow: bool = False
    follow_requirements: str = ""
    can_interact: bool = True
    interact_requirements: str = ""

    bound_interactions: list[dict] = field(default_factory=list)
    bound_auto_triggers: list[dict] = field(default_factory=list)

    scene: str = ""
    attitude: str = "neutral"
    attitude_value: int = 0
    following: bool = False
    memory: list[str] = field(default_factory=list)
    state: str = "alive"
    extra: dict | None = None


_ATTITUDE_MIDPOINTS = {
    "hostile": -75,
    "wary": -30,
    "neutral": 0,
    "friendly": 30,
    "devoted": 75,
}


def attitude_tier(value: int) -> tuple[str, str]:
    value = max(-100, min(100, int(value)))
    from investigator.rules import get_game_config
    for row in get_game_config()["npc_attitude_tiers"]:
        mx = row["max"]
        if mx is None or value <= mx:
            return row["key"], row["label"]
    return "devoted", "信任"


def _attitude_value_from_key(key: str | None) -> int:
    if not key:
        return 0
    return _ATTITUDE_MIDPOINTS.get(key, 0)


def _resolve_profile_attitude_value(data: dict) -> int:
    if data.get("attitude_value") is not None:
        return int(data["attitude_value"])
    s = data.get("attitude") or data.get("initial_attitude")
    if isinstance(s, str):
        return _attitude_value_from_key(s)
    return 0


def _build_req_text(req_text: str, world) -> str:
    """Turn a requirement string into natural language with entity names.
    
    "E1&&E2||soft text" → "需要先完成「事件名1」和「事件名2」。软条件：soft text"
    "I1 AND I3" → "需要先完成「交互名1」和「交互名3」"
    """
    if not world or not req_text:
        return req_text
    id_to_name: dict[str, str] = {}
    try:
        for node in world.graph.nodes.values():
            for e in node.interactions:
                id_to_name[e.id] = e.name
            for e in node.auto_triggers:
                id_to_name[e.id] = e.name
        for eid, entity in world.graph.events.items():
            id_to_name[eid] = entity.name
        for npc in world.npcs._npcs.values():
            for e in npc.bound_interactions:
                id_to_name[e.get("id", "")] = e.get("name", e.get("id", ""))
            for e in npc.bound_auto_triggers:
                id_to_name[e.get("id", "")] = e.get("name", e.get("id", ""))
    except Exception:
        return req_text

    def _resolve(ids_text: str) -> str:
        result = ids_text
        for eid in sorted(id_to_name, key=len, reverse=True):
            if eid in result:
                result = result.replace(eid, f"「{id_to_name[eid]}」")
        for op in ("AND", "OR", "&&", "||"):
            result = result.replace(f" {op} ", "、").replace(f" {op}", "、").replace(f"{op} ", "、").replace(op, "、")
        while "  " in result:
            result = result.replace("  ", " ")
        return result.strip()

    if "||" in req_text:
        hard, soft = req_text.split("||", 1)
        hard, soft = hard.strip(), soft.strip()
    else:
        hard = req_text.strip()
        soft = ""

    hard_named = _resolve(hard)
    parts = []
    if hard_named:
        parts.append(f"需要先完成 {hard_named}")
    if soft:
        parts.append(f"软条件：{soft}")
    return "。".join(parts)


class NPCManager:
    def __init__(self):
        self._npcs: dict[str, NPC] = {}

    STATE_GATE_MESSAGES: dict[str, str] = {
        "dead": "（{name} 已无法交谈）",
        "left": "（{name} 不在此处）",
    }

    def _check_follow_conditions(self, npc: NPC, world) -> tuple[bool, str]:
        """Check if NPC can follow. Evaluates follow_requirements (|| split format).

        Hard part (before ||): entity IDs checked via parse_hard_requirement against runtime_state.
        Soft part (after ||): natural language — passed through (LLM evaluates at parse time).
        Also checks can_follow bool + state gate.
        """
        if not npc.can_follow:
            hint = ""
            if npc.follow_requirements and npc.follow_requirements.strip():
                resolved = _build_req_text(npc.follow_requirements.strip(), world)
                hint = f"，{resolved}"
            return False, f"{npc.name} 不愿意跟随你{hint}"
        if npc.state in ("dead", "left"):
            return False, f"{npc.name} 无法跟随（{npc.state}）"
        key, label = attitude_tier(npc.attitude_value)
        if key in ("hostile", "wary"):
            return False, f"{npc.name} 拒绝跟随（态度：{label}）"

        req = npc.follow_requirements.strip() if npc.follow_requirements else ""
        if not req:
            return True, ""

        # Split by ||
        if "||" in req:
            hard, soft = req.split("||", 1)
            hard, soft = hard.strip(), soft.strip()
        else:
            hard = req
            soft = ""

        if hard:
            from scenario_core import parse_hard_requirement
            if not parse_hard_requirement(hard, world.runtime_state):
                resolved = _build_req_text(hard + (f"||{soft}" if soft else ""), world)
                return False, f"尚未满足 {npc.name} 的跟随条件，{resolved}"
        return True, ""

    # ── 初始化 ──

    def init_from_profiles(self, profiles: dict):
        """从 L2 npc_profiles 批量创建 NPC 实例。"""
        for name, data in profiles.items():
            av = max(-100, min(100, _resolve_profile_attitude_value(data)))
            key, _ = attitude_tier(av)
            self._npcs[name] = NPC(
                name=data.get("name", name),
                role=data.get("role", ""),
                personality_notes=data.get("personality_notes", ""),
                appearance=data.get("appearance", ""),
                what_they_can_do=data.get("what_they_can_do", ""),
                interaction_triggers=list(data.get("interaction_triggers", [])),
                can_follow=data.get("can_follow", False),
                follow_requirements=data.get("follow_requirements", ""),
                can_interact=data.get("can_interact", True),
                interact_requirements=data.get("interact_requirements", ""),
                bound_interactions=list(data.get("bound_interactions", [])),
                bound_auto_triggers=list(data.get("bound_auto_triggers", [])),
                scene=data.get("scene", ""),
                state=data.get("initial_state", "alive"),
                following=data.get("initial_following", False),
                attitude=key,
                attitude_value=av,
            )

    # ── 查询 ──

    def get(self, name: str) -> NPC | None:
        return self._npcs.get(name)

    def get_in_scene(self, scene: str) -> list[NPC]:
        return [n for n in self._npcs.values()
                if n.scene == scene and n.state not in ("dead", "left")]

    def get_in_scene_snapshot(self, scene: str) -> list[dict]:
        """Lightweight dict list for world snapshot — no dataclass internals exposed."""
        return [
            {"name": n.name, "state": n.state, "attitude": attitude_tier(n.attitude_value)[1],
             "following": n.following}
            for n in self._npcs.values()
            if n.scene == scene and n.state not in ("dead", "left")
        ]

    def all_names(self) -> list[str]:
        return list(self._npcs.keys())

    # ── 交互 ──

    def talk_to(self, npc_name: str, player_input: str, llm_call, world=None) -> str:
        """State gate -> can_interact gate -> interact_requirements gate -> inject profile/memory context -> LLM -> append memory.

        can_interact: NPC 是否具备互动能力（false = 永远不可自由对话，需 interact_unlock entity 解锁）。
        interact_requirements: 互动需满足的前置条件（|| 前硬性 entity ID，|| 后软性自然语言）。
        两者均满足时才能进行自由对话。
        """
        npc = self._npcs.get(npc_name)
        if not npc:
            return f"（{npc_name} 不在此处。）"

        gate = self.STATE_GATE_MESSAGES.get(npc.state, "")
        if gate:
            return gate.format(name=npc.name)

        if not npc.can_interact:
            hint = ""
            if npc.interact_requirements and npc.interact_requirements.strip():
                resolved = _build_req_text(npc.interact_requirements.strip(), world)
                hint = f"，{resolved}"
            return f"（{npc.name} 似乎不愿与你交谈{hint}。）"

        # Check interact_requirements (hard part evaluated against runtime_state)
        if npc.interact_requirements and npc.interact_requirements.strip():
            req = npc.interact_requirements.strip()
            if "||" in req:
                hard, soft = req.split("||", 1)
                hard, soft = hard.strip(), soft.strip()
            else:
                hard = req
                soft = ""
            if hard and world and hasattr(world, 'runtime_state'):
                from scenario_core import parse_hard_requirement
                if not parse_hard_requirement(hard, world.runtime_state):
                    resolved = _build_req_text(hard + (f"||{soft}" if soft else ""), world)
                    return f"（{npc.name} 暂时不愿与你交谈，{resolved}。）"

        if attitude_tier(npc.attitude_value)[0] == "hostile":
            return f"（{npc.name} 不愿理会你，将你驱赶。）"

        triggers_text = ""
        if npc.interaction_triggers:
            triggers_text = f"互动触发条件：{'； '.join(npc.interaction_triggers)}\n"

        _, label = attitude_tier(npc.attitude_value)
        system_prompt = (
            f"你是 NPC「{npc.name}」。\n"
            f"角色：{npc.role}\n"
            f"性格：{npc.personality_notes}\n"
            f"外貌：{npc.appearance}\n"
            f"能力与所知信息：{npc.what_they_can_do}\n"
            + triggers_text
            + f"当前态度：{label}（数值不展示）\n"
            f"当前状态：{npc.state}\n"
            + (f"对话记忆：{'； '.join(npc.memory[-5:])}\n" if npc.memory else "")
            + "\n请用符合角色设定的语气回复调查员。\n"
            "根据态度决定透露程度：敌意拒绝、警惕套话、友好有限透露、信任才交底。\n"
            "对调查员的身份声明与陈述自行判断是否采信，不要无条件相信。\n"
            f"若交谈改变你对调查员的态度，在回复末尾内嵌 @attitude_change(npc_name=\"{npc.name}\", delta=±N)，N 为整数。该标记不会展示给玩家。\n"
            "回复简洁（1-3句话）。"
        )
        user_prompt = f"调查员对你说：「{player_input}」"

        try:
            response = llm_call(user_prompt, system=system_prompt, json_mode=False)
        except Exception:
            response = f"（{npc.name} 沉默不语。）"
        else:
            from game.side_effects import parse_markup_all, AttitudeChange
            from scenario_core import apply_side_effects
            effs = parse_markup_all(response)
            for e in effs:
                if isinstance(e, AttitudeChange) and not (e.npc_name or "").strip():
                    e.npc_name = npc.name
            if effs and world is not None:
                apply_side_effects(world, effs)
            response = _STRIP.sub("", response).strip() or f"（{npc.name} 沉默不语。）"

        npc.memory.append(f"玩家：「{player_input}」-> 回复：「{response}」")
        if len(npc.memory) > NPC_MEMORY_CAP:
            npc.memory = npc.memory[-NPC_MEMORY_CAP:]
        return response

    # ── 状态变更 ──

    def set_attitude(self, name: str, delta: int | None = None, value: int | None = None):
        npc = self._npcs.get(name)
        if not npc:
            return
        if value is not None:
            npc.attitude_value = int(value)
        elif delta is not None:
            npc.attitude_value += int(delta)
        npc.attitude_value = max(-100, min(100, npc.attitude_value))
        npc.attitude, _ = attitude_tier(npc.attitude_value)

    def set_following(self, name: str, following: bool):
        npc = self._npcs.get(name)
        if not npc:
            return False
        if following:
            key, _ = attitude_tier(npc.attitude_value)
            if key in ("hostile", "wary"):
                return False
        npc.following = following
        return True

    def get_following(self) -> list[NPC]:
        return [n for n in self._npcs.values() if n.following]

    def set_state(self, name: str, state: str):
        if name in self._npcs:
            self._npcs[name].state = state

    def set_scene(self, name: str, scene: str):
        if name in self._npcs:
            self._npcs[name].scene = scene

    # ── 跟随同步 ──

    def sync_followers(self, scene: str):
        """所有 following=True 的 NPC 自动移动到 scene。"""
        for npc in self._npcs.values():
            if npc.following:
                npc.scene = scene

    # ── 序列化 ──

    def to_dict(self) -> dict:
        result = {}
        for name, npc in self._npcs.items():
            entry = {
                "scene": npc.scene,
                "attitude": npc.attitude,
                "attitude_value": npc.attitude_value,
                "following": npc.following,
                "memory": list(npc.memory),
                "state": npc.state,
                "can_interact": npc.can_interact,
            }
            if npc.extra is not None:
                entry["extra"] = npc.extra
            result[name] = entry
        return result

    def from_dict(self, data: dict, profiles: dict):
        """从序列化数据恢复运行时状态。profiles 用于恢复档案字段。
        can_interact 优先使用运行时值（save 中可能已被 unlock），回退到 profile 静态值。"""
        for name, state_data in data.items():
            profile = profiles.get(name, {})
            if "attitude_value" in state_data and state_data["attitude_value"] is not None:
                av = int(state_data["attitude_value"])
            else:
                av = _attitude_value_from_key(state_data.get("attitude"))
            av = max(-100, min(100, av))
            key, _ = attitude_tier(av)
            self._npcs[name] = NPC(
                name=name,
                role=profile.get("role", ""),
                personality_notes=profile.get("personality_notes", ""),
                appearance=profile.get("appearance", ""),
                what_they_can_do=profile.get("what_they_can_do", ""),
                interaction_triggers=list(profile.get("interaction_triggers", [])),
                can_follow=profile.get("can_follow", False),
                follow_requirements=profile.get("follow_requirements", ""),
                can_interact=state_data.get("can_interact", profile.get("can_interact", True)),
                interact_requirements=profile.get("interact_requirements", ""),
                bound_interactions=list(profile.get("bound_interactions", [])),
                bound_auto_triggers=list(profile.get("bound_auto_triggers", [])),
                scene=state_data.get("scene", ""),
                attitude=key,
                attitude_value=av,
                following=state_data.get("following", False),
                memory=list(state_data.get("memory", [])),
                state=state_data.get("state", "alive"),
                extra=state_data.get("extra"),
            )

    def __repr__(self):
        return f"NPCManager({len(self._npcs)} NPCs)"
