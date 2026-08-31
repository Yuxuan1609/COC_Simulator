"""U4 幕末成长检定（COC7）：checked 技能 roll>value → +1d10；结算后清零。
导出=版本化副本（不覆盖原卡）。结局触发自动调用；战斗败北不触发。"""
import json
import os
import random
from datetime import datetime

GROWTH_DIE = 10  # 成长骰 1d10


def settle_growth(inv, rng=random) -> list[dict]:
    """对 checked=True 的技能逐一成长检定。rng 可注入（测试钉骰）。"""
    report = []
    for skill in inv.skills:
        if not getattr(skill, "checked", False):
            continue
        roll = rng.randint(1, 100)
        entry = {"skill": skill.name, "value": skill.value, "roll": roll,
                 "grown": False, "gain": 0}
        if roll > skill.value:
            gain = rng.randint(1, GROWTH_DIE)
            inv.modify_skill(skill.name, gain)
            entry["grown"] = True
            entry["gain"] = gain
        skill.checked = False
        report.append(entry)
    return report


def export_grown_card(inv, source_path: str, module_name: str,
                      out_dir: str | None = None) -> str:
    """导出成长后角色卡为版本化副本。返回新文件路径。"""
    from investigator.serialization import to_dict
    base = os.path.splitext(os.path.basename(source_path))[0]
    date = datetime.now().strftime("%Y%m%d")
    name = f"{base}_after_{module_name}_{date}.json"
    out_dir = out_dir or os.path.dirname(source_path) or "."
    path = os.path.join(out_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(to_dict(inv), f, ensure_ascii=False, indent=2)
    return path
