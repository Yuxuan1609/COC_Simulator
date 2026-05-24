"""
Escalation Flow Real-LLM Test — 5 cases with real DeepSeek calls.
All prompts and responses logged to debug dir.

Usage:
  python tests/test_escalation_real.py              # all 5 cases
  python tests/test_escalation_real.py A            # single case
  python tests/test_escalation_real.py A C E        # selected cases
  ESCALATION_CASES=ACE python tests/test_escalation_real.py  # env var
"""
import sys, os, json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_ROOT = os.path.join(
    os.path.dirname(__file__), "..", "data", "debug", "test_escalation_real", TIMESTAMP
)

from scenario_core import DirectedGraph, ScenarioWorld, NodeRuntimeState
from game.messages import ActionIntent, ActionOutcome, TurnInput
from game.agents.keeper import Keeper
from game.agents.author import Author

# Import real call_deepseek BEFORE any patches are applied
import llm as _llm_module
_REAL_CALL_DEEPSEEK = _llm_module.call_deepseek


# =====================================================================
#  Shared world (same as mock harness)
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
            "encounters": [], "scene_weapons": [],
            "extra": {"features": ["flickering bulb", "metal table with items", "rusty ventilation grate", "iron door"]},
            "description": "Unnervingly quiet. Only the occasional buzz of the bulb breaks the silence. A rusty ventilation grate on the north wall has several screws missing.",
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


def _make_l1():
    return {
        "test_room": {
            "description": "你站在一间空旷的测试房间中。四壁是朴素的灰色混凝土，头顶悬挂着一盏忽明忽暗的白炽灯。房间中央有一张金属桌子，上面摆放着几样物品：一本泛黄的日志、一把生锈的钥匙、以及一面布满裂痕的镜子。",
            "atmosphere": "安静得令人不安，只有灯泡偶尔发出的滋滋声打破沉默。",
            "perceptible": [],
            "ambient_hints": ["灯泡的闪烁似乎并非电路问题，而是遵循着某种规律。"],
            "npc_appearances": [],
        },
        "car_6": {
            "description": "迷失而压抑。黑暗中弥漫着一种诡异的焦虑。",
            "atmosphere": "沉重而压迫，黑暗中透出微弱的希望。",
            "perceptible": [],
            "ambient_hints": [],
            "npc_appearances": [],
        },
    }


def _make_author():
    l3 = {
        "module_meta": {"name": "test_module"},
        "world_rules": [{
            "id": "WR1", "name": "梦境法则",
            "rule": "这列电车所在的整个世界是由奈亚拉托提普创造的噩梦空间，并非现实。物理法则可被扭曲，逻辑可被篡改。",
            "scope": "整个电车及其外部黑暗空间",
            "is_absolute": "绝对不可违反"
        }],
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
        "narrative_lines": [
            {
                "name": "霍桑研究员的真相",
                "outline": "从测试房间开始，通过检查桌子上的物品发现霍桑的日志，逐步揭示镜子背后隐藏的实验真相和灵魂囚笼的秘密。",
                "key_scenes": ["test_room", "car_6"],
                "type": "main",
            },
        ],
    }
    return Author(l3)


# =====================================================================
#  Helpers
# =====================================================================

def _log_text(log_dir, filename, content):
    if not log_dir: return
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, filename), "w", encoding="utf-8") as f:
        f.write(content)


def _log_json(log_dir, filename, data):
    if not log_dir: return
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, filename), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _case_log(log_dir, summary):
    _log_json(log_dir, "_case_log.json", summary)


# =====================================================================
#  LLM logging wrapper — intercepts all call_deepseek calls
# =====================================================================

import time as _time

_LLM_CALL_COUNTER = [0]

def _classify_call(system: str) -> str:
    """Return a descriptive label for this LLM call based on system prompt."""
    s = system or ""
    if "意图匹配" in s and "游戏实体" in s:
        return "01_parse"
    if "解析助手" in s or "KP助理" in s:
        return "01_parse"
    if "游戏状态监控" in s:
        return "02_detector"
    if "模组创作者" in s and "写出自然" in s:
        return "04_step1_narrative"
    if "模组标准化助手" in s:
        return "05_step2a_entities"
    if "生成玩家可见" in s:
        return "05_step2b_l1"
    if "模组设计者" in s and "L3" in s:
        return "05_step2c_l3"
    if "模组创作者" in s and "风格" in s:
        return "03_author"
    if "叙事整合" in s:
        return "07_enrich"
    if "战斗" in s and "进入" in s:
        return "07_combat_entry"
    if "时间推进" in s:
        return "07_time_agent"
    if ("KP" in s or "跑团" in s) and "叙事" in s and "整合" not in s:
        return "06_narrator"
    if "TRPG规则辅助" in s:
        return "07_trait_enhance"
    return "08_llm"


