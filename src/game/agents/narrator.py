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

    def narrate(self, brief: NarratorBrief, l3_data: Any = None) -> tuple[str, str]:
        """Generate immersive narrative from KP's curated brief.

        Returns (brief_summary, immersive_narrative).
        """
        scene_name = brief.scene_snapshot.location
        l1_scene = self.l1_data.get(scene_name) if self.l1_data else None

        prompt = self._build_prompt(brief, l1_scene=l1_scene, l3_data=l3_data)
        response = call_deepseek(prompt, json_mode=False)
        return parse_narrative_output(response)

    def _build_prompt(self, brief: NarratorBrief,
                      l1_scene: Any = None, l3_data: Any = None) -> str:
        return build_narrator_prompt(brief, l1_scene=l1_scene, l3_data=l3_data)
