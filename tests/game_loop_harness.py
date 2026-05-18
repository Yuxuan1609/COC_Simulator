"""
Game Loop Test Harness — 15 个玩家输入场景测试，并行执行。
每个 test case 独立启动游戏流程，不互相干扰。
"""
import sys, os, json
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_ROOT = os.path.join(os.path.dirname(__file__), "..", "data", "debug", "test_harness", TIMESTAMP)

PROJECT_ROOT = os.path.dirname(__file__)
L2_PATH = os.path.join(PROJECT_ROOT, "..", "data", "modules", "常暗之厢", "l2_keeper.json")
L1_PATH = os.path.join(PROJECT_ROOT, "..", "data", "modules", "常暗之厢", "l1_player.json")
L3_PATH = os.path.join(PROJECT_ROOT, "..", "data", "modules", "常暗之厢", "l3_designer.json")
ESCALATION_PATH = os.path.join(PROJECT_ROOT, "..", "data", "modules", "常暗之厢", "escalation_config.json")
CHAR_PATH = os.path.join(PROJECT_ROOT, "..", "investigator", "test_character.json")

# ═══════════════════════════════════════════════════════════════
#  Case definitions — each case specifies its own start_node
# ═══════════════════════════════════════════════════════════════

def get_all_cases():
    """Return list of (case_name, start_node, [(input, description), ...])."""
    return [
        # ── 基础动作 ──
        ("case_01_观察四周", "6号车厢", [
            ("环顾四周，看看有没有什么异常", "search + 侦查检定"),
        ]),
        ("case_02_移动去7号车厢", "6号车厢", [
            ("去7号车厢", "move 到相邻场景"),
        ]),
        ("case_03_交互无检定", "6号车厢", [
            ("阅读门扉上的便签", "interact I1 无技能检定"),
        ]),
        ("case_04_交互有检定", "6号车厢", [
            ("仔细观察电车示意地图", "interact I4 需侦查检定+##GRADED##"),
        ]),
        ("case_05_移动被拒", "6号车厢", [
            ("去驾驶室", "move 到不存在路径的目标"),
        ]),
        ("case_06_前置不满足", "6号车厢", [
            ("打开通往驾驶室的门", "interact 但无此实体"),
        ]),
        # ── 复杂意图 ──
        ("case_07_多动作", "6号车厢", [
            ("先检查随身物品然后去5号车厢", "interact I5 + move 到 5号车厢"),
        ]),
        ("case_08_无意义输入", "6号车厢", [
            ("唱一首快乐的小曲", "other 动作"),
        ]),
        # ── Auto-trigger ──
        ("case_09_auto_trigger", "6号车厢", [
            ("靠近通往7号车厢的后门", "move到7号车厢后可能触发AT"),
        ]),
        # ── 事件链 / 重复 ──
        ("case_10_事件链", "6号车厢", [
            ("感知电车异常", "交互，可触发事件"),
            ("检查随身物品留存", "交互 I5，检查物品"),
            ("阅读门扉上的便签", "交互 I1"),
        ]),
        ("case_11_检定失败", "6号车厢", [
            ("仔细观察电车示意地图", "同一个检定交互(侦查)，可能检定失败"),
        ]),
        ("case_12_偏离行为", "6号车厢", [
            ("我想砸碎车窗玻璃跳出去", "完全偏离模组预期的行为"),
        ]),
        # ── 移动 / 重复 ──
        ("case_13_返回移动", "6号车厢", [
            ("去5号车厢", "move 到 5号车厢"),
            ("返回6号车厢", "move 返回，验证 to_here"),
        ]),
        ("case_14_重复交互", "6号车厢", [
            ("感知电车异常", "首次执行"),
            ("感知电车异常", "再次执行，应拒绝"),
        ]),
        # ── 结局 ──
        ("case_15_结局路径", "6号车厢", [
            ("/trigger E22", "手动触发E22(击败循声者→疯狂终结)，验证##END_"),
        ]),
    ]


# ═══════════════════════════════════════════════════════════════
#  Per-case game init (fully isolated)
# ═══════════════════════════════════════════════════════════════

