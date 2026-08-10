"""场景化 E2E runner：场景 YAML -> goal 驱动 llm_player -> 三层判定 verdict。

用法: python tests/e2e/run_scenario.py tests/e2e/scenarios/standoff_avoid.yaml

三层判定：
  1. invariants —— 每回合日志契约结构（字段存在性/类型/pending 合法值），机器硬断言
  2. predicates —— 声明式机器谓词（见 scenario_predicates.PREDICATES）
  3. judging    —— 场景绑定 LLM rubric 审计（pro 模型，逐项给证据）

最终 verdict = invariants AND predicates AND judge.overall；退出码 0=PASS / 1=FAIL。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from scenario_predicates import PREDICATES


def load_scenario(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def make_seed_fn(seed_cfg: dict | None):
    """命令式播种：spawn 敌人（可挂 avoidable flags）+ 覆盖玩家技能。"""
    if not seed_cfg:
        return None

    def hook(game):
        world = game["keeper"].world
        enemy = seed_cfg.get("enemy")
        if enemy:
            inst = world.enemies.spawn(
                enemy["name"], enemy["scene"], int(enemy.get("qty", 1)))
            if enemy.get("avoidable") and "avoidable" not in inst.flags:
                inst.flags.append("avoidable")
            print(f"[seed] spawned {enemy['name']} x{enemy.get('qty', 1)} "
                  f"in {enemy['scene']} flags={inst.flags}")
        skills = seed_cfg.get("player_skills") or {}
        player = world.player
        for name, val in skills.items():
            sk = player.get_skill(name)
            if sk:
                sk.value = int(val)
            else:
                from investigator.models import Skill
                player.skills.append(Skill(name=name, base_value=int(val)))
            print(f"[seed] player skill {name} = {val}")

    return hook


def build_profile(scn: dict) -> dict:
    """由场景 YAML 生成临时 llm_player profile。

    success_checks 默认只收录期望为 true 的谓词（正事件，达成即提前终止）；
    可用场景 YAML 的 success_checks 字段显式覆盖（如需要观察 standoff 之后的
    回合，就不应把 standoff_occurred 当作提前终止条件）。
    期望为 false 的谓词是全程不变量，留待终局判定。
    """
    predicates = scn.get("predicates") or {}
    if "success_checks" in scn:
        success_checks = list(scn["success_checks"] or [])
    else:
        success_checks = [k for k, v in predicates.items() if v is True]
    return {
        "test_mode": "goal",
        "goal": scn.get("goal", ""),
        "success_checks": success_checks,
        "player_strategy": [],
        "audit_targets": [],
        "player_config": {
            "max_turns": int(scn.get("max_turns", 10)),
            "max_duration_s": int(scn.get("max_duration_s", 900)),
            "memory_compress_interval": 5,
            "model": scn.get("player_model", "deepseek-v4-flash"),
            "module_name": scn["module"],
        },
    }


# ── 第 1 层：invariants（日志版契约硬断言，思路同 helpers.assert_player_turn_contract）──

_TURN_SCHEMA = {
    "turn": int, "input": str, "skill_results": list,
    "npc_events": list, "npcs_visible": dict, "time_state": dict,
}
_VALID_PENDING = ("weapon_offer", "standoff", "clarify")


def check_invariants(turns: list[dict]) -> list[str]:
    problems = []
    if not turns:
        problems.append("无任何回合日志")
        return problems
    for t in turns:
        tn = t.get("turn", "?")
        for key, typ in _TURN_SCHEMA.items():
            if key not in t:
                problems.append(f"T{tn}: 缺字段 {key}")
            elif not isinstance(t[key], typ):
                problems.append(f"T{tn}: 字段 {key} 类型错误（{type(t[key]).__name__}）")
        for key in ("brief", "narrative"):
            if key not in t:
                problems.append(f"T{tn}: 缺字段 {key}")
            elif t[key] is not None and not isinstance(t[key], str):
                problems.append(f"T{tn}: 字段 {key} 类型错误（{type(t[key]).__name__}）")
        pending = t.get("pending")
        if pending is not None and pending not in _VALID_PENDING:
            problems.append(f"T{tn}: pending 值非法（{pending}）")
    return problems


# ── 第 2 层：predicates（机器谓词）──

def check_predicates(scn: dict, turns: list[dict]) -> dict:
    results = {}
    for name, expected in (scn.get("predicates") or {}).items():
        if name not in PREDICATES:
            results[name] = {"expected": expected, "actual": None,
                             "pass": False, "error": f"未知谓词 {name}"}
            continue
        actual = PREDICATES[name](turns)
        results[name] = {"expected": expected, "actual": actual,
                         "pass": actual == expected}
    return results


# ── 第 3 层：judging（场景绑定 LLM rubric）──

def _build_digest(summary: dict) -> str:
    turns = summary.get("turns_detail", [])
    lines = []
    for t in turns:
        combat = t.get("combat")
        combat_str = (f"{combat.get('outcome', '?')}: "
                      f"{str(combat.get('narrative', ''))[:60]}") if combat else "-"
        nv = t.get("npcs_visible", {})
        lines.append(
            f"T{t['turn']:02d}:\n"
            f"  玩家输入: {t['input']}\n"
            f"  玩家意图: {t.get('reasoning', '')}\n"
            f"  系统输出(Brief): {str(t.get('brief') or '（空）')[:300]}\n"
            f"  系统输出(Narrative): {str(t.get('narrative') or '（空）')[:300]}\n"
            f"  pending交互: {t.get('pending') or '-'}\n"
            f"  战斗结果: {combat_str}\n"
            f"  位置: {t.get('location', '?')} | 存活: {t.get('player_alive')} | "
            f"武器: {t.get('weapons') or []}\n"
            f"  场景NPC: {', '.join(nv.get('in_scene', [])) or '无'} | "
            f"跟随: {', '.join(nv.get('following', [])) or '无'}"
        )
    return "\n".join(lines)


def run_judge(scn: dict, summary: dict, log_dir: str,
              pred_results: dict | None = None) -> dict:
    from llm import call_deepseek
    from config_llm import LLM_DEFAULT_MODEL

    rubric = scn.get("judging", "")
    digest = _build_digest(summary)
    # 机制事件时间线（机器采集事实层，防捏造）
    timeline = "\n".join(
        t.get("mech", "") for t in summary.get("turns_detail", []) if t.get("mech")
    ) or "（无时间线数据）"
    # 机器谓词结果作为参照事实注入，供 judge 交叉核对、防止凭空捏造证据
    pred_facts = "\n".join(
        f"- {name}: {r['actual']}" for name, r in (pred_results or {}).items()
    ) or "（无）"

    guide_path = Path(__file__).resolve().parent / "scenarios" / "audit_guide.md"
    guide = guide_path.read_text(encoding="utf-8") if guide_path.exists() else ""

    system = f"""{guide}

