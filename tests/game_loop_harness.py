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
    from scenario_core import (
        parse_markup_all, apply_side_effects as apply_se, has_ending,
    )
    from llm import call_deepseek

    raw = user_input

    # ── Pre-parse: /trigger debug command ──
    direct_trigger_event = None
    if raw.strip().startswith("/trigger "):
        eid = raw.strip().split()[1] if len(raw.strip().split()) > 1 else ""
        ev = world.graph.events.get(eid)
        if ev:
            world.triggered_events[ev.id] = True
            direct_trigger_event = ev
            raw = f"（KP命令：手动触发事件 {eid}）"

    # ── Step 1: Parse (new unified format) ──
    parse_prompt = build_keeper_parse_prompt(world, raw)
    parse_response = call_deepseek(parse_prompt, json_mode=True, model="deepseek-v4-flash")
    parse_data = json.loads(parse_response) if isinstance(parse_response, str) else parse_response
    parse_actions = parse_data.get("actions", [])
    if not parse_actions:
        parse_actions = [{"type": "other", "text": raw}]

    with open(os.path.join(turn_dir, "01_parse_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(parse_prompt)
    with open(os.path.join(turn_dir, "01_parse_response.json"), "w", encoding="utf-8") as f:
        json.dump(parse_data, f, ensure_ascii=False, indent=2)

    # ── Step 2: Judge (deterministic) ──
    from game.judge import Judge
    judge = Judge(world)
    all_outcomes = []
    judged_entities = []
    for entry in parse_actions:
        entry_type = entry.get("type", "")
        if entry_type in ("auto_trigger", "interaction", "event"):
            eid = entry.get("id", "")
            entity = keeper._find_entity_by_id(eid)
            if not entity:
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="other"), success=False,
                    message=f"未找到实体「{eid}」"))
                continue
            intent = ActionIntent(
                action=entry_type if entry_type != "auto_trigger" else "other",
                target=entity.name if entry_type == "interaction" else "",
            )
            outcome = judge._execute_entity(entity, intent=intent)
            apply_se(world, outcome.side_effects)
            all_outcomes.append(outcome)
            if outcome.success:
                judged_entities.append({
                    "entity_type": entity.entity_type,
                    "id": entity.id,
                    "name": entity.name,
                    "result": outcome.message,
                    "success": True,
                    "skill_tier": outcome.skill_tier,
                })
        elif entry_type == "move":
            result = world.move(entry.get("target", ""))
            all_outcomes.append(ActionOutcome(
                intent=ActionIntent(action="move", target=entry.get("target", "")),
                success=result.success, message=result.message,
                side_effects=result.side_effects,
            ))
            apply_se(world, result.side_effects)
        elif entry_type == "search":
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
            all_outcomes.append(ActionOutcome(intent=ActionIntent(action="search"), success=True, message=msg))
        else:
            all_outcomes.append(ActionOutcome(
                intent=ActionIntent(action="other"), success=True,
                message=f"（{entry.get('text', '没有特别的事情发生')}）"))

    # Inject direct trigger event if /trigger was used
    if direct_trigger_event:
        se = []
        for se_text in direct_trigger_event.side_effects:
            se.extend(parse_markup_all(se_text))
        apply_se(world, se)
        all_outcomes.append(ActionOutcome(
            intent=ActionIntent(action="other"), success=True,
            message=direct_trigger_event.result,
            entity_id=direct_trigger_event.id, entity_type="event",
            side_effects=se,
        ))
        judged_entities.append({
            "entity_type": "event", "id": direct_trigger_event.id,
            "name": direct_trigger_event.name,
            "result": direct_trigger_event.result, "success": True,
        })

    with open(os.path.join(turn_dir, "02_judge.json"), "w", encoding="utf-8") as f:
        json.dump({
            "action_outcomes": [{"entity_id": o.entity_id, "entity_type": o.entity_type,
                                  "success": o.success, "message": o.message,
                                  "side_effects": str(o.side_effects),
                                  "skill_tier": o.skill_tier} for o in all_outcomes],
        }, f, ensure_ascii=False, indent=2)

    # ── Step 3: Enrich ──
    emphasis = ""
    if judged_entities:
        enrich_prompt = build_keeper_enrich_prompt(world, judged_entities, raw)
        enrich_response = call_deepseek(enrich_prompt, json_mode=True, model="deepseek-v4-flash")
        enrichment = json.loads(enrich_response) if isinstance(enrich_response, str) else enrich_response

        with open(os.path.join(turn_dir, "03_enrich_prompt.txt"), "w", encoding="utf-8") as f:
            f.write(enrich_prompt)
        with open(os.path.join(turn_dir, "03_enrich_response.json"), "w", encoding="utf-8") as f:
            json.dump(enrichment, f, ensure_ascii=False, indent=2)

        emphasis = enrichment.get("emphasis_hint", "")
        at_descs = enrichment.get("at_descriptions", {})
        enriched = enrichment.get("enriched_results", {})
        for o in all_outcomes:
            eid = o.entity_id
            if o.entity_type == "auto_trigger" and eid in at_descs:
                o.message = at_descs[eid]
            elif eid in enriched:
                o.message = enriched[eid]
    else:
        with open(os.path.join(turn_dir, "03_enrich_prompt.txt"), "w", encoding="utf-8") as f:
            f.write("(no judged entities — enrich skipped)\n")
        with open(os.path.join(turn_dir, "03_enrich_response.json"), "w", encoding="utf-8") as f:
            json.dump({"skipped": True}, f)

    # ── Ending detection ──
    ending_name = None; ending_narrative = None
    for o in all_outcomes:
        en, ed = has_ending(o.message)
        if en:
            ending_name = en; ending_narrative = ed; break
    if not ending_name and direct_trigger_event:
        en, ed = has_ending(direct_trigger_event.result)
        if en:
            ending_name = en; ending_narrative = ed
    with open(os.path.join(turn_dir, "05_ending.json"), "w", encoding="utf-8") as f:
        json.dump({"ending_triggered": ending_name is not None,
                    "ending_name": ending_name, "ending_narrative": ending_narrative}, f, ensure_ascii=False, indent=2)

    # ── Step 4: Narrate ──
    from game.curator import Curator
    curator = Curator(world)
    ambient = [o.message for o in all_outcomes if o.entity_type == "auto_trigger"]
    brief = curator.assemble(all_outcomes, ambient, emphasis)

    l1_scene = narrator.l1_data.get(world.current_location) if narrator.l1_data else None
    narrator_prompt = build_narrator_prompt(brief, l1_scene=l1_scene)
    with open(os.path.join(turn_dir, "04_narrator_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(narrator_prompt)

    narrative_response = call_deepseek(narrator_prompt, json_mode=False, model="deepseek-v4-flash")
    narrative_brief, narrative = parse_narrative_output(narrative_response)
    with open(os.path.join(turn_dir, "04_narrative.txt"), "w", encoding="utf-8") as f:
        f.write(f"=== PLAYER INPUT ===\n{raw}\n\n=== BRIEF ===\n{narrative_brief}\n\n=== NARRATIVE ===\n{narrative}\n")

    # ── Memory ──
    first_entry = parse_actions[0] if parse_actions else {"type": "other"}
    brief_text = "\n".join(o.message for o in all_outcomes)
    world.memory.add_record(
        raw, first_entry.get("type", "other"), first_entry.get("target", ""),
        brief_text, location=world.current_location,
        success=any(o.success for o in all_outcomes))
    if world.memory.should_compress():
        world.memory.compress(lambda p: call_deepseek(p, json_mode=False, model="deepseek-v4-flash"))

    return {"brief": narrative_brief, "narrative": narrative,
            "ending_name": ending_name, "ending_narrative": ending_narrative}


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
