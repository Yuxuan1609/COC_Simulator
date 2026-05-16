"""
Game Loop Test Harness — 15 个玩家输入场景测试。
运行完整 parse → judge → enrich → narrate 流程，所有中间结果写入日志。
"""
import sys, os, json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from game_loop import init_game
from prompts import set_prompt_log_file
from llm import set_llm_log_file, call_deepseek


# ═══════════════════════════════════════════════════════════════
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_ROOT = os.path.join(os.path.dirname(__file__), "..", "data", "debug", "test_harness", TIMESTAMP)


# ═══════════════════════════════════════════════════════════════
#  Setup
# ═══════════════════════════════════════════════════════════════

def setup():
    os.makedirs(OUT_ROOT, exist_ok=True)

    prompt_log = os.path.join(OUT_ROOT, "_prompt_log.txt")
    set_prompt_log_file(prompt_log)
    set_llm_log_file(prompt_log)

    game = init_game(
        l2_path=os.path.join(os.path.dirname(__file__), "..", "data", "modules", "常暗之厢", "l2_keeper.json"),
        l1_path=os.path.join(os.path.dirname(__file__), "..", "data", "modules", "常暗之厢", "l1_player.json"),
        l3_path=os.path.join(os.path.dirname(__file__), "..", "data", "modules", "常暗之厢", "l3_designer.json"),
        escalation_config_path=os.path.join(os.path.dirname(__file__), "..", "data", "modules", "常暗之厢", "escalation_config.json"),
        start_node="6号车厢",
    )

    keeper = game["keeper"]
    world = keeper.world

    char_path = os.path.join(os.path.dirname(__file__), "..", "investigator", "test_character.json")
    if os.path.exists(char_path):
        from investigator import load_investigator
        world.set_player(load_investigator(char_path))
    else:
        from investigator import Investigator
        from investigator.rules import roll_stats, calc_derived, create_skill_list
        inv = Investigator(name="测试调查员", age=25, gender="男")
        inv.stats = roll_stats()
        inv.skills = create_skill_list()
        inv.derived = calc_derived(inv.stats, inv.age)
        world.set_player(inv)

    init_log = os.path.join(OUT_ROOT, "_game_init.log")
    with open(init_log, "w", encoding="utf-8") as f:
        f.write(f"Timestamp: {TIMESTAMP}\n")
        f.write(f"Scenes: {len(world.graph.nodes)}\n")
        f.write(f"Events: {len(world.graph.events)}\n")
        f.write(f"Start node: {world.current_location}\n")
        f.write(f"Player: {world.player.name if world.player else 'None'}\n")
        for name, node in world.graph.nodes.items():
            f.write(f"  Scene: {name} — {len(node.interactions)} interactions, "
                    f"{len(node.auto_triggers)} auto_triggers, "
                    f"{len(node.edges)} exits\n")

    return game


# ═══════════════════════════════════════════════════════════════
#  Turn runner with full logging
# ═══════════════════════════════════════════════════════════════

