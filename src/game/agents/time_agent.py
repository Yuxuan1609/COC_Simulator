"""TimeAgent — LLM sub-agent for time narrative guidance."""
from __future__ import annotations
import json
from llm import call_deepseek
from prompts import _show_prompt


class TimeAgent:
    """LLM sub-agent: evaluates time consumption for the current turn's actions."""

    def build_prompt(
        self,
        actions: list[dict],
        current_input: str = "",
    ) -> str:
        actions_text = ""
        for a in actions:
            tr = a.get("time_range")
            tr_text = f" 建议耗时={tr['min']}-{tr['max']}分钟" if tr else ""
            actions_text += f"  [{a['type']}] {a['name']} (成功={a['success']}){tr_text}\n"

        return f"""你是 TRPG 时间推进的判断者。基于玩家本轮的所有行动，评估时间推进情况。

玩家本轮输入：{current_input}

本轮行动：
{actions_text or '（无）'}

评估要点：
- 综合所有行动评估本轮总耗时，行动越复杂、越仔细耗时越久
- 如有 time_range 建议，以此为参考范围
- 自由动作（交谈、思考、观察等未触发实体的输入）评估其自然耗时

返回 JSON：
{{"time_delta": 0, "narrative_hint": "时间相关的叙事提示（可为空）"}}

time_delta 是本轮总推进分钟数，默认 0。narrative_hint 具体而非泛泛。"""

    def assess(self, actions: list[dict] | None = None, current_input: str = "", **kwargs) -> dict:
        prompt = self.build_prompt(
            actions=actions or [],
            current_input=current_input,
            **kwargs,
        )
        _show_prompt("TimeAgent", prompt)
        try:
            response = call_deepseek(
                prompt,
                json_mode=True,
                model="deepseek-v4-flash",
                system="你是 COC 7th KP 时间推进的判断者。",
                max_tokens=300,
                fallback_schema={"time_delta": 0, "narrative_hint": ""},
                thinking=False,
            )
            return json.loads(response) if isinstance(response, str) else response
        except Exception:
            return {"time_delta": 0, "narrative_hint": ""}
