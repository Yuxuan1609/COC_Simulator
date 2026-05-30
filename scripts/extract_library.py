"""从小说文本中自动提取 enemy/boss/weapon，补充到标准库。

用法：
    python scripts/extract_library.py <文本文件路径>

流程：
    1. 读取文本 → LLM 提取 JSON
    2. 与现有标准库去重（按 name）
    3. 展示新条目
    4. 手动确认 → 写入 JSON
"""
from __future__ import annotations
import json
import os
import sys

# 确保 src 在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

LIB_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "library", "core")
ENEMIES_PATH = os.path.join(LIB_DIR, "enemies.json")
BOSSES_PATH = os.path.join(LIB_DIR, "bosses.json")
WEAPONS_PATH = os.path.join(LIB_DIR, "weapons.json")
TEMPLATES_PATH = os.path.join(LIB_DIR, "templates.json")


def _load_templates() -> dict:
    with open(TEMPLATES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _template_to_example(template: dict) -> str:
    """Convert a template field dict to a JSON example string for LLM prompt."""
    return json.dumps(template["fields"], ensure_ascii=False, indent=2)



def _load_existing() -> tuple[set[str], set[str], set[str]]:
    existing_enemy_names: set[str] = set()
    existing_boss_names: set[str] = set()
    existing_weapon_names: set[str] = set()
    try:
        with open(ENEMIES_PATH, "r", encoding="utf-8") as f:
            for e in json.load(f).get("items", []):
                existing_enemy_names.add(e["name"])
    except Exception:
        pass
    try:
        with open(BOSSES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            for name in data.keys():
                existing_boss_names.add(data[name].get("name", name))
    except Exception:
        pass
    try:
        with open(WEAPONS_PATH, "r", encoding="utf-8") as f:
            for w in json.load(f).get("items", []):
                existing_weapon_names.add(w["name"])
    except Exception:
        pass
    return existing_enemy_names, existing_boss_names, existing_weapon_names


def _extract_via_llm(text: str):
    from llm import call_deepseek
    from config_llm import LLM_DEFAULT_MODEL

    templates = _load_templates()
    enemy_example = _template_to_example(templates["enemy"])
    boss_example = _template_to_example(templates["boss"])
    weapon_example = _template_to_example(templates["weapon"])

    prompt = f"""你是 TRPG 素材提取助手。从以下小说文本中提取所有可作为 COC 跑团素材的实体。

请按以下三种类型分别输出 JSON 数组：

【敌人(enemy)模板】
{enemy_example}

【Boss 模板】
{boss_example}

【武器(weapon)模板】
{weapon_example}

提取规则：
- 只提取文本中有名有姓、描述足够具体的实体
- 不要凭空编造；没有对应类型就不输出该数组
- damage 统一使用 dict 格式：{{"dice_n": n, "dice_d": d, "bonus": 0, "use_db": false}}
- 敌人：{templates['enemy'].get('llm_hint', '')}
- Boss：{templates['boss'].get('llm_hint', '')}
- 武器：{templates['weapon'].get('llm_hint', '')}

小说文本：
---
{text[:12000]}
---

返回 JSON：
{{"enemies": [...], "bosses": [...], "weapons": [...]}}
直接输出 JSON。"""

    response = call_deepseek(
        prompt,
        json_mode=True,
        model=LLM_DEFAULT_MODEL,
        system="你是 TRPG 素材提取助手，从小说中提取可用的敌人/Boss/武器数据。",
        fallback_schema={"enemies": [], "bosses": [], "weapons": []},
    )
    return json.loads(response) if isinstance(response, str) else response


def _dedup(items: list[dict], existing_names: set[str]) -> tuple[list[dict], list[dict]]:
    new = []
    dup = []
    for item in items:
        name = item.get("name", "")
        if name in existing_names:
            dup.append(item)
        else:
            new.append(item)
    return new, dup


def _show_item(item: dict):
    print(f"   名称: {item.get('name', '?')}")
    print(f"   类型: {item.get('type', '?')}")
    if "attributes" in item:
        attrs = item["attributes"]
        print(f"   属性: STR{attrs.get('STR','?')} CON{attrs.get('CON','?')} SIZ{attrs.get('SIZ','?')} DEX{attrs.get('DEX','?')} POW{attrs.get('POW','?')}")
    if "attacks" in item:
        for a in item["attacks"]:
            dmg = a.get("damage", {})
            d_str = f"{dmg.get('dice_n',0)}D{dmg.get('dice_d',0)}" if dmg.get('dice_d') else str(dmg.get('bonus', 0))
            print(f"   攻击: {a.get('name','?')} {d_str} 命中{a.get('skill_value','?')}%")
    if "damage" in item:
        dmg = item["damage"]
        d_str = f"{dmg.get('dice_n',0)}D{dmg.get('dice_d',0)}+{dmg.get('bonus',0)}" if dmg.get('dice_d') else "特殊"
        print(f"   伤害: {d_str} | 射程: {item.get('range','?')} | 技能: {item.get('skill_name','?')}")
    if "boss_mechanics" in item:
        print(f"   Boss机制: {item['boss_mechanics'][:80]}...")
    desc = item.get("description", "") or item.get("special_rules", "")
    if desc:
        print(f"   描述: {str(desc)[:120]}")


def _write_enemies(new_items: list[dict]):
    with open(ENEMIES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("items", []).extend(new_items)
    with open(ENEMIES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  → 已写入 {len(new_items)} 个敌人到 {ENEMIES_PATH}")


def _write_bosses(new_items: list[dict]):
    with open(BOSSES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    for b in new_items:
        data[b["name"]] = b
    with open(BOSSES_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  → 已写入 {len(new_items)} 个 Boss 到 {BOSSES_PATH}")


def _write_weapons(new_items: list[dict]):
    with open(WEAPONS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("items", []).extend(new_items)
    with open(WEAPONS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  → 已写入 {len(new_items)} 个武器到 {WEAPONS_PATH}")


def main(text_path: str):
    if not os.path.exists(text_path):
        print(f"[错误] 文件不存在: {text_path}")
        return

    with open(text_path, "r", encoding="utf-8") as f:
        text = f.read()

    existing_enemy, existing_boss, existing_weapon = _load_existing()
    print(f"已加载 {len(existing_enemy)} 敌人 / {len(existing_boss)} Boss / {len(existing_weapon)} 武器")

    print("\n正在调用 LLM 提取...")
    result = _extract_via_llm(text)

    for category, existing_names, label in [
        ("enemies", existing_enemy, "敌人"),
        ("bosses", existing_boss, "Boss"),
        ("weapons", existing_weapon, "武器"),
    ]:
        items = result.get(category, [])
        if not items:
            continue

        new_items, dup_items = _dedup(items, existing_names)

        if dup_items:
            print(f"\n[{label}] 已存在（跳过）: {', '.join(d.get('name','?') for d in dup_items)}")

        if not new_items:
            continue

        print(f"\n── [{label}] 新发现 {len(new_items)} 个 ──")
        for item in new_items:
            _show_item(item)
            print()

        while True:
            choice = input(f"写入这 {len(new_items)} 个{label}？(y=全部写入 / n=跳过 / 1-N=逐个确认): ").strip().lower()
            if choice == "y":
                if category == "enemies":
                    _write_enemies(new_items)
                elif category == "bosses":
                    _write_bosses(new_items)
                else:
                    _write_weapons(new_items)
                break
            elif choice == "n":
                print("  跳过")
                break
            else:
                # 逐个确认
                confirmed = []
                for i, item in enumerate(new_items):
                    c = input(f"  [{i+1}] {item['name']} 写入？(y/n): ").strip().lower()
                    if c == "y":
                        confirmed.append(item)
                if confirmed:
                    if category == "enemies":
                        _write_enemies(confirmed)
                    elif category == "bosses":
                        _write_bosses(confirmed)
                    else:
                        _write_weapons(confirmed)
                break

    print("\n完成。")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python scripts/extract_library.py <文本文件.txt>")
        sys.exit(1)
    main(sys.argv[1])
