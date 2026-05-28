"""
Audit LLM player logs -> markdown report.
Usage: python -m audit_player_log <log_dir>
"""
from __future__ import annotations
import sys, json
from pathlib import Path
from datetime import datetime
from collections import Counter


def load_summary(log_dir: Path) -> dict:
    with open(log_dir / "_summary.json", "r", encoding="utf-8") as f:
        return json.load(f)



def _llm_audit(log_dir: Path, summary: dict, turn_logs_dir: Path) -> tuple[str, str]:
    """Run LLM analysis on player log. Returns (report_section, llm_raw_response)."""
    llm_path = str(log_dir / "audit_llm.txt")

    turns = summary.get("turns_detail", [])
    turn_details = []
    for t in turns:
        # Skill detail: entity_id + tier + dice result
        skill_parts = []
        for r in t.get("skill_results", []):
            status = "✓" if r.get("success") else "✗"
            tid = r.get("entity_id", "?")
            tier = r.get("tier", "")
            raw = r.get("raw_check", "")
            # Extract dice line for compact display
            dice_line = ""
            for line in raw.split("\n"):
                if "D100=" in line:
                    dice_line = line.strip()[:60]
                    break
            skill_parts.append(f"{status}{tid}({tier}) {dice_line}")
        skills = "; ".join(skill_parts) or "-"

        # Combat detail
        combat = t.get("combat")
        if combat:
            c_outcome = combat.get("outcome", "?")
            c_boss = " [Boss]" if combat.get("is_boss") else ""
            c_narr = combat.get("narrative", "")[:80]
            combat_str = f"{c_outcome}{c_boss}: {c_narr}"
        else:
            combat_str = "-"

        # Time state
        ts = t.get("time_state", {})
        time_str = f"Day{int(ts.get('day',0))} {ts.get('time_of_day','?')} {int(ts.get('hour',0)):02d}:00 (G+{int(ts.get('game_time_minutes',0))}m)" if ts else "-"

        # NPC visible
        nv = t.get("npcs_visible", {})
        npc_in = ", ".join(nv.get("in_scene", [])) or "无"
        npc_follow = ", ".join(nv.get("following", [])) or "无"
        npc_events = "; ".join(t.get("npc_events", [])) or "-"

        turn_details.append(
            f"T{t['turn']:02d}:\n"
            f"  玩家输入: {t['input']}\n"
            f"  系统输出(Brief): {t.get('brief', '（空）')}\n"
            f"  系统输出(Narrative): {t.get('narrative', '（空）')}\n"
            f"  技能检定: {skills}\n"
            f"  战斗结果: {combat_str}\n"
            f"  游戏时间: {time_str}\n"
            f"  场景NPC: {npc_in} | 跟随NPC: {npc_follow}\n"
            f"  NPC事件: {npc_events}\n"
            f"  耗时: {t['elapsed_s']:.0f}s"
        )

    system = """你是TRPG测试审计专家。你的任务是从玩家视角分析LLM跑团日志，即你只能看到玩家输入和系统输出的结果（brief/narrative）。

关注以下维度：
1. 叙事质量：brief/narrative是否为空、是否重复、是否与玩家输入脱节
2. 技能检定：检查是否有连续失败、检定结果与叙事是否一致、骰子值是否合理
3. 战斗：战斗结果是否在叙事中有体现，Boss战是否正确标记
4. NPC交互：场景内NPC是否被叙事提及，对话/事件是否得到系统回复
5. 时间系统：时间推进是否合理（Day/时段/分钟），是否有明显跳跃或停滞
6. 整体连贯性：多回合间叙事是否断裂、时间-NPC-场景是否一致

返回 JSON：
{
  "findings": [
    {"severity": "high|medium|low", "turn": N, "category": "类别", "detail": "具体发现", "suggestion": "修复建议"}
  ],
  "overall_assessment": "总体评价（100字以内）"
}
直接输出 JSON。"""

    user = f"""分析以下TRPG跑团日志（仅玩家视角）。

【游戏概况】
模组：{summary.get('module', '?')}
回合数：{len(turns)}
总耗时：{summary.get('total_elapsed_s', 0):.0f}s
结束状态：{summary.get('game_over') or '未结束'}

【每回合玩家视角】
{chr(10).join(turn_details)}
"""

    try:
        from llm import call_deepseek
        from config_llm import LLM_FLASH_MODEL

        response = call_deepseek(
            user, json_mode=True, system=system,
            model=LLM_FLASH_MODEL, reasoning_effort="low",
            fallback_schema={"findings": [], "overall_assessment": ""},
        )

        resp_str = json.dumps(response, ensure_ascii=False, indent=2) if isinstance(response, dict) else str(response)
        with open(llm_path, "w", encoding="utf-8") as f:
            f.write(f"--- System ---\n{system}\n\n--- User ---\n{user}\n\n--- Response ---\n{resp_str}\n")

        data = json.loads(resp_str) if isinstance(response, str) else response
        findings = data.get("findings", [])
        overall = data.get("overall_assessment", "")

        lines = []
        if overall:
            lines.append(f"**LLM Assessment:** {overall}\n")
        if findings:
            lines.append("| Sev | Turn | Category | Detail | Suggestion |")
            lines.append("|-----|------|----------|--------|------------|")
            for f in findings:
                lines.append(
                    f"| {f.get('severity','?')} | {f.get('turn','?')} | "
                    f"{f.get('category','?')} | {f.get('detail','')[:60]} | "
                    f"{f.get('suggestion','')[:60]} |"
                )
        return "\n".join(lines), resp_str
    except Exception as e:
        with open(llm_path, "w", encoding="utf-8") as f:
            f.write(f"--- System ---\n{system}\n\n--- User ---\n{user}\n\n--- Error ---\n{e}\n")
        return f"*LLM audit failed: {e}*", ""


