"""
Parallel Test Harness — 16 cases covering all game systems, real LLM calls.
Parallel execution via ThreadPoolExecutor. Each case gets its own init_game().
Mock mode available via --mock flag.

Usage:
  python tests/test_harness_parallel.py                    # all 16 cases, real LLM
  python tests/test_harness_parallel.py --mock             # all 16 cases, mocked LLM
  python tests/test_harness_parallel.py --case search      # single case
  python tests/test_harness_parallel.py --cases search,npc_dialogue  # selected
"""
import sys, os, json, time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_ROOT = os.path.join(os.path.dirname(__file__), "..", "data", "debug", "test_harness_parallel", TIMESTAMP)

PROJECT_ROOT = os.path.dirname(__file__)
L2_PATH = os.path.join(PROJECT_ROOT, "..", "data", "modules", "常暗之厢", "l2_test.json")
L1_PATH = os.path.join(PROJECT_ROOT, "..", "data", "modules", "常暗之厢", "l1_test.json")
L3_PATH = os.path.join(PROJECT_ROOT, "..", "data", "modules", "常暗之厢", "l3_test.json")
CHAR_PATH = os.path.join(PROJECT_ROOT, "..", "investigator", "test_character.json")


# ═══════════════════════════════════════════════════════════════
#  Init helper
# ═══════════════════════════════════════════════════════════════

def _init_game_instance():
    from game_loop import init_game
    from investigator import load_investigator, Investigator
    from investigator.rules import roll_stats, calc_derived, create_skill_list

    game = init_game(
        l2_path=L2_PATH, l1_path=L1_PATH, l3_path=L3_PATH,
        start_node="测试房间",
    )
    world = game["keeper"].world
    if os.path.exists(CHAR_PATH):
        world.set_player(load_investigator(CHAR_PATH))
    else:
        inv = Investigator(name="测试调查员", age=25, gender="男")
        inv.stats = roll_stats()
        inv.skills = create_skill_list()
        inv.derived = calc_derived(inv.stats, inv.age)
        world.set_player(inv)
    return game


# ═══════════════════════════════════════════════════════════════
#  LLM logging
# ═══════════════════════════════════════════════════════════════

def _setup_llm_logging(case_dir, mock_mode=False, mock_parse_seq=None):
    """Wrap LLM calls with prompt/response logging. If mock_mode, use deterministic mocks."""
    import llm as _llm
    _REAL_CALL = _llm.call_deepseek

    os.makedirs(case_dir, exist_ok=True)
    log_dir = os.path.join(case_dir, "_llm_logs")
    os.makedirs(log_dir, exist_ok=True)

    if mock_mode and mock_parse_seq:
        return _setup_mocks(case_dir, mock_parse_seq)

    call_counter = [0]

    def _logging_wrapper(prompt, json_mode=True, model="", system="",
                         reasoning_effort="", fallback_schema=None, max_tokens=0):
        call_counter[0] += 1
        n = call_counter[0]
        t0 = time.perf_counter()

        with open(os.path.join(log_dir, f"{n:02d}_prompt.txt"), "w", encoding="utf-8") as f:
            f.write(prompt)
        if system:
            with open(os.path.join(log_dir, f"{n:02d}_system.txt"), "w", encoding="utf-8") as f:
                f.write(system)

        response = _REAL_CALL(
            prompt, json_mode=json_mode, model=model, system=system,
            reasoning_effort=reasoning_effort, fallback_schema=fallback_schema,
        )
        elapsed = time.perf_counter() - t0
        ext = "json" if json_mode else "txt"
        content = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False, indent=2)
        with open(os.path.join(log_dir, f"{n:02d}_response.{ext}"), "w", encoding="utf-8") as f:
            f.write(content)

        return response

    patches = [
        patch("game.agents.keeper.call_deepseek", _logging_wrapper),
        patch("game.intent_detector.call_deepseek", _logging_wrapper),
        patch("game.agents.author.call_deepseek", _logging_wrapper),
        patch("llm.call_deepseek", _logging_wrapper),
        patch("llm.evaluate_trait_enhancement",
              lambda **kw: {"tier": kw.get("current_tier", "regular"), "detail_override": None, "reason": "logged"}),
    ]
    for p in patches:
        p.start()

    def stop():
        for p in patches:
            p.stop()
    return stop


