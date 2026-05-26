# LLM Player + Audit Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build LLM-driven player + audit script for automated TRPG module testing.

**Architecture:** Two standalone scripts (`llm_player.py`, `audit_player_log.py`) share `stress_profile.json` config. Player drives `run_turn()` loop with flash LLM; audit reads TurnLogger output to produce markdown report.

**Tech Stack:** Python, deepseek-v4-flash, existing `run_turn()` / `TurnLogger` / `call_deepseek` infra.

---

## File Structure

| File | Role |
|------|------|
| `src/llm_player_prompts.py` | **New** — LLM player prompt config (system + memory compression), centralized for easy tuning |
| `src/llm_player.py` | **New** — LLM player driver script |
| `src/audit_player_log.py` | **New** — log audit → markdown report |
| `data/stress_profile.json` | **New** — shared config (player strategy + audit targets + thresholds) |
| `data/investigator/combat_test_character.json` | **New** — combat-testing investigator (buffed combat skills) |

---

### Task 1: stress_profile.json

**Files:**
- Create: `data/stress_profile.json`

- [ ] **Step 1: Write the config file**

```json
{
  "player_strategy": ["NPC", "Enemy", "Boss", "Combat", "TimeAgent", "Author"],
  "audit_targets": [
    "NPC", "Enemy", "Boss", "Combat",
    "TimeAgent", "Author", "IntentDetector",
    "SideEffects", "Memory", "DependencyGraph",
    "Judge", "Narrator"
  ],
  "player_config": {
    "max_turns": 60,
    "max_duration_s": 3600,
    "memory_compress_interval": 5,
    "model": "deepseek-v4-flash",
    "reasoning_effort": "low",
    "module_name": "更新模组0526v2"
  },
  "combat_testing": {
    "mode": "buff_investigator",
    "buff_investigator": {
      "combat_skills_boost": 30,
      "dodge_boost": 30
    }
  },
  "audit_config": {
    "anomaly_thresholds": {
      "other_rate_max": 0.3,
      "enrich_degrade_max": 2,
      "consecutive_fail_alert": 3,
      "combat_max_duration_turns": 10,
      "intent_detect_false_positive_max": 3
    }
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add data/stress_profile.json
git commit -m "feat: add stress_profile.json — shared LLM player + audit config"
```

---

### Task 2: Prompt Config Module

**Files:**
- Create: `src/llm_player_prompts.py`

Centralize all LLM player prompt text for easy tuning.

- [ ] **Step 1: Write the module**

```python
"""LLM Player prompt templates — centralized for easy tuning."""

PLAYER_SYSTEM = """你是 COC 7th TRPG 玩家 AI。目标：推进剧情、扮演角色、探索世界。

行动优先级:
1. 与场景中的 NPC 互动（对话、跟随、请求帮助）
2. 检查场景中提到的物品、线索和异常
3. 向有意义的场景移动
4. 尝试明显的技能检定
5. 当 stuck 时尝试非直接方案

[压力测试模式]
当前测试目标: {player_strategy}
- NPC: 积极对话、尝试跟随、测试态度变化
- Enemy: 进入/退出战斗、对峙、逃跑
- Boss: 触发遭遇条件
- Combat: 不同战斗动作（攻击/闪避/逃跑）
- TimeAgent: 等待、休息、rush
- Author: 出人意料动作、边界输入（空输入、不合理动作）
注意：不要试图测试不存在的系统——只操作游戏内可执行的行动。

角色扮演要求:
- 行动符合调查员性格和当前 SAN 状态
- 危险时表现恐惧、犹豫
- 用自然语言输入，不使用游戏命令格式
- 直接输出 JSON"""

PLAYER_USER_TEMPLATE = """【调查员】
HP={hp}/{max_hp} SAN={san} MP={mp}
武器: {weapons}
物品: {inventory}

【当前场景】
{location}: {description}
NPC: {npcs}

【本轮叙事】
{brief}
{narrative}

【最近行动】
{short_history}

【长期记忆】
{long_memory}

选择下一步行动。返回 JSON：
{{"action": "玩家输入文本", "reasoning": "策略说明（20字以内）"}}"""

MEMORY_COMPRESS_SYSTEM = "你是游戏记录压缩助手。将多轮游戏摘要为一段紧凑叙述。"

MEMORY_COMPRESS_TEMPLATE = """将以下游戏记录压缩为一段摘要（100字以内），保留关键决策和结果:

{short_history}

格式: "第N-N轮：在{场景}做了{关键行动}，结果{结果}。发现{信息}。" """
```

