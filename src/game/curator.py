"""Curator — assembles NarratorBrief from turn outcomes."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scenario_core import ScenarioWorld

from .messages import ActionOutcome, NarratorBrief, SceneSnapshot


class Curator:
    """Assembles curated NarratorBrief from raw turn outcomes + world state."""

    def __init__(self, world: ScenarioWorld):
        self.world = world

    def assemble(
        self,
        outcomes: list[ActionOutcome],
        ambient_changes: list[str],
        emphasis: str = ""
    ) -> NarratorBrief:
        return NarratorBrief(
            action_outcomes=outcomes,
            ambient_changes=ambient_changes,
            scene_snapshot=self._build_snapshot(),
            suggested_emphasis=emphasis,
        )

    def _build_snapshot(self) -> SceneSnapshot:
        node = self.world._current_node()
        if not node:
            return SceneSnapshot(
                location=self.world.current_location,
                description="未知地点",
                exits=[],
                perceptible_interactions=[],
                visible_npcs=[],
            )

        exits = [{"target": e.target, "method": e.method}
                 for e in self.world.get_possible_exits()]

        done = self.world.completed_interactions.get(self.world.current_location, set())
        perceptible = [e.name for e in node.interactions if e.name not in done]

        return SceneSnapshot(
            location=self.world.current_location,
            description=node.description,
            exits=exits,
            perceptible_interactions=perceptible,
            visible_npcs=[],
        )
