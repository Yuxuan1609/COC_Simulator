"""B 裁决：judge 循环 + 依赖图自动触发。W6 起尾部吞入作者门。"""
from __future__ import annotations

from ..agents.keeper import _describe_time_condition
from ..messages import ActionIntent, ActionOutcome


def phase_b_adjudicate(ctx, acc, tools) -> None:
    """judge 各 entry 类型(interaction/event/use/move/search/other) + 依赖自动触发。
    产出: acc.all_outcomes / acc.enrich_input / tools._pending_side_effects /
    tools._pending_move / tools._weapon_offer(search 发现)。"""
    # Step 2: Judge — iterate over parse result entries
    for entry in acc.parse_result:
        entry_type = entry.get("type", "")
        if entry_type in ("auto_trigger", "interaction", "event"):
            eid = entry.get("id", "")
            entity = tools._find_entity_by_id(eid)
            if not entity:
                continue
            # Time condition check — independent of requirement/dependency_graph
            if tools.world and tools.world.clock:
                from scenario_core import check_time_condition as _check_tc
                tc = entity.get("time_condition", "") if isinstance(entity, dict) else getattr(entity, "time_condition", "")
                if not _check_tc(tc, tools.world.clock.day, tools.world.clock.time_of_day):
                    hint = _describe_time_condition(tc) or "当前时间不满足触发条件"
                    now = f"第{tools.world.clock.day}天 {tools.world.clock.time_of_day}"
                    acc.all_outcomes.append(ActionOutcome(
                        intent=ActionIntent(action=entry_type, target=entity.name),
                        success=False,
                        message=f"「{entity.name}」{hint}（当前：{now}）",
                        entity_id=entity.id,
                        entity_type=entity.entity_type,
                    ))
                    continue
            intent = ActionIntent(
                action=entry_type,
                target=entity.name if entry_type == "interaction" else "",
            )
            outcome = tools.judge._execute_entity(entity, intent=intent, player_input=ctx.raw)
            tools._pending_side_effects.extend(outcome.side_effects)
            if outcome.success:
                tr = entity.extra.get("time_range") if entity.extra else None
                acc.enrich_input.actions.append({
                    "type": entity.entity_type,
                    "name": entity.name,
                    "success": True,
                    "time_range": tr,
                    "time_category": tools._infer_time_category(entity),
                })
            acc.all_outcomes.append(outcome)
            acc.enrich_input.entities.append({
                "entity_type": entity.entity_type,
                "id": entity.id,
                "name": entity.name,
                "result": outcome.message,
                "success": outcome.success,
                "skill_tier": outcome.skill_tier,
            })
        elif entry_type == "use":
            material = entry.get("material")
            if material is not None:
                outcome = tools.judge.execute_material(material, ctx.raw)
                acc.all_outcomes.append(outcome)
                acc.enrich_input.entities.append({
                    "entity_type": "material",
                    "id": material.material_id,
                    "name": material.name,
                    "result": outcome.message,
                    "success": outcome.success,
                    "skill_tier": outcome.skill_tier,
                })
        elif entry_type == "move":
            target = entry.get("target", "")
            origin = tools.world.current_location
            tools._pending_move = target  # defer move until Author check passes
            acc.all_outcomes.append(ActionOutcome(
                intent=ActionIntent(action="move", target=target),
                success=True, message=f"从{origin}前往{target}...",
            ))
            acc.enrich_input.actions.append({
                "type": "move",
                "name": f"移动到{target}",
                "success": True,
                "time_range": None,
                "time_category": "move",
            })
            acc.enrich_input.entities.append({
                "entity_type": "move",
                "id": f"MOVE_{target}",
                "name": f"前往{target}",
                "result": f"从{origin}前往{target}。",
                "success": True,
                "skill_tier": "",
            })
        elif entry_type == "search":
            # Search always performs a 侦查 (Spot Hidden) check.
            # No dependency check, no flag update, no enrich.
            trait_enh = None
            if tools.world.player:
                ok, skill_msg, tier = tools.world.player.check_skill("侦查", "regular")
                skill_detail = (
                    f"[SEARCH] 侦查检定 | 等级={tier} | {'成功' if ok else '失败'}\n"
                    f"  {skill_msg}"
                )
                from prompts import log_skill_result, apply_trait_enhancement
                log_skill_result(skill_detail)
                # Trait enhancement for search
                new_tier, enh = apply_trait_enhancement(
                    tools.world.player, "侦查", skill_msg,
                    entity_name="搜索", search_context=True,
                    player_input=ctx.raw,
                )
                if new_tier and new_tier != tier:
                    skill_detail += f"\n  [特质修正] {tier} → {new_tier}：{enh.get('reason', '') if enh else ''}"
                    log_skill_result(skill_detail)
                    if enh is not None:
                        enh["original_tier"] = tier
                    tier = new_tier
                    ok = (tier != "failure")
                trait_enh = enh
                if ok:
                    interactions = tools.world.get_available_interactions()
                    done = tools.world.completed_interactions.get(tools.world.current_location, set())
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
                # Weapon discovery: always check scene weapons (visible even on failed search)
                scene_weps = tools.world.scene_weapons.get(
                    tools.world.current_location, []
                )
                if scene_weps:
                    wep_names = "、".join(
                        f"{f'{sw.quantity}把 ' if sw.quantity > 1 else ''}{sw.weapon_ref}"
                        for sw in scene_weps
                    )
                    msg += f'\n\n（你发现了 {wep_names}。是否拾取？（是/否））'
                    tools._weapon_offer = [{"weapon_ref": sw.weapon_ref, "scene": tools.world.current_location} for sw in scene_weps]
            else:
                msg = "（仔细查看四周，没有特别的发现）"
            acc.all_outcomes.append(ActionOutcome(
                intent=ActionIntent(action="search"), success=True, message=msg,
                entity_id="SEARCH", entity_type="search",
                skill_tier=tier if tools.world.player else "",
                skill_detail=skill_detail if tools.world.player else "",
                enhancement=trait_enh))
            acc.enrich_input.actions.append({
                "type": "search",
                "name": "搜索",
                "success": True,
                "time_range": None,
                "time_category": "search",
            })
            acc.enrich_input.entities.append({
                "entity_type": "search",
                "id": "SEARCH",
                "name": "搜索",
                "result": msg[:200],
                "success": True,
                "skill_tier": tier if tools.world.player else "",
            })
        elif entry_type == "other":
            text = entry.get("text", "")
            acc.all_outcomes.append(ActionOutcome(
                intent=ActionIntent(action="other"), success=True,
                message=f"（{text}）"))
            acc.enrich_input.actions.append({
                "type": "other",
                "name": text,
                "success": True,
                "time_range": None,
                "time_category": "other",
            })
            acc.enrich_input.entities.append({
                    "entity_type": "other",
                    "id": "OTHER",
                    "name": text[:40],
                    "result": f"（{text}）"[:200],
                    "success": True,
                    "skill_tier": "",
                })
        else:
            acc.all_outcomes.append(ActionOutcome(
                intent=ActionIntent(action="other"), success=True,
                message=f"（{entry.get('text', '没有特别的事情发生')}）"))
            acc.enrich_input.actions.append({
                "type": "other",
                "name": entry.get("text", ""),
                "success": True,
                "time_range": None,
                "time_category": "other",
            })
            acc.enrich_input.entities.append({
                "entity_type": "other",
                "id": "OTHER",
                "name": str(entry.get("text", ""))[:40],
                "result": f"（{entry.get('text', '没有特别的事情发生')}）"[:200],
                "success": True,
                "skill_tier": "",
            })

    # Deterministic event auto-trigger: after judge, fire events whose dependencies just satisfied
    dep_graph = tools.world.dependency_graph if hasattr(tools.world, 'dependency_graph') else {}
    for edge in dep_graph.get("edges", dep_graph.get("dependency_edges", [])):
        if edge.get("dep_type") == "interaction":
            source_id = edge.get("source", "")
            target_id = edge.get("target", "")
            if tools.world.is_entity_completed(target_id):
                # Source is an event that should auto-fire when target completes
                source_entity = tools.world.graph.events.get(source_id)
                if source_entity and not tools.world.is_event_triggered(source_id):
                    outcome = tools.judge._execute_entity(source_entity, intent=ActionIntent(action="event"), player_input=ctx.raw)
                    tools._pending_side_effects.extend(outcome.side_effects)
                    acc.all_outcomes.append(outcome)
                    acc.enrich_input.entities.append({
                        "entity_type": "event",
                        "id": source_entity.id,
                        "name": source_entity.name,
                        "result": outcome.message,
                        "success": outcome.success,
                        "skill_tier": outcome.skill_tier,
                    })
