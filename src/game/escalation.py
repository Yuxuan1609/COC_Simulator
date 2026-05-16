"""Escalation policy -- configurable thresholds + natural-language rules via LLM."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Any
import json


@dataclass
class DimensionConfig:
    enabled: bool = True
    threshold: float = 0.5
    cooldown: int = 3
    max_per_session: int | None = None
    last_triggered_turn: int = -999
    trigger_count: int = 0

    def can_trigger(self, current_turn: int) -> bool:
        if not self.enabled:
            return False
        if self.max_per_session is not None and self.trigger_count >= self.max_per_session:
            return False
        if current_turn - self.last_triggered_turn < self.cooldown:
            return False
        return True


@dataclass
class EscalationRule:
    name: str
    description: str
    condition: str  # natural language
    priority: int = 0


@dataclass
class EscalationContext:
    severities: dict[str, float]
    player_input: str
    parsed_intents: list
    action_outcomes: list
    at_results: list
    world_snapshot: dict
    dimension_configs: dict[str, DimensionConfig]
    recent_escalations: list[str]
    turn_number: int


class EscalationPolicy:
    """Configurable escalation policy with LLM evaluation."""

    def __init__(self):
        self.dimensions: dict[str, DimensionConfig] = {}
        self.rules: list[EscalationRule] = []

    @classmethod
    def from_dict(cls, data: dict) -> EscalationPolicy:
        policy = cls()
        for name, cfg in data.get("dimensions", {}).items():
            policy.dimensions[name] = DimensionConfig(
                enabled=cfg.get("enabled", True),
                threshold=cfg.get("threshold", 0.5),
                cooldown=cfg.get("cooldown", 3),
                max_per_session=cfg.get("max_per_session"),
            )
        for rule_data in data.get("rules", []):
            policy.rules.append(EscalationRule(
                name=rule_data["name"],
                description=rule_data.get("description", ""),
                condition=rule_data["condition"],
                priority=rule_data.get("priority", 0),
            ))
        return policy

    @classmethod
    def from_file(cls, path: str) -> EscalationPolicy:
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def _check_dimension(self, name: str, severity: float) -> bool:
        cfg = self.dimensions.get(name)
        if not cfg:
            return False
        if not cfg.enabled:
            return False
        return severity >= cfg.threshold

    def _build_eval_prompt(self, ctx: EscalationContext) -> str:
        rules_text = ""
        for r in sorted(self.rules, key=lambda r: r.priority, reverse=True):
            rules_text += f"  [{r.name}] (priority={r.priority}): {r.condition}\n"

        dims_text = ""
        for name, cfg in self.dimensions.items():
            if cfg.enabled:
                dims_text += f"  {name}: threshold={cfg.threshold}\n"

        outcomes_text = ""
        for o in ctx.action_outcomes:
            outcomes_text += f"  [{'OK' if o.success else 'FAIL'}] {o.message}\n"

        prompt = f"""评估以下TRPG游戏状态是否需要作者介入。

【维度阈值】
{dims_text or '（无启用维度）'}

【规则】
{rules_text or '（无规则）'}

【当前回合】T{ctx.turn_number}
【玩家输入】{ctx.player_input}
【动作结果】
{outcomes_text or '（无）'}

【世界状态】{json.dumps(ctx.world_snapshot, ensure_ascii=False)}
【近期介入】{ctx.recent_escalations or '（无）'}

请评估每个维度的严重程度(0.0-1.0)和哪些规则被触发。返回 JSON：
{{
  "severities": {{"uncovered_action": 0.0, "narrative_deviation": 0.0, "world_inconsistency": 0.0}},
  "rules_triggered": [],
  "should_escalate": false
}}

直接输出 JSON。
"""
        return prompt
