"""
Game Loop Test Harness — 测试房间串行多轮测试。
使用测试 JSON (*_test.json)，从测试房间开始，串行执行多轮互动。
"""
import sys, os, json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_ROOT = os.path.join(os.path.dirname(__file__), "..", "data", "debug", "test_harness", TIMESTAMP)

PROJECT_ROOT = os.path.dirname(__file__)
L2_PATH = os.path.join(PROJECT_ROOT, "..", "data", "modules", "常暗之厢", "l2_test.json")
L1_PATH = os.path.join(PROJECT_ROOT, "..", "data", "modules", "常暗之厢", "l1_test.json")
L3_PATH = os.path.join(PROJECT_ROOT, "..", "data", "modules", "常暗之厢", "l3_test.json")
ESCALATION_PATH = os.path.join(PROJECT_ROOT, "..", "data", "modules", "常暗之厢", "escalation_config.json")
CHAR_PATH = os.path.join(PROJECT_ROOT, "..", "investigator", "test_character.json")


# ═══════════════════════════════════════════════════════════════
#  Case: 测试房间多轮互动
#  覆盖: search, 无检定交互, 技能检定+##GRADED##, 依赖链,
#        auto_trigger, 结局触发, 移动出口
# ═══════════════════════════════════════════════════════════════

CASE = {
    "name": "case_test_room",
    "start_node": "测试房间",
    "turns": [
        # Turn 1: Search — 侦查检定 + trait enhancement
        ("观察四周，看看房间里有什么", "search + 侦查检定"),

        # Turn 2: 无检定交互 — IT3 观察镜子
        ("拿起桌上的镜子仔细看看", "interact IT3 无检定"),

        # Turn 3: 技能检定 — IT1 检查桌子物品 (侦查, regular, ##GRADED##)
        ("仔细检查桌子上的每样物品", "interact IT1 侦查检定+##GRADED##"),

        # Turn 4: 依赖链 — IT2 阅读日志 (依赖 IT1 成功)
        ("翻开那本泛黄的日志仔细读一读", "interact IT2 图书馆检定, 依赖IT1"),

        # Turn 5: 困难检定 — IT4 推开铁门 (力量, hard)
        ("用尽全力去撞开那扇铁门", "interact IT4 力量检定 hard"),

        # Turn 6: 保留 — 移动交互测试
        ("去6号车厢", "move 到 6号车厢"),

        # Turn 7: 保留 — 无意义输入
        ("唱一首快乐的小曲", "other 动作"),
    ],
}


# ═══════════════════════════════════════════════════════════════
#  Init
# ═══════════════════════════════════════════════════════════════