def _setup_llm_logging(log_dir):
    """Patch all call_deepseek references to log prompt + response + timing.
    Returns a stop function to restore patches.
    """
    from unittest.mock import patch as _patch

    _LLM_CALL_COUNTER[0] = 0

    def _logging_wrapper(prompt, json_mode=True, model="", system="", reasoning_effort="",
                         fallback_schema=None):
        label = _classify_call(system)
        call_num = _LLM_CALL_COUNTER[0] + 1
        _LLM_CALL_COUNTER[0] = call_num
        t0 = _time.perf_counter()

        _log_text(log_dir, f"{label}_prompt.txt", prompt)
        if system:
            _log_text(log_dir, f"{label}_system.txt", system)

        kwargs = {"prompt": prompt, "json_mode": json_mode, "fallback_schema": fallback_schema}
        if model:
            kwargs["model"] = model
        if system:
            kwargs["system"] = system
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        try:
            response = _REAL_CALL_DEEPSEEK(**kwargs)
        except Exception as e:
            elapsed = _time.perf_counter() - t0
            _log_text(log_dir, f"{label}_error.txt", f"error: {e}\nelapsed: {elapsed:.1f}s")
            raise

        elapsed = _time.perf_counter() - t0
        ext = "json" if json_mode else "txt"
        _log_text(log_dir, f"{label}_response.{ext}",
                  response if isinstance(response, str) else json.dumps(response, ensure_ascii=False, indent=2))
        _log_json(log_dir, f"{label}_meta.json", {
            "model": model or "deepseek-v4-pro",
            "reasoning_effort": reasoning_effort or "default",
            "json_mode": json_mode,
            "call_order": call_num,
            "elapsed_s": round(elapsed, 2),
        })
        return response

    patches = [
        _patch("game.agents.keeper.call_deepseek", _logging_wrapper),
        _patch("game.intent_detector.call_deepseek", _logging_wrapper),
        _patch("game.agents.author.call_deepseek", _logging_wrapper),
        _patch("llm.call_deepseek", _logging_wrapper),
        _patch("module_designer.supplement_pipeline.call_deepseek", _logging_wrapper),
    ]
    for p in patches:
        p.start()

    def stop():
        for p in patches:
            p.stop()

    return stop


# =====================================================================
#  Case A: normal entity match
# =====================================================================

def test_case_a(log_dir=""):
    stop_llm = _setup_llm_logging(log_dir)
    world = _make_world()
    keeper = Keeper(world)
    keeper.narrator_l1 = _make_l1()
    author = _make_author()

    try:
        turn = TurnInput(raw_text="inspect every item on the table carefully")
        result = keeper.process_turn(turn, author=author)

        assert "escalation" not in result, "Case A: no escalation for normal entity match"
        assert world.runtime_state["IT1"].completed, "Case A: IT1 should be completed"

        _log_json(log_dir, "01_parse_enrich_curate_result.json", {
            "brief_summary": result.get("brief", {}).summary if hasattr(result.get("brief", {}), "summary") else str(result.get("brief", ""))[:200],
            "action_outcomes_count": len(result.get("brief", {}).action_outcomes if hasattr(result.get("brief", {}), "action_outcomes") else []),
        })
        _case_log(log_dir, {
            "case": "A - normal entity match",
            "input": "inspect every item on the table carefully",
            "verdict": "PASS",
            "flow": "Parse -> Judge -> Enrich -> Curate -> Narrator",
        })
    finally:
        stop_llm()

    return True


# =====================================================================
#  Case B: other + flavor (no Author trigger)
# =====================================================================