def run_turn_with_log(game, user_input: str, case_dir: str, turn_num: int) -> dict:
    """Run one turn, capturing all intermediates to case_dir/turn_NN/."""
    turn_dir = os.path.join(case_dir, f"turn_{turn_num:02d}")
    os.makedirs(turn_dir, exist_ok=True)

    keeper = game["keeper"]
    narrator = game["narrator"]
    world = keeper.world

    from prompts import (
        build_keeper_parse_prompt, build_keeper_enrich_prompt,
        build_narrator_prompt, parse_narrative_output,
    )
    from game.messages import ActionIntent, ActionOutcome
    from game.judge import Judge
    from game.curator import Curator
    from scenario_core import parse_markup_all, apply_side_effects as apply_se

    raw = user_input

    # ── Step 1: Parse ──
    parse_prompt = build_keeper_parse_prompt(world, raw)
    parse_response = call_deepseek(parse_prompt, json_mode=True, model="deepseek-v4-flash")
    parse_data = json.loads(parse_response) if isinstance(parse_response, str) else parse_response
    actions = parse_data.get("actions", [])
    if not actions:
        actions = [{"action": "other"}]

    with open(os.path.join(turn_dir, "01_parse_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(parse_prompt)
    with open(os.path.join(turn_dir, "01_parse_response.json"), "w", encoding="utf-8") as f:
        json.dump(parse_data, f, ensure_ascii=False, indent=2)

    parsed = [
        ActionIntent(
            action=a.get("action", "other"),
            target=a.get("target", ""),
            skill_checks=a.get("skill_checks", []),
            reasoning=a.get("reasoning", ""),
            condition=a.get("condition", ""),
        )
        for a in actions
    ]

    # ── Step 2: Judge ──
    judge = Judge(world)
    at_results = judge.check_auto_triggers()
    action_outcomes = []
    for intent in parsed:
        if intent.action == "interact":
            outcome = judge.execute_interaction(intent)
            apply_se(world, outcome.side_effects)
            action_outcomes.append(outcome)
        elif intent.action == "move":
            result = world.move(intent.target)
            action_outcomes.append(ActionOutcome(
                intent=intent, success=result.success,
                message=result.message,
                side_effects=result.side_effects,
            ))
            apply_se(world, result.side_effects)
        elif intent.action == "search":
            interactions = world.get_available_interactions()
            done = world.completed_interactions.get(world.current_location, set())
            available = [i for i in interactions if i.name not in done]
            if available:
                lines = ["（环顾四周，注意到可以做的事：）"]
                for inter in available:
                    lines.append(f"  [{inter.type}] {inter.name} —— {inter.trigger}")
                msg = "\n".join(lines)
            else:
                msg = "（仔细查看四周，没有特别的发现）"
            action_outcomes.append(ActionOutcome(intent=intent, success=True, message=msg))
        else:
            action_outcomes.append(ActionOutcome(intent=intent, success=True,
                                                  message="（没有特别的事情发生）"))

    judge_data = {
        "at_results": [{"entity_id": a.entity_id, "entity_type": a.entity_type,
                         "success": a.success, "message": a.message} for a in at_results],
        "action_outcomes": [{"entity_id": o.entity_id, "entity_type": o.entity_type,
                              "success": o.success, "message": o.message,
                              "side_effects": str(o.side_effects)} for o in action_outcomes],
    }
    with open(os.path.join(turn_dir, "02_judge.json"), "w", encoding="utf-8") as f:
        json.dump(judge_data, f, ensure_ascii=False, indent=2)

    # ── Step 3: Enrich ──
    deferred_ats = judge.get_deferred_auto_triggers()
    pending_events = judge.filter_pending_events()
    needs_enrich = deferred_ats or pending_events or any(
        "##GRADED##" in o.message for o in action_outcomes
    )

    enriched_ats = []
    enriched_events = []
    emphasis = ""
    if needs_enrich:
        enrich_prompt = build_keeper_enrich_prompt(
            world, action_outcomes, list(at_results),
            pending_events, deferred_ats, raw
        )
        enrich_response = call_deepseek(enrich_prompt, json_mode=True, model="deepseek-v4-flash")
        enrichment = json.loads(enrich_response) if isinstance(enrich_response, str) else enrich_response

        with open(os.path.join(turn_dir, "03_enrich_prompt.txt"), "w", encoding="utf-8") as f:
            f.write(enrich_prompt)
        with open(os.path.join(turn_dir, "03_enrich_response.json"), "w", encoding="utf-8") as f:
            json.dump(enrichment, f, ensure_ascii=False, indent=2)

        emphasis = enrichment.get("emphasis_hint", "")
        for at_id in enrichment.get("triggered_ats", []):
            node = world._current_node()
            if node:
                for at in node.auto_triggers:
                    if at.id == at_id:
                        side_effects = []
                        for se_text in at.side_effects:
                            side_effects.extend(parse_markup_all(se_text))
                        apply_se(world, side_effects)
                        enriched_ats.append(at)
                        break
        for ev_id in enrichment.get("triggered_events", []):
            ev = world.graph.events.get(ev_id)
            if ev:
                world.triggered_events[ev.id] = True
                side_effects = []
                for se_text in ev.side_effects:
                    side_effects.extend(parse_markup_all(se_text))
                apply_se(world, side_effects)
                enriched_events.append(ev)
        for flag_key, flag_val in enrichment.get("new_flags", {}).items():
            world.set_flag(flag_key, flag_val)
    else:
        with open(os.path.join(turn_dir, "03_enrich_prompt.txt"), "w", encoding="utf-8") as f:
            f.write("(no pending ATs, events, or graded results — enrich skipped)\n")
        with open(os.path.join(turn_dir, "03_enrich_response.json"), "w", encoding="utf-8") as f:
            json.dump({"skipped": True}, f)

    # ── Step 4: Narrate ──
    curator = Curator(world)
    all_outcomes = action_outcomes + list(at_results) + [
        ActionOutcome(intent=ActionIntent(action="other"), success=True,
                       message=at.result, entity_id=at.id, entity_type="auto_trigger")
        for at in enriched_ats
    ] + [
        ActionOutcome(intent=ActionIntent(action="other"), success=True,
                       message=ev.result, entity_id=ev.id, entity_type="event")
        for ev in enriched_events
    ]
    ambient = [a.message for a in list(at_results)] + [at.result for at in enriched_ats]
    brief = curator.assemble(all_outcomes, ambient, emphasis)

    l1_data = narrator.l1_data
    l1_scene = l1_data.get(world.current_location) if l1_data else None
    narrator_prompt = build_narrator_prompt(brief, l1_scene=l1_scene)

    with open(os.path.join(turn_dir, "04_narrator_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(narrator_prompt)

    narrative_response = call_deepseek(narrator_prompt, json_mode=False, model="deepseek-v4-flash")
    narrative_brief, narrative = parse_narrative_output(narrative_response)

    with open(os.path.join(turn_dir, "04_narrative.txt"), "w", encoding="utf-8") as f:
        f.write(f"=== PLAYER INPUT ===\n{raw}\n\n")
        f.write(f"=== BRIEF ===\n{narrative_brief}\n\n")
        f.write(f"=== NARRATIVE ===\n{narrative}\n")

    # ── Memory ──
    first_intent = parsed[0] if parsed else ActionIntent(action="other")
    brief_text = "\n".join(o.message for o in all_outcomes)
    world.memory.add_record(
        raw, first_intent.action, first_intent.target,
        brief_text, location=world.current_location,
        success=any(o.success for o in action_outcomes)
    )
    if world.memory.should_compress():
        world.memory.compress(lambda p: call_deepseek(p, json_mode=False, model="deepseek-v4-flash"))

    return {"brief": narrative_brief, "narrative": narrative}


# ═══════════════════════════════════════════════════════════════
#  Cases
# ═══════════════════════════════════════════════════════════════

def get_all_cases():
    return [
        ("case_01_观察四周", [
            ("环顾四周，看看有没有什么异常", "search 当前场景，应返回可感知元素列表"),
        ]),
        ("case_02_移动去7号车厢", [
            ("去7号车厢", "move 到相邻场景，应成功移动并显示新场景描述"),
        ]),
        ("case_03_交互无检定", [
            ("阅读门扉上的便签", "interact 无技能检定，应直接返回便签内容"),
        ]),
        ("case_04_交互有检定", [
            ("仔细观察电车示意地图", "interact 需侦查检定，应显示检定结果和分级叙事"),
        ]),
        ("case_05_移动被拒", [
            ("去驾驶室", "move 到不存在路径的目标，应返回失败提示"),
        ]),
        ("case_06_前置不满足", [
            ("打开通往驾驶室的门", "interact 但 requirement 不满足，应提示缺少前置"),
        ]),
        ("case_07_多动作", [
            ("先检查随身物品然后去5号车厢", "多意图解析：interact + move"),
        ]),
        ("case_08_无意义输入", [
            ("唱一首快乐的小曲", "other 动作，应委婉提示无实际影响"),
        ]),
        ("case_09_auto_trigger", [
            ("靠近通往7号车厢的后门", "应触发 AT（血腥味），ambient 信息出现在叙事中"),
        ]),
        ("case_10_事件链", [
            ("感知电车异常", "交互 I1：尝试侦查检定感知异常"),
            ("检查随身物品留存", "交互 I2：检查物品"),
            ("阅读门扉上的便签", "交互 I3：阅读便签获取信息"),
        ]),
        ("case_11_检定失败", [
            ("仔细观察电车示意地图", "同一个检定交互，若调查员侦查值低则检定失败"),
        ]),
        ("case_12_偏离行为", [
            ("我想砸碎车窗玻璃跳出去", "完全偏离模组预期的行为，应触发 other"),
        ]),
        ("case_13_返回移动", [
            ("去5号车厢", "move 到 5 号车厢"),
            ("返回6号车厢", "move 返回，验证 to_here 路径可用"),
        ]),
        ("case_14_重复交互", [
            ("感知电车异常", "首次执行 I1"),
            ("感知电车异常", "再次执行同一交互，应显示已完成或拒绝重复"),
        ]),
        ("case_15_结局路径", [
            ("/trigger E1", "手动触发结局事件，验证 ##END_ 标记被检测"),
        ]),
    ]


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

def run_all():
    print(f"Test harness starting...")
    print(f"Output: {OUT_ROOT}")
    print()

    game = setup()

    all_cases = get_all_cases()
    for case_name, turns in all_cases:
        print(f"=== {case_name} ===")
        case_dir = os.path.join(OUT_ROOT, case_name)
        os.makedirs(case_dir, exist_ok=True)

        with open(os.path.join(case_dir, "_case_summary.log"), "w", encoding="utf-8") as f:
            f.write(f"Case: {case_name}\nTurns: {len(turns)}\n")
            for i, (inp, desc) in enumerate(turns):
                f.write(f"  Turn {i+1}: {desc}\n    Input: {inp}\n")

        for turn_num, (user_input, description) in enumerate(turns):
            print(f"  Turn {turn_num+1}: {description}")
            print(f"    Input: {user_input}")

            try:
                result = run_turn_with_log(game, user_input, case_dir, turn_num + 1)
                b = result.get("brief", "")
                n = result.get("narrative", "")
                print(f"    Brief: {b[:80]}{'...' if len(b) > 80 else ''}")
                print(f"    Narrative: {n[:80]}{'...' if len(n) > 80 else ''}")
            except Exception as e:
                print(f"    ERROR: {e}")
                import traceback
                traceback.print_exc()

        print()

    print(f"Done. Output at: {OUT_ROOT}")


if __name__ == "__main__":
    run_all()
