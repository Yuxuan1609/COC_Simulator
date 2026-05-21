"""Narrator agent — owns L1, converts NarratorBrief into immersive narrative."""
from __future__ import annotations
from typing import Any

from ..messages import NarratorBrief
from prompts import build_narrator_prompt, parse_narrative_output
from llm import call_deepseek


class Narrator:
    """Narrator agent. Owns L1, only agent that faces the player.

    Must never: make rulings, access L2/L3, know about game mechanics.
    """

    def __init__(self, l1_data: dict[str, Any]):
        self.l1_data = l1_data

    def narrate(self, brief: NarratorBrief, inv_info: str = "",
                user_input: str = "") -> tuple[str, str, str]:
        """Generate immersive narrative from KP's curated brief.

        Returns (brief_summary, immersive_narrative, scene_update).
        scene_update: "" if no scene change, else updated scene description.
        """
        scene_name = brief.scene_snapshot.location
        l1_scene = self.l1_data.get(scene_name) if self.l1_data else None

        prompt = self._build_prompt(brief, l1_scene=l1_scene, inv_info=inv_info,
                                    user_input=user_input)
        response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
                                 system="你是一个优秀的跑团KP，擅长生动、沉浸的叙事。"
                                        "你将系统裁定结果转化为富有氛围感的描述，融入克苏鲁式的压抑与未知，"
                                        "让玩家仿佛身临其境地感受每一刻的紧张与恐惧。",
                                 fallback_schema={"brief": "", "narrative": "", "scene_update": ""})
        return parse_narrative_output(response)

    def _build_prompt(self, brief: NarratorBrief, l1_scene: Any = None,
                      inv_info: str = "", user_input: str = "") -> str:
        return build_narrator_prompt(brief, l1_scene=l1_scene, inv_info=inv_info,
                                      user_input=user_input)