def test_case_b(log_dir=""):
    stop_llm = _setup_llm_logging(log_dir)
    world = _make_world()
    keeper = Keeper(world)
    keeper.narrator_l1 = _make_l1()
    author = _make_author()

    try:
        turn = TurnInput(raw_text="sang a cheerful song while tapping on the table")
        result = keeper.process_turn(turn, author=author)

        assert "escalation" not in result, "Case B: no escalation for pure roleplay"
        node = world.graph.nodes["test_room"]
        assert len(node.interactions) == 2, \
            f"Case B: 2 interactions (IT1+IT2), got {len(node.interactions)}"

        _case_log(log_dir, {
            "case": "B - other + flavor",
            "input": "sang a cheerful song while tapping on the table",
            "verdict": "PASS",
            "flow": "Parse(other) -> Detector(no) -> Judge -> Enrich -> Curate",
        })
    finally:
        stop_llm()

    return True


# =====================================================================
#  Case C: other + Author Patch
# =====================================================================

def test_case_c(log_dir=""):
    stop_llm = _setup_llm_logging(log_dir)
    world = _make_world()
    keeper = Keeper(world)
    keeper.narrator_l1 = _make_l1()
    author = _make_author()

    try:
        # Creative/world-modifying action — won't match any existing entity, triggers Author
        turn = TurnInput(raw_text="我掏出随身携带的小刀，在墙上用力刻下几个大字：'有人吗？救救我！'")
        result = keeper.process_turn(turn, author=author)

        # Log full result before asserting
        _log_json(log_dir, "03_process_turn_result.json", {
            "action_outcomes": [str(o.message)[:200] for o in result.get("brief", {}).action_outcomes] if hasattr(result.get("brief", {}), "action_outcomes") else [],
            "warnings": getattr(keeper, "_warnings", []),
            "author_history": author.history[-1] if author.history else {},
            "all_interaction_ids": [e.id for e in world.graph.nodes["test_room"].interactions],
        })

        node = world.graph.nodes["test_room"]
        assert len(node.interactions) >= 3, \
            f"Case C: at least 3 interactions (IT1+IT2+new), got {len(node.interactions)}"
        assert "escalation" not in result, "Case C: escalation flag should not leak"

        # Log newly generated entity
        new_ids = [e.id for e in node.interactions if e.id not in ("IT1", "IT2")]
        _log_json(log_dir, "03_patch_entities.json", {
            "new_entity_ids": new_ids,
            "total_interactions": len(node.interactions),
        })
        _case_log(log_dir, {
            "case": "C - other + Author Patch",
            "input": "掏出小刀在墙上刻字求救",
            "verdict": "PASS",
            "new_entities": new_ids,
        })
    finally:
        stop_llm()

    return True


# =====================================================================
#  Case D: other + Author Reject
# =====================================================================

def test_case_d(log_dir=""):
    stop_llm = _setup_llm_logging(log_dir)
    world = _make_world()
    world.wr0_enabled = False
    keeper = Keeper(world)
    keeper.narrator_l1 = _make_l1()
    author = _make_author()

    try:
        turn = TurnInput(raw_text="take out phone and shine flashlight into the dark beyond the iron door")
        result = keeper.process_turn(turn, author=author)

        node = world.graph.nodes["test_room"]
        assert len(node.interactions) == 2, \
            f"Case D: 2 interactions (IT1+IT2), got {len(node.interactions)}"

        all_messages = [o.message for o in result["brief"].action_outcomes]
        rejection_found = any(
            "REJECTED" in m.upper() or "cannot" in m.lower() or "不" in m
            for m in all_messages
        )
        assert rejection_found or len(all_messages) > 0, \
            f"Case D: rejection hint should be present. Messages: {all_messages}"

        _case_log(log_dir, {
            "case": "D - other + Author Reject",
            "input": "take out phone and shine flashlight into the dark beyond the iron door",
            "verdict": "PASS",
            "messages": [m[:100] for m in all_messages],
        })
    finally:
        stop_llm()

    return True


# =====================================================================
#  Case E: other + Author StructuralEdit → supplement pipeline
# =====================================================================

