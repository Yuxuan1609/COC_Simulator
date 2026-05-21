"""TimeAgent — LLM sub-agent for time narrative guidance."""
from __future__ import annotations
import json
from llm import call_deepseek
from prompts import _show_prompt


class TimeAgent:
    """LLM sub-agent: narrative time guidance. Not a counter."""

    def build_prompt(
        self,
        game_time: int,
        day: int,
        time_of_day: str,
        hour: int,
        recent_actions: str,
        current_scene: str,
        scene_description: str,
        time_costs_guideline: str,
    ) -> str:
        return f"""你是 TRPG 时间叙事引导者。基于当前游戏状态，评估时间推进的节奏和叙事影响。

当前时间：累计{game_time}分钟 (第{day}天 {time_of_day} {hour}时)
玩家最近行动：{recent_actions}
当前场景：{current_scene}
场景描述：{scene_description}
时间消耗参考：{time_costs_guideline}

评估要点：
- 玩家刚刚的动作消耗了多少时间？节奏需要加速还是减速？
- 时间变化是否影响场景氛围或实体可见性？
- 是否有需要 day/time_of_day 变更的重大时间跳跃？

返回 JSON：
{{"time_delta": 0, "narrative_hint": "时间相关的叙事提示（可为空）", "signal_hint": ""}}

time_delta 是额外推进的分钟数（如"睡觉"跳8小时），默认 0。narrative_hint 具体而非泛泛。signal_hint 仅在时间压力相关信号出现时填写。"""

    def assess(self, **kwargs) -> dict:
        prompt = self.build_prompt(**kwargs)
        _show_prompt("TimeAgent", prompt)
        try:
            response = call_deepseek(
                prompt,
                json_mode=True,
                model="deepseek-v4-flash",
                system="你是 COC 7th KP 时间叙事引导者。",
                max_tokens=300,
                fallback_schema={"time_delta": 0, "narrative_hint": "", "signal_hint": ""},
            )
            return json.loads(response) if isinstance(response, str) else response
        except Exception:
            return {"time_delta": 0, "narrative_hint": "", "signal_hint": ""}
