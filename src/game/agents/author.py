"""Author agent — owns L3, creates ModulePatch when KP escalates."""
from __future__ import annotations
from typing import Any

from ..messages import EscalationRequest, ModulePatch, StructuralEdit
from prompts import build_author_prompt
from llm import call_deepseek
import json


class Author:
    """Author agent. Owns L3, only faces KP.

    Must never: make rulings, output to player, touch L1.
    WR0 applies — Author is not bound by world rules.
    """

    def __init__(self, l3_data: Any):
        self.l3_data = l3_data
        self.escalation_history: list[EscalationRequest] = []

    def handle_escalation(self, request: EscalationRequest) -> ModulePatch:
        """Process an escalation request. Returns ModulePatch for KP to integrate."""
        self.escalation_history.append(request)

        prompt = self._build_prompt(request)
        response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash")
        patch_data = json.loads(response) if isinstance(response, str) else response

        return ModulePatch(
            entities=patch_data.get("entities", []),
            scene_descriptions=patch_data.get("scene_descriptions", {}),
            justification=patch_data.get("justification", ""),
        )

    # StructuralEdit reserved for future implementation
    def _structural_edit(self, request: EscalationRequest) -> StructuralEdit:
        raise NotImplementedError("StructuralEdit is reserved for future implementation")

    def _build_prompt(self, request: EscalationRequest) -> str:
        return build_author_prompt(request, self.l3_data)