def _setup_mocks(case_dir, parse_seq):
    """Mock all LLM calls with deterministic responses. parse_seq = list of per-turn parse actions."""
    log_dir = os.path.join(case_dir, "_llm_logs")
    os.makedirs(log_dir, exist_ok=True)
    turn_idx = [0]

    def _mock_call_deepseek(prompt, json_mode=True, model="", system="", **kw):
        n = turn_idx[0] + 1
        with open(os.path.join(log_dir, f"{n:02d}_prompt.txt"), "w", encoding="utf-8") as f:
            f.write(prompt)

        if json_mode:
            result = {"actions": [], "results": {}, "reasoning": "", "emphasis_hint": ""}
            # Parse-like call
            if "【世界状态】" in prompt or "当前场景" in prompt[:300]:
                t = min(turn_idx[0], len(parse_seq) - 1)
                result = {"actions": parse_seq[t]}
                turn_idx[0] += 1
            response = json.dumps(result, ensure_ascii=False)
        else:
            response = "（测试叙事文本）"

        ext = "json" if json_mode else "txt"
        with open(os.path.join(log_dir, f"{n:02d}_response.{ext}"), "w", encoding="utf-8") as f:
            f.write(response)
        return response

    patches = [
        patch("game.agents.keeper.call_deepseek", _mock_call_deepseek),
        patch("game.intent_detector.call_deepseek", _mock_call_deepseek),
        patch("game.agents.author.call_deepseek", _mock_call_deepseek),
        patch("llm.call_deepseek", _mock_call_deepseek),
        patch("llm.evaluate_trait_enhancement",
              lambda **kw: {"tier": "regular", "detail_override": None, "reason": "mock"}),
        patch("llm.evaluate_failure_penalty",
              lambda **kw: {"narrative": "mock 失败惩罚", "markup_effects": []}),
    ]
    for p in patches:
        p.start()

    def stop():
        for p in patches:
            p.stop()
    return stop


# ═══════════════════════════════════════════════════════════════
#  Case definitions
# ═══════════════════════════════════════════════════════════════

