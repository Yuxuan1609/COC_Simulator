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
        if t.get("combat_outcome"):
            combat_count += 1

    lines.append(f"- Skill checks: {skill_pass}/{skill_total} passed" if skill_total else "- Skill checks: N/A")
    lines.append(f"- Combat encounters: {combat_count}")
    lines.append(f"- Entity hits: {len(entity_hits)} unique / {sum(entity_hits.values())} total")
    lines.append("")

    # Per-Turn Detail
    lines.append("## Per-Turn Detail")
    lines.append("| # | Input | Skills | Combat | NPC Events | Elapsed |")
    lines.append("|---|---|---|---|---|---|")
    for t in turns:
        sr = t.get("skill_results", [])
        skill_str = ", ".join(
            f"{'[OK]' if r.get('success') else '[FAIL]'}{r.get('entity_id','?')}"
            for r in sr
        ) or "-"
        combat_str = t.get("combat_outcome") or "-"
        npc_str = "; ".join(t.get("npc_events", []))[:40] or "-"
        lines.append(
            f"| {t['turn']} | {t['input'][:30]} | {skill_str} | "
            f"{combat_str} | {npc_str} | {t['elapsed_s']:.0f}s |"
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

    # Recommendations
    lines.append("## Recommendations")
    recs = []
    enrich_degrade = sum(1 for t in turns
                         if t.get("brief", "").strip() in ("", "（处理中）"))
    combat_total = sum(1 for t in turns if t.get("combat_outcome"))
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
    lines.append("")


def _audit_enemy(lines: list[str], turns: list[dict]):
    lines.append("### Enemy")
    combats = sum(1 for t in turns if t.get("combat_outcome"))
    lines.append(f"- Combat outcomes: {combats}")
    lines.append("")


def _audit_combat(lines: list[str], turns: list[dict]):
    lines.append("### Combat")
    combats = [t for t in turns if t.get("combat_outcome")]
    outcomes = Counter(t.get("combat_outcome") for t in combats)
    lines.append(f"- Total combats: {len(combats)}")
    if outcomes:
        lines.append(f"- Outcomes: {dict(outcomes)}")
    lines.append("")


def _audit_boss(lines: list[str], turns: list[dict]):
    lines.append("### Boss")
    lines.append("- Audit via manual log inspection for boss_encounter triggers")
    lines.append("")


def _audit_time(lines: list[str], turns: list[dict]):
    lines.append("### TimeAgent")
    lines.append(f"- Total turns: {len(turns)} (time advance tracked per-turn in game logs)")
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
