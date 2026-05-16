# tests/test_narrator.py
import sys
sys.path.insert(0, "src")
from game.agents.narrator import Narrator
from game.messages import NarratorBrief, ActionOutcome, ActionIntent, SceneSnapshot


def test_narrator_initializes():
    l1_data = {"6号车厢": type("SceneL1", (), {
        "description": "测试", "atmosphere": "紧张", "mood": "uneasy",
        "perceptible": [], "ambient_hints": [], "npc_appearances": []
    })()}
    narrator = Narrator(l1_data)
    assert narrator.l1_data is not None


def test_narrator_builds_prompt():
    narrator = Narrator({})
    snapshot = SceneSnapshot(
        location="test", description="desc", exits=[],
        perceptible_interactions=[], visible_npcs=[]
    )
    brief = NarratorBrief(
        action_outcomes=[],
        ambient_changes=[],
        scene_snapshot=snapshot,
        suggested_emphasis="test"
    )
    prompt = narrator._build_prompt(brief)
    assert "test" in prompt
    assert "desc" in prompt