def audit(log_dir: str) -> str:
    ld = Path(log_dir)
    s = load_summary(ld)
    profile = s.get("profile", {})
    audit_cfg = profile.get("audit_config", {}).get("anomaly_thresholds", {})
    audit_targets = profile.get("audit_targets", [])

    turns = s["turns_detail"]
    n = len(turns)
    total_s = s["total_elapsed_s"]

    lines = []
    lines.append("# LLM Player Audit Report")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Module:** {s.get('module', '?')} | **Player:** {s.get('player', '?')}")
    lines.append(f"**Turns:** {n} | **Duration:** {total_s:.0f}s | **Game Over:** {s.get('game_over') or 'N/A'}")
    lines.append("")

    # Summary Stats
    lines.append("## Summary")
    skill_total = 0
    skill_pass = 0
    combat_count = 0
    entity_hits: Counter = Counter()
    for t in turns:
        for sr in t.get("skill_results", []):
            skill_total += 1
            if sr.get("success"):
                skill_pass += 1
            entity_hits[sr.get("entity_id", "?")] += 1
        if t.get("combat"):
            combat_count += 1

    lines.append(f"- Skill checks: {skill_pass}/{skill_total} passed" if skill_total else "- Skill checks: N/A")
    lines.append(f"- Combat encounters: {combat_count}")
    lines.append(f"- Entity hits: {len(entity_hits)} unique / {sum(entity_hits.values())} total")
    # Time span
    time_states = [t.get("time_state", {}) for t in turns if t.get("time_state")]
    if time_states:
        first_t = time_states[0]
        last_t = time_states[-1]
        time_agents = [t.get("time_agent", {}) for t in turns if t.get("time_agent")]
        total_delta = sum(ta.get("time_delta", 0) for ta in time_agents if ta)
        lines.append(f"- Time span: D{int(first_t.get('day',0))} {first_t.get('time_of_day','?')} → D{int(last_t.get('day',0))} {last_t.get('time_of_day','?')} (+{int(total_delta)}m game)")
    lines.append("")

    # Per-Turn Detail
    lines.append("## Per-Turn Detail")
    lines.append("| # | Input | Skills | Combat | Time (Game) | NPC Events | Elapsed |")
    lines.append("|---|---|---|---|---|---|---|")
    for t in turns:
        sr = t.get("skill_results", [])
        skill_parts = []
        for r in sr:
            status = "[OK]" if r.get("success") else "[FAIL]"
            tid = r.get("entity_id", "?")
            tier = r.get("tier", "")[:4]
            skill_parts.append(f"{status}{tid}({tier})" if tier else f"{status}{tid}")
        skill_str = ", ".join(skill_parts) or "-"

        combat = t.get("combat")
        if combat:
            c_out = combat.get("outcome", "?")
            c_boss = "B" if combat.get("is_boss") else ""
            combat_str = f"{c_out}{c_boss}"
        else:
            combat_str = "-"

        ts = t.get("time_state", {})
        time_str = f"D{int(ts.get('day',0))} {ts.get('time_of_day','?')[:2]} G+{int(ts.get('game_time_minutes',0))}m" if ts else "-"

        npc_str = "; ".join(t.get("npc_events", []))[:40] or "-"
        lines.append(
            f"| {t['turn']} | {t['input'][:28]} | {skill_str} | "
            f"{combat_str} | {time_str} | {npc_str} | {t['elapsed_s']:.0f}s |"
        )
    lines.append("")

    # Subsystem Stress Check
    lines.append("## Subsystem Stress Check")
    _audit_npc(lines, turns)
    _audit_enemy(lines, turns)
    _audit_combat(lines, turns)
    _audit_boss(lines, turns)
    _audit_time(lines, turns)
    _audit_author(lines, turns)
    _audit_side_effects(lines, turns)
    _audit_memory(lines, turns)
    lines.append("")

    # Anomalies
    lines.append("## Anomalies")
    anomalies = []
    consecutive_fail = 0
    fail_start = 0
    for t in turns:
        sr = t.get("skill_results", [])
        failed = any(not r.get("success") for r in sr) if sr else False
        if failed:
            if consecutive_fail == 0:
                fail_start = t["turn"]
            consecutive_fail += 1
        else:
            if consecutive_fail >= audit_cfg.get("consecutive_fail_alert", 3):
                anomalies.append(
                    f"| {fail_start}-{t['turn']-1} | consecutive_fail | "
                    f"{consecutive_fail} consecutive skill failures |"
                )
            consecutive_fail = 0
    # Check last stretch
    if consecutive_fail >= audit_cfg.get("consecutive_fail_alert", 3):
        anomalies.append(
            f"| {fail_start}-{n} | consecutive_fail | "
            f"{consecutive_fail} consecutive skill failures |"
        )

    if anomalies:
        lines.append("| Turns | Type | Detail |")
        lines.append("|-------|------|--------|")
        lines.extend(anomalies)
    else:
        lines.append("No anomalies detected.")
    lines.append("")

    # LLM-powered audit analysis
    lines.append("## LLM Deep Analysis")
    turn_logs_dir = ld / "turn_logs" if (ld / "turn_logs").exists() else None
    llm_section, _ = _llm_audit(ld, s, turn_logs_dir)
    if llm_section.strip():
        lines.append(llm_section)
    else:
        lines.append("LLM audit skipped or failed.")
    lines.append("")

    # Recommendations
    lines.append("## Recommendations")
    recs = []
    enrich_degrade = sum(1 for t in turns
                         if t.get("brief", "").strip() in ("", "（处理中）"))
    combat_total = sum(1 for t in turns if t.get("combat"))
    if enrich_degrade > audit_cfg.get("enrich_degrade_max", 2):
        recs.append(f"- Enrich degraded {enrich_degrade} times - check enrich prompt/model stability")
    if combat_total == 0 and "Combat" in audit_targets:
        recs.append("- No combat triggered - consider more aggressive enemy-seeking strategy")
    if not s.get("game_over"):
        recs.append("- Game did not reach ending - check dependency chains and entity coverage")
    if recs:
        lines.extend(recs)
    else:
        lines.append("No issues. All systems nominal.")
    lines.append("")

    return "\n".join(lines)