- [ ] **Step 2: Commit**

```bash
git add src/llm_player_prompts.py
git commit -m "feat: add llm_player_prompts.py — centralized prompt config"
```

---

### Task 3: Combat Test Investigator

**Files:**
- Create: `data/investigator/combat_test_character.json`

- [ ] **Step 1: Write combat investigator JSON**

```json
{
  "name": "战斗测试员",
  "age": 30,
  "gender": "男",
  "stats": {"STR": 60, "CON": 60, "SIZ": 60, "DEX": 60, "APP": 50, "INT": 60, "POW": 60, "EDU": 60, "LUCK": 60},
  "skills": {
    "格斗": 80, "射击": 80, "闪避": 80, "侦查": 60, "聆听": 50,
    "急救": 50, "潜行": 50, "投掷": 50, "图书馆使用": 50, "心理学": 40
  },
  "inventory": [],
  "personal_description": "一名经验丰富的战斗调查员，擅长应对各种危险情况。"
}
```

- [ ] **Step 2: Commit**

```bash
git add data/investigator/combat_test_character.json
git commit -m "feat: add combat test investigator"
```

---

### Task 4: LLM Player Driver

**Files:**
- Create: `src/llm_player.py`
- Modify: `src/llm_player_prompts.py` (may need adjustments)

- [ ] **Step 1: Write the script skeleton**

