"""A 理解：入口守卫 → LUCK → parse → NPC 对话 → use 归一 → intent 预发射。"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from config import MAX_ESCALATION_DEPTH
from ..messages import (
    TurnResult, TurnStatus, PendingInteraction, TurnDiagnostics,
)
from .context import Early


def phase_a_understand(ctx, acc, tools) -> Early | None:
    """返回 Early(早退) 或 None(继续)。产出写入 acc / tools 会话态。"""
    ctx.raw = ctx.turn_input.raw_text
    at = ctx.turn_input.action_type

    # 直接拾取通路（R1）：turn_number += 1 之前短路；hidden 点名不推进回合
    hit = tools._detect_direct_pickup(ctx.raw)
    if hit:
        kind, ref, hidden = hit
        if hidden:
            return Early(TurnResult(status=TurnStatus.COMPLETED, text="你没发现这东西。"))
        names = tools._grant_scene_item(kind, ref)
        return Early(TurnResult(status=TurnStatus.COMPLETED, text=f"你拾起了{names}。"))

    if ctx.depth >= MAX_ESCALATION_DEPTH:
        # Guard against infinite recursion — re-execute deterministically
        return Early(tools._process_deterministic_only(ctx.turn_input))
    tools.turn_number += 1
    tools._warnings.clear()
    tools._npc_events.clear()
    tools._pending_side_effects.clear()
    tools._pending_move = None
    tools._standoff_pending = None

    # Inject NPC ATs + interactions before normal parse
    tools._inject_npc_at()

    # U9：LUCK 声明式消耗——「烧/用 N 点幸运」→ spend_luck + pending_luck_bonus
    # 原子绑定：仅扣减成功时才置加值，失败只记 warning
    _luck_m = re.search(r"(?:烧|燃烧|用|消耗)\s*(\d{1,2})\s*点?\s*(?:幸运|运气|LUCK|luck)",
                        ctx.raw)
    if _luck_m and tools.world.player:
        _n = int(_luck_m.group(1))
        _ok, _msg = tools.world.player.spend_luck(_n)
        if _ok:
            tools.world.player.pending_luck_bonus = _n
        tools._warnings.append(f"LUCK 消耗：{_msg}")

    # ── Pre-parse shortcut: move/search bypass LLM parse entirely ──
    pre_result = None
    # UseParser 确定性短路（统一资源层）：使用谓词+素材名命中 -> use 动作，跳过 LLM parse
    use_hit = None
    if tools.use_parser:
        use_hit = tools.use_parser.resolve(ctx.raw, tools._material_catalogs())
    if use_hit:
        parse_result = [{"type": "use", "material": use_hit}]
    elif at == "move":
        target = (ctx.turn_input.action_target or "").strip()
        if not target:
            return Early(TurnResult(status=TurnStatus.COMPLETED,
                              text="（移动目标未指定。）",
                              npc_events=list(tools._npc_events)))
        exits = tools.world.get_possible_exits()
        valid_targets = {e.target for e in exits}
        if target not in valid_targets:
            return Early(TurnResult(status=TurnStatus.COMPLETED,
                              text=f"（无法移动到「{target}」。）",
                              npc_events=list(tools._npc_events)))
        ctx.raw = f"移动到{target}"
        parse_result = [{"type": "move", "target": target}]
    elif at == "search":
        ctx.raw = "搜索"
        parse_result = [{"type": "search"}]
    else:
        # Step 0: Pre-parse — disambiguation gate
        pre_result = tools.pre_parse.disambiguate(ctx.raw, tools._build_world_brief())
        if pre_result.clarity == "ambiguous":
            return Early(TurnResult(
                status=TurnStatus.SUSPENDED,
                text=pre_result.question,
                pending_interaction=PendingInteraction(
                    kind="clarify", question=pre_result.question,
                    interaction_id="clarify"),
                diagnostics=TurnDiagnostics(pre_parse=pre_result),
            ))
        # Use resolved_text as effective input when cross-turn integration happened
        if pre_result.resolved_text:
            ctx.raw = pre_result.resolved_text

        # Step 1: Parse (LLM) — entity matching + NL requirement evaluation
        parse_result = tools.turn_monitor.execute_step(
            "parse", lambda: tools._parse(ctx.raw), is_critical=True)

    # NPC general conversation: parse returned npc_interact (no matching entity).
    # Generate dialogue via talk_to(), route follow requests, inject into enrich_input.
    # Pure-dialogue turns short-circuit return; mixed turns continue through normal pipeline.
    npc_interact_entries = [e for e in parse_result if e.get("type") == "npc_interact"]
    non_npc_entries = [e for e in parse_result if e.get("type") != "npc_interact"]
    _FOLLOW_KEYWORDS = ("跟我", "跟着", "跟随", "一起走", "加入我", "跟我来", "跟我走",
                       "一起行动", "陪同", "随行", "随我")
    _has_follow_request = lambda txt: any(kw in txt for kw in _FOLLOW_KEYWORDS)

    if npc_interact_entries:
        # talk_to 走 keeper.call_deepseek（测试/helpers 既有 monkeypatch 目标）
        from ..agents import keeper as keeper_mod
        for entry in npc_interact_entries:
            npc_name = entry.get("npc_name", "")
            npc = tools.world.npcs.get(npc_name) if npc_name and tools.world.npcs else None
            if not npc:
                tools._npc_events.append(f"（没有叫「{npc_name}」的 NPC）")
                continue
            if npc.scene != tools.world.current_location:
                tools._npc_events.append(f"（{npc_name} 不在当前场景）")
                continue
            dialogue = tools.world.npcs.talk_to(
                npc_name, ctx.raw,
                lambda prompt, **kw: keeper_mod.call_deepseek(prompt, **kw),
                world=tools.world,
            )
            tools._npc_events.append(f"{npc_name}：{dialogue}")
            acc.enrich_input.entities.append({
                "entity_type": "npc_dialogue",
                "id": f"NPC_{npc_name}",
                "name": f"与{npc_name}对话",
                "result": f"「{dialogue[:120]}」",
                "success": True,
                "skill_tier": "",
            })
            # Detect follow request via keyword match
            if _has_follow_request(ctx.raw):
                ok, reason = tools.world.npcs._check_follow_conditions(npc, tools.world)
                if ok:
                    tools.world.npcs.set_following(npc_name, True)
                    tools._npc_events.append(f"{npc_name} 开始跟随你")
                else:
                    tools._npc_events.append(reason)
        # If ONLY npc_interact, short-circuit — dialogue is the narrative.
        if not non_npc_entries:
            dialogue_text = tools._npc_events[-1] if tools._npc_events else ""
            return Early(TurnResult(status=TurnStatus.COMPLETED,
                              text=dialogue_text,
                              npc_events=list(tools._npc_events)))
        parse_result = non_npc_entries

    # use 条目归一：LLM 粗识别但确定性层未命中 -> LLM 兜底；仍未命中转 other/creative
    _normalized = []
    for e in parse_result:
        if e.get("type") == "use" and not e.get("material"):
            _m = (tools.use_parser.resolve_llm(ctx.raw, tools._material_catalogs())
                  if tools.use_parser else None)
            if _m is not None:
                _normalized.append({"type": "use", "material": _m})
            else:
                _normalized.append({"type": "other", "impact": "creative",
                                    "text": e.get("text") or ctx.raw})
        else:
            _normalized.append(e)
    parse_result = _normalized

    # Launch IntentDetector early if there are creative "other" entries.
    # 门控（flavor 豁免，2026-08-18 spec §1.2 细化）：
    # - other/impact=flavor：永不触发 detector（氛围动作 enrich 消化）
    # - other/impact=creative：仅当帧内无【实质性动作】时升级--
    #   实质性 = interaction/event/move/search/use/NPC 对话（防递归丢帧，硬挡保留）；
    #   仅氛围 auto_trigger 捎带（如 AT_AMBIENT）不算实质覆盖（escalation C/E 修复）
    other_entries = [e for e in parse_result if e.get("type") == "other"]
    other_creative = [e for e in other_entries if e.get("impact") != "flavor"]
    _SUBSTANTIVE_TYPES = ("interaction", "event", "move", "search", "use")
    has_substantive = bool(npc_interact_entries) or any(
        e.get("type") in _SUBSTANTIVE_TYPES for e in parse_result)
    detect_future = None
    executor = None
    if other_creative and ctx.author and not has_substantive:
        other_text = "; ".join(e.get("text", "") for e in other_creative)
        world_snapshot = tools._build_world_snapshot()
        executor = ThreadPoolExecutor(max_workers=1)
        detect_future = executor.submit(
            tools.intent_detector.detect, other_text, world_snapshot
        )

    acc.pre_result = pre_result
    acc.parse_result = parse_result
    acc.npc_interact_entries = npc_interact_entries
    acc.other_entries = other_entries
    acc.detect_future = detect_future
    acc.executor = executor
    return None