---

以上为《审计操作手册》，你必须严格遵循其中的名词表、时间线格式、判定程序、误判警示与证据规范。
补充强调：
- 【机制事件时间线】与【机器谓词结果】是机器采集的确定事实，判定必须与它们一致
- 每个判定项必须给出具体证据（T编号 + 引用），证据必须真实存在于提供的材料中
- overall：所有 target=engine 的判定项 pass 才为 PASS；仅 target=player 失败不阻塞 PASS，但须在 reason 注明
直接输出 JSON。"""

    user = f"""【场景】{scn.get('name', '?')}——{scn.get('description', '')}

【玩家目标】
{scn.get('goal', '')}

【判定标准 rubric】
{rubric}

【机器谓词结果】（确定事实）
{pred_facts}

【机制事件时间线】（机器采集事实层）
{timeline}

【跑团日志摘要】
模组：{summary.get('module', '?')} | 回合数：{summary.get('turns', 0)} | \
结束状态：{summary.get('game_over') or '未结束'} | 目标提前达成：{summary.get('goal_achieved')}

{digest}
"""

    try:
        response = call_deepseek(
            user, json_mode=True, system=system,
            model=LLM_DEFAULT_MODEL,
            fallback_schema={"items": [], "overall": "FAIL", "reason": "judge 调用异常"},
            max_retries=3, timeout=300,
        )
        data = json.loads(response) if isinstance(response, str) else response
    except Exception as e:
        data = {"items": [], "overall": "FAIL", "reason": f"judge 调用失败: {e}"}
        response = json.dumps(data, ensure_ascii=False)

    resp_str = json.dumps(data, ensure_ascii=False, indent=2)
    with open(Path(log_dir) / "judge_llm.txt", "w", encoding="utf-8") as f:
        f.write(f"--- System ---\n{system}\n\n--- User ---\n{user}\n\n"
                f"--- Response ---\n{resp_str}\n")

    items = data.get("items", [])
    # 机器复核：target=engine 的判定项全 pass 才 PASS，不盲信 LLM 的 overall
    engine_items = [it for it in items if it.get("target", "engine") == "engine"]
    overall = "PASS" if engine_items and all(it.get("pass") for it in engine_items) else "FAIL"
    return {"items": items, "overall": overall,
            "llm_overall": data.get("overall"), "reason": data.get("reason", "")}


# ── 主流程 ──

def main() -> int:
    parser = argparse.ArgumentParser(description="场景化 E2E runner")
    parser.add_argument("scenario", help="场景 YAML 路径")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="每回合打印机制事件时间线（默认只打印输入摘要）")
    args = parser.parse_args()

    scn = load_scenario(args.scenario)
    name = scn.get("name", Path(args.scenario).stem)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = str(PROJECT_ROOT / "data" / "debug" / "e2e_scenarios" / f"{ts}_{name}")
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    profile = build_profile(scn)
    profile_path = Path(log_dir) / "profile.json"
    with open(profile_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    print(f"Scenario: {name} — {scn.get('description', '')}")
    print(f"Module: {scn['module']} | Max turns: {profile['player_config']['max_turns']}")
    print(f"Log: {log_dir}\n")

    from llm_player import run_llm_player
    result = run_llm_player(
        profile_path=str(profile_path),
        post_init_hook=make_seed_fn(scn.get("seed")),
        log_dir=log_dir,
        verbose=args.verbose,
    )
    summary = result["summary"]
    turns = summary.get("turns_detail", [])

    # 机制事件时间线落盘（审计事实层）
    timeline_lines = [t.get("mech", "") for t in turns if t.get("mech")]
    with open(Path(log_dir) / "timeline.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(timeline_lines) + "\n")

    # 三层判定
    inv_problems = check_invariants(turns)
    pred_results = check_predicates(scn, turns)
    judge = run_judge(scn, summary, log_dir, pred_results=pred_results)

    inv_ok = not inv_problems
    pred_ok = all(r["pass"] for r in pred_results.values())
    judge_ok = judge["overall"] == "PASS"
    verdict = "PASS" if (inv_ok and pred_ok and judge_ok) else "FAIL"

    verdict_doc = {
        "scenario": name,
        "verdict": verdict,
        "goal_achieved": summary.get("goal_achieved"),
        "turns": summary.get("turns"),
        "layers": {
            "invariants": {"pass": inv_ok, "problems": inv_problems},
            "predicates": {"pass": pred_ok, "results": pred_results},
            "judging": judge,
        },
        "log_dir": log_dir,
    }
    with open(Path(log_dir) / "verdict.json", "w", encoding="utf-8") as f:
        json.dump(verdict_doc, f, ensure_ascii=False, indent=2)

    # 报告
    print("\n" + "=" * 60)
    print(f"VERDICT: {verdict}  ({name})")
    print("=" * 60)
    print(f"[1] invariants : {'PASS' if inv_ok else 'FAIL'}")
    for p in inv_problems:
        print(f"      - {p}")
    print(f"[2] predicates : {'PASS' if pred_ok else 'FAIL'}")
    for pname, r in pred_results.items():
        mark = "OK" if r["pass"] else "XX"
        print(f"      [{mark}] {pname}: expected={r['expected']} actual={r['actual']}"
              + (f" ({r['error']})" if r.get("error") else ""))
    print(f"[3] judging    : {'PASS' if judge_ok else 'FAIL'}"
          f" (llm_overall={judge.get('llm_overall')}) — {judge.get('reason', '')}")
    for it in judge.get("items", []):
        mark = "OK" if it.get("pass") else "XX"
        tgt = it.get("target", "engine")
        print(f"      [{mark}] {it.get('item', '?')}" + (f"  ({tgt})" if tgt != "engine" else ""))
        print(f"           证据: {str(it.get('evidence', ''))[:100]}")
    print(f"\nTurns: {summary.get('turns')} | goal_achieved: {summary.get('goal_achieved')}")
    print(f"Log: {log_dir}")

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