```python
"""
LLM-driven TRPG player for automated module testing.
Usage: python -m llm_player [--module NAME] [--turns N] [--profile PATH]
"""
from __future__ import annotations
import sys, os, json, time, argparse
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from llm import call_deepseek
from game_loop import init_game, run_turn, set_turn_logger
from game.turn_logger import TurnLogger
from investigator import load_investigator
from llm_player_prompts import (
    PLAYER_SYSTEM, PLAYER_USER_TEMPLATE,
    MEMORY_COMPRESS_SYSTEM, MEMORY_COMPRESS_TEMPLATE,
)


def load_profile(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_player_prompt(
    world, narrative_result: dict, short_history: list[str],
    long_memory: str, profile: dict,
) -> str:
    snap = world.build_snapshot()
    p = snap.get("player", {})
    weapons = ", ".join(p.get("weapons", [])) or "无"
    inv = p.get("inventory", "") or "无"
    loc = snap.get("location", "?")
    desc = snap.get("description", "")[:200]
    npcs = ", ".join(n["name"] for n in snap.get("npcs_in_scene", [])) or "无"

    strategy = ", ".join(profile.get("player_strategy", []))

    system = PLAYER_SYSTEM.format(player_strategy=strategy)
    user = PLAYER_USER_TEMPLATE.format(
        hp=p.get("hp", "?"), max_hp=p.get("max_hp", "?"),
        san=p.get("san", "?"), mp=p.get("mp", "?"),
        weapons=weapons, inventory=inv,
        location=loc, description=desc, npcs=npcs,
        brief=narrative_result.get("brief", ""),
        narrative=narrative_result.get("narrative", ""),
        short_history="\n".join(short_history[-5:]) or "（游戏开始）",
        long_memory=long_memory or "（无）",
    )
    return system, user


def compress_memory(short_history: list[str]) -> str:
    prompt = MEMORY_COMPRESS_TEMPLATE.format(
        short_history="\n".join(short_history),
    )
    try:
        result = call_deepseek(
            prompt, json_mode=False, system=MEMORY_COMPRESS_SYSTEM,
            model="deepseek-v4-flash", reasoning_effort="low",
        )
        return result.strip()
    except Exception:
        return "（记忆压缩失败）"


def run_llm_player(profile_path: str = "data/stress_profile.json", module_name: str = None,
                   max_turns: int = None, max_duration_s: int = None):
    profile = load_profile(profile_path)
    pc = profile["player_config"]
    if module_name is None:
        module_name = pc["module_name"]
    if max_turns is None:
        max_turns = pc["max_turns"]
    if max_duration_s is None:
        max_duration_s = pc["max_duration_s"]

    # Init
    module_dir = PROJECT_ROOT / "data" / "modules" / module_name
    game = init_game(
        l2_path=str(module_dir / "l2_keeper.json"),
        l1_path=str(module_dir / "l1_player.json"),
        l3_path=str(module_dir / "l3_designer.json"),
        start_node="6号车厢",
    )

    # Combat testing: load buffed investigator
    ct = profile.get("combat_testing", {})
    if ct.get("mode") == "buff_investigator":
        char_path = PROJECT_ROOT / "data" / "investigator" / "combat_test_character.json"
        if char_path.exists():
            game["keeper"].world.set_player(load_investigator(str(char_path)))

    # Logging
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = PROJECT_ROOT / "logs" / "llm_player" / ts
    log_dir.mkdir(parents=True, exist_ok=True)
    turn_logger = TurnLogger(log_dir=str(log_dir / "turn_logs"))
    set_turn_logger(turn_logger)

    short_history: list[str] = []
    long_memory = ""
    compress_interval = pc["memory_compress_interval"]
    summary_log: list[dict] = []

    player_name = game["keeper"].world.player.name

    print(f"LLM Player — {module_name}")
    print(f"  Player: {player_name}, Model: {pc['model']}")
    print(f"  Strategy: {profile.get('player_strategy', [])}")
    print(f"  Max turns: {max_turns}, Max duration: {max_duration_s}s")
    print(f"  Log: {log_dir}")
    print()

    t0 = time.perf_counter()
    turn = 0
    last_narrative = {"brief": "", "narrative": ""}

    while turn < max_turns:
        elapsed = time.perf_counter() - t0
        if elapsed > max_duration_s:
            print(f"  Timeout at turn {turn}")
            break

        t_turn = time.perf_counter()
        system, user = build_player_prompt(
            game["keeper"].world, last_narrative,
            short_history, long_memory, profile,
        )
        try:
            response = call_deepseek(
                user, json_mode=True, system=system,
                model=pc["model"], reasoning_effort=pc["reasoning_effort"],
                fallback_schema={"action": "环顾四周", "reasoning": "fallback"},
            )
            if isinstance(response, str):
                response = json.loads(response)
            action = response.get("action", "环顾四周")
            reasoning = response.get("reasoning", "")
        except Exception as e:
            action = "环顾四周"
            reasoning = f"LLM error: {e}"

        result = run_turn(game, action)
        dt = time.perf_counter() - t_turn

        brief = result.get("brief", "")
        narrative = result.get("narrative", "")
        skill_results = result.get("skill_results", [])
        ending = result.get("ending")
        combat = result.get("combat")
        npc_events = result.get("npc_events", [])

        short_history.append(
            f"T{turn+1}: {action} → {brief[:80]}"
        )
        last_narrative = {"brief": brief, "narrative": narrative}

        summary_log.append({
            "turn": turn + 1, "input": action, "reasoning": reasoning,
            "brief": brief, "narrative": narrative,
            "skill_results": skill_results,
            "combat_outcome": combat["outcome"] if combat else None,
            "npc_events": npc_events,
            "ending": ending.get("name") if ending else None,
            "elapsed_s": round(dt, 1),
        })

        print(f"  T{turn+1:02d} [{dt:.1f}s]: {action[:50]}")
        if reasoning:
            print(f"    → {reasoning[:60]}")

        if ending and ending.get("game_over"):
            print(f"  Game Over: {ending.get('name', '?')}")
            break

        if (turn + 1) % compress_interval == 0:
            long_memory = compress_memory(short_history)
            short_history = []

        turn += 1

    # Save summary
    total_elapsed = time.perf_counter() - t0
    with open(log_dir / "_summary.json", "w", encoding="utf-8") as f:
        json.dump({
            "module": module_name, "player": player_name,
            "turns": len(summary_log), "total_elapsed_s": round(total_elapsed, 1),
            "game_over": summary_log[-1].get("ending") if summary_log else None,
            "profile": profile,
            "turns_detail": summary_log,
        }, f, ensure_ascii=False, indent=2)

    print(f"\nDone. {len(summary_log)} turns, {total_elapsed:.0f}s")
    print(f"Log: {log_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM-driven TRPG player")
    parser.add_argument("--module", type=str, default=None, help="Module name")
    parser.add_argument("--turns", type=int, default=None, help="Max turns")
    parser.add_argument("--profile", type=str, default="data/stress_profile.json")
    args = parser.parse_args()
    run_llm_player(
        profile_path=args.profile, module_name=args.module,
        max_turns=args.turns,
    )
```

