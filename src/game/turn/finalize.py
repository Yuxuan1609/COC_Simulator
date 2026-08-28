"""E 收尾：落账 → ending② → warnings → event型Boss → 吞对峙② → curate → Boss记账 → assemble。"""
from __future__ import annotations

from config_llm import LLM_FLASH_MODEL
from ..messages import (
    ActionIntent, ActionOutcome,
    TurnStatus, TurnResult, PendingInteraction, EndingInfo, TurnDiagnostics,
)


def phase_e_finalize(ctx, acc, tools) -> None:
    """结果写 acc.result(TurnResult)。curate 的 TurnFrozenError 冒泡（runner 兜底）。"""
    # ── Apply all deferred side effects + move (Author check passed) ──
    tools._apply_pending()

    # Ending detection — already scanned pre-enrich; if not found, scan post-enrich messages as fallback
    if not acc.ending_result:
        acc.ending_result = tools._scan_ending(acc.all_outcomes, ctx.author)

    # Inject LLM error warnings as player-visible outcomes
    for w in tools._warnings:
        acc.all_outcomes.append(ActionOutcome(
            intent=ActionIntent(action="other"), success=True,
            message=f"⚠ {w}"))

    # Boss "event" check: after judge completes
    # Don't return early — let curate run so enrich/narrator output is preserved
    if tools.world.bosses:
        event_bosses = tools.world.bosses.check_by_engage_type("event")
        for boss_entity in event_bosses:
            boss_id = boss_entity.get("id", boss_entity.get("boss_ref", "unknown"))
            if tools.world.is_entity_completed(boss_id):
                continue
            if tools.world.bosses.has_spawned(boss_id):
                continue
            if tools._check_boss_requirements(boss_entity, ctx.turn_input.raw_text):
                boss_init = tools.world.bosses.build_combat_init(boss_entity, tools.world.player, tools.world.current_location)
                tools.world.bosses.set_active(boss_id)
                tools.world.bosses.mark_spawned(boss_id)
                boss_enemy = boss_init.enemies[0] if boss_init.enemies else None
                if boss_enemy and tools.world.enemies:
                    tools.world.enemies.register(boss_enemy)
                    tools.world.enemies.add_to_combat(boss_enemy.instance_id)
                    tools._last_player_input = ctx.raw  # stored for combat completion replay
                    if acc.combat_init_result and acc.combat_init_result.enemies:
                        # Merge into existing combat — same as "at"/"interaction" path
                        acc.combat_init_result.enemies.append(boss_enemy)
                    else:
                        acc.combat_init_result = boss_init
                else:
                    acc.combat_init_result = boss_init
                break  # only handle one boss per turn; curate + return below

    # F3（event 通路）：event 型 Boss 开战同样吞掉本回合对峙。
    # 此时 enrich 已消费 acc.enrich_input，仍需清 acc.all_outcomes（curate 用）与
    # standoff_prompt（PendingInteraction 用），并把 avoidable 敌人拖入战斗。
    if acc.standoff_prompt and acc.combat_init_result is not None:
        acc.standoff_prompt = tools._devour_standoff_for_boss(
            acc.standoff_prompt, acc.combat_init_result, acc.all_outcomes, None)

    # Step 5: Curate — TurnFrozenError 冒泡，由 TurnRunner 兜底
    ambient = [o.message for o in acc.all_outcomes if o.entity_type == "auto_trigger"]
    acc.brief = tools.turn_monitor.execute_step(
        "curate",
        lambda: tools.curator.assemble(acc.all_outcomes, ambient, acc.emphasis, acc.enriched_summary),
        is_critical=True,
    )

    # Step 6: Memory (now handled in game_loop after narrator.narrate)
    if tools.world.memory.should_compress():
        from threading import Thread
        from ..agents import keeper as keeper_mod
        t = Thread(target=tools.world.memory.compress, args=(
            lambda p: keeper_mod.call_deepseek(p, json_mode=False, model=LLM_FLASH_MODEL,
                                    system="你是一个擅长总结和提炼信息的助手。请将游戏历史压缩为简洁摘要，"
                                           "保留关键事件、重要细节和当前状态，去除冗余对话。"),
        ), daemon=True)
        t.start()

    # Inject weapon offer prompt if direct grant is pending
    if tools._weapon_offer_msg:
        acc.brief.action_outcomes.append(ActionOutcome(
            intent=ActionIntent(action="other"), success=True,
            message=tools._weapon_offer_msg,
            entity_id="WEAPON_OFFER", entity_type="information",
        ))
        tools._weapon_offer_msg = ""

    tools._last_outcomes = list(acc.all_outcomes)  # store for combat resolution replay

    standoff_pending = None
    if acc.standoff_prompt:
        standoff_pending = PendingInteraction(
            kind="standoff",
            question=f"你还有最后一次机会避免与{acc.standoff_prompt['current_group']}的战斗——你要怎么做？",
            interaction_id="standoff",
        )

    offer_pending = None
    if not standoff_pending and tools._weapon_offer:
        offer_names = "、".join(w["weapon_ref"] for w in tools._weapon_offer)
        offer_pending = PendingInteraction(
            kind="weapon_offer",
            question=f"是否拾取{offer_names}？请只回复「是」或「否」；直接说「捡起{offer_names}」也可以。",
            interaction_id="weapon_offer",
        )

    # Boss 开战记账（延后至此：curate 成功后才记账；freeze 时 Boss 不被消耗，下回合可重触发；spec §4.1）
    if acc.boss_accounting and acc.combat_init_result:
        boss_engaged_id, boss_enemy = acc.boss_accounting
        if boss_enemy:
            tools.world.enemies.register(boss_enemy)
            tools.world.enemies.add_to_combat(boss_enemy.instance_id)
            tools.world.bosses.set_active(boss_engaged_id)
            tools.world.bosses.mark_spawned(boss_engaged_id)

    acc.result = TurnResult(
        status=TurnStatus.COMPLETED,
        brief=acc.brief,
        pending_interaction=standoff_pending or offer_pending,
        combat_init=acc.combat_init_result,
        ending=EndingInfo(**acc.ending_result) if acc.ending_result else None,
        npc_events=list(tools._npc_events),
        warnings=list(tools._warnings),
        diagnostics=TurnDiagnostics(
            combat_entry=acc.combat_entry,
            time_agent=acc.ta_result,
            enrich_raw=acc.enrichment,
            pre_parse=acc.pre_result,
        ),
    )
