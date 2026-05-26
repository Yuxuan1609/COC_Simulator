"""
LLM-driven TRPG player for automated module testing.
Usage: python -m llm_player [--module NAME] [--turns N] [--profile PATH]
"""
from __future__ import annotations
import sys, os, json, time, argparse
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from llm import call_deepseek
from game_loop import init_game, run_turn, set_turn_logger
from game.turn_logger import TurnLogger
from investigator import load_investigator
from llm_player_prompts import (
    PLAYER_SYSTEM, PLAYER_USER_TEMPLATE,
    MEMORY_COMPRESS_SYSTEM, MEMORY_COMPRESS_TEMPLATE,
)


def load_profile(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_player_prompt(
    world, narrative_result: dict, short_history: list[str],
    long_memory: str, profile: dict,
) -> tuple[str, str]:
    snap = world.build_snapshot()
    p = snap.get("player", {})
    weapons = ", ".join(str(w) for w in p.get("weapons", [])) or "无"
    inv = p.get("inventory", "") or "无"
    loc = snap.get("location", "?")
    desc = snap.get("description", "")[:200]
    npcs = ", ".join(n["name"] for n in snap.get("npcs_in_scene", [])) or "无"

    strategy = ", ".join(profile.get("player_strategy", []))

    system = PLAYER_SYSTEM.format(player_strategy=strategy)
    user = PLAYER_USER_TEMPLATE.format(
        hp=p.get("hp", "?"), max_hp=p.get("max_hp", "?"),
        san=p.get("san", "?"), mp=p.get("mp", "?"),
        weapons=weapons, inventory=inv,
        location=loc, description=desc, npcs=npcs,
        brief=narrative_result.get("brief", ""),
        narrative=narrative_result.get("narrative", ""),
        short_history="\n".join(short_history[-5:]) or "（游戏开始）",
        long_memory=long_memory or "（无）",
    )
    return system, user


def compress_memory(short_history: list[str]) -> str:
    prompt = MEMORY_COMPRESS_TEMPLATE.format(
        short_history="\n".join(short_history),
    )
    try:
        result = call_deepseek(
            prompt, json_mode=False, system=MEMORY_COMPRESS_SYSTEM,
            model="deepseek-v4-flash", reasoning_effort="low",
        )
        return result.strip()
    except Exception:
        return "（记忆压缩失败）"


def run_llm_player(profile_path: str = "data/stress_profile.json", module_name: str = None,
                   max_turns: int = None, max_duration_s: int = None):
    profile = load_profile(profile_path)
    pc = profile["player_config"]
    if module_name is None:
        module_name = pc["module_name"]
    if max_turns is None:
        max_turns = pc["max_turns"]
    if max_duration_s is None:
        max_duration_s = pc["max_duration_s"]

    module_dir = PROJECT_ROOT / "data" / "modules" / module_name
    game = init_game(
        l2_path=str(module_dir / "l2_keeper.json"),
        l1_path=str(module_dir / "l1_player.json"),
        l3_path=str(module_dir / "l3_designer.json"),
        start_node="6号车厢",
    )

    # Monkey-patch combat → auto-win (combat tested separately)
    from game.combat import CombatSystem, CombatResult
    _orig_run_combat = CombatSystem.run_combat
    def _auto_win_combat(self, combat_init):
        return CombatResult(
            outcome="win",
            defeated_instance_ids=[e.instance_id for e in combat_init.enemies],
            player_hp=game["keeper"].world.player.derived.HP,
            player_san=game["keeper"].world.player.derived.SAN,
            rounds=1,
            narrative="（战斗已短路——压力测试模式自动胜利）",
        )
    CombatSystem.run_combat = _auto_win_combat

    ct = profile.get("combat_testing", {})
    if ct.get("mode") == "buff_investigator":
        char_path = PROJECT_ROOT / "data" / "investigator" / "combat_test_character.json"
        if char_path.exists():
            game["keeper"].world.set_player(load_investigator(str(char_path)))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = PROJECT_ROOT / "logs" / "llm_player" / ts
    log_dir.mkdir(parents=True, exist_ok=True)
    from llm import set_llm_log_dir
    from prompts import set_prompt_log_dir
    set_prompt_log_dir(str(log_dir))
    set_llm_log_dir(str(log_dir))
    turn_logger = TurnLogger(log_dir=str(log_dir / "turn_logs"))
    set_turn_logger(turn_logger)

    short_history: list[str] = []
    long_memory = ""
    compress_interval = pc["memory_compress_interval"]
    summary_log: list[dict] = []

    player_name = game["keeper"].world.player.name

    print(f"LLM Player — {module_name}")
    print(f"  Player: {player_name}, Model: {pc['model']}")
    print(f"  Strategy: {profile.get('player_strategy', [])}")
    print(f"  Max turns: {max_turns}, Max duration: {max_duration_s}s")
    print(f"  Log: {log_dir}")
    print()

    t0 = time.perf_counter()
    turn = 0
    last_narrative = {"brief": "", "narrative": ""}

    while turn < max_turns:
        elapsed = time.perf_counter() - t0
        if elapsed > max_duration_s:
            print(f"  Timeout at turn {turn}")
            break

        t_turn = time.perf_counter()
        try:
            system, user = build_player_prompt(
                game["keeper"].world, last_narrative,
                short_history, long_memory, profile,
            )
        except Exception as e:
            print(f"  [WARN] build_player_prompt failed: {e}")
            action = "环顾四周"
            reasoning = "prompt build error"
            system, user = "", ""

        try:
            response = call_deepseek(
                user, json_mode=True, system=system,
                model=pc["model"], reasoning_effort=pc["reasoning_effort"],
                fallback_schema={"action": "环顾四周", "reasoning": "fallback"},
                max_retries=3, timeout=60,
            )
            if isinstance(response, str):
                response = json.loads(response)
            action = response.get("action", "环顾四周")
            reasoning = response.get("reasoning", "")
        except Exception as e:
            print(f"  [WARN] LLM call failed: {e}")
            action = "环顾四周"
            reasoning = f"LLM error: {e}"

        try:
            result = run_turn(game, action)
        except Exception as e:
            print(f"  [WARN] run_turn failed: {e}")
            result = {"brief": str(e), "narrative": "", "skill_results": [],
                      "ending": None, "combat": None, "npc_events": []}

        dt = time.perf_counter() - t_turn

        brief = result.get("brief", "")
        narrative = result.get("narrative", "")
        skill_results = result.get("skill_results", [])
        ending = result.get("ending")
        combat = result.get("combat")
        npc_events = result.get("npc_events", [])

        short_history.append(
            f"T{turn+1}: {action} → {str(brief)[:80]}"
        )
        last_narrative = {"brief": brief, "narrative": narrative}

        summary_log.append({
            "turn": turn + 1, "input": action, "reasoning": reasoning,
            "brief": brief, "narrative": narrative,
            "skill_results": skill_results,
            "combat_outcome": combat["outcome"] if combat else None,
            "npc_events": npc_events,
            "ending": ending.get("name") if ending else None,
            "elapsed_s": round(dt, 1),
        })

        print(f"  T{turn+1:02d} [{dt:.1f}s]: {action[:50]}")
        if reasoning:
            print(f"    -> {reasoning[:60]}")

        if ending and ending.get("game_over"):
            print(f"  Game Over: {ending.get('name', '?')}")
            break

        if (turn + 1) % compress_interval == 0:
            long_memory = compress_memory(short_history)
            short_history = []

        turn += 1

    total_elapsed = time.perf_counter() - t0
    with open(log_dir / "_summary.json", "w", encoding="utf-8") as f:
        json.dump({
            "module": module_name, "player": player_name,
            "turns": len(summary_log), "total_elapsed_s": round(total_elapsed, 1),
            "game_over": summary_log[-1].get("ending") if summary_log else None,
            "profile": profile,
            "turns_detail": summary_log,
        }, f, ensure_ascii=False, indent=2)

    print(f"\nDone. {len(summary_log)} turns, {total_elapsed:.0f}s")
    print(f"Log: {log_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM-driven TRPG player")
    parser.add_argument("--module", type=str, default=None, help="Module name")
    parser.add_argument("--turns", type=int, default=None, help="Max turns")
    parser.add_argument("--profile", type=str, default="data/stress_profile.json")
    args = parser.parse_args()
    run_llm_player(
        profile_path=args.profile, module_name=args.module,
        max_turns=args.turns,
    )
