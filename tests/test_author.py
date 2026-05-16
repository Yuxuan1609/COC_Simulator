# tests/test_author.py
import sys
sys.path.insert(0, "src")
from game.agents.author import Author
from game.messages import EscalationRequest


def test_author_initializes():
    l3_data = type("L3Designer", (), {
        "module_meta": {"title": "test"},
        "tone_constraints": type("TC", (), {
            "genre": "horror", "forbidden": [], "recommended": [],
            "required": [], "narrative_style": ""
        })(),
        "scene_intents": {},
        "ending_conditions": [],
        "characters": [],
        "driving_force": "test",
        "world_rules": [],
    })()
    author = Author(l3_data)
    assert author.l3_data is not None


def test_author_builds_prompt():
    l3_data = type("L3Designer", (), {
        "module_meta": {"title": "test"},
        "tone_constraints": type("TC", (), {
            "genre": "horror", "forbidden": [], "recommended": [],
            "required": [],
            "narrative_style": ""
        })(),
        "scene_intents": {},
        "ending_conditions": [],
        "characters": [],
        "driving_force": "test",
        "world_rules": [],
    })()
    author = Author(l3_data)
    req = EscalationRequest(
        trigger="uncovered_action", severity=0.8,
        player_input="我想跳车",
        world_context={"location": "6号车厢"},
        unmatched_intent="跳车",
        reason="No entity matches"
    )
    prompt = author._build_prompt(req)
    assert "uncovered_action" in prompt
    assert "跳车" in prompt