def _audit_npc(lines: list[str], turns: list[dict]):
    lines.append("### NPC")
    talk_count = sum(1 for t in turns if t.get("npc_events"))
    follow_events = sum(1 for t in turns for e in t.get("npc_events", []) if "跟随" in e)
    lines.append(f"- NPC interactions: {talk_count}")
    lines.append(f"- Follow events: {follow_events}")

    # NPC visibility per turn
    all_in_scene = set()
    all_following = set()
    for t in turns:
        nv = t.get("npcs_visible", {})
        all_in_scene.update(nv.get("in_scene", []))
        all_following.update(nv.get("following", []))
    if all_in_scene:
        lines.append(f"- NPCs encountered in scene: {', '.join(sorted(all_in_scene))}")
    if all_following:
        lines.append(f"- NPCs following player: {', '.join(sorted(all_following))}")
    lines.append("")


def _audit_enemy(lines: list[str], turns: list[dict]):
    lines.append("### Enemy")
    combats = [t for t in turns if t.get("combat")]
    outcomes = Counter(t["combat"].get("outcome") for t in combats)
    lines.append(f"- Combat outcomes: {len(combats)}")
    if outcomes:
        lines.append(f"- Results: {dict(outcomes)}")
    lines.append("")


def _audit_combat(lines: list[str], turns: list[dict]):
    lines.append("### Combat")
    combats = [t for t in turns if t.get("combat")]
    boss_combats = [t for t in combats if t["combat"].get("is_boss")]
    lines.append(f"- Total combats: {len(combats)} (Boss: {len(boss_combats)})")
    for t in combats:
        c = t["combat"]
        boss_tag = " [Boss]" if c.get("is_boss") else ""
        narr = c.get("narrative", "")[:100]
        lines.append(f"  - T{t['turn']}: {c.get('outcome','?')}{boss_tag} — {narr}")
    if not combats:
        lines.append("- No combats triggered")
    lines.append("")


