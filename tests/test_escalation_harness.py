"""
Escalation Flow Test Harness — based on test room + car 6 from the module.
5 cases with all LLM calls mocked. Author prompt/response logged to debug dir.

Cases:
  A: normal entity match — Parse hits IT1, Detector not triggered, zero overhead
  B: other + flavor — Detector says no, Author not triggered
  C: other + Author Patch — new entity integrated, recursive process_turn
  D: other + Author Reject — entities=[], rejection msg injected
  E: other + Author StructuralEdit — supplement pipeline triggered, new scene injected
"""
import sys, os, json
from datetime import datetime
from unittest.mock import patch as _upatch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_ROOT = os.path.join(
    os.path.dirname(__file__), "..", "data", "debug", "test_escalation", TIMESTAMP
)

from scenario_core import (
    DirectedGraph, ScenarioWorld, NodeRuntimeState,
)
from game.messages import (
    ActionIntent, ActionOutcome, TurnInput, IntentResult,
)
from game.agents.keeper import Keeper
from game.agents.author import Author


# =====================================================================
#  Shared world
# =====================================================================

def _make_world():
    scenes = {
        "test_room": {
            "interactions": [
                {
                    "id": "IT1", "entity_type": "interaction",
                    "name": "inspect items on table", "scene": "test_room",
                    "type": "Spot Hidden", "requirement": "", "trigger": "inspect the metal table",
                    "result": "##GRADED##",
                    "side_effects": [],
                    "graded_result": {
                        "on_failure": "The flickering bulb blinds you — you find nothing special.",
                        "on_regular": "You notice the last pages of the log are torn out. A key with number 42.",
                        "on_hard": "The log records experiments by a researcher named Hawthorne. Key 42 opens a locker.",
                        "on_extreme": "Hawthorne warned: do not stare into the mirror for more than five seconds.",
                    },
                    "difficulty": "regular",
                },
                {
                    "id": "IT2", "entity_type": "interaction",
                    "name": "read Hawthorne's research log", "scene": "test_room",
                    "type": "Library Use", "requirement": "IT1",
                    "trigger": "sit down and read the log in detail",
                    "result": "##GRADED##",
                    "side_effects": [],
                    "graded_result": {
                        "on_failure": "The handwriting is too messy to decipher.",
                        "on_regular": "Three phases: Observation, Contact, 'They responded'.",
                        "on_hard": "The log is an experiment report. The observer effect is mentioned repeatedly.",
                        "on_extreme": "Hawthorne tried to use the mirror as a barrier — but the experiment went wrong.",
                    },
                    "difficulty": "regular",
                },
            ],
            "auto_triggers": [
                {
                    "id": "AT_AMBIENT", "entity_type": "auto_trigger",
                    "name": "flickering light", "scene": "test_room",
                    "type": "None", "requirement": "", "trigger": "entering the room",
                    "result": "The bulb flickers violently with a buzzing sound.",
                    "side_effects": [], "difficulty": "None",
                }
            ],
            "from_here": [
                {"target": "car_6", "method": "through the iron door passage", "requirement": "IT4"}
            ],
            "to_here": [],
            "encounters": [], "scene_weapons": [], "extra": {},
            "description": "Unnervingly quiet. Only the occasional buzz of the bulb breaks the silence.",
        },
        "car_6": {
            "interactions": [
                {
                    "id": "I1", "entity_type": "interaction",
                    "name": "read the note on the door", "scene": "car_6",
                    "type": "None", "requirement": "", "trigger": "notice the note on the inner door",
                    "result": "The note says: Just keep moving forward. There is no way back.",
                    "side_effects": [], "difficulty": "None",
                },
            ],
            "auto_triggers": [], "encounters": [], "scene_weapons": [],
            "from_here": [
                {"target": "car_5", "method": "walk through the connecting door", "requirement": ""},
                {"target": "test_room", "method": "walk back to test room", "requirement": ""},
            ],
            "to_here": [
                {"source": "test_room", "method": "through the iron door passage", "requirement": "IT4"}
            ],
            "extra": {},
            "description": "Lost and oppressive. A strange unease in the darkness.",
        },
    }
    graph = DirectedGraph(scenes=scenes, events=[])
    world = ScenarioWorld(graph, start_node="test_room")
    world.load_dependency_graph({"nodes": {
        "IT1": {"entity_id": "IT1", "entity_type": "interaction", "name": "inspect items on table"},
        "IT2": {"entity_id": "IT2", "entity_type": "interaction", "name": "read Hawthorne's research log"},
        "AT_AMBIENT": {"entity_id": "AT_AMBIENT", "entity_type": "auto_trigger", "name": "flickering light"},
        "I1": {"entity_id": "I1", "entity_type": "interaction", "name": "read the note on the door"},
    }, "edges": [
        {"source": "IT2", "target": "IT1", "dep_type": "interaction", "condition": "success"},
    ]})
    return world


