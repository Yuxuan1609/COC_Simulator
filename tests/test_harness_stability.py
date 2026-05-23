"""
Mini Stability Test Harness — 2 cases, 3 turns serial, real LLM calls.
Tests system stability: normal flow + mixed stress.
Uses Keeper.process_turn() via init_game() + run_turn().

Usage:
  python tests/test_harness_stability.py              # run both cases
  python tests/test_harness_stability.py --case A     # single case
"""
import sys, os, json
from datetime import datetime
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_ROOT = os.path.join(os.path.dirname(__file__), "..", "data", "debug", "test_stability", TIMESTAMP)

PROJECT_ROOT = os.path.dirname(__file__)
L2_PATH = os.path.join(PROJECT_ROOT, "..", "data", "modules", "常暗之厢", "l2_test.json")
L1_PATH = os.path.join(PROJECT_ROOT, "..", "data", "modules", "常暗之厢", "l1_test.json")
L3_PATH = os.path.join(PROJECT_ROOT, "..", "data", "modules", "常暗之厢", "l3_test.json")
CHAR_PATH = os.path.join(PROJECT_ROOT, "..", "investigator", "test_character.json")


# ═══════════════════════════════════════════════════════════════
#  Init
# ═══════════════════════════════════════════════════════════════

def _init_game():
    from game_loop import init_game
    from investigator import load_investigator

    game = init_game(
        l2_path=L2_PATH, l1_path=L1_PATH, l3_path=L3_PATH,
        start_node="测试房间",
    )
    world = game["keeper"].world
    if os.path.exists(CHAR_PATH):
        world.set_player(load_investigator(CHAR_PATH))
    else:
        from investigator import Investigator
        from investigator.rules import roll_stats, calc_derived, create_skill_list
        inv = Investigator(name="测试调查员", age=25, gender="男")
        inv.stats = roll_stats()
        inv.skills = create_skill_list()
        inv.derived = calc_derived(inv.stats, inv.age)
        world.set_player(inv)
    return game


# ═══════════════════════════════════════════════════════════════
#  LLM logging wrapper
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
#  LLM logging — agent-named files + full sub-agent coverage
# ═══════════════════════════════════════════════════════════════

def _identify_agent(prompt: str, kw: dict = None) -> str:
    """Return agent label from prompt fingerprint."""
    p = prompt or ""
    if "为玩家的输入匹配结构化的内容" in p:
        return "Keeper_Parse"
    if "请为以上已触发实体做叙事整合" in p:
        return "Keeper_Enrich"
    if "请以TRPG主持人身份生成沉浸式叙事" in p:
        return "Narrator"
    if "你是 TRPG 时间推进的判断者" in p:
        return "TimeAgent"
    if "请判断是否有敌人应进入战斗" in p:
        return "CombatEntry"
    if "判断以下玩家行为是纯角色扮演" in p:
        return "IntentDetector"
    if "玩家在面对敌人时试图避免战斗" in p or "你打算如何避免与" in p:
        return "Standoff"
    if "请判断背包中是否有物品与" in p:
        return "ConsumeFuzzy"
    if "你是TRPG模组写作者" in p and "description" in p:
        return "Author"
    if "请将以下游戏历史压缩为简洁摘要" in p or "压缩" in p:
        return "MemoryCompress"
    system = (kw or {}).get("system", "")
    if "你是一个TRPG游戏状态监控者" in system:
        return "IntentDetector"
    if "TRPG规则辅助裁判" in system:
        return "TraitEnhance"
    return "LLM_Unknown"