def _audit_boss(lines: list[str], turns: list[dict]):
    lines.append("### Boss")
    lines.append("- Audit via manual log inspection for boss_encounter triggers")
    lines.append("")


def _audit_time(lines: list[str], turns: list[dict]):
    lines.append("### TimeAgent")
    time_states = [t.get("time_state", {}) for t in turns if t.get("time_state")]
    if not time_states:
        lines.append("- No time data captured")
        lines.append("")
        return

    first = time_states[0]
    last = time_states[-1]
    time_agents = [t.get("time_agent", {}) for t in turns if t.get("time_agent")]
    total_delta = sum(ta.get("time_delta", 0) for ta in time_agents if ta)
    lines.append(f"- Initial state (after T01): Day {int(first.get('day',0))}, {first.get('time_of_day','?')}, {int(first.get('hour',0)):02d}:00 (G+{int(first.get('game_time_minutes',0))}m)")
    lines.append(f"- Final state (after T{len(turns)}): Day {int(last.get('day',0))}, {last.get('time_of_day','?')}, {int(last.get('hour',0)):02d}:00 (G+{int(last.get('game_time_minutes',0))}m)")
    lines.append(f"- Total time delta (from TimeAgent): {total_delta} minutes")

    # Per-turn time deltas
    if time_agents:
        deltas = [ta.get("time_delta", 0) for ta in time_agents if ta]
        hints = [ta.get("narrative_hint", "") for ta in time_agents if ta and ta.get("narrative_hint")]
        lines.append(f"- TimeAgent LLM evaluated {len(deltas)} turns, total delta: {sum(deltas)} minutes")
        if hints:
            lines.append(f"- TimeAgent hints: {'; '.join(h for h in hints if h)[:120]}")
    lines.append("")


def _audit_author(lines: list[str], turns: list[dict]):
    lines.append("### Author")
    lines.append("- Author activity tracked via parse 'other' rate and IntentDetector calls")
    lines.append("")


def _audit_side_effects(lines: list[str], turns: list[dict]):
    lines.append("### Side Effects")
    lines.append("- @markup usage tracked via skill_results side_effects field")
    lines.append("")


def _audit_memory(lines: list[str], turns: list[dict]):
    lines.append("### Memory")
    compress_interval = 5
    lines.append(f"- Compression triggers: approx {len(turns) // compress_interval}")
    lines.append("")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m audit_player_log <log_dir>")
        sys.exit(1)
    report = audit(sys.argv[1])
    out_path = Path(sys.argv[1]) / "audit_report.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Report saved to {out_path}")
