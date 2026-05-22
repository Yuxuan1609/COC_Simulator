"""Quasi-unit tests for Author intervention flow — all LLM calls mocked.

Covers the complete chain: IntentDetector → Author → Keeper integration.
Each test injects mock LLM responses via monkeypatch to simulate different scenarios.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import json
import pytest
from unittest.mock import patch, MagicMock
from scenario_core import (
    DirectedGraph, ScenarioWorld, Entity, Node, Edge,
    NodeRuntimeState,
)
from game.messages import (
    ActionIntent, ActionOutcome, TurnInput, NarratorBrief,
    AuthorRequest, IntentResult, ModulePatch, StructuralEdit,
)
from game.intent_detector import IntentDetector
from game.agents.keeper import Keeper
from game.agents.author import Author
from module_designer.l3_designer import L3Designer, ModuleMeta, ToneConstraints


# ═══════════════════════════════════════════════════════════════
#  Test fixtures
# ═══════════════════════════════════════════════════════════════

def _make_test_world():
    """Minimal ScenarioWorld with one scene, one interaction."""
    scenes = {
        "测试房间": {
            "interactions": [
                {
                    "id": "I1", "entity_type": "interaction",
                    "name": "检查桌子", "scene": "测试房间",
                    "type": "侦查", "requirement": "", "trigger": "检查桌子",
                    "result": "##GRADED##",
                    "side_effects": [],
                    "graded_result": {
                        "on_failure": "没发现什么",
                        "on_regular": "发现了一些东西",
                        "on_hard": "发现了很多东西",
                        "on_extreme": "完全理解了",
                    },
                    "difficulty": "regular",
                }
            ],
            "auto_triggers": [],
            "from_here": [],
            "to_here": [],
            "encounters": [],
            "scene_weapons": [],
            "description": "一个测试房间",
            "extra": {},
        }
    }
    graph = DirectedGraph(scenes=scenes, events=[])
    world = ScenarioWorld(graph, start_node="测试房间")
    world.load_dependency_graph({"nodes": {}, "edges": []})
    return world


def _make_test_author():
    """Minimal Author with L3 data (L3Designer object, not raw dict)."""
    l3 = L3Designer(
        module_meta=ModuleMeta(title="test"),
        tone_constraints=ToneConstraints(
            genre="恐怖",
            narrative_style="克苏鲁",
        ),
        driving_force="逃离",
    )
    return Author(l3)


# ═══════════════════════════════════════════════════════════════
#  Test A: No "other" — zero overhead
# ═══════════════════════════════════════════════════════════════

def test_no_other_zero_overhead(monkeypatch):
    """Parse returns only entity matches — no IntentDetector call, no Author call."""
    world = _make_test_world()
    keeper = Keeper(world)

    detect_called = [False]
    original_detect = keeper.intent_detector.detect
    def _no_detect(*args, **kwargs):
        detect_called[0] = True
        return original_detect(*args, **kwargs)
    keeper.intent_detector.detect = _no_detect

    def _mock_llm(prompt, json_mode=True, model="", system="", reasoning_effort="",
                   fallback_schema=None):
        return json.dumps({"actions": [{"type": "interaction", "id": "I1"}]})

    monkeypatch.setattr("game.agents.keeper.call_deepseek", _mock_llm)

    turn = TurnInput(raw_text="检查桌子")
    result = keeper.process_turn(turn, author=None)

    assert not detect_called[0], "Detector should not be called when no 'other' in parse"
    assert "escalation" not in result


# ═══════════════════════════════════════════════════════════════
#  Test B: "other" + flavor → Detector says no
# ═══════════════════════════════════════════════════════════════

def test_other_flavor_no_escalation(monkeypatch):
    """Player sings a song → Detector says needs_author=False → normal flow."""
    world = _make_test_world()
    keeper = Keeper(world)
    author = _make_test_author()

    call_count = [0]
    def _mock_call(prompt, json_mode=True, model="", system="", reasoning_effort="",
                   fallback_schema=None):
        call_count[0] += 1
        if call_count[0] == 1:  # Parse
            return json.dumps({"actions": [{"type": "other", "text": "唱了一首快乐的小曲"}]})
        elif call_count[0] == 2:  # Detector
            return json.dumps({"has_intent": False, "intent": "", "reasoning": "纯角色扮演"})
        return json.dumps({})

    monkeypatch.setattr("game.agents.keeper.call_deepseek", _mock_call)
    monkeypatch.setattr("game.intent_detector.call_deepseek", _mock_call)

    turn = TurnInput(raw_text="唱了一首快乐的小曲")
    result = keeper.process_turn(turn, author=author)

    assert "escalation" not in result


# ═══════════════════════════════════════════════════════════════
#  Test C: "other" + meaningful → Author patch → integrate
# ═══════════════════════════════════════════════════════════════

def test_other_meaningful_author_patch(monkeypatch):
    """Player tries new action → Detector triggers → Author returns patch → integrated."""
    world = _make_test_world()
    keeper = Keeper(world)
    author = _make_test_author()

    call_seq = [0]
    def _mock_call(prompt, json_mode=True, model="", system="", reasoning_effort="",
                   fallback_schema=None):
        call_seq[0] += 1
        n = call_seq[0]
        if "判断以下玩家行为是纯角色扮演" in prompt:
            return json.dumps({
                "has_intent": True,
                "intent": "玩家想检查座椅底下的暗格",
                "reasoning": "模组中未覆盖此搜索点",
            })
        elif "请评估此意图的范围" in prompt:
            return json.dumps({
                "level": "patch",
                "entities": [{
                    "id": "SI1", "entity_type": "interaction",
                    "scene": "测试房间", "name": "检查座椅底下",
                    "type": "侦查", "requirement": "", "trigger": "玩家弯腰检查座椅底部",
                    "result": "你发现了一个隐藏的暗格",
                    "side_effects": [], "graded_result": None, "difficulty": "regular",
                }],
                "scene_descriptions": {},
                "justification": "座椅底下是合理的搜索点，模组未覆盖",
            })
        elif n == 1:  # Parse
            return json.dumps({"actions": [{"type": "other", "text": "检查座椅底下有没有暗格"}]})
        else:  # Enrich on recursion
            return json.dumps({"results": {}, "reasoning": "", "emphasis_hint": ""})

    monkeypatch.setattr("game.agents.keeper.call_deepseek", _mock_call)
    monkeypatch.setattr("game.intent_detector.call_deepseek", _mock_call)
    monkeypatch.setattr("game.agents.author.call_deepseek", _mock_call)

    turn = TurnInput(raw_text="检查座椅底下有没有暗格")
    result = keeper.process_turn(turn, author=author)

    node = world.graph.nodes.get("测试房间")
    entity_names = [e.name for e in (node.interactions if node else [])]
    assert "检查座椅底下" in entity_names, f"Patch entity not integrated. Found: {entity_names}"


# ═══════════════════════════════════════════════════════════════
#  Test D: Author rejects → entities=[] → normal flow
# ═══════════════════════════════════════════════════════════════

def test_other_author_rejects(monkeypatch):
    """Player tries something world-rule-breaking, WR0=off, Author rejects."""
    world = _make_test_world()
    keeper = Keeper(world)
    author = _make_test_author()

    call_seq = [0]
    def _mock_call(prompt, json_mode=True, model="", system="", reasoning_effort="",
                   fallback_schema=None):
        call_seq[0] += 1
        if "判断以下玩家行为是纯角色扮演" in prompt:
            return json.dumps({
                "has_intent": True,
                "intent": "玩家想一拳打碎墙壁",
                "reasoning": "这是对场景的破坏性行为",
            })
        elif "请评估此意图的范围" in prompt:
            return json.dumps({
                "level": "patch",
                "entities": [],
                "scene_descriptions": {},
                "justification": "REJECTED: 墙壁是列车结构，无法用拳头打碎",
            })
        elif call_seq[0] == 1:  # Parse
            return json.dumps({"actions": [{"type": "other", "text": "一拳打碎车厢墙壁"}]})
        else:  # Enrich
            return json.dumps({"results": {}, "reasoning": "", "emphasis_hint": ""})

    monkeypatch.setattr("game.agents.keeper.call_deepseek", _mock_call)
    monkeypatch.setattr("game.intent_detector.call_deepseek", _mock_call)
    monkeypatch.setattr("game.agents.author.call_deepseek", _mock_call)

    turn = TurnInput(raw_text="一拳打碎车厢墙壁")
    result = keeper.process_turn(turn, author=author)

    assert "escalation" not in result
    node = world.graph.nodes["测试房间"]
    assert len(node.interactions) == 1  # Only original I1


# ═══════════════════════════════════════════════════════════════
#  Test E: Duplicate intent suppression
# ═══════════════════════════════════════════════════════════════

def test_duplicate_intent_suppressed(monkeypatch):
    """Same intent within cooldown window should not re-trigger Author."""
    world = _make_test_world()
    keeper = Keeper(world)
    author = _make_test_author()

    author_call_count = [0]
    def _mock_author(request, turn_number=0):
        author_call_count[0] += 1
        return ModulePatch(
            entities=[{
                "id": "SI_test", "entity_type": "interaction",
                "scene": "测试房间", "name": "测试对话",
                "type": "", "requirement": "", "trigger": "",
                "result": "NPC回应了",
                "side_effects": [], "graded_result": None, "difficulty": "regular",
            }],
            scene_descriptions={},
            justification="test",
        )

    original_handle = author.handle_request
    author.handle_request = _mock_author

    # Mock detector to always say yes
    def _mock_detect(other_text, world_snapshot):
        return IntentResult(needs_author=True, intent="玩家想和NPC对话", reasoning="未覆盖")

    keeper.intent_detector.detect = _mock_detect

    # Pre-fill recent_intents with the same intent
    keeper._recent_intents = ["玩家想和npc对话", "玩家想和npc对话", "玩家想和npc对话"]

    call_seq = [0]
    def _mock_llm(prompt, json_mode=True, model="", system="", reasoning_effort="",
                   fallback_schema=None):
        call_seq[0] += 1
        return json.dumps({"actions": [{"type": "other", "text": "和乘务员聊聊吧"}]})

    monkeypatch.setattr("game.agents.keeper.call_deepseek", _mock_llm)

    turn = TurnInput(raw_text="和乘务员再聊聊")
    result = keeper.process_turn(turn, author=author)
    assert author_call_count[0] == 0, f"Expected 0 Author calls (suppressed), got {author_call_count[0]}"

    author.handle_request = original_handle


# ═══════════════════════════════════════════════════════════════
#  Test F: AuthorRequest field integrity
# ═══════════════════════════════════════════════════════════════

def test_author_request_fields():
    """AuthorRequest carries all required fields correctly."""
    req = AuthorRequest(
        other_texts=["唱了一首歌", "试图对话"],
        intent="沟通意图",
        reasoning="未覆盖的社交行为",
        scene_context={
            "location": "测试房间",
            "description": "昏暗的房间",
            "available_scenes": ["测试房间", "走廊"],
            "npc_states": {"乘务员": "清醒"},
            "runtime_summary": {"I1": "regular"},
            "wr0_enabled": False,
        },
    )
    assert len(req.other_texts) == 2
    assert req.scene_context["wr0_enabled"] is False
    assert req.scene_context["available_scenes"] == ["测试房间", "走廊"]


# ═══════════════════════════════════════════════════════════════
#  Test G: _integrate_supplement entry/exit connections
# ═══════════════════════════════════════════════════════════════

def test_integrate_supplement_connects_entry():
    """_integrate_supplement adds from_here edge from entry scene."""
    world = _make_test_world()
    keeper = Keeper(world)
    author = _make_test_author()

    import module_designer.supplement_pipeline as sp

    def _mock_pipeline(**kwargs):
        return {
            "l1": {"新场景": {"description": "新场景", "atmosphere": "", "mood": "",
                              "perceptible": [], "ambient_hints": [], "npc_appearances": {}}},
            "l2": {
                "scenes": {
                    "新场景": {
                        "description": "全新的区域",
                        "interactions": [],
                        "auto_triggers": [],
                        "from_here": [],
                        "to_here": [{"source": "测试房间", "method": "走进去", "requirement": ""}],
                        "encounters": [], "scene_weapons": [], "extra": {},
                    }
                },
                "events": [],
                "npc_profiles": {},
                "dependency_graph": {"nodes": {}, "edges": []},
                "_scene_names": {},
                "_phase1": {},
            },
            "l3": {"module_meta": {}, "world_rules": {}, "scene_intents": {},
                   "ending_conditions": [], "tone_constraints": {}, "characters": {},
                   "driving_force": ""},
            "output_dir": "/tmp/test_supp",
        }

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sp, "run_supplement_pipeline", _mock_pipeline)

    se = StructuralEdit(entry_scene="测试房间", exit_scene="", justification="测试")
    result = keeper._integrate_supplement(se, author)

    assert "新场景" in world.graph.nodes
    entry_node = world.graph.nodes["测试房间"]
    targets = [e.target for e in entry_node.edges]
    assert "新场景" in targets, f"Entry scene should connect to new scene. Edges: {targets}"
    assert result.supplement_path == "/tmp/test_supp"

    monkeypatch.undo()


# ═══════════════════════════════════════════════════════════════
#  Test H: Keeper._build_scene_context_for_author
# ═══════════════════════════════════════════════════════════════

def test_build_scene_context_for_author():
    """_build_scene_context_for_author returns all required keys."""
    world = _make_test_world()
    world.wr0_enabled = True
    from game.npc_manager import NPC
    world.npcs._npcs["乘务员"] = NPC(name="乘务员", state="清醒")
    world.runtime_state["I1"] = NodeRuntimeState(completed=True, result_tier="regular")

    keeper = Keeper(world)
    ctx = keeper._build_scene_context_for_author()

    assert ctx["location"] == "测试房间"
    assert ctx["description"] == "一个测试房间"
    assert "测试房间" in ctx["available_scenes"]
    assert ctx["npc_states"] == {"乘务员": "清醒"}
    assert ctx["runtime_summary"] == {"I1": "regular"}
    assert ctx["wr0_enabled"] is True