def _init_game_for_case(start_node: str) -> dict:
    """Create a fresh game instance for a single test case."""
    from game_loop import init_game
    from investigator import Investigator, load_investigator
    from investigator.rules import roll_stats, calc_derived, create_skill_list

    game = init_game(
        l2_path=L2_PATH, l1_path=L1_PATH, l3_path=L3_PATH,
        escalation_config_path=ESCALATION_PATH, start_node=start_node,
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
#  Turn runner (unchanged from single-case flow)
# ═══════════════════════════════════════════════════════════════

def run_turn_with_log(game, user_input: str, case_dir: str, turn_num: int,
                       prompt_log: str | None = None) -> dict:
    """Run one turn, capturing all intermediates to case_dir/turn_NN/."""
    turn_dir = os.path.join(case_dir, f"turn_{turn_num:02d}")
    os.makedirs(turn_dir, exist_ok=True)

    keeper = game["keeper"]
    narrator = game["narrator"]
    world = keeper.world

    from prompts import (
        build_keeper_parse_prompt, build_keeper_enrich_prompt,
        build_narrator_prompt, parse_narrative_output, set_prompt_log_file,
    )
    from game.messages import ActionIntent, ActionOutcome
    from scenario_core import (
        parse_markup_all, apply_side_effects as apply_se, has_ending,
    )
    from llm import call_deepseek

    if prompt_log:
        set_prompt_log_file(prompt_log)

    raw = user_input

    # Pre-parse: /trigger debug command
    direct_trigger_event = None
    if raw.strip().startswith("/trigger "):
        eid = raw.strip().split()[1] if len(raw.strip().split()) > 1 else ""
        ev = world.graph.events.get(eid)
        if ev:
            world.triggered_events[ev.id] = True
            direct_trigger_event = ev
            raw = f"（KP命令：手动触发事件 {eid}）"

    # Step 1: Parse
    parse_prompt = build_keeper_parse_prompt(world, raw)
    parse_response = call_deepseek(parse_prompt, json_mode=True, model="deepseek-v4-flash",
                                    fallback_schema={"actions": []})
    parse_data = json.loads(parse_response) if isinstance(parse_response, str) else parse_response
    parse_actions = parse_data.get("actions", [])
    if not parse_actions:
        parse_actions = [{"type": "other", "text": raw}]

    with open(os.path.join(turn_dir, "01_parse_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(parse_prompt)
    with open(os.path.join(turn_dir, "01_parse_response.json"), "w", encoding="utf-8") as f:
        json.dump(parse_data, f, ensure_ascii=False, indent=2)

    # Step 2: Judge
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
                    "id": entity.id, "name": entity.name,
                    "result": outcome.message, "success": True,
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
            tier = ""
            if world.player:
                ok, skill_msg, tier = world.player.check_skill("侦查", "regular")
                from prompts import log_skill_result
                log_skill_result(
                    f"[SEARCH] 侦查检定 | 等级={tier} | {'成功' if ok else '失败'}\n  {skill_msg}",
                    log_path=prompt_log,
                )
                # Trait enhancement for search
                inv_desc = getattr(world.player, 'personal_description', '') or \
                           getattr(world.player, 'description', '')
                inv_app = getattr(world.player, 'appearance', '')
                if inv_desc or inv_app:
                    from llm import evaluate_trait_enhancement
                    enh = evaluate_trait_enhancement(
                        inv_desc=inv_desc, inv_appearance=inv_app,
                        skill_name="侦查", skill_detail=skill_msg,
                        current_tier=tier, entity_name="搜索",
                        search_context=True,
                    )
                    new_tier = enh.get("tier", tier)
                    if new_tier != tier:
                        log_skill_result(
                            f"  [特质修正] {tier} → {new_tier}：{enh.get('reason', '')}",
                            log_path=prompt_log,
                        )
                        tier = new_tier
                        ok = (tier != "failure")
                if ok:
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
                else:
                    msg = "（你环顾四周，但昏暗的光线让你无法看清任何有用的东西）"
            else:
                msg = "（仔细查看四周，没有特别的发现）"
            all_outcomes.append(ActionOutcome(intent=ActionIntent(action="search"),
                                              success=True, message=msg, skill_tier=tier))
        else:
            all_outcomes.append(ActionOutcome(
                intent=ActionIntent(action="other"), success=True,
                message=f"（{entry.get('text', '没有特别的事情发生')}）"))

    if direct_trigger_event:
        se = []
        for se_text in direct_trigger_event.side_effects:
            se.extend(parse_markup_all(se_text))
        apply_se(world, se)
        all_outcomes.append(ActionOutcome(
            intent=ActionIntent(action="other"), success=True,
            message=direct_trigger_event.result,
            entity_id=direct_trigger_event.id, entity_type="event", side_effects=se,
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

    # Step 3: Enrich
    emphasis = ""
    if judged_entities:
        enrich_prompt = build_keeper_enrich_prompt(world, judged_entities, raw)
        enrich_response = call_deepseek(enrich_prompt, json_mode=True, model="deepseek-v4-flash",
                                         fallback_schema={
                                             "at_descriptions": {},
                                             "enriched_results": {},
                                             "emphasis_hint": "",
                                         })
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

    # Ending detection
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
                    "ending_name": ending_name, "ending_narrative": ending_narrative},
                  f, ensure_ascii=False, indent=2)

    # Step 4: Narrate
    from game.curator import Curator
    curator = Curator(world)
    ambient = [o.message for o in all_outcomes if o.entity_type == "auto_trigger"]
    brief = curator.assemble(all_outcomes, ambient, emphasis)

    l1_scene = narrator.l1_data.get(world.current_location) if narrator.l1_data else None
    from prompts import _build_investigator_info
    inv_info = _build_investigator_info(world)
    narrator_prompt = build_narrator_prompt(brief, l1_scene=l1_scene, inv_info=inv_info)
    with open(os.path.join(turn_dir, "04_narrator_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(narrator_prompt)

    narrative_response = call_deepseek(narrator_prompt, json_mode=False, model="deepseek-v4-flash")
    narrative_brief, narrative = parse_narrative_output(narrative_response)
    with open(os.path.join(turn_dir, "04_narrative.txt"), "w", encoding="utf-8") as f:
        f.write(f"=== PLAYER INPUT ===\n{raw}\n\n=== BRIEF ===\n{narrative_brief}\n\n=== NARRATIVE ===\n{narrative}\n")

    # Memory
    first_entry = parse_actions[0] if parse_actions else {"type": "other"}
    brief_text = "\n".join(o.message for o in all_outcomes)
    world.memory.add_record(
        raw, first_entry.get("type", "other"), first_entry.get("target", ""),
        brief_text, location=world.current_location,
        success=any(o.success for o in all_outcomes))

    return {"brief": narrative_brief, "narrative": narrative,
            "ending_name": ending_name, "ending_narrative": ending_narrative}


# ═══════════════════════════════════════════════════════════════
#  Case runner (one fresh game per case, isolated prompt log)
# ═══════════════════════════════════════════════════════════════

def _run_single_case(case_name: str, start_node: str, turns: list) -> dict:
    """Run one full test case with a fresh game instance."""
    case_dir = os.path.join(OUT_ROOT, case_name)
    os.makedirs(case_dir, exist_ok=True)

    prompt_log = os.path.join(case_dir, "_prompt_log.txt")

    game = _init_game_for_case(start_node)
    world = game["keeper"].world

    # Write case init log
    with open(os.path.join(case_dir, "_case_init.log"), "w", encoding="utf-8") as f:
        f.write(f"Case: {case_name}\nStart node: {start_node}\nTurns: {len(turns)}\n")
        f.write(f"Player: {world.player.name if world.player else 'None'}\n")
        for name, node in world.graph.nodes.items():
            f.write(f"  Scene: {name} — {len(node.interactions)} interactions, "
                    f"{len(node.auto_triggers)} ATs, {len(node.edges)} exits\n")

    with open(os.path.join(case_dir, "_case_summary.log"), "w", encoding="utf-8") as f:
        f.write(f"Case: {case_name}\nStart: {start_node}\nTurns: {len(turns)}\n")
        for i, (inp, desc) in enumerate(turns):
            f.write(f"  Turn {i+1}: {desc}\n    Input: {inp}\n")

    results = []
    for turn_num, (user_input, description) in enumerate(turns):
        result = run_turn_with_log(game, user_input, case_dir, turn_num + 1,
                                    prompt_log=prompt_log)
        results.append(result)

    return {"case_name": case_name, "start_node": start_node, "results": results}


# ═══════════════════════════════════════════════════════════════
#  Main — parallel execution
# ═══════════════════════════════════════════════════════════════

def run_all(workers: int = 4):
    os.makedirs(OUT_ROOT, exist_ok=True)

    print(f"Test harness starting...")
    print(f"Output: {OUT_ROOT}")
    print(f"Parallel workers: {workers}")
    print()

    all_cases = get_all_cases()
    print(f"Cases: {len(all_cases)}")

    # Write master init log
    with open(os.path.join(OUT_ROOT, "_master_init.log"), "w", encoding="utf-8") as f:
        f.write(f"Timestamp: {TIMESTAMP}\n")
        f.write(f"Workers: {workers}\n")
        for case_name, start_node, turns in all_cases:
            f.write(f"  {case_name}: start={start_node}, turns={len(turns)}\n")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {}
        for case_name, start_node, turns in all_cases:
            f = ex.submit(_run_single_case, case_name, start_node, turns)
            futures[f] = case_name

        for f in as_completed(futures):
            case_name = futures[f]
            try:
                outcome = f.result()
                start = outcome["start_node"]
                print(f"\n=== {case_name} (start={start}) ===")
                for i, r in enumerate(outcome["results"]):
                    b = r.get("brief", "")[:80]
                    n = r.get("narrative", "")[:80]
                    en = r.get("ending_name")
                    print(f"  T{i+1}: brief={b}...")
                    print(f"       narrative={n}...")
                    if en:
                        print(f"       >>> ENDING: {en} — {r.get('ending_narrative', '')}")
            except Exception as e:
                print(f"\n=== {case_name} FAILED ===")
                import traceback
                traceback.print_exc()

    print(f"\nDone. Output at: {OUT_ROOT}")


if __name__ == "__main__":
    run_all()