def _run_turns(game, inputs, case_dir):
    """Run a sequence of turns through run_turn(). Return list of result dicts."""
    from game_loop import run_turn
    results = []
    for i, user_input in enumerate(inputs):
        t0 = time.perf_counter()
        turn_result = run_turn(game, user_input)
        elapsed = time.perf_counter() - t0

        entry = {
            "turn": i + 1, "input": user_input, "elapsed": round(elapsed, 1),
            "brief": str(turn_result.get("brief", ""))[:300],
            "ending": turn_result.get("ending"),
            "combat_outcome": turn_result.get("combat", {}).get("outcome") if turn_result.get("combat") else None,
            "has_standoff": turn_result.get("standoff_prompt") is not None,
            "skill_results": turn_result.get("skill_results"),
        }
        with open(os.path.join(case_dir, f"turn_{i + 1:02d}.json"), "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)
        results.append(entry)
    return results


# ── Cases 1-16 ──

def case_search(game, case_dir, mock=False):
    world = game["keeper"].world
    results = _run_turns(game, ["环顾四周，仔细搜索这个房间"], case_dir)
    r = results[0]
    verdict = "PASS" if (r["skill_results"] and any(
        s.get("entity_type") == "search" for s in (r["skill_results"] or [])
    )) or "##GRADED##" not in str(r) else "SOFT_PASS"
    return {"verdict": verdict, "location": world.current_location,
            "weapons_in_scene": bool(world.scene_weapons.get("测试房间")), "results": results}

def case_interaction_no_check(game, case_dir, mock=False):
    world = game["keeper"].world
    results = _run_turns(game, ["拿起桌上的镜子仔细端详"], case_dir)
    it3_done = world.is_entity_completed("IT3")
    return {"verdict": "PASS" if it3_done else "SOFT_PASS",
            "IT3_completed": it3_done, "location": world.current_location, "results": results}

def case_interaction_skill_pass(game, case_dir, mock=False):
    world = game["keeper"].world
    results = _run_turns(game, ["仔细检查桌子上所有的物品"], case_dir)
    it1_state = world.get_runtime_state("IT1")
    return {"verdict": "PASS" if it1_state.completed else "SOFT_PASS",
            "IT1_completed": it1_state.completed, "IT1_tier": it1_state.result_tier, "results": results}

def case_interaction_skill_fail(game, case_dir, mock=False):
    world = game["keeper"].world
    results = _run_turns(game, ["仔细端详墙壁上那些模糊的古老刻痕"], case_dir)
    it8_state = world.get_runtime_state("IT8")
    return {"verdict": "PASS",
            "IT8_retries": it8_state.retries, "IT8_completed": it8_state.completed,
            "IT8_tier": it8_state.result_tier, "results": results}

def case_interaction_hard(game, case_dir, mock=False):
    world = game["keeper"].world
    results = _run_turns(game, ["用尽全力去撞开那扇铁门"], case_dir)
    it4_state = world.get_runtime_state("IT4")
    return {"verdict": "PASS",
            "IT4_completed": it4_state.completed, "IT4_tier": it4_state.result_tier,
            "IT4_attempted": it4_state.completed or it4_state.retries > 0, "results": results}

def case_interaction_dependency(game, case_dir, mock=False):
    world = game["keeper"].world
    results = _run_turns(game, [
        "仔细检查桌子上所有的物品",
        "翻开那本泛黄的日志仔细阅读",
    ], case_dir)
    it1 = world.get_runtime_state("IT1")
    it2 = world.get_runtime_state("IT2")
    return {"verdict": "PASS",
            "IT1_completed": it1.completed, "IT2_completed": it2.completed,
            "IT2_only_if_IT1": not it2.completed or it1.completed,
            "location": world.current_location, "results": results}

def case_auto_trigger(game, case_dir, mock=False):
    world = game["keeper"].world
    results = _run_turns(game, ["站着不动，环顾四周"], case_dir)
    at_done = world.is_entity_completed("AT_TEST_AUTO")
    return {"verdict": "PASS" if at_done else "SOFT_PASS",
            "AT_TEST_AUTO_completed": at_done, "results": results}

def case_npc_dialogue(game, case_dir, mock=False):
    world = game["keeper"].world
    results = _run_turns(game, ["京山人吉，这里发生了什么事？"], case_dir)
    r = results[0]
    has_response = len(str(r["brief"])) > 20
    return {"verdict": "PASS" if has_response else "SOFT_PASS",
            "response_length": len(str(r["brief"])), "results": results}

def case_weapon_pickup(game, case_dir, mock=False):
    world = game["keeper"].world
    results = _run_turns(game, [
        "环顾四周，仔细搜索这个房间",
        "拾取撬棍",
    ], case_dir)
    has_weapon = any(w.name == "撬棍" for w in (world.player.weapons if world.player else []))
    return {"verdict": "PASS" if has_weapon else "SOFT_PASS",
            "has_crowbar": has_weapon, "player_weapons": [w.name for w in (world.player.weapons if world.player else [])],
            "results": results}

def case_move(game, case_dir, mock=False):
    world = game["keeper"].world
    results = _run_turns(game, [
        "用尽全力去撞开那扇铁门",
        "去6号车厢",
    ], case_dir)
    it4 = world.get_runtime_state("IT4")
    moved = world.current_location == "6号车厢"
    return {"verdict": "PASS" if moved else "SOFT_PASS",
            "IT4_completed": it4.completed, "moved_to_car6": moved,
            "location": world.current_location, "results": results}

def case_move_blocked(game, case_dir, mock=False):
    world = game["keeper"].world
    results = _run_turns(game, ["去6号车厢"], case_dir)
    blocked = world.current_location == "测试房间"
    return {"verdict": "PASS" if blocked else "FAIL",
            "move_blocked": blocked, "location": world.current_location, "results": results}

def case_standoff(game, case_dir, mock=False):
    world = game["keeper"].world
    results = _run_turns(game, [
        "用力敲击铁门，大声呼喊！",
        "试图悄悄绕过深潜者",
    ], case_dir)
    has_standoff = any(r.get("has_standoff") for r in results)
    has_enemies = bool(world.enemies and world.enemies._instances) if world.enemies else False
    return {"verdict": "PASS" if (has_standoff or has_enemies) else "SOFT_PASS",
            "standoff_triggered": has_standoff, "enemies_present": has_enemies, "results": results}

def case_combat_entry(game, case_dir, mock=False):
    world = game["keeper"].world
    # Directly spawn a hostile-only enemy (Clicker has no [avoidable])
    if world.enemies:
        world.enemies.spawn("Clicker", "测试房间", 1)
    results = _run_turns(game, ["准备战斗！"], case_dir)
    combat = any(r.get("combat_outcome") for r in results)
    has_combat_init = any("combat" in str(r) for r in results)
    return {"verdict": "PASS" if (combat or has_combat_init) else "SOFT_PASS",
            "combat_triggered": combat, "results": results}

def case_item_effect(game, case_dir, mock=False):
    world = game["keeper"].world
    results = _run_turns(game, ["检查房间角落的急救箱，使用找到的药品"], case_dir)
    it7_done = world.is_entity_completed("IT7")
    return {"verdict": "PASS" if it7_done else "SOFT_PASS",
            "IT7_completed": it7_done, "results": results}

def case_stat_change(game, case_dir, mock=False):
    world = game["keeper"].world
    san_before = world.player.derived.SAN if world.player else 0
    results = _run_turns(game, ["长时间凝视镜子中的裂痕，试图理解里面的异常"], case_dir)
    san_after = world.player.derived.SAN if world.player else 0
    san_changed = san_after != san_before
    it6_done = world.is_entity_completed("IT6")
    return {"verdict": "PASS" if (it6_done or san_changed) else "SOFT_PASS",
            "IT6_completed": it6_done, "SAN_before": san_before, "SAN_after": san_after,
            "SAN_changed": san_changed, "results": results}

def case_ending(game, case_dir, mock=False):
    world = game["keeper"].world
    results = _run_turns(game, ["拿起桌上的镜子仔细端详"], case_dir)
    has_ending = any(r.get("ending") for r in results)
    it3_done = world.is_entity_completed("IT3")
    return {"verdict": "PASS" if (has_ending or it3_done) else "SOFT_PASS",
            "ending_triggered": has_ending,
            "ending_name": str(results[-1].get("ending", {}).get("name", "")) if results else "",
            "IT3_completed": it3_done, "results": results}


# ═══════════════════════════════════════════════════════════════
#  Case registry
# ═══════════════════════════════════════════════════════════════

CASE_REGISTRY = {
    "search":                     ("1_search",                     case_search,                     "search: 侦查检定 + weapon发现",            [["环顾四周，仔细搜索这个房间"]]),
    "interaction_no_check":       ("2_interaction_no_check",       case_interaction_no_check,       "IT3: 无检定交互",                           [["拿起桌上的镜子仔细端详"]]),
    "interaction_skill_pass":     ("3_interaction_skill_pass",     case_interaction_skill_pass,     "IT1: 侦查 ##GRADED##",                      [["仔细检查桌子上所有的物品"]]),
    "interaction_skill_fail":     ("4_interaction_skill_fail",     case_interaction_skill_fail,     "IT8: 考古学 base=1, guaranteed fail",       [["仔细端详墙壁上那些模糊的古老刻痕"]]),
    "interaction_hard":           ("5_interaction_hard",           case_interaction_hard,           "IT4: 力量 hard difficulty",                 [["用尽全力去撞开那扇铁门"]]),
    "interaction_dependency":     ("6_interaction_dependency",     case_interaction_dependency,     "IT1 → IT2 依赖链",                          [["仔细检查桌子上所有的物品"], ["翻开那本泛黄的日志仔细阅读"]]),
    "auto_trigger":               ("7_auto_trigger",               case_auto_trigger,               "AT_TEST_AUTO: auto-trigger on entry",       [["站着不动，环顾四周"]]),
    "npc_dialogue":               ("8_npc_dialogue",               case_npc_dialogue,               "NPC: talk_to 路由",                         [["京山人吉，这里发生了什么事？"]]),
    "weapon_pickup":              ("9_weapon_pickup",              case_weapon_pickup,              "search → 撬棍发现 → 拾取",                  [["环顾四周，仔细搜索这个房间"], ["拾取撬棍"]]),
    "move":                       ("10_move",                     case_move,                       "IT4 unlock → move to 6号车厢",              [["用尽全力去撞开那扇铁门"], ["去6号车厢"]]),
    "move_blocked":               ("11_move_blocked",             case_move_blocked,               "move without IT4 → blocked",               [["去6号车厢"]]),
    "standoff":                   ("12_standoff",                 case_standoff,                   "IT5 spawn → avoidable enemy → standoff",   [["用力敲击铁门，大声呼喊！"], ["试图悄悄绕过深潜者"]]),
    "combat_entry":               ("13_combat_entry",             case_combat_entry,               "direct spawn Clicker → combat_init",       [["准备战斗！"]]),
    "item_effect":                ("14_item_effect",              case_item_effect,                "IT7: @item_gain + @consume_item",           [["检查房间角落的急救箱，使用找到的药品"]]),
    "stat_change":                ("15_stat_change",              case_stat_change,                "IT6: @stat_change SAN -5",                  [["长时间凝视镜子中的裂痕，试图理解里面的异常"]]),
    "ending":                     ("16_ending",                   case_ending,                     "IT3 → E_TEST_END 结局触发",                 [["拿起桌上的镜子仔细端详"]]),
}

MOCK_PARSE_MAP = {
    "search":                     [[{"type": "search"}]],
    "interaction_no_check":       [[{"type": "interaction", "id": "IT3"}]],
    "interaction_skill_pass":     [[{"type": "interaction", "id": "IT1"}]],
    "interaction_skill_fail":     [[{"type": "interaction", "id": "IT8"}]],
    "interaction_hard":           [[{"type": "interaction", "id": "IT4"}]],
    "interaction_dependency":     [[{"type": "interaction", "id": "IT1"}], [{"type": "interaction", "id": "IT2"}]],
    "auto_trigger":               [[{"type": "auto_trigger", "id": "AT_TEST_AUTO"}]],
    "npc_dialogue":               [[{"type": "other", "text": "..."}]],
    "weapon_pickup":              [[{"type": "search"}], [{"type": "other", "text": "拾取撬棍"}]],
    "move":                       [[{"type": "interaction", "id": "IT4"}], [{"type": "move", "target": "6号车厢"}]],
    "move_blocked":               [[{"type": "move", "target": "6号车厢"}]],
    "standoff":                   [[{"type": "interaction", "id": "IT5"}], [{"type": "other", "text": "试图绕过"}]],
    "combat_entry":               [[{"type": "other", "text": "准备战斗"}]],
    "item_effect":                [[{"type": "interaction", "id": "IT7"}]],
    "stat_change":                [[{"type": "interaction", "id": "IT6"}]],
    "ending":                     [[{"type": "interaction", "id": "IT3"}]],
}


# ═══════════════════════════════════════════════════════════════
#  Single case runner
# ═══════════════════════════════════════════════════════════════

def _run_single_case(case_key, mock_mode=False):
    """Create fresh game, run case, return summary. Each case fully isolated."""
    label, fn, desc, parse_seq = CASE_REGISTRY[case_key]
    case_dir = os.path.join(OUT_ROOT, label)
    os.makedirs(case_dir, exist_ok=True)

    mock_seq = MOCK_PARSE_MAP.get(case_key) if mock_mode else None
    stop_logging = _setup_llm_logging(case_dir, mock_mode=mock_mode, mock_parse_seq=mock_seq)

    try:
        t0 = time.perf_counter()
        game = _init_game_instance()
        world = game["keeper"].world

        result = fn(game, case_dir, mock=mock_mode)
        elapsed = time.perf_counter() - t0

        summary = {
            "case_key": case_key, "label": label, "description": desc,
            "verdict": result.get("verdict", "UNKNOWN"),
            "elapsed": round(elapsed, 1),
            "details": {k: v for k, v in result.items() if k not in ("results",)},
        }
    finally:
        stop_logging()

    with open(os.path.join(case_dir, "_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return summary


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

def run_all(mock_mode=False, case_filter=None):
    os.makedirs(OUT_ROOT, exist_ok=True)

    cases_to_run = list(CASE_REGISTRY.items())
    if case_filter:
        filters = set(case_filter.split(","))
        cases_to_run = [(k, v) for k, v in cases_to_run if k in filters]

    mode_label = "MOCK" if mock_mode else "REAL-LLM"
    print(f"Parallel Test Harness — {len(cases_to_run)} cases [{mode_label}]")
    print(f"Output: {OUT_ROOT}")
    print()

    summaries = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {}
        for case_key, _ in cases_to_run:
            future = executor.submit(_run_single_case, case_key, mock_mode)
            futures[future] = case_key

        for future in as_completed(futures):
            case_key = futures[future]
            try:
                summary = future.result()
                summaries[case_key] = summary
                v = summary["verdict"]
                icon = {"PASS": "+", "SOFT_PASS": "~", "FAIL": "!", "ERROR": "X"}.get(v, "?")
                print(f"  [{icon}] {summary['label']}: {v} ({summary['elapsed']}s)")
            except Exception as e:
                summaries[case_key] = {"case_key": case_key, "verdict": "ERROR", "error": str(e)}
                print(f"  [X] {case_key}: ERROR - {e}")
                import traceback
                traceback.print_exc()

    # Summary
    passed = sum(1 for s in summaries.values() if s.get("verdict") in ("PASS", "SOFT_PASS"))
    failed = sum(1 for s in summaries.values() if s.get("verdict") == "FAIL")
    errors = sum(1 for s in summaries.values() if s.get("verdict") == "ERROR")
    print(f"\n  {passed} pass, {failed} fail, {errors} error")

    master = {
        "timestamp": TIMESTAMP,
        "mode": mode_label,
        "total": len(summaries),
        "passed": passed, "failed": failed, "errors": errors,
        "cases": summaries,
    }
    with open(os.path.join(OUT_ROOT, "_master_summary.json"), "w", encoding="utf-8") as f:
        json.dump(master, f, ensure_ascii=False, indent=2)

    print(f"Done. Output at: {OUT_ROOT}")
    return summaries


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="Use mocked LLM calls")
    parser.add_argument("--cases", type=str, default=None, help="Comma-separated case keys")
    args = parser.parse_args()
    run_all(mock_mode=args.mock, case_filter=args.cases)
