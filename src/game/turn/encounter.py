"""C 遭遇：敌战入口 + Boss 接入。EncounterProvider 有序链，plugin 接入点。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol
import json

from config_llm import LLM_FLASH_MODEL, RE_COMBAT_ENTRY
from ..messages import (
    ActionIntent, ActionOutcome, CombatEntryCheck, CombatInit,
)


@dataclass
class EncounterContribution:
    """单个 provider 的产出。"""
    combat_init: Any = None
    standoff: dict | None = None
    outcomes: list = field(default_factory=list)
    enrich_entities: list[dict] = field(default_factory=list)
    boss_accounting: tuple | None = None  # (boss_id, boss_enemy)


class EncounterProvider(Protocol):
    def probe(self, ctx, acc, tools) -> EncounterContribution | None: ...


class EnemyCombatProvider:
    def probe(self, ctx, acc, tools) -> EncounterContribution | None:
        # Combat entry 必须在 enrich 之前，战斗信息才能注入 enrichment
        enemy_ctx = None
        if tools.world and tools.world.enemies and not tools.world.enemies._combat_active:
            enemy_ctx = tools.world.enemies.get_combat_context(
                tools.world.current_location, tools.world.graph
            )
        if not enemy_ctx:
            return None
        outcomes_summary = "\n".join(
            f"[{o.entity_type}] {o.message}" for o in acc.all_outcomes
        )
        from prompts import build_combat_entry_prompt
        from ..agents import keeper as keeper_mod
        combat_prompt = build_combat_entry_prompt(
            player_input=ctx.raw,
            outcomes_summary=outcomes_summary,
            enemy_context=enemy_ctx,
            current_scene=tools.world.current_location,
        )
        try:
            # 走 keeper.call_deepseek：helpers/e2e 既有 monkeypatch 目标
            raw_result = keeper_mod.call_deepseek(
                combat_prompt,
                json_mode=True,
                model=LLM_FLASH_MODEL,
                reasoning_effort=RE_COMBAT_ENTRY,
                _label="combat_entry",
                system="你是 COC 7th KP 助理，负责根据玩家行为和场景内敌人习性判断是否进入回合制战斗。"
                       "\n\n输出 JSON：{\"enter_combat\": true/false, \"enemy_instance_ids\": [...], \"reasoning\": \"简述理由\"}。直接输出 JSON。",
                fallback_schema={"enter_combat": False, "enemy_instance_ids": [], "reasoning": ""},
            )
            result = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
            acc.combat_entry = CombatEntryCheck(
                enter_combat=result.get("enter_combat", False),
                enemy_instance_ids=result.get("enemy_instance_ids", []),
                reasoning=result.get("reasoning", ""),
            )
        except Exception:
            acc.combat_entry = None
            return None

        if not acc.combat_entry.enter_combat:
            return None

        # 直接从场景收集所有敌对敌人，不依赖 LLM 返回的 ID 列表
        scene_enemies = tools.world.enemies.get_active_in_scene(
            tools.world.current_location
        ) if tools.world.enemies else []
        combat_candidates = [
            inst for inst in scene_enemies
            if inst.status not in ("dead", "defeated")
        ]
        avoidable_by_ref: dict[str, list[str]] = {}
        hostile_iids: list[str] = []
        for inst in combat_candidates:
            if "avoidable" in inst.flags:
                avoidable_by_ref.setdefault(inst.enemy_ref, []).append(inst.instance_id)
            else:
                hostile_iids.append(inst.instance_id)

        contribution = EncounterContribution()
        if avoidable_by_ref:
            first_ref = next(iter(avoidable_by_ref))
            standoff_prompt = {
                "groups": {ref: iids for ref, iids in avoidable_by_ref.items()},
                "current_group": first_ref,
                "hostile_iids": hostile_iids,
                "all_enemy_iids": [inst.instance_id for inst in combat_candidates],
                "reasoning": acc.combat_entry.reasoning,
            }
            tools._standoff_pending = standoff_prompt  # 播种，供 continue_standoff 消费
            standoff_msg = f"你还有最后一次机会避免与{first_ref}的战斗——你要怎么做？"
            contribution.standoff = standoff_prompt
            contribution.outcomes.append(ActionOutcome(
                intent=ActionIntent(action="standoff"),
                success=True,
                message=standoff_msg,
                entity_id="STANDOFF",
                entity_type="standoff",
            ))
            contribution.enrich_entities.append({
                "entity_type": "standoff",
                "id": "STANDOFF",
                "name": f"对峙：{first_ref}",
                "result": standoff_msg,
                "success": True,
                "skill_tier": "",
            })
            return contribution
        elif hostile_iids:
            enemies = [tools.world.enemies.get_by_id(iid)
                      for iid in hostile_iids
                      if tools.world.enemies and tools.world.enemies.get_by_id(iid)]
            if enemies and tools.world.enemies:
                tools.world.enemies.enter_combat(hostile_iids)
            enemy_names = ", ".join(
                getattr(e, 'enemy_ref', getattr(e, 'name', '未知')) for e in enemies
            )
            combat_msg = f"⚔ 你与{enemy_names}进入了战斗！"
            contribution.enrich_entities.append({
                "entity_type": "combat",
                "id": "COMBAT",
                "name": f"战斗：{enemy_names}",
                "result": combat_msg,
                "success": True,
                "skill_tier": "",
            })
            contribution.combat_init = CombatInit(
                enemies=enemies,
                player=tools.world.player,
                scene=tools.world.current_location,
                initiative_context=acc.combat_entry.reasoning,
                player_action="",
                player_targets=[],
                player_extra="",
            )
            tools._last_player_input = ctx.raw  # stored for combat completion replay
            return contribution
        return None


class SceneBossProvider:
    def probe(self, ctx, acc, tools) -> EncounterContribution | None:
        # scene-bound at/interaction：必须在 enrich 之前注入；开战记账延后到 E curate 成功后——
        # freeze 时 Boss 不被消耗，下回合可重触发（spec §4.1）。
        boss_combat_init = None
        boss_engaged_id = None
        enrich_entities: list[dict] = []
        if tools.world.bosses:
            for engage in ("at", "interaction"):
                candidates = tools.world.bosses.check_by_engage_type(
                    engage, scene=tools.world.current_location)
                for boss_entity in candidates:
                    boss_id = boss_entity.get("id", boss_entity.get("boss_ref", "unknown"))
                    if tools.world.is_entity_completed(boss_id):
                        continue
                    if tools.world.bosses.has_spawned(boss_id):
                        continue
                    if tools._check_boss_requirements(boss_entity, ctx.turn_input.raw_text):
                        try:
                            boss_combat_init = tools.world.bosses.build_combat_init(
                                boss_entity, tools.world.player, tools.world.current_location,
                                enemy_manager=tools.world.enemies)
                        except KeyError as e:
                            tools._warnings.append(f"Boss 遭遇 {boss_id} 装载失败：{e}")
                            continue
                        boss_engaged_id = boss_id
                        boss_name = boss_entity.get("name", boss_entity.get("boss_ref", boss_id))
                        boss_msg = f"⚠ {boss_name}发现了你！退路已断，战斗一触即发——"
                        enrich_entities.append({
                            "entity_type": "boss_encounter",
                            "id": f"BOSS_{boss_id}",
                            "name": f"Boss遭遇：{boss_name}",
                            "result": boss_msg,
                            "success": True,
                            "skill_tier": "",
                        })
                        break
                if boss_combat_init:
                    break
        if not boss_combat_init:
            return None

        contribution = EncounterContribution(enrich_entities=enrich_entities)
        boss_enemy = boss_combat_init.enemies[0] if boss_combat_init.enemies else None
        acc.boss_accounting = (boss_engaged_id, boss_enemy)
        contribution.boss_accounting = acc.boss_accounting
        if boss_enemy:
            if acc.combat_init_result and acc.combat_init_result.enemies:
                existing_iids = {e.instance_id for e in acc.combat_init_result.enemies}
                if boss_enemy.instance_id not in existing_iids:
                    acc.combat_init_result.enemies.append(boss_enemy)
                tools._last_player_input = ctx.raw  # stored for combat completion replay
                contribution.combat_init = acc.combat_init_result
            else:
                acc.combat_init_result = boss_combat_init
                tools._last_player_input = ctx.raw  # stored for combat completion replay
                contribution.combat_init = boss_combat_init
        return contribution


_PROVIDERS = (EnemyCombatProvider(), SceneBossProvider())


def phase_c_encounter(ctx, acc, tools) -> None:
    for provider in _PROVIDERS:
        contribution = provider.probe(ctx, acc, tools)
        if contribution is None:
            continue
        acc.all_outcomes.extend(contribution.outcomes)
        acc.enrich_input.entities.extend(contribution.enrich_entities)
        if contribution.combat_init is not None:
            acc.combat_init_result = contribution.combat_init
        if contribution.standoff is not None:
            acc.standoff_prompt = contribution.standoff
        if contribution.boss_accounting is not None:
            acc.boss_accounting = contribution.boss_accounting
    # 吞对峙①：F3 Boss 强制战吞掉对峙
    if acc.boss_accounting and acc.standoff_prompt:
        acc.standoff_prompt = tools._devour_standoff_for_boss(
            acc.standoff_prompt, acc.combat_init_result, acc.all_outcomes,
            acc.enrich_input)
