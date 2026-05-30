"""Narrator agent — owns L1, converts NarratorBrief into immersive narrative."""
from __future__ import annotations
from typing import Any

from ..messages import NarratorBrief
from prompts import build_narrator_prompt, parse_narrative_output
from llm import call_deepseek
from config_llm import LLM_FLASH_MODEL, RE_NARRATOR


class Narrator:
    """Narrator agent. Owns L1, only agent that faces the player.

    Must never: make rulings, access L2/L3, know about game mechanics.
    """

    def __init__(self, l1_data: dict[str, Any]):
        self.l1_data = l1_data
        from monitor.agent_monitor import AgentMonitor
        from monitor.policies import NarratorPolicy
        from llm import _init_sensor
        self.monitor = AgentMonitor("Narrator", _init_sensor(), NarratorPolicy())

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
        response = self.monitor.call(
            lambda p, **kw: call_deepseek(p, **kw),
            prompt, json_mode=True, model=LLM_FLASH_MODEL,
            reasoning_effort=RE_NARRATOR,
            system="你是一个优秀的跑团KP，擅长生动、沉浸的叙事。"
                   "\n\n你的任务是结合实体行动结果和场景感知信息，为玩家本轮的行动生成沉浸式叙事。"
                   "\n\n输出格式：{\"brief\": \"...\", \"narrative\": \"...\", \"scene_update\": \"\"}。直接输出 JSON。"
                   "\n\n── 字段规则 ──"
                   "\n- brief: 第三人称视角，简单清晰阐述本轮发生了什么（谁对谁做了什么）。仅陈述事实，不含情绪色彩。不超过50字。"
                   "\n- narrative: 第一人称视角（用「你」），以沉浸式语言描述玩家主观感受和经历——看到什么、听到什么、闻到什么、心里怎么想。融入场景氛围。不超过100字。"
                   "\n- brief 与 narrative 严格呼应：brief 陈述事实，narrative 展开感受"
                   "\n- scene_update: 当本轮行动导致场景发生「持久可见变化」时，输出变化后的完整场景描述。该字段会直接更新到玩家可见的场景描述（L1层），后续回合将使用新描述。变化包括但不限于：物品被移走/拾取、门被打开/关上、出现血迹/痕迹、光源亮起/熄灭、NPC 出现/离开。即兴行为（仅叙述性描写、无实际影响）不填此字段。无变化时填空字符串。"
                   "\n- 禁止在未提及获得物品时描述获得物品；禁止给出前文没有的实质性信息"
                   "\n- 叙事强调指明了本轮的叙事核心方向",
            fallback_schema={"brief": "", "narrative": "", "scene_update": ""},
        )
        return parse_narrative_output(response)

    def _build_prompt(self, brief: NarratorBrief, l1_scene: Any = None,
                      snap: dict | None = None, user_input: str = "") -> str:
        return build_narrator_prompt(brief, l1_scene=l1_scene, snap=snap,
                                      user_input=user_input)