def _setup_llm_logging(case_dir, case_name):
    """Patch all LLM call sites to log prompts/responses per turn."""
    from unittest.mock import patch
    import llm as _llm
    _REAL_CALL = _llm.call_deepseek
    _REAL_TRAIT = _llm.evaluate_trait_enhancement
    _REAL_PENALTY = _llm.evaluate_failure_penalty

    call_counter = [0]
    log_dir = os.path.join(case_dir, "_llm_logs")
    os.makedirs(log_dir, exist_ok=True)

    def _logging_wrapper(prompt, json_mode=True, **kw):
        call_counter[0] += 1
        n = call_counter[0]
        agent = _identify_agent(prompt, kw)
        prefix = f"{n:03d}_{agent}"
        t0 = time.perf_counter()

        with open(os.path.join(log_dir, f"{prefix}_prompt.txt"), "w", encoding="utf-8") as f:
            f.write(prompt)
        system = kw.get("system", "")
        if system:
            with open(os.path.join(log_dir, f"{prefix}_system.txt"), "w", encoding="utf-8") as f:
                f.write(system)

        allowed = {"json_mode", "model", "system", "reasoning_effort",
                   "fallback_schema", "thinking", "temperature", "max_tokens"}
        filtered = {k: v for k, v in kw.items() if k in allowed}
        filtered["json_mode"] = json_mode
        response = _REAL_CALL(prompt, **filtered)
        elapsed = time.perf_counter() - t0

        ext = "json" if json_mode else "txt"
        content = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False, indent=2)
        with open(os.path.join(log_dir, f"{prefix}_response.{ext}"), "w", encoding="utf-8") as f:
            f.write(content)

        with open(os.path.join(log_dir, "_timing.txt"), "a", encoding="utf-8") as f:
            f.write(f"{prefix}: {elapsed:.1f}s\n")

        return response

    def _logged_trait_enhancement(**kw):
        call_counter[0] += 1
        n = call_counter[0]
        prefix = f"{n:03d}_TraitEnhance"
        with open(os.path.join(log_dir, f"{prefix}_input.json"), "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in kw.items() if k != "graded_tiers"}, f, ensure_ascii=False, indent=2)
        result = _REAL_TRAIT(**kw)
        with open(os.path.join(log_dir, f"{prefix}_response.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    def _logged_failure_penalty(**kw):
        call_counter[0] += 1
        n = call_counter[0]
        prefix = f"{n:03d}_FailurePenalty"
        with open(os.path.join(log_dir, f"{prefix}_input.json"), "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in kw.items() if k != "graded_on_failure"}, f, ensure_ascii=False, indent=2)
        result = _REAL_PENALTY(**kw)
        with open(os.path.join(log_dir, f"{prefix}_response.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return result

    patches = [
        patch("game.agents.keeper.call_deepseek", _logging_wrapper),
        patch("game.agents.narrator.call_deepseek", _logging_wrapper),
        patch("game.agents.time_agent.call_deepseek", _logging_wrapper),
        patch("game.intent_detector.call_deepseek", _logging_wrapper),
        patch("game.agents.author.call_deepseek", _logging_wrapper),
        patch("llm.call_deepseek", _logging_wrapper),
        patch("llm.evaluate_trait_enhancement", _logged_trait_enhancement),
        patch("llm.evaluate_failure_penalty", _logged_failure_penalty),
    ]
    for p in patches:
        p.start()

    def stop():
        for p in patches:
            p.stop()
    return stop


# ═══════════════════════════════════════════════════════════════
#  Case A: Normal Exploration (3 turns)
# ═══════════════════════════════════════════════════════════════

CASE_A = {
    "name": "A_normal_exploration",
    "turns": [
        ("环顾四周，仔细搜索这个房间",
         "search: 侦查检定, discover interactions and scene weapons"),
        ("仔细检查桌子上所有的物品",
         "IT1: 侦查检定 ##GRADED##, dependency for IT2"),
        ("拿起桌上的镜子仔细看看",
         "IT3: 无检定交互, 镜中异常描述"),
    ],
}


# ═══════════════════════════════════════════════════════════════
#  Case B: Mixed Stress (3 turns)
# ═══════════════════════════════════════════════════════════════

CASE_B = {
    "name": "B_mixed_stress",
    "turns": [
        ("用力敲击铁门，大声呼喊！",
         "IT5: spawn 深潜者+Clicker, combat entry detection triggers"),
        ("京山 人吉，这里发生了什么事？",
         "NPC dialogue: name-match routing, early return via talk_to"),
        ("检查房间角落的急救箱",
         "IT7: @item_gain + @consume_item, item lifecycle"),
    ],
}


# ═══════════════════════════════════════════════════════════════
#  Runner
# ═══════════════════════════════════════════════════════════════

def run_case(case, case_dir):
    """Run one case, return summary dict."""
    os.makedirs(case_dir, exist_ok=True)
    stop_logging = _setup_llm_logging(case_dir, case["name"])

    try:
        from game_loop import run_turn
        game = _init_game()
        world = game["keeper"].world
        print(f"  Player: {world.player.name}, SAN={world.player.derived.SAN}")
        print(f"  Location: {world.current_location}")

        results = []
        for turn_num, (user_input, description) in enumerate(case["turns"]):
            print(f"  Turn {turn_num + 1}: {description[:80]}")
            t0 = time.perf_counter()

            turn_result = run_turn(game, user_input)

            elapsed = time.perf_counter() - t0
            turn_data = {
                "turn": turn_num + 1,
                "input": user_input,
                "description": description,
                "elapsed": round(elapsed, 1),
            }
            if isinstance(turn_result, dict):
                brief = str(turn_result.get("brief", ""))
                turn_data.update({
                    "brief": brief[:300],
                    "has_ending": turn_result.get("ending") is not None,
                    "has_combat": turn_result.get("combat") is not None,
                    "has_standoff": turn_result.get("standoff_prompt") is not None,
                    "skill_results": turn_result.get("skill_results"),
                })
            results.append(turn_data)

            # Per-turn log
            turn_log = {
                "turn": turn_num + 1,
                "input": user_input,
                "brief": str(turn_result.get("brief", ""))[:500] if isinstance(turn_result, dict) else str(turn_result),
                "ending": str(turn_result.get("ending")) if isinstance(turn_result, dict) else None,
                "combat_outcome": turn_result.get("combat", {}).get("outcome") if isinstance(turn_result, dict) and turn_result.get("combat") else None,
            }
            with open(os.path.join(case_dir, f"turn_{turn_num + 1:02d}.json"), "w", encoding="utf-8") as f:
                json.dump(turn_log, f, ensure_ascii=False, indent=2)

            status = ""
            if turn_data.get("has_ending"):
                status += " ENDING"
            if turn_data.get("has_combat"):
                status += " COMBAT"
            if turn_data.get("has_standoff"):
                status += " STANDOFF"
            print(f"    => {elapsed:.1f}s{status}")

        summary = {
            "case": case["name"],
            "turns": len(case["turns"]),
            "location": world.current_location,
            "clock": world.clock.game_time,
            "memory_records": len(world.memory.raw_history),
            "enemies_active": len(world.enemies._instances) if world.enemies else 0,
            "results": results,
        }

    finally:
        stop_logging()

    return summary


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

def run_all(case_filter=None):
    os.makedirs(OUT_ROOT, exist_ok=True)

    cases = [
        (CASE_A, os.path.join(OUT_ROOT, "case_A")),
        (CASE_B, os.path.join(OUT_ROOT, "case_B")),
    ]

    if case_filter:
        cases = [(c, d) for c, d in cases if c["name"].startswith(case_filter)]

    print(f"Stability Test Harness — {len(cases)} case(s)")
    print(f"Output: {OUT_ROOT}")
    print()

    all_summaries = []
    for case, case_dir in cases:
        print(f"=== Case {case['name']} ({len(case['turns'])} turns) ===")
        t0 = time.perf_counter()
        summary = run_case(case, case_dir)
        elapsed = time.perf_counter() - t0
        summary["total_elapsed"] = round(elapsed, 1)
        all_summaries.append(summary)

        with open(os.path.join(case_dir, "_summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        print(f"  Total: {elapsed:.1f}s | Location: {summary['location']} | "
              f"Clock: {summary['clock']}m | Memory: {summary['memory_records']} records")
        print()

    # Master summary
    master = {
        "timestamp": TIMESTAMP,
        "cases": all_summaries,
    }
    with open(os.path.join(OUT_ROOT, "_master_summary.json"), "w", encoding="utf-8") as f:
        json.dump(master, f, ensure_ascii=False, indent=2)

    print(f"Done. Output at: {OUT_ROOT}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=str, default=None, help="Run single case (A/B)")
    args = parser.parse_args()
    run_all(case_filter=args.case)
