"""Message types for inter-agent communication."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActionIntent:
    """Parsed player intent from step 1 (LLM parse)."""
    action: str                      # "move" | "interact" | "search" | "other"
    target: str = ""                 # target scene (move) or interaction name (interact)
    skill_checks: list[str] = field(default_factory=list)
    reasoning: str = ""
    condition: str = ""              # non-empty when player tries unmet interaction


@dataclass
class ActionOutcome:
    """Result of executing one action."""
    intent: ActionIntent
    success: bool
    message: str                     # human-readable result
    entity_id: str = ""              # which entity was executed ("I1", "AT3", etc.)
    entity_type: str = ""            # "interaction" | "auto_trigger" | "event"
    side_effects: list[Any] = field(default_factory=list)


@dataclass
class SceneSnapshot:
    """Deterministic scene info for Narrator curation."""
    location: str
    description: str
    exits: list[dict]                # [{"target": "...", "method": "..."}]
    perceptible_interactions: list[str]  # names of available interactions
    visible_npcs: list[dict]         # [{"name": "...", "brief": "...", "demeanor": "..."}]


@dataclass
class NarratorBrief:
    """KP -> Narrator: curated ruling for narrative generation."""
    action_outcomes: list[ActionOutcome]
    ambient_changes: list[str]       # AT results perceptible to player
    scene_snapshot: SceneSnapshot
    suggested_emphasis: str          # what to highlight + tone direction


@dataclass
class EscalationRequest:
    """KP -> Author: escalation with context."""
    trigger: str                     # which dimension fired
    severity: float                  # 0.0-1.0
    player_input: str
    world_context: dict              # relevant subset of world state
    unmatched_intent: str | None = None
    reason: str = ""


@dataclass
class ModulePatch:
    """Author -> KP: persistent entity additions."""
    entities: list[dict]             # new entities in L2 dict format
    scene_descriptions: dict[str, str]  # scene_name -> updated description
    justification: str = ""


@dataclass
class StructuralEdit:
    """Author -> KP + Author: heavy module rewrite. WR0 applies. Reserved for future."""
    new_scenes: dict[str, dict]
    new_ending_conditions: list[dict]
    l3_adjustments: dict
    dependency_edges: list[dict]
    justification: str = ""


@dataclass
class TurnInput:
    """Entry point input."""
    raw_text: str
    player: Any | None = None  # Investigator | None
