"""Test evaluate_trait_enhancement with various dice/stat/trait combos.
Saves prompts + results to data/debug/trait_enhancement/<timestamp>/"""
import sys, os, json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from llm import evaluate_trait_enhancement

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "debug", "trait_enhancement", TIMESTAMP)
os.makedirs(OUT_DIR, exist_ok=True)

RESULTS = []


def test_case(case_id: int, name: str, inv_desc: str, skill_name: str,
              dice_roll: int, skill_value: int, base_tier_expected: str,
              entity_name="测试", search_context=False, player_input=""):
    """Run one test case, save prompt + response, log result."""
    skill_detail = f"{skill_name}检定：D100={dice_roll}/{skill_value}"
    ext = max(1, skill_value // 5)
    hard = max(1, skill_value // 2)
    reg = skill_value

    header = (
        f"\n{'='*60}\n"
        f"【Case {case_id}: {name}】\n"
        f"  调查员: {inv_desc}\n"
        f"  技能: {skill_name}({skill_value}) | D100={dice_roll}\n"
        f"  阈值: 极难≤{ext} 困难≤{hard} 常规≤{reg} 大失败≥96\n"
        f"  期望基础等级: {base_tier_expected}\n"
        + (f"  玩家输入: {player_input}\n" if player_input else "")
    )
    print(header)

    result = evaluate_trait_enhancement(
        inv_desc=inv_desc,
        skill_name=skill_name,
        skill_detail=skill_detail,
        dice_roll=dice_roll,
        skill_value=skill_value,
        entity_name=entity_name,
        search_context=search_context,
        player_input=player_input or None,
    )

    tier = result["tier"]
    reason = result.get("reason", "")
    override = result.get("detail_override")
    prompt = result.get("prompt", "")
    changed = "*** 修正 ***" if tier != base_tier_expected else "(未修正)"

    print(f"  结果: tier={tier} {changed}")
    print(f"  理由: {reason}")
    if override:
        print(f"  新描述: {override}")

    # Save prompt
    prompt_file = os.path.join(OUT_DIR, f"case{case_id}_prompt.txt")
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write(prompt)

    # Save response
    response_file = os.path.join(OUT_DIR, f"case{case_id}_response.json")
    with open(response_file, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in result.items() if k != "prompt"},
                  f, ensure_ascii=False, indent=2)

    RESULTS.append({
        "id": case_id,
        "name": name,
        "inv_desc": inv_desc,
        "skill": f"{skill_name}({skill_value})",
        "dice_roll": dice_roll,
        "base_tier_expected": base_tier_expected,
        "result_tier": tier,
        "changed": tier != base_tier_expected,
        "reason": reason,
        "override": override,
    })


if __name__ == "__main__":
    CASES = [
        (1, "特质匹配 — 观察力优秀 → 侦查提升",
         "观察力极其优秀，任何细节都逃不过眼睛",
         "侦查", 45, 60, "regular", "测试", False, "我仔细观察房间的每个角落"),

        (2, "特质无关 — 大力士 → 侦查不变",
         "身材魁梧，力大无穷，能徒手掰弯钢管",
         "侦查", 18, 50, "hard", "测试", False, "我查看桌上的文件"),

        (3, "特质降级 — 胆小如鼠 → 勇气检定降级",
         "胆小如鼠，遇到危险第一反应是逃跑",
         "恐吓", 22, 50, "hard", "测试", False, "我对着怪物大吼，试图吓退它"),

        (4, "临界 — 差1点极难，特质能否补上",
         "身手敏捷，有十年杂技经验",
         "闪避", 16, 75, "hard", "测试", False, "我一个翻滚躲开攻击"),

        (5, "大失败 — 特质能否缓和",
         "天生幸运，总在危急时刻逢凶化吉",
         "幸运", 98, 70, "failure", "测试", False, "我祈祷好运降临"),

        (6, "大成功 — 已经最好，不应修正",
         "观察力极其优秀",
         "侦查", 1, 50, "extreme", "测试", False, "我扫视整个房间"),

        (7, "刚好失败 — 特质能否挽救",
         "精通机械，十年工程师经验",
         "机械维修", 62, 60, "failure", "测试", False, "我尝试修理损坏的引擎"),

        (8, "搜索侦查 — 观察力特质",
         "观察力极其优秀，任何细节都逃不过眼睛",
         "侦查", 35, 60, "regular", "搜索", True, "搜索"),
    ]

    for case in CASES:
        test_case(*case)

    # Save summary
    summary_file = os.path.join(OUT_DIR, "_summary.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(RESULTS, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"全部 {len(RESULTS)} 个测试完成")
    print(f"产物目录: {OUT_DIR}")
    for r in RESULTS:
        print(f"  case{r['id']}_prompt.txt / case{r['id']}_response.json")
    print(f"  _summary.json — 汇总对比表")