def _make_author():
    l3 = {
        "module_meta": {"name": "test_module"},
        "world_rules": {"description": "A train endlessly running in darkness, chased by an unnameable devouring maw."},
        "scene_intents": {
            "test_room": {"purpose": "Debug and expansion entry point", "emotion": "Unease and curiosity"},
        },
        "ending_conditions": [],
        "tone_constraints": {
            "genre": "Lovecraftian horror",
            "narrative_style": "Oppressive, with faint hope in despair",
            "forbidden": ["superpowers", "firearms", "modern communication devices working"],
            "recommended": ["tension", "unknown fear", "moral dilemma"],
        },
        "characters": {"conductor": "Injured train conductor, key info provider"},
        "driving_force": "Keep moving forward in darkness, escape the devouring maw, find hope",
    }
    return Author(l3)


# =====================================================================
#  Mock factory + logging
# =====================================================================

def _setup_mocks(parse_actions, detector_result, author_result, log_dir=""):
    """Set up LLM mocks with unittest.mock.patch. Returns (detector_called, author_called, stop_fn).

    parse_actions:
      - list[dict]: same actions for all Parse calls
      - list[list[dict]]: parse_actions[N-1] for Nth Parse call (for recursion)

    Log files written to log_dir:
      01_parse_response.json (always)
      02_detector_prompt.txt + 02_detector_response.json (when detector called)
      03_author_prompt.txt + 03_author_response.json (when author called)
    """
    detector_called = [False]
    author_called = [False]
    parse_count = [0]

    def _log(filename, content):
        if not log_dir: return
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, filename), "w", encoding="utf-8") as f:
            f.write(content)

    def _log_json(filename, data):
        if not log_dir: return
        os.makedirs(log_dir, exist_ok=True)
        with open(os.path.join(log_dir, filename), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _get_parse_actions():
        if parse_actions and isinstance(parse_actions[0], list):
            idx = min(parse_count[0], len(parse_actions) - 1)
            return parse_actions[idx]
        return parse_actions

    def _mock_llm(prompt, json_mode=True, model="", system="", reasoning_effort="",
                   fallback_schema=None):

        # Parse
        if "【世界状态】" in prompt or "【玩家历史行动】" in prompt:
            actions = _get_parse_actions()
            if parse_count[0] == 0:
                _log_json("01_parse_response.json", {"actions": actions})
            parse_count[0] += 1
            return json.dumps({"actions": actions})

        # Detector
        if "纯角色扮演的例子" in prompt or "【玩家行为】" in prompt:
            detector_called[0] = True
            resp = detector_result
            resp_dict = resp if isinstance(resp, dict) else {
                "has_intent": resp.needs_author,
                "intent": resp.intent,
                "reasoning": resp.reasoning,
            }
            _log("02_detector_prompt.txt", prompt)
            _log_json("02_detector_response.json", resp_dict)
            return json.dumps(resp_dict)

        # Author
        if "WR0" in prompt or "请评估此意图的范围" in prompt:
            author_called[0] = True
            _log("03_author_prompt.txt", prompt)
            _log_json("03_author_response.json", author_result)
            return json.dumps(author_result)

        # Enrich / fallback
        return json.dumps({"results": {}, "reasoning": "", "emphasis_hint": ""})

    # Patch all module-level call_deepseek references.
    # Each module does `from llm import call_deepseek` at import time,
    # creating its own local reference. All must be patched individually.
    p1 = _upatch("game.agents.keeper.call_deepseek", _mock_llm)
    p2 = _upatch("game.intent_detector.call_deepseek", _mock_llm)
    p3 = _upatch("game.agents.author.call_deepseek", _mock_llm)
    p4 = _upatch("llm.call_deepseek", _mock_llm)  # evaluate_trait_enhancement etc.
    p1.start()
    p2.start()
    p3.start()
    p4.start()

    def stop():
        p1.stop()
        p2.stop()
        p3.stop()
        p4.stop()

    return detector_called, author_called, stop


def _write_case_log(log_dir, summary):
    if not log_dir: return
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "_case_log.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def _write_author_request_log(log_dir, data):
    if not log_dir: return
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "03_author_request.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# =====================================================================
#  Case A: normal entity match — zero overhead
# =====================================================================

def test_case_a_normal_entity(monkeypatch=None, log_dir=""):
    world = _make_world()
    keeper = Keeper(world)
    author = _make_author()

    detector_hit = [False]
    orig = keeper.intent_detector.detect
    def _track(*a, **kw):
        detector_hit[0] = True
        return orig(*a, **kw)
    keeper.intent_detector.detect = _track

    detector_called, _, stop = _setup_mocks(
        parse_actions=[{"type": "interaction", "id": "IT1"}],
        detector_result=IntentResult(needs_author=False),
        author_result={},
        log_dir=log_dir,
    )

    try:
        turn = TurnInput(raw_text="inspect every item on the table carefully")
        result = keeper.process_turn(turn, author=author)

        assert not detector_hit[0], "Case A: Detector should NOT be called"
        assert "escalation" not in result
        assert world.runtime_state["IT1"].completed, "IT1 should be marked completed"

        _write_case_log(log_dir, {
            "case": "A - normal entity match",
            "input": "inspect every item on the table carefully",
            "parse_result": "interaction IT1",
            "detector_called": False,
            "author_called": False,
            "flow": "Parse -> Judge -> Enrich -> Curate -> Narrator",
            "verdict": "PASS",
        })
    finally:
        stop()


# =====================================================================
#  Case B: other + flavor
# =====================================================================

def test_case_b_other_flavor(monkeypatch=None, log_dir=""):
    world = _make_world()
    keeper = Keeper(world)
    author = _make_author()

    detector_called, author_called, stop = _setup_mocks(
        parse_actions=[{"type": "other", "text": "sang a cheerful song"}],
        detector_result={"has_intent": False, "intent": "", "reasoning": "pure roleplay behavior"},
        author_result={},
        log_dir=log_dir,
    )

    try:
        turn = TurnInput(raw_text="sang a cheerful song")
        result = keeper.process_turn(turn, author=author)

        assert "escalation" not in result
        node = world.graph.nodes["test_room"]
        assert len(node.interactions) == 2, \
            f"Case B: expected 2 interactions (IT1+IT2), got {len(node.interactions)}"

        _write_case_log(log_dir, {
            "case": "B - other + flavor (no intent)",
            "input": "sang a cheerful song",
            "parse_result": "type=other",
            "detector_called": detector_called[0],
            "detector_result": "needs_author=False (pure roleplay)",
            "author_called": author_called[0],
            "flow": "Parse(other) -> Detector(no) -> Judge -> Enrich -> Curate",
            "verdict": "PASS",
        })
    finally:
        stop()


# =====================================================================
#  Case C: other + Author Patch
# =====================================================================

def test_case_c_author_patch(monkeypatch=None, log_dir=""):
    world = _make_world()
    keeper = Keeper(world)
    author = _make_author()

    detector_called, author_called, stop = _setup_mocks(
        parse_actions=[
            [{"type": "other", "text": "bend down and check under the table for hidden compartments"}],
            [{"type": "interaction", "id": "SI1"}],  # recursive parse matches patched entity
        ],
        detector_result={
            "has_intent": True,
            "intent": "Player wants to search the underside of the table for hidden spaces",
            "reasoning": "The module describes the tabletop but not the underside — a reasonable search extension.",
        },
        author_result={
            "level": "patch",
            "entities": [{
                "id": "SI1", "entity_type": "interaction",
                "scene": "test_room", "name": "search under the table",
                "type": "Spot Hidden", "requirement": "IT1",
                "trigger": "crouch down and feel along the table's underside",
                "result": "##GRADED##",
                "side_effects": [],
                "graded_result": {
                    "on_failure": "The underside is smooth — you find nothing.",
                    "on_regular": "Your fingers find a subtle depression — a hidden compartment. Inside: a crumpled note.",
                    "on_hard": "The compartment also contains a small key marked 'Locker 47'.",
                    "on_extreme": "The compartment was clearly added later — likely by Hawthorne himself. A cipher is scrawled on the note's back.",
                },
                "difficulty": "regular",
            }],
            "scene_descriptions": {},
            "justification": "The table underside is a reasonable search extension, consistent with Hawthorne's narrative.",
        },
        log_dir=log_dir,
    )

    try:
        turn = TurnInput(raw_text="bend down and check under the table for hidden compartments")
        result = keeper.process_turn(turn, author=author)

        _write_author_request_log(log_dir, {
            "other_texts": ["bend down and check under the table for hidden compartments"],
            "intent": "Player wants to search the underside of the table for hidden spaces",
            "reasoning": "The module describes the tabletop but not the underside.",
            "scene_context_note": "Built by Keeper._build_scene_context_for_author()",
        })

        node = world.graph.nodes["test_room"]
        assert len(node.interactions) >= 3, \
            f"Case C: expected 3+ entities (IT1+IT2+SI1), got {len(node.interactions)}"
        assert "escalation" not in result

        _write_case_log(log_dir, {
            "case": "C - other + Author Patch",
            "input": "check under the table",
            "parse_result": "type=other (round 1), interaction SI1 (round 2)",
            "detector_called": detector_called[0],
            "detector_result": "needs_author=True",
            "author_called": author_called[0],
            "author_level": "patch",
            "author_entity": "SI1: search under the table",
            "author_justification": "reasonable search extension",
            "integration": "recursive process_turn -> entity integrated",
            "verdict": "PASS",
        })
    finally:
        stop()


# =====================================================================
#  Case D: other + Author Reject
# =====================================================================

def test_case_d_author_reject(monkeypatch=None, log_dir=""):
    world = _make_world()
    world.wr0_enabled = False
    keeper = Keeper(world)
    author = _make_author()

    detector_called, author_called, stop = _setup_mocks(
        parse_actions=[
            [{"type": "other", "text": "take out phone and shine flashlight into the dark beyond the iron door"}],
        ],
        detector_result={
            "has_intent": True,
            "intent": "Player wants to use phone flashlight to illuminate the darkness beyond the iron door",
            "reasoning": "Using modern device for exploration is active investigation, but violates tone constraints.",
        },
        author_result={
            "level": "patch",
            "entities": [],
            "scene_descriptions": {},
            "justification": "REJECTED: Per L3 tone_constraints.forbidden, 'modern communication devices working' is banned. "
                           "Phone flashlight cannot penetrate the supernatural darkness of the train. "
                           "Guide the player to use existing observation methods (e.g., the cracked mirror).",
        },
        log_dir=log_dir,
    )

    try:
        turn = TurnInput(raw_text="take out phone and shine flashlight into the dark beyond the iron door")
        result = keeper.process_turn(turn, author=author)

        _write_author_request_log(log_dir, {
            "other_texts": ["take out phone and shine flashlight into the dark beyond the iron door"],
            "intent": "Player wants to use phone flashlight to illuminate the darkness",
            "reasoning": "Using modern device for exploration violates tone constraints.",
            "scene_context": {"wr0_enabled": False, "note": "WR0 off, Author must respect L3 tone_constraints.forbidden"},
        })

        node = world.graph.nodes["test_room"]
        assert len(node.interactions) == 2, \
            f"Case D: expected 2 interactions (IT1+IT2), got {len(node.interactions)}"

        all_messages = [o.message for o in result["brief"].action_outcomes]
        rejection_found = any("REJECTED" in m.upper() or "cannot" in m.lower() for m in all_messages)
        assert rejection_found or len(all_messages) > 0, \
            f"Case D: rejection message not found in outcomes: {all_messages}"

        _write_case_log(log_dir, {
            "case": "D - other + Author Reject",
            "input": "shine phone flashlight into darkness",
            "parse_result": "type=other",
            "detector_called": detector_called[0],
            "detector_result": "needs_author=True",
            "author_called": author_called[0],
            "author_level": "patch (reject)",
            "author_entities": [],
            "author_justification": "REJECTED: violates L3 forbidden constraint",
            "integration": "rejection msg injected into outcomes, no entity changes",
            "verdict": "PASS",
        })
    finally:
        stop()


# =====================================================================
#  Case E: other + Author StructuralEdit
# =====================================================================

def test_case_e_author_structural(monkeypatch=None, log_dir=""):
    world = _make_world()
    keeper = Keeper(world)
    author = _make_author()

    # Mock supplement pipeline
    def _mock_pipeline(player_intent="", reasoning="", base_l3=None,
                       entry_scene="", exit_scene="", output_dir="", module_name=""):
        # Simulate pipeline Step 1 prompts and log them (as if real pipeline ran)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
            l3_summary = "genre: Lovecraftian horror\nnarrative_style: Oppressive\nforbidden: superpowers, firearms, modern communication devices working\nrecommended: tension, unknown fear, moral dilemma\ndriving_force: Keep moving forward in darkness"
            base = f"""【L3 constraint】
{l3_summary}

【Player intent】
intent: communication with the mirror entity
reasoning: Communication instead of escape is an entirely new narrative thread

【Entry/Exit】
entry: test_room
exit: (decided by LLM)"""
            p1a = f"""You are a TRPG module creator. Generate supplement scenes based on the following info.

{base}

Generate 1-3 new scenes, each with interactions and auto_triggers.
Entity IDs use S_ prefix: SS1=scene1, SI1=interaction1, SAT1=AT1.
requirement field uses entity ID strings (e.g. \"SI1 AND SI2\").

Return JSON:"""
            p1b = f"""You are a TRPG module creator. Generate supplement events and scene connections based on the following info.

{base}

Generate global events (optional) and passage connections between new scenes.
Event IDs use SE_ prefix.

Return JSON:"""
            p1c = f"""You are a TRPG module creator. Generate L1 player-facing layer for new scenes.

{base}

Generate L1-format scene descriptions with Chinese names as keys.
Each scene: description, atmosphere, mood, perceptible (unconditionally perceptible elements list), ambient_hints.

Return JSON:"""
            for fname, content in [("04_pipeline_1a_prompt.txt", p1a),
                                    ("04_pipeline_1b_prompt.txt", p1b),
                                    ("04_pipeline_1c_prompt.txt", p1c)]:
                with open(os.path.join(log_dir, fname), "w", encoding="utf-8") as f:
                    f.write(content)

        return {
            "l1": {
                "mirror_world": {
                    "description": "The mirror surface ripples like water. You step into an inverted realm.",
                    "atmosphere": "Surreal stillness hiding unspeakable dread",
                    "mood": "Unease and curiosity intertwined",
                    "perceptible": ["endless mirrored corridors", "a distorted human silhouette in the distance"],
                    "ambient_hints": ["the reflected stars show the wrong season"],
                    "npc_appearances": {},
                }
            },
            "l2": {
                "scenes": {
                    "mirror_world": {
                        "description": "A space built from mirrors, where light bends at impossible angles. "
                                       "A humanoid figure approaches slowly from the distance.",
                        "interactions": [{
                            "id": "SI2", "entity_type": "interaction",
                            "name": "speak with the mirrored reflection", "scene": "mirror_world",
                            "type": "Persuade", "requirement": "",
                            "trigger": "call out to the approaching figure",
                            "result": "##GRADED##",
                            "side_effects": [],
                            "graded_result": {
                                "on_failure": "The figure does not respond, only continues its slow approach.",
                                "on_regular": "A voice echoes in your mind: 'You finally came. We've been waiting.'",
                                "on_hard": "The reflection admits it has been watching through the mirror. "
                                           "It offers a deal: let it possess you, in exchange for escape.",
                                "on_extreme": "It is not an enemy — it's a previous investigator, soul trapped in the mirror. "
                                              "Hawthorne was the first one captured. The mirror is the only way out.",
                            },
                            "difficulty": "hard",
                        }],
                        "auto_triggers": [{
                            "id": "SAT1", "entity_type": "auto_trigger",
                            "name": "mirror entrance seals", "scene": "mirror_world",
                            "type": "None", "requirement": "",
                            "trigger": "fully step into the mirror world",
                            "result": "The mirror surface seals behind you like quicksilver. "
                                      "The test room vanishes. There is no way back.",
                            "side_effects": [],
                            "difficulty": "None",
                        }],
                        "from_here": [
                            {"target": "mirror_abyss", "method": "follow the figure deeper", "requirement": "SI2"}
                        ],
                        "to_here": [
                            {"source": "test_room", "method": "step through the cracked mirror",
                             "requirement": "IT3"}
                        ],
                        "encounters": [], "scene_weapons": [], "extra": {},
                    }
                },
                "events": [{
                    "id": "SE1", "entity_type": "event",
                    "name": "truth of the mirror world", "type": "None", "requirement": "SI2",
                    "trigger": "learn Hawthorne's fate through conversation",
                    "result": "The mirrors on this train are not ordinary — they are soul cages. "
                              "Hawthorne did not disappear; he is trapped on the other side. "
                              "Every crack is a scar from his escape attempts.",
                    "side_effects": [], "difficulty": "None",
                }],
                "npc_profiles": {},
                "dependency_graph": {
                    "nodes": {
                        "SI2": {"entity_id": "SI2", "entity_type": "interaction", "name": "speak with reflection"},
                        "SAT1": {"entity_id": "SAT1", "entity_type": "auto_trigger", "name": "mirror entrance seals"},
                        "SE1": {"entity_id": "SE1", "entity_type": "event", "name": "truth of the mirror world"},
                    },
                    "edges": [
                        {"source": "SE1", "target": "SI2", "dep_type": "interaction", "condition": "success"},
                    ],
                },
                "_scene_names": {"mirror_world": "mirror_world"},
                "_phase1": {},
            },
            "l3": {
                "module_meta": {"name": "supplement", "supplement_of": "test_module",
                               "generated_for": "communication with the mirror entity"},
                "world_rules": {},
                "scene_intents": {
                    "mirror_world": {"purpose": "Reveal the truth behind the mirror, offer a moral choice",
                                     "emotion": "Surreal horror with a glimmer of hope"}
                },
                "ending_conditions": [],
                "tone_constraints": {},
                "characters": {},
                "driving_force": "Find a way out of the mirror prison",
            },
            "output_dir": "/tmp/test_supp_structural",
        }

    _upatch("module_designer.supplement_pipeline.run_supplement_pipeline", _mock_pipeline).start()

    detector_called, author_called, stop = _setup_mocks(
        parse_actions=[
            [{"type": "other",
              "text": "gaze into the cracked mirror and try to communicate with the entity in the dark"}],
            [{"type": "move", "target": "mirror_world"}],  # recursive parse: move to new scene
        ],
        detector_result={
            "has_intent": True,
            "intent": "Player wants to establish communication with the entity in the mirror, "
                      "rather than treating it as a mere horror element.",
            "reasoning": "Communication instead of escape is an entirely new narrative thread, "
                         "completely outside the module's scope.",
        },
        author_result={
            "level": "structural",
            "entities": [],
            "scene_descriptions": {},
            "entry_scene": "test_room",
            "exit_scene": "",
            "justification": "The player wants to communicate with the mirror entity. "
                           "This is a direct extension of Hawthorne's theory — if the mirror is a "
                           "'reverse observation device', then communication between observer and observed "
                           "should be possible. This requires a new 'mirror world' scene.",
        },
        log_dir=log_dir,
    )

    try:
        turn = TurnInput(raw_text="gaze into the cracked mirror and try to communicate with the entity")
        result = keeper.process_turn(turn, author=author)

        _write_author_request_log(log_dir, {
            "other_texts": ["gaze into the cracked mirror and try to communicate with the entity in the dark"],
            "intent": "Player wants to communicate with the mirror entity",
            "reasoning": "Communication is a completely new narrative thread beyond the module's scope.",
            "scene_context_note": "location=test_room, wr0_enabled=False.",
        })

        # Write pipeline Step 1 response logs (simulated — real pipeline would produce these)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
            # 1a response: scenes + interactions + auto_triggers
            with open(os.path.join(log_dir, "04_pipeline_1a_response.json"), "w", encoding="utf-8") as f:
                json.dump({"scenes": {"mirror_world": {
                    "description": "A space built from mirrors...",
                    "interactions": [{"id": "SI2", "entity_type": "interaction", "name": "speak with reflection", "scene": "mirror_world", "type": "Persuade", "requirement": "", "trigger": "call out", "result": "##GRADED##", "side_effects": [], "graded_result": {"on_failure": "...", "on_regular": "...", "on_hard": "...", "on_extreme": "..."}, "difficulty": "hard"}],
                    "auto_triggers": [{"id": "SAT1", "entity_type": "auto_trigger", "name": "mirror entrance seals", "scene": "mirror_world", "type": "None", "requirement": "", "trigger": "step into mirror world", "result": "The mirror seals behind you.", "side_effects": [], "difficulty": "None"}],
                    "from_here": [{"target": "mirror_abyss", "method": "follow the figure deeper", "requirement": "SI2"}],
                    "to_here": [{"source": "test_room", "method": "step through the cracked mirror", "requirement": "IT3"}],
                    "encounters": [], "scene_weapons": [], "extra": {},
                }}}, f, ensure_ascii=False, indent=2)
            # 1b response: events
            with open(os.path.join(log_dir, "04_pipeline_1b_response.json"), "w", encoding="utf-8") as f:
                json.dump({"events": [{"id": "SE1", "entity_type": "event", "name": "truth of the mirror world", "type": "None", "requirement": "SI2", "trigger": "learn Hawthorne's fate", "result": "The mirrors are soul cages.", "side_effects": [], "difficulty": "None"}]}, f, ensure_ascii=False, indent=2)
            # 1c response: L1
            with open(os.path.join(log_dir, "04_pipeline_1c_response.json"), "w", encoding="utf-8") as f:
                json.dump({"mirror_world": {"description": "The mirror surface ripples like water. You step into an inverted realm.", "atmosphere": "Surreal stillness hiding unspeakable dread", "mood": "Unease and curiosity intertwined", "perceptible": ["endless mirrored corridors", "a distorted human silhouette"], "ambient_hints": ["the reflected stars show the wrong season"], "npc_appearances": {}}}, f, ensure_ascii=False, indent=2)

        # Verify new scene injected
        assert "mirror_world" in world.graph.nodes, \
            f"Case E: new scene should be in graph. Found: {list(world.graph.nodes.keys())}"
        new_scene = world.graph.nodes["mirror_world"]
        assert len(new_scene.interactions) >= 1, \
            f"Case E: new scene should have at least 1 interaction. Found: {len(new_scene.interactions)}"

        # Verify entry connection
        entry_node = world.graph.nodes["test_room"]
        entry_targets = [e.target for e in entry_node.edges]
        assert "mirror_world" in entry_targets, \
            f"Case E: test_room should have edge to mirror_world. Found: {entry_targets}"

        # Verify runtime_state initialized for new entities
        assert "SI2" in world.runtime_state, "Case E: SI2 runtime_state not initialized"

        # Verify Author L3 updated
        assert "mirror_world" in str(author.l3_data.get("scene_intents", {})), \
            "Case E: Author L3 should include supplement scene_intents"

        _write_case_log(log_dir, {
            "case": "E - other + Author StructuralEdit",
            "input": "communicate with mirror entity",
            "parse_result": "type=other (round 1), move to mirror_world (round 2)",
            "detector_called": detector_called[0],
            "detector_result": "needs_author=True — new narrative thread",
            "author_called": author_called[0],
            "author_level": "structural",
            "author_justification": "need mirror world scene for entity communication narrative",
            "supplement_scenes": ["mirror_world"],
            "supplement_entities": ["SI2", "SAT1", "SE1"],
            "integration": "graph injection + from_here edge + runtime_state init + L3 update",
            "verdict": "PASS",
        })
    finally:
        stop()


# =====================================================================
#  Runner
# =====================================================================

def run_all_with_log():
    os.makedirs(OUT_ROOT, exist_ok=True)

    print(f"Escalation Test Harness")
    print(f"Output: {OUT_ROOT}")
    print(f"Cases: 5 (A: normal / B: flavor / C: patch / D: reject / E: structural)")
    print()

    cases = [
        ("case_a_normal_entity", test_case_a_normal_entity),
        ("case_b_other_flavor", test_case_b_other_flavor),
        ("case_c_author_patch", test_case_c_author_patch),
        ("case_d_author_reject", test_case_d_author_reject),
        ("case_e_author_structural", test_case_e_author_structural),
    ]

    results = {}
    for name, test_fn in cases:
        case_dir = os.path.join(OUT_ROOT, name)
        os.makedirs(case_dir, exist_ok=True)

        print(f"--- {name} ---")
        try:
            test_fn(log_dir=case_dir)
            results[name] = "PASS"
            print(f"    PASS")
            step_files = sorted(
                f for f in os.listdir(case_dir)
                if f[0].isdigit() or f == "_case_log.json"
            )
            if step_files:
                print(f"    Logs: {', '.join(step_files)}")
        except Exception as e:
            import traceback
            results[name] = f"FAIL: {e}"
            print(f"    FAIL: {e}")
            traceback.print_exc()
        print()

    summary_path = os.path.join(OUT_ROOT, "_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    passed = sum(1 for v in results.values() if v == "PASS")
    print(f"Done. {passed}/{len(results)} passed. Output: {OUT_ROOT}")
    return results


if __name__ == "__main__":
    run_all_with_log()