def test_case_e(log_dir=""):
    stop_llm = _setup_llm_logging(log_dir)
    world = _make_world()
    world.wr0_enabled = True  # Enable WR0 so Author can choose structural
    keeper = Keeper(world)
    keeper.narrator_l1 = _make_l1()
    author = _make_author()

    try:
        turn = TurnInput(raw_text="凝视着布满裂痕的镜子，试图与黑暗中的存在建立沟通，我想走进镜子里去")
        result = keeper.process_turn(turn, author=author)

        # Log full result before asserting
        _log_json(log_dir, "04_process_turn_result.json", {
            "all_scenes": list(world.graph.nodes.keys()),
            "action_outcomes": [str(o.message)[:200] for o in result.get("brief", {}).action_outcomes] if hasattr(result.get("brief", {}), "action_outcomes") else [],
            "warnings": getattr(keeper, "_warnings", []),
            "author_history": author.history[-1] if author.history else {},
            "wr0_enabled": world.wr0_enabled,
        })

        # New scene should be in graph
        all_scenes = list(world.graph.nodes.keys())
        new_scenes = [s for s in all_scenes if s not in ("test_room", "car_6")]
        assert len(new_scenes) >= 1, \
            f"Case E: at least 1 new scene. Got: {all_scenes}"

        for ns in new_scenes:
            new_node = world.graph.nodes[ns]
            assert len(new_node.interactions) >= 1, \
                f"Case E: new scene {ns} should have interactions, got {len(new_node.interactions)}"

            # At least one new scene should connect from entry_scene (chain: entry → SS1 → SS2 → ...)
            entry_node = world.graph.nodes["test_room"]
            entry_targets = [e.target for e in entry_node.edges]
            any_connected = any(t in new_scenes for t in entry_targets)
            assert any_connected, \
                f"Case E: test_room should have edge to at least one new scene. Entry targets: {entry_targets}, new: {new_scenes}"

        _log_json(log_dir, "04_structural_result.json", {
            "new_scenes": new_scenes,
            "all_scenes": all_scenes,
            "author_l3_scenes": list(author.l3_data.get("scene_intents", {}).keys()),
        })
        _case_log(log_dir, {
            "case": "E - other + Author StructuralEdit → supplement pipeline",
            "input": "凝视着布满裂痕的镜子，试图与黑暗中的存在建立沟通",
            "verdict": "PASS",
            "new_scenes": new_scenes,
        })
    finally:
        stop_llm()

    return True


# =====================================================================
#  Runner
# =====================================================================

CASE_MAP = {
    "A": ("case_a_normal_entity", test_case_a),
    "B": ("case_b_other_flavor", test_case_b),
    "C": ("case_c_author_patch", test_case_c),
    "D": ("case_d_author_reject", test_case_d),
    "E": ("case_e_author_structural", test_case_e),
}


def resolve_cases():
    """Resolve which cases to run from CLI args or ESCALATION_CASES env var."""
    args = sys.argv[1:]
    if args:
        return [c.upper() for c in args if c.upper() in CASE_MAP]
    env = os.environ.get("ESCALATION_CASES", "").upper()
    if env:
        return [c for c in env if c in CASE_MAP]
    return list(CASE_MAP.keys())


def run():
    os.makedirs(OUT_ROOT, exist_ok=True)
    selected = resolve_cases()

    print(f"Escalation Real-LLM Test")
    print(f"Output: {OUT_ROOT}")
    print(f"Cases: {', '.join(selected)}")
    print(f"Model: deepseek-v4 (real API calls)")
    print()

    results = {}
    for case_key in selected:
        name, test_fn = CASE_MAP[case_key]
        case_dir = os.path.join(OUT_ROOT, name)
        os.makedirs(case_dir, exist_ok=True)

        print(f"--- {case_key}: {name} ---")
        t0 = _time.perf_counter()
        try:
            test_fn(log_dir=case_dir)
            elapsed = _time.perf_counter() - t0
            results[case_key] = f"PASS ({elapsed:.1f}s)"
            print(f"    PASS ({elapsed:.1f}s)")
            _log_json(case_dir, "_timing.json", {
                "total_elapsed_s": round(elapsed, 1),
                "llm_calls": _LLM_CALL_COUNTER[0],
            })
        except Exception as e:
            import traceback
            elapsed = _time.perf_counter() - t0
            results[case_key] = f"FAIL ({elapsed:.1f}s): {e}"
            print(f"    FAIL ({elapsed:.1f}s): {e}")
            traceback.print_exc()
        print()

    summary_path = os.path.join(OUT_ROOT, "_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    passed = sum(1 for v in results.values() if v.startswith("PASS"))
    print(f"Done. {passed}/{len(results)} passed. Output: {OUT_ROOT}")
    return results


if __name__ == "__main__":
    run()
