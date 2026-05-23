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

    def narrate(self, brief: NarratorBrief, snap: dict | None = None,
                user_input: str = "") -> tuple[str, str, str]:
        """Generate immersive narrative from KP's curated brief.

        Returns (brief_summary, immersive_narrative, scene_update).
        scene_update: "" if no scene change, else updated scene description.
        """
        scene_name = brief.scene_snapshot.location
        l1_scene = self.l1_data.get(scene_name) if self.l1_data else None

        prompt = self._build_prompt(brief, l1_scene=l1_scene, snap=snap,
                                    user_input=user_input)
        response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
                                 reasoning_effort="max",
                                 system="你是一个优秀的跑团KP，擅长生动、沉浸的叙事。"
                                        "\n\n你的任务是结合实体行动结果和场景感知信息，为玩家输入生成沉浸式叙事。"
                                        "\n\n输出规则："
                                        "\n- brief: 简洁、清晰、客观概括本轮发生了什么，仅陈述事实，不含情绪色彩"
                                        "\n- narrative: 基于结果文学性展开，融入场景氛围，中文不超过100字"
                                        "\n- brief 与 narrative 必须严格呼应: brief 概述事实，narrative 文学展开"
                                        "\n- scene_update: 判断本轮是否导致场景可见变化（物品/门/血迹/光源/NPC），有则输出完整描述，无则为空"
                                        "\n- 即兴行为不导致场景变化，不填写 scene_update"
                                        "\n- 禁止在未提及获得物品时描述获得物品；禁止给出前文没有的实质性信息"
                                        "\n- 叙事强调指明了本轮的叙事核心方向"
                                        "\n\n输出格式：{\"brief\": \"...\", \"narrative\": \"...\", \"scene_update\": \"\"}。直接输出 JSON。",
                                 fallback_schema={"brief": "", "narrative": "", "scene_update": ""})
        return parse_narrative_output(response)

    def _build_prompt(self, brief: NarratorBrief, l1_scene: Any = None,
                      snap: dict | None = None, user_input: str = "") -> str:
        return build_narrator_prompt(brief, l1_scene=l1_scene, snap=snap,
                                      user_input=user_input)
