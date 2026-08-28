"""D 充实：战斗结果注入 → enrich ∥ time_agent → advance_time → ending扫描① → 时压。"""
from __future__ import annotations

from ..messages import ActionIntent, ActionOutcome, TimeCommsPacket


def phase_d_enrich(ctx, acc, tools) -> None:
    """产出: acc.enrichment / acc.ta_result / acc.emphasis / acc.enriched_summary /
    acc.ending_result(首次扫描) / world.advance_time 副作用 / 时压 outcome。"""
    # Step 3: [Enrich(LLM) ∥ TimeAgent(LLM)] — combat + boss info already injected into acc.enrich_input

    # Inject pending combat result (from frontend combat path, same turn)
    if tools._combat_result_pending:
        cr = tools._combat_result_pending
        tools._combat_result_pending = None
        outcome_label = {"win": "胜利", "loss": "败北", "flee": "逃脱", "draw": "平局"}.get(cr.get("outcome", ""), cr.get("outcome", ""))
        acc.enrich_input.entities.append({
            "entity_type": "combat_result",
            "id": "COMBAT_RESULT",
            "name": f"战斗{outcome_label}",
            "result": cr.get("narrative", f"战斗结束，结果是{outcome_label}。")[:300],
            "success": cr.get("outcome") == "win",
            "skill_tier": "",
        })

    acc.emphasis = ""
    acc.enrichment = None
    acc.ta_result = None
    if acc.enrich_input.entities or acc.enrich_input.actions:
        have_enrich = bool(acc.enrich_input.entities)
        have_ta = bool(acc.enrich_input.actions)
        steps = []
        if have_enrich:
            steps.append(("enrich",
                lambda: tools._enrich(acc.enrich_input.entities, ctx.raw),
                False, 2))
        else:
            steps.append(("enrich",
                lambda: {"results": {}, "reasoning": "", "emphasis_hint": ""},
                False, 0))
        if have_ta:
            steps.append(("time_agent",
                lambda: tools._run_time_agent(acc.enrich_input.actions, ctx.raw),
                False, 2))
        else:
            steps.append(("time_agent",
                lambda: {"time_delta": 0, "narrative_hint": ""},
                False, 0))
        parallel_results = tools.turn_monitor.execute_parallel(steps)
        acc.enrichment = parallel_results.get("enrich")
        acc.ta_result = parallel_results.get("time_agent")

    # Step 3.5: Collect enrich + TA results
    # Scan for endings BEFORE curate/narrate
    acc.ending_result = tools._scan_ending(acc.all_outcomes, ctx.author)

    acc.enriched_summary = ""
    if acc.enrichment:
        acc.emphasis = acc.enrichment.get("emphasis_hint", "")
        results = acc.enrichment.get("results", "")
        if isinstance(results, str):
            acc.enriched_summary = results
    if acc.ta_result:
        if acc.ta_result.get("time_delta", 0) > 0:
            # 走 world.advance_time 三合一入口(T7):时钟 + MP 恢复 + timed 过期清除
            tools.world.advance_time(acc.ta_result["time_delta"])
        narrative = (acc.ta_result.get("narrative_hint", "") or "")
        if narrative:
            tools.world.clock.time_context = narrative

    # TimePressure comms dispatch (at most 1 per turn)
    tp = ctx.author.time_pressure if ctx.author else None
    if tp and tools.world.clock.game_time - tools._last_comms_time >= tools.world.comms_interval:
        tools._last_comms_time = tools.world.clock.game_time
        try:
            recent = tools.world.memory.raw_history[-5:] if tools.world.memory.raw_history else []
            packet = TimeCommsPacket(
                game_time=tools.world.clock.game_time,
                day=tools.world.clock.day,
                time_of_day=tools.world.clock.time_of_day,
                current_scene=tools.world.current_location,
                player_actions="; ".join(
                    (r.get("user_input", "") or "")[:60] for r in recent[-3:]
                ),
                world_state=f"场景:{tools.world.current_location}, "
                           f"NPC:{tools.world.npcs.all_names()[:3]}",
            )
            tp_result = ctx.author.assess_time_pressure(packet)
            if tp_result.get("should_press") and tp_result.get("signal"):
                acc.all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="time_pressure"),
                    success=True,
                    message=f"【{tp.get('name', '时间压力')}】{tp_result.get('signal', '')}",
                    entity_id="TIME_PRESS",
                    entity_type="time_pressure",
                ))
        except Exception:
            pass  # Comms is best-effort