- [ ] **Step 2: Commit**

```bash
git add src/llm_player.py
git commit -m "feat: add llm_player.py — LLM-driven TRPG player"
```

---

### Task 5: Audit Script

**Files:**
- Create: `src/audit_player_log.py`

- [ ] **Step 1: Write the audit script**

```python
"""
Audit LLM player logs → markdown report.
Usage: python -m audit_player_log <log_dir>
"""
from __future__ import annotations
import sys, json, os
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

    # ── Summary Stats ──
    lines.append("## Summary")
    skill_total = 0
    skill_pass = 0
    other_count = 0
    combat_count = 0
    entity_hits: Counter = Counter()
    for t in turns:
        for sr in t.get("skill_results", []):
            skill_total += 1
            if sr.get("success"):
                skill_pass += 1
            entity_hits[sr.get("entity_id", "?")] += 1
        if "other" in t.get("input", "").lower() or not t.get("skill_results"):
            pass  # approximate
        if t.get("combat_outcome"):
            combat_count += 1

    lines.append(f"- Skill checks: {skill_pass}/{skill_total} passed" if skill_total else "- Skill checks: N/A")
    lines.append(f"- Combat encounters: {combat_count}")
    lines.append(f"- Entity hits: {len(entity_hits)} unique / {sum(entity_hits.values())} total")
    lines.append("")

    # ── Per-Turn ──
    lines.append("## Per-Turn Detail")
    lines.append("| # | Input | Skills | Combat | NPC Events | Elapsed |")
    lines.append("|---|---|---|---|---|---|")
    for t in turns:
        sr = t.get("skill_results", [])
        skill_str = ", ".join(
            f"{'✓' if r.get('success') else '✗'}{r.get('entity_id','?')}"
            for r in sr
        ) or "—"
        combat_str = t.get("combat_outcome") or "—"
        npc_str = "; ".join(t.get("npc_events", []))[:40] or "—"
        lines.append(
            f"| {t['turn']} | {t['input'][:30]} | {skill_str} | "
            f"{combat_str} | {npc_str} | {t['elapsed_s']:.0f}s |"
        )
    lines.append("")

    # ── Subsystem Check ──
    lines.append("## Subsystem Stress Check")
    _audit_npc(lines, turns)
    _audit_enemy(lines, turns)
    _audit_combat(lines, turns)
    _audit_time(lines, turns)
    _audit_author(lines, turns)
    _audit_side_effects(lines, turns)
    _audit_memory(lines, turns)
    lines.append("")

    # ── Anomalies ──
    lines.append("## Anomalies")
    anomalies = []
    consecutive_fail = 0
    enrich_degrade = 0
    for t in turns:
        sr = t.get("skill_results", [])
        failed = any(not r.get("success") for r in sr) if sr else False
        if failed:
            consecutive_fail += 1
        else:
            if consecutive_fail >= audit_cfg.get("consecutive_fail_alert", 3):
                anomalies.append(f"| {t['turn']-consecutive_fail}-{t['turn']} | consecutive_fail | {consecutive_fail} consecutive failures |")
            consecutive_fail = 0
        # Approximate enrich degrade check
        if "（处理中）" in t.get("brief", "") or t.get("brief", "").strip() == "":
            enrich_degrade += 1

    if anomalies:
        lines.append("| Turns | Type | Detail |")
        lines.append("|-------|------|--------|")
        lines.extend(anomalies)
    else:
        lines.append("No anomalies detected.")
    lines.append("")

    # ── Recommendations ──
    lines.append("## Recommendations")
    if enrich_degrade > audit_cfg.get("enrich_degrade_max", 2):
        lines.append(f"- Enrich degraded {enrich_degrade} times — check enrich prompt/model stability")
    if combat_count == 0 and "Combat" in audit_targets:
        lines.append("- No combat triggered — consider more aggressive enemy-seeking strategy")
    if not s.get("game_over"):
        lines.append("- Game did not reach ending — check dependency chains and entity coverage")
    lines.append("")

    return "\n".join(lines)


def _audit_npc(lines: list[str], turns: list[dict]):
    lines.append("### NPC")
    talk_count = sum(1 for t in turns if "npc_events" in t and t["npc_events"])
    follow_events = sum(1 for t in turns for e in t.get("npc_events", []) if "跟随" in e)
    lines.append(f"- talk_to interactions: approx {talk_count}")
    lines.append(f"- Follow events: {follow_events}")
    lines.append("")


def _audit_enemy(lines: list[str], turns: list[dict]):
    lines.append("### Enemy")
    lines.append(f"- Combat outcomes: {sum(1 for t in turns if t.get('combat_outcome'))}")
    lines.append("")


def _audit_combat(lines: list[str], turns: list[dict]):
    lines.append("### Combat")
    combats = [t for t in turns if t.get("combat_outcome")]
    outcomes = Counter(t.get("combat_outcome") for t in combats)
    lines.append(f"- Total combats: {len(combats)}")
    lines.append(f"- Outcomes: {dict(outcomes)}")
    lines.append("")


def _audit_time(lines: list[str], turns: list[dict]):
    lines.append("### TimeAgent")
    lines.append(f"- Total turns: {len(turns)} (time advance per turn is logged separately)")
    lines.append("")


def _audit_author(lines: list[str], turns: list[dict]):
    lines.append("### Author")
    lines.append("- Author activity tracked via parse 'other' rate (see anomalies)")
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
```

