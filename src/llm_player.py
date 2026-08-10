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
from config_llm import LLM_FLASH_MODEL, RE_INTENT_DETECTOR
from game_loop import init_game, run_turn, setup_logging
from game.messages import PlayerTurnResult, TurnStatus
from game.turn_logger import TurnLogger
from investigator import load_investigator
from llm_player_prompts import (
    PLAYER_SYSTEM, PLAYER_USER_TEMPLATE,
    MEMORY_COMPRESS_SYSTEM, MEMORY_COMPRESS_TEMPLATE,
    TEST_MODE_STRESS, TEST_MODE_EXPLORATION, TEST_MODE_ROLEPLAY, TEST_MODE_GOAL,
)


def load_profile(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_player_prompt(
    world, narrative_result: dict, short_history: list[str],
    long_memory: str, profile: dict,
    player_snapshot=None,
) -> tuple[str, str]:
    from game_loop import format_turn_dynamic
    snap = world.build_snapshot()
    p = snap.get("player", {})
    weapons = ", ".join(str(w) for w in p.get("weapons", [])) or "无"
    inv = p.get("inventory", "") or "无"
    loc = snap.get("location", "?")
    desc = snap.get("description", "")[:200]
    npcs_raw = snap.get("npcs_in_scene", [])
    npcs = ", ".join(n["name"] for n in npcs_raw) or "无"
    npc_states = "、".join(
        f"{n['name']}({n.get('state','?')}{', 跟随中' if n.get('following') else ''})"
        for n in npcs_raw
    ) or "无"

    # Exits
    exits = snap.get("exits", [])
    exits_text = "、".join(f"{e['target']}({e['method']})" for e in exits) or "无已知出口"

    # Enemies
    enemies = snap.get("enemies_in_scene", [])
    enemy_text = "、".join(f"{e['enemy_ref']}×{e.get('quantity',1)}[{e.get('status','?')}]" for e in enemies) or "无"

    # Time
    t = snap.get("time", {})
    gt = int(t.get("game_time", 0)) if t else 0
    day = gt // 1440 if gt else 0
    hour_val = (gt % 1440) // 60 if gt else 0
    min_val = gt % 60
    if hour_val < 5: tod = "夜间"
    elif hour_val < 8: tod = "早晨"
    elif hour_val < 17: tod = "白天"
    elif hour_val < 20: tod = "黄昏"
    else: tod = "夜间"
    time_text = f"第{day}天 {tod} {int(hour_val):02d}:{int(min_val):02d}" if gt else "游戏开始"

    brief = narrative_result.get("brief", "")
    narrative = narrative_result.get("narrative", "")
    turn_output = format_turn_dynamic(player_snapshot, brief, narrative)

    test_mode = profile.get("test_mode", "exploration")
    strategy = ", ".join(profile.get("player_strategy", []))

    if test_mode == "stress":
        mode_section = TEST_MODE_STRESS.format(player_strategy=strategy)
    elif test_mode == "roleplay":
        mode_section = TEST_MODE_ROLEPLAY
    elif test_mode == "goal":
        mode_section = TEST_MODE_GOAL.format(goal=profile.get("goal", ""))
    else:
        mode_section = TEST_MODE_EXPLORATION

    system = PLAYER_SYSTEM.format(test_mode_section=mode_section)
    user = PLAYER_USER_TEMPLATE.format(
        hp=p.get("hp", "?"), max_hp=p.get("max_hp", "?"),
        san=p.get("san", "?"), mp=p.get("mp", "?"),
        weapons=weapons, inventory=inv,
        location=loc, description=desc, npcs=npcs, npc_states=npc_states,
        exits=exits_text, enemies=enemy_text, time=time_text,
        turn_output=turn_output,
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
            model=LLM_FLASH_MODEL, reasoning_effort="low",
        )
        return result.strip()
    except Exception:
        return "（记忆压缩失败）"


def _eval_success_checks(names: list[str], entries: list[dict]) -> bool:
    """按声明式谓词名评估是否全部满足（谓词注册表在 tests/e2e/scenario_predicates.py）。"""
    if not names:
        return False
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "scenario_predicates",
            PROJECT_ROOT / "tests" / "e2e" / "scenario_predicates.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        preds = mod.PREDICATES
    except Exception:
        return False
    if any(n not in preds for n in names):
        return False
    return all(preds[n](entries) for n in names)


_TIER_RANK = {"": 0, "fumble": 0, "failure": 0, "regular": 1, "hard": 2, "extreme": 3}


def _collect_mech_line(game, result, turn_no: int, action: str, dt: float,
                       prev_loc: str, prev_boss_active) -> str:
    """采集单回合机制事件，格式对齐 tests/e2e/scenarios/audit_guide.md 第三节。"""
    keeper = game["keeper"]
    world = keeper.world
    parts = [f'T{turn_no:02d} [{dt:.1f}s] in="{action[:30]}"']

    if result.status == TurnStatus.FROZEN:
        parts.append(f"frozen={str(result.narrative or '')[:40]}")
        return " | ".join(parts)

    outcomes = getattr(keeper, "_last_outcomes", []) or []
    intents = [getattr(o.intent, "action", "") for o in outcomes if getattr(o, "intent", None)]
    intent = next((i for i in intents if i and i != "other"), intents[0] if intents else "")
    if intent:
        parts.append(f"intent={intent}")

    ents, ats, spawns = [], [], []
    for o in outcomes:
        et = getattr(o, "entity_type", "")
        eid = getattr(o, "entity_id", "")
        for se in getattr(o, "side_effects", []) or []:
            if type(se).__name__ == "SpawnEnemy":
                spawns.append(f"{se.enemy_ref}×{se.quantity}")
        if not eid or eid in ("OTHER", "STANDOFF", "COMBAT", "COMBAT_RESULT", "WEAPON_OFFER"):
            continue
        if et == "auto_trigger":
            ats.append(eid)
        elif et in ("interaction", "event"):
            tier = getattr(o, "skill_tier", "") or ""
            enh = getattr(o, "enhancement", None)
            if isinstance(enh, dict):
                orig = enh.get("original_tier")
                if orig and orig != tier:
                    arrow = "↑" if _TIER_RANK.get(tier, 0) > _TIER_RANK.get(orig, 0) else "↓"
                    tier = f"{tier}(原{orig}{arrow})"
            ents.append(f"{eid}:{tier}" if tier else eid)
    if ents:
        parts.append("entities=" + ",".join(ents))
    if ats:
        parts.append("at=" + ",".join(ats))
    if spawns:
        parts.append("spawn=" + ",".join(spawns))

    loc = world.current_location
    if prev_loc and loc != prev_loc:
        parts.append(f"move={prev_loc}→{loc}")

    bosses = getattr(world, "bosses", None)
    active = bosses.active_boss_id if bosses else None
    if active and not prev_boss_active:
        parts.append(f"boss=engage({active})")

    if result.combat_init:
        names = ",".join(getattr(e, "enemy_ref", "?") for e in result.combat_init.enemies)
        parts.append(f"combat=start({names})")
    if result.combat:
        parts.append(f"combat=end({result.combat.get('outcome', '?')})")

    if result.pending_interaction:
        parts.append(f"pending={result.pending_interaction.kind}")

    npc_events = result.diagnostics.get("npc_events", []) if isinstance(result.diagnostics, dict) else []
    if npc_events:
        parts.append("npc=" + ",".join(str(e)[:20] for e in npc_events[:3]))

    if result.ending:
        parts.append(f"ending={result.ending.name}")

    return " | ".join(parts)


def run_llm_player(profile_path: str = "data/stress_profile.json", module_name: str = None,
                   max_turns: int = None, max_duration_s: int = None,
                   post_init_hook=None, log_dir: str = None, verbose: bool = False):
    profile = load_profile(profile_path)
    pc = profile["player_config"]
    if module_name is None:
        module_name = pc["module_name"]
    if max_turns is None:
        max_turns = pc["max_turns"]
    if max_duration_s is None:
        max_duration_s = pc["max_duration_s"]

    module_dir = PROJECT_ROOT / "data" / "modules" / module_name
    l2_name = "l2_keeper_test.json" if (module_dir / "l2_keeper_test.json").exists() else "l2_keeper.json"
    l1_name = "l1_player.json"
    l3_name = "l3_designer.json"
    with open(module_dir / l3_name, "r", encoding="utf-8") as f:
        start_node = json.load(f).get("start_scene", "6号车厢")
    game = init_game(
        l2_path=str(module_dir / l2_name),
        l1_path=str(module_dir / l1_name),
        l3_path=str(module_dir / l3_name),
        start_node=start_node,
    )

    # Ensure a player is always set (default investigator if none provided)
    if game["keeper"].world.player is None:
        from investigator import load_investigator, Investigator
        from investigator.rules import roll_stats, calc_derived, create_skill_list
        char_path = PROJECT_ROOT / "data" / "investigator" / "combat_test_character.json"
        if char_path.exists():
            game["keeper"].world.set_player(load_investigator(str(char_path)))
        else:
            inv = Investigator(name="测试调查员", age=25, gender="男")
            inv.stats = roll_stats()
            inv.skills = create_skill_list()
            inv.derived = calc_derived(inv.stats, inv.age)
            game["keeper"].world.set_player(inv)
    # 应用 AT_WORLD 延后的 item_gain
    for item_gain in game.get("pending_world_items", []):
        if hasattr(game["keeper"].world.player, 'item_manager'):
            game["keeper"].world.player.item_manager.add(item_gain.item_name, quantity=item_gain.quantity)

    # Combat is short-circuited in game_loop.run_turn() (auto-win, Pyrrhic victory narrative).
    # CombatSystem.run_combat() is only used in standalone smoke tests.

    # Buff investigator only in stress mode with combat testing enabled
    ct = profile.get("combat_testing", {})
    test_mode = profile.get("test_mode", "exploration")
    if test_mode == "stress" and ct.get("mode") == "buff_investigator":
        char_path = PROJECT_ROOT / "data" / "investigator" / "combat_test_character.json"
        if char_path.exists():
            game["keeper"].world.set_player(load_investigator(str(char_path)))

    # 场景 runner 的命令式播种入口（spawn 敌人 / 设置技能等模块数据表达不了的种子）
    if post_init_hook is not None:
        post_init_hook(game)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if log_dir is None:
        log_dir = str(PROJECT_ROOT / "logs" / "llm_player" / ts)
    import os as _os
    _os.makedirs(log_dir, exist_ok=True)
    from llm import set_llm_log_dir
    from prompts import set_prompt_log_dir
    set_prompt_log_dir(log_dir)
    set_llm_log_dir(log_dir)
    turn_logger = TurnLogger(log_dir=log_dir)
    from game_loop import set_turn_logger
    set_turn_logger(turn_logger)

    def _log_player_call(turn: int, system_prompt: str, user_prompt: str, response):
        """Write full player LLM interaction (system + user + response) to log."""
        import os as _os
        player_log_path = _os.path.join(log_dir, "player_llm.txt")
        resp_str = json.dumps(response, ensure_ascii=False, indent=2) if isinstance(response, dict) else str(response)
        with open(player_log_path, "a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"Turn {turn}\n")
            f.write(f"{'='*60}\n")
            f.write(f"--- System ---\n{system_prompt}\n\n")
            f.write(f"--- User ---\n{user_prompt}\n\n")
            f.write(f"--- Response ---\n{resp_str}\n\n")

    short_history: list[str] = []
    long_memory = ""
    compress_interval = pc["memory_compress_interval"]
    summary_log: list[dict] = []
    success_checks = list(profile.get("success_checks", []))
    goal_achieved = False
    player_model = pc.get("model") or LLM_FLASH_MODEL

    player_name = game["keeper"].world.player.name

    print(f"LLM Player — {module_name}")
    print(f"  Player: {player_name}, Model: {player_model}")
    print(f"  Strategy: {profile.get('player_strategy', [])}")
    print(f"  Max turns: {max_turns}, Max duration: {max_duration_s}s")
    print(f"  Log: {log_dir}")
    print()

    t0 = time.perf_counter()
    turn = 0
    prev_loc = game["keeper"].world.current_location
    prev_boss_active = None
    last_narrative = {"brief": "", "narrative": ""}
    last_snapshot = None

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
                player_snapshot=last_snapshot,
            )
        except Exception as e:
            print(f"  [WARN] build_player_prompt failed: {e}")
            action = "环顾四周"
            reasoning = "prompt build error"
            system, user = "", ""

        try:
            response = call_deepseek(
                user, json_mode=True, system=system,
                model=player_model, reasoning_effort=RE_INTENT_DETECTOR,
                fallback_schema={"action": "环顾四周", "reasoning": "fallback"},
                max_retries=3, timeout=300,
            )
            if isinstance(response, str):
                response = json.loads(response)
            action = response.get("action", "环顾四周")
            reasoning = response.get("reasoning", "")
            _log_player_call(turn + 1, system, user, json.dumps(response, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"  [WARN] LLM call failed: {e}")
            action = "环顾四周"
            reasoning = f"LLM error: {e}"

        try:
            result = run_turn(game, action)
        except Exception as e:
            print(f"  [WARN] run_turn failed: {e}")
            result = PlayerTurnResult(status=TurnStatus.COMPLETED, brief=str(e))

        dt = time.perf_counter() - t_turn

        mech_line = _collect_mech_line(game, result, turn + 1, action, dt,
                                       prev_loc, prev_boss_active)
        prev_loc = game["keeper"].world.current_location
        bosses = game["keeper"].world.bosses
        prev_boss_active = bosses.active_boss_id if bosses else None

        brief = result.brief
        narrative = result.narrative
        skill_results = result.skill_results
        ending = result.ending
        combat = result.combat
        npc_events = result.diagnostics.get("npc_events", [])

        short_history.append(
            f"T{turn+1}: {action} → {str(brief)[:80]}"
        )
        last_narrative = {"brief": brief, "narrative": narrative}
        last_snapshot = result.player_snapshot

        clock = game["keeper"].world.clock
        time_state = {
            "day": clock.day,
            "hour": clock.hour,
            "time_of_day": clock.time_of_day,
            "game_time_minutes": clock.game_time,
        }
        # 场景谓词所需的世界快照字段（供 success_checks / runner predicates 判定）
        world = game["keeper"].world
        try:
            p_snap = world.build_snapshot().get("player", {})
            weapons_now = [str(w) for w in p_snap.get("weapons", [])]
            hp_now = p_snap.get("hp")
            player_alive = (hp_now is None) or (int(hp_now) > 0)
        except Exception:
            weapons_now, player_alive = [], True
        summary_log.append({
            "turn": turn + 1, "input": action, "reasoning": reasoning,
            "brief": brief, "narrative": narrative,
            "skill_results": skill_results,
            "combat": combat,
            "npc_events": npc_events,
            "npcs_visible": result.diagnostics.get("npcs_visible", {"in_scene": [], "following": []}),
            "pending": result.pending_interaction.kind if result.pending_interaction else None,
            "location": world.current_location,
            "weapons": weapons_now,
            "player_alive": player_alive,
            "ending": ending.name if ending else None,
            "elapsed_s": round(dt, 1),
            "time_state": time_state,
            "time_agent": result.diagnostics.get("time_agent"),
            "mech": mech_line,
        })

        if verbose:
            print(f"  {mech_line}")
        else:
            print(f"  T{turn+1:02d} [{dt:.1f}s]: {action[:50]}")
            if reasoning:
                print(f"    -> {reasoning[:60]}")

        if ending and ending.game_over:
            print(f"  Game Over: {ending.name}")
            break

        # goal 模式：success_checks 全部满足则提前终止
        if success_checks and _eval_success_checks(success_checks, summary_log):
            goal_achieved = True
            print(f"  Goal achieved at turn {turn+1} ({success_checks})")
            break

        if (turn + 1) % compress_interval == 0:
            before_compress = list(short_history)
            long_memory = compress_memory(short_history)
            _log_player_call(turn + 1, MEMORY_COMPRESS_SYSTEM,
                           MEMORY_COMPRESS_TEMPLATE.format(short_history="\n".join(before_compress)),
                           long_memory)
            short_history = []

        turn += 1

    total_elapsed = time.perf_counter() - t0
    summary = {
        "module": module_name, "player": player_name,
        "turns": len(summary_log), "total_elapsed_s": round(total_elapsed, 1),
        "game_over": summary_log[-1].get("ending") if summary_log else None,
        "goal_achieved": goal_achieved,
        "profile": profile,
        "turns_detail": summary_log,
    }
    with open(os.path.join(log_dir, "_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\nDone. {len(summary_log)} turns, {total_elapsed:.0f}s")
    print(f"Log: {log_dir}")

    return {"log_dir": log_dir, "summary": summary, "goal_achieved": goal_achieved}


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
