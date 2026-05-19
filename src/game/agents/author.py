"""Author agent — owns L3, creates ModulePatch or triggers StructuralEdit."""
from __future__ import annotations
from typing import Any
import json

from ..messages import AuthorRequest, ModulePatch, StructuralEdit
from prompts import build_author_prompt
from llm import call_deepseek


class Author:
    """Author agent. Owns L3, only faces KP.

    Two-level response:
    - Patch: fill module gaps within existing scenes
    - StructuralEdit: trigger supplement pipeline for new scenes/content

    Must never: make rulings, output to player, touch L1.
    WR0 applies independently — see build_author_prompt.
    """

    def __init__(self, l3_data: Any):
        self.l3_data = l3_data
        self.history: list[dict] = []  # {intent, level, justification, turn}

    def handle_request(self, request: AuthorRequest, turn_number: int = 0) -> ModulePatch | StructuralEdit:
        """Process an AuthorRequest. Returns ModulePatch (patch or reject) or StructuralEdit."""
        self.history.append({
            "intent": request.intent,
            "turn": turn_number,
        })

        prompt = self._build_prompt(request)
        response = call_deepseek(
            prompt, json_mode=True, model="deepseek-v4-flash",
            reasoning_effort="max",
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

    def _build_prompt(self, request: AuthorRequest) -> str:
        return build_author_prompt(request, self.l3_data)