def _init_game():
    from game_loop import init_game
    from investigator import Investigator, load_investigator
    from investigator.rules import roll_stats, calc_derived, create_skill_list

    game = init_game(
        l2_path=L2_PATH, l1_path=L1_PATH, l3_path=L3_PATH,
        escalation_config_path=ESCALATION_PATH, start_node=CASE["start_node"],
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
#  Turn runner
# ═══════════════════════════════════════════════════════════════

def run_turn_with_log(game, user_input: str, case_dir: str, turn_num: int) -> dict:
    turn_dir = os.path.join(case_dir, f"turn_{turn_num:02d}")
    os.makedirs(turn_dir, exist_ok=True)

    keeper = game["keeper"]
    narrator = game["narrator"]
    world = keeper.world

    from prompts import (
        build_keeper_parse_prompt, build_keeper_enrich_prompt,
        build_narrator_prompt, parse_narrative_output, _build_investigator_info,
    )
    from game.messages import ActionIntent, ActionOutcome
    from scenario_core import (
        parse_markup_all, apply_side_effects as apply_se, has_ending,
    )
    from llm import call_deepseek

    raw = user_input

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
                    "entity_type": entity.entity_type, "id": entity.id,
                    "name": entity.name, "result": outcome.message,
                    "success": True, "skill_tier": outcome.skill_tier,
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
                    f"[SEARCH] 侦查检定 | 等级={tier} | {'成功' if ok else '失败'}\n  {skill_msg}")
                inv_desc = getattr(world.player, 'personal_description', '') or \
                           getattr(world.player, 'description', '')
                if inv_desc:
                    from llm import evaluate_trait_enhancement
                    enh = evaluate_trait_enhancement(
                        inv_desc=inv_desc, skill_name="侦查", skill_detail=skill_msg,
                        current_tier=tier, entity_name="搜索", search_context=True)
                    new_tier = enh.get("tier", tier)
                    if new_tier != tier:
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
            all_outcomes.append(ActionOutcome(
                intent=ActionIntent(action="search"), success=True, message=msg,
                entity_id="SEARCH", entity_type="search", skill_tier=tier))
        else:
            all_outcomes.append(ActionOutcome(
                intent=ActionIntent(action="other"), success=True,
                message=f"（{entry.get('text', '没有特别的事情发生')}）"))

    with open(os.path.join(turn_dir, "02_judge.json"), "w", encoding="utf-8") as f:
        json.dump({
            "outcomes": [{"entity_id": o.entity_id, "entity_type": o.entity_type,
                          "success": o.success, "message": o.message,
                          "skill_tier": o.skill_tier} for o in all_outcomes],
        }, f, ensure_ascii=False, indent=2)

    # Step 3: Enrich
    emphasis = ""
    if judged_entities:
        enrich_prompt = build_keeper_enrich_prompt(world, judged_entities, raw)
        enrich_response = call_deepseek(enrich_prompt, json_mode=True, model="deepseek-v4-flash",
                                         fallback_schema={"results": {}, "reasoning": "",
                                                          "emphasis_hint": ""})
        enrichment = json.loads(enrich_response) if isinstance(enrich_response, str) else enrich_response
        with open(os.path.join(turn_dir, "03_enrich_prompt.txt"), "w", encoding="utf-8") as f:
            f.write(enrich_prompt)
        with open(os.path.join(turn_dir, "03_enrich_response.json"), "w", encoding="utf-8") as f:
            json.dump(enrichment, f, ensure_ascii=False, indent=2)
        emphasis = enrichment.get("emphasis_hint", "")
        results = enrichment.get("results", {})
        for o in all_outcomes:
            eid = o.entity_id
            if eid in results:
                o.message = results[eid]
    else:
        with open(os.path.join(turn_dir, "03_enrich_prompt.txt"), "w", encoding="utf-8") as f:
            f.write("(no judged entities — enrich skipped)\n")

    # Ending detection
    ending_name = None; ending_narrative = None
    for o in all_outcomes:
        en, ed = has_ending(o.message)
        if en:
            ending_name = en; ending_narrative = ed; break
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
    inv_info = _build_investigator_info(world)
    narrator_prompt = build_narrator_prompt(brief, l1_scene=l1_scene, inv_info=inv_info)
    with open(os.path.join(turn_dir, "04_narrator_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(narrator_prompt)

    narrative_response = call_deepseek(narrator_prompt, json_mode=True, model="deepseek-v4-flash",
                                        fallback_schema={"brief": "", "narrative": "", "scene_update": ""})
    narrative_brief, narrative, scene_update = parse_narrative_output(narrative_response)
    if scene_update:
        world.apply_scene_update(scene_update)
    with open(os.path.join(turn_dir, "04_narrative.json"), "w", encoding="utf-8") as f:
        json.dump({"brief": narrative_brief, "narrative": narrative,
                   "scene_update": scene_update or "(无)"}, f, ensure_ascii=False, indent=2)

    # Memory
    first_entry = parse_actions[0] if parse_actions else {"type": "other"}
    brief_text = "\n".join(o.message for o in all_outcomes)
    world.memory.add_record(
        raw, first_entry.get("type", "other"), first_entry.get("target", ""),
        brief_text, location=world.current_location,
        success=any(o.success for o in all_outcomes))

    return {"brief": narrative_brief, "narrative": narrative,
            "ending_name": ending_name, "ending_narrative": ending_narrative,
            "skill_results": [{"entity_id": o.entity_id, "tier": o.skill_tier,
                               "success": o.success, "detail": o.skill_detail}
                              for o in all_outcomes if o.skill_tier]}


# ═══════════════════════════════════════════════════════════════
#  Main — serial single case
# ═══════════════════════════════════════════════════════════════

def run_all():
    os.makedirs(OUT_ROOT, exist_ok=True)
    case_dir = os.path.join(OUT_ROOT, CASE["name"])
    os.makedirs(case_dir, exist_ok=True)

    print(f"Test Harness — 测试房间串行多轮")
    print(f"Output: {OUT_ROOT}")
    print(f"Start: {CASE['start_node']}")
    print(f"Turns: {len(CASE['turns'])}")
    print()

    game = _init_game()
    world = game["keeper"].world
    print(f"Player: {world.player.name if world.player else 'None'}")
    print(f"Scenes: {list(world.graph.nodes.keys())}")
    print()

    results = []
    for turn_num, (user_input, description) in enumerate(CASE["turns"]):
        print(f"--- Turn {turn_num + 1}: {description} ---")
        print(f"    Input: {user_input}")
        result = run_turn_with_log(game, user_input, case_dir, turn_num + 1)
        results.append(result)
        brief = result['brief']
        if isinstance(brief, str) and len(brief) > 80:
            brief = brief[:80] + "..."
        print(f"    Brief: {brief}")
        if result.get("skill_results"):
            for sr in result["skill_results"]:
                ok = "[PASS]" if sr["success"] else "[FAIL]"
                detail = sr.get("detail", "")
                if isinstance(detail, str) and "\n" in detail:
                    detail = detail.split("\n")[1].strip()
                print(f"    Skill: {ok} [{sr['entity_id']}] {sr['tier']} | {detail}")
        if result.get("ending_name"):
            print(f"    >>> ENDING: {result['ending_name']}")
        print()

    # Summary
    with open(os.path.join(case_dir, "_summary.json"), "w", encoding="utf-8") as f:
        json.dump({
            "case": CASE["name"], "start": CASE["start_node"],
            "turns": [{"input": inp, "desc": desc, "brief": r["brief"],
                       "ending": r.get("ending_name")}
                      for (inp, desc), r in zip(CASE["turns"], results)],
        }, f, ensure_ascii=False, indent=2)

    print(f"Done. Output at: {OUT_ROOT}")


if __name__ == "__main__":
    run_all()
