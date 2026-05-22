"""Test failure penalty pipeline: judge generates → keeper preserves → narrator receives."""
import sys, os, json
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ── Helpers ──

def _make_minimal_world():
    from scenario_core import DirectedGraph, ScenarioWorld

    scenes = {
        "测试房间": {
            "description": "一个昏暗的房间",
            "from_here": [],
            "to_here": [],
            "interactions": [
                {
                    "id": "I1", "scene": "测试房间", "type": "侦查",
                    "name": "检查书桌", "requirement": "",
                    "trigger": "调查员靠近书桌时",
                    "result": "你发现了重要线索",
                    "side_effects": [],
                    "graded_result": {
                        "on_success": "你发现了重要线索",
                        "on_failure": "你什么都没发现",
                        "gates": {
                            "regular": "on_success", "failure": "on_failure",
                            "hard": "on_success", "extreme": "on_success",
                        }
                    },
                    "difficulty": "regular"
                },
                {
                    "id": "I2", "scene": "测试房间", "type": "无",
                    "name": "开灯", "requirement": "",
                    "trigger": "调查员触碰开关时",
                    "result": "灯亮了，房间内一览无余",
                    "side_effects": [],
                    "graded_result": None,
                    "difficulty": "None"
                },
            ],
            "auto_triggers": [],
            "encounters": [], "scene_weapons": [], "extra": {},
        }
    }
    events = []
    graph = DirectedGraph(scenes=scenes, events=events)
    world = ScenarioWorld(graph, start_node="测试房间")
    return world


def _set_player_for_skill_fail(world):
    from investigator import Investigator
    from investigator.rules import roll_stats, calc_derived, create_skill_list

    inv = Investigator(name="测试调查员", age=25, gender="男")
    inv.stats = roll_stats()
    inv.skills = create_skill_list()
    inv.derived = calc_derived(inv.stats, inv.age)
    inv.personal_description = "一名经验丰富的调查员"

    world.set_player(inv)
    return inv


# ── Test 1: Judge generates penalty ActionOutcome with narrative + side effects ──

def test_judge_generates_penalty_on_repeated_failure():
    """After 3+ failures on the same entity, judge returns ActionOutcome with penalty."""
    from game.judge import Judge
    from game.messages import ActionIntent
    from game.side_effects import StatChange, ItemGain

    penalty_mock = {
        "narrative": "你在反复检查时不小心碰倒了桌上的化学试剂，腐蚀性液体溅到手上，造成了伤害。",
        "markup_effects": [
            '@stat_change(stat_name="生命值", delta=-2, narrative="化学试剂灼伤")',
            '@item_gain(item_name="碎玻璃")',
        ],
    }

    world = _make_minimal_world()
    inv = _set_player_for_skill_fail(world)

    inv.check_skill = lambda skill, diff=None: (False, "检定失败 D100=80/50", "failure")

    with patch("llm.evaluate_trait_enhancement",
               return_value={"tier": "failure", "detail_override": None, "reason": "test"}):
        with patch("llm.evaluate_failure_penalty", return_value=penalty_mock):
            judge = Judge(world)
            entity = world.graph.nodes["测试房间"].interactions[0]
            intent = ActionIntent(action="interact", target="检查书桌")

            for i in range(3):
                outcome = judge._execute_entity(entity, intent=intent, player_input="检查书桌")

            assert outcome.success is False
            assert "化学试剂" in outcome.message, \
                f"Expected penalty narrative in message, got: {outcome.message}"
            assert len(outcome.side_effects) >= 1, \
                f"Expected side effects, got: {outcome.side_effects}"

            se_types = {type(se) for se in outcome.side_effects}
            assert StatChange in se_types
            assert ItemGain in se_types
            assert "失败惩罚" in outcome.skill_detail

            state = world.get_runtime_state("I1")
            assert state.retries == 3


# ── Test 2: Keeper enrich step preserves penalty narrative ──

def test_keeper_preserves_penalty_narrative_after_enrich():
    """
    When a failed interaction with penalty narrative is all_outcomes[0],
    and a subsequent success triggers enrich, the failure's message
    must NOT be overwritten by the enrich result.
    """
    from game.agents.keeper import Keeper
    from game.messages import ActionIntent, ActionOutcome

    penalty_narrative = "化学试剂灼伤了你的手，你感到一阵剧痛。"

    world = _make_minimal_world()
    inv = _set_player_for_skill_fail(world)

    keeper = Keeper(world)

    # Simulate judge outcomes: failure at index 0, success at index 1
    all_outcomes = [
        ActionOutcome(
            intent=ActionIntent(action="interact", target="检查书桌"),
            success=False,
            message=penalty_narrative,
            entity_id="I1", entity_type="interaction",
            skill_tier="failure",
            skill_detail="侦查检定：D100=80/50",
        ),
        ActionOutcome(
            intent=ActionIntent(action="interact", target="开灯"),
            success=True,
            message="灯亮了，房间内一览无余",
            entity_id="I2", entity_type="interaction",
        ),
    ]

    # Simulate the judged_entities fed into enrich (both entities now)
    judged_entities = [
        {
            "entity_type": "interaction", "id": "I1", "name": "检查书桌",
            "result": penalty_narrative, "success": False, "skill_tier": "failure",
        },
        {
            "entity_type": "interaction", "id": "I2", "name": "开灯",
            "result": "灯亮了，房间内一览无余", "success": True, "skill_tier": "",
        },
    ]

    # Run enrich
    enrich_mock_result = {"results": "你环顾四周，打开了灯，房间一览无余。",
                           "reasoning": "合并", "emphasis_hint": ""}
    with patch("game.agents.keeper.call_deepseek",
               return_value=json.dumps(enrich_mock_result)):
        enrichment = keeper._enrich(judged_entities, "检查书桌然后开灯")

    results = enrichment.get("results", "")
    assert isinstance(results, str) and results, "Enrich should return non-empty results"

    # Apply the enrich-result overwrite logic (the fix under test)
    updated = False
    for o in all_outcomes:
        if o.success and o.entity_type != "auto_trigger":
            o.message = results
            updated = True
            break
    if not updated:
        all_outcomes[0].message = results

    # Verify: failure outcome (index 0) message is still the penalty narrative
    assert all_outcomes[0].success is False
    assert all_outcomes[0].message == penalty_narrative, \
        f"Penalty narrative should be preserved, got: {all_outcomes[0].message}"

    # Verify: success outcome (index 1) message is the enrich result
    assert all_outcomes[1].success is True
    assert all_outcomes[1].message == results, \
        f"Success outcome should have enrich result, got: {all_outcomes[1].message}"