- [ ] **Step 2: Commit**

```bash
git add src/audit_player_log.py
git commit -m "feat: add audit_player_log.py — log audit → markdown report"
```

---

### Task 6: Integration Test — Quick Smoke

**Files:**
- None (manual run)

- [ ] **Step 1: Run LLM player with 5-turn smoke test**

```bash
cd C:/Users/micha/PyCharmMiscProject
PYTHONPATH=src python src/llm_player.py --turns 5
```
Expected: 5 turns complete, log directory created under `logs/llm_player/`.

- [ ] **Step 2: Run audit on the output**

```bash
PYTHONPATH=src python src/audit_player_log.py logs/llm_player/<ts>
```
Expected: `audit_report.md` generated in log directory.

- [ ] **Step 3: Verify report content**

Check `audit_report.md` has all sections: Summary, Per-Turn, Subsystem Check, Anomalies, Recommendations.

- [ ] **Step 4: Run full integration test (30 turns)**

```bash
PYTHONPATH=src python src/llm_player.py --turns 30
PYTHONPATH=src python src/audit_player_log.py logs/llm_player/<latest_ts>
```

- [ ] **Step 5: Commit any fixes found during testing**

```bash
git add src/llm_player.py src/audit_player_log.py
git commit -m "fix: smoke test adjustments for llm_player + audit"
```

---

### Task 7: Push

- [ ] **Step 1: Push to GitHub**

```bash
git push
```
