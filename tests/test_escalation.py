# tests/test_escalation.py
import json
import sys
sys.path.insert(0, "src")
from game.escalation import EscalationPolicy, EscalationContext


SAMPLE_CONFIG = {
    "dimensions": {
        "uncovered_action": {
            "enabled": True, "threshold": 0.5, "cooldown": 3, "max_per_session": None
        },
        "narrative_deviation": {
            "enabled": True, "threshold": 0.6, "cooldown": 3, "max_per_session": None
        },
        "world_inconsistency": {
            "enabled": False, "threshold": 0.5, "cooldown": 2, "max_per_session": None
        }
    },
    "rules": [
        {
            "name": "npc_death", "priority": 10,
            "description": "NPC death triggers review",
            "condition": "An NPC died during this turn"
        }
    ]
}


def test_policy_loads_from_dict():
    policy = EscalationPolicy.from_dict(SAMPLE_CONFIG)
    assert len(policy.dimensions) == 3
    assert policy.dimensions["uncovered_action"].enabled is True
    assert policy.dimensions["world_inconsistency"].enabled is False
    assert len(policy.rules) == 1


def test_policy_builds_escalation_prompt():
    policy = EscalationPolicy.from_dict(SAMPLE_CONFIG)
    ctx = EscalationContext(
        severities={},
        player_input="test",
        parsed_intents=[],
        action_outcomes=[],
        at_results=[],
        world_snapshot={},
        dimension_configs={},
        recent_escalations=[],
        turn_number=1
    )
    prompt = policy._build_eval_prompt(ctx)
    assert "uncovered_action" in prompt
    assert "npc_death" in prompt
    assert "JSON" in prompt


def test_policy_checks_threshold():
    policy = EscalationPolicy.from_dict(SAMPLE_CONFIG)
    # severity 0.7 > threshold 0.5 => should trigger
    assert policy._check_dimension("uncovered_action", 0.7) is True
    # severity 0.3 < threshold 0.5 => should not
    assert policy._check_dimension("uncovered_action", 0.3) is False


def test_disabled_dimension_never_triggers():
    policy = EscalationPolicy.from_dict(SAMPLE_CONFIG)
    assert policy._check_dimension("world_inconsistency", 0.9) is False
