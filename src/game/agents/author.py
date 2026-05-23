"""Author agent — owns L3, creates ModulePatch or triggers StructuralEdit."""
from __future__ import annotations
from typing import Any
import json

from ..messages import AuthorRequest, ModulePatch, StructuralEdit
from prompts import build_author_prompt
from llm import call_deepseek
from config_llm import LLM_FLASH_MODEL, RE_AUTHOR


DEFAULT_AUTHOR_PERSONA = (
    "专业的COC模组和小说作者，会根据一般游戏规则合理地反馈调查员们，"
    "对合理的探索行为以中性、正面性的回复，对不合理或者极度违背剧情线的行为予以负面回复或驳回。"
)


class Author:
    """Author agent. Owns L3, only faces KP.

    Two-level response:
    - Patch: fill module gaps within existing scenes
    - StructuralEdit: trigger supplement pipeline for new scenes/content

    Must never: make rulings, output to player, touch L1.
    WR0 applies independently — see build_author_prompt.
    """

    def __init__(self, l3_data: Any, persona: str = ""):
        self.l3_data = l3_data
        self.persona = persona or DEFAULT_AUTHOR_PERSONA
        if self.l3_data:
            tp = self.l3_data.get("time_pressure") if isinstance(self.l3_data, dict) else getattr(self.l3_data, "time_pressure", None)
            self.time_pressure = tp
        else:
            self.time_pressure = None
        self.history: list[dict] = []  # {intent, level, justification, turn}

    def handle_request(self, request: AuthorRequest, turn_number: int = 0) -> ModulePatch | StructuralEdit:
        """Process an AuthorRequest. Returns ModulePatch (patch or reject) or StructuralEdit."""
        self.history.append({
            "intent": request.intent,
            "turn": turn_number,
        })

        prompt = self._build_prompt(request)
        response = call_deepseek(
            prompt, json_mode=True, model=LLM_FLASH_MODEL,
            reasoning_effort=RE_AUTHOR,
            system="你是一个优秀的TRPG模组创作者，擅长根据游戏中突发情况动态扩展模组内容。"
                   "你的创作应与既有风格保持一致。",
            fallback_schema={
                "level": "patch",
                "entities": [],
                "scene_descriptions": {},
                "justification": "",
                "entry_scene": "",
                "exit_scene": "",
            },
        )
        data = json.loads(response) if isinstance(response, str) else response

        level = data.get("level", "patch")
        justification = data.get("justification", "")

        self.history[-1]["level"] = level
        self.history[-1]["justification"] = justification

        if level == "structural":
            return StructuralEdit(
                entry_scene=data.get("entry_scene", request.scene_context.get("location", "")),
                exit_scene=data.get("exit_scene", ""),
                justification=justification,
            )
        else:
            # patch or reject (entities=[] means reject)
            return ModulePatch(
                entities=data.get("entities", []),
                scene_descriptions=data.get("scene_descriptions", {}),
                justification=justification,
            )

    def update_l3(self, l3_updates: dict):
        """Merge supplement L3 updates into existing L3 data."""
        if isinstance(self.l3_data, dict):
            self.l3_data.update(l3_updates)

    def assess_time_pressure(self, comms_packet) -> dict:
        """Receive comms packet from Keeper, judge if time pressure needs action.
        Returns {"should_press": bool, "urgency_update": int|None, "reason": str, "signal": str}."""

        tp = self.time_pressure
        if not tp:
            return {"should_press": False, "urgency_update": None, "reason": "", "signal": ""}

        from prompts import build_time_pressure_assess_prompt
        import json as _json

        prompt = build_time_pressure_assess_prompt(
            guide=tp.get("guide", ""),
            urgency=tp.get("urgency", 0),
            urgency_max=tp.get("urgency_max", 10),
            key_signals=tp.get("key_signals", []),
            game_time=comms_packet.game_time,
            day=comms_packet.day,
            time_of_day=comms_packet.time_of_day,
            current_scene=comms_packet.current_scene,
            player_actions=comms_packet.player_actions,
            world_state=comms_packet.world_state,
        )
        try:
            response = call_deepseek(
                prompt, json_mode=True, model=LLM_FLASH_MODEL,
                system="你是 COC 7th 模组的时间压力管理者。",
                fallback_schema={"should_press": False, "urgency_update": None, "reason": "", "signal": ""},
            )
            result = _json.loads(response) if isinstance(response, str) else response
            if result.get("urgency_update") is not None:
                tp["urgency"] = min(result["urgency_update"], tp.get("urgency_max", 10))
            return result
        except Exception:
            return {"should_press": False, "urgency_update": None, "reason": "", "signal": ""}

    def _build_prompt(self, request: AuthorRequest) -> str:
        return build_author_prompt(request, self.l3_data, persona=self.persona)
