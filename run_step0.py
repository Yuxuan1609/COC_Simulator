"""Step 0: 将小说叙事文本转写为 TRPG 模组格式。
用法: python run_step0.py <输入小说路径> [输出路径]
默认输出: data/modules/<模块名>/module_step0.txt
"""
import sys, os, json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "src")
from llm import call_deepseek, set_llm_log_dir
from datetime import datetime

STEP0_SYSTEM = """你是一个经验丰富的 TRPG 模组作者。你的任务是将小说/叙事文本转写为标准的 TRPG 模组文档。

转写规则：
1. 将小说中的叙事视角转换为模组的客观描述——所有"他感到"、"她想起"改为"调查员可以发现"、"此场景中"
2. 将小说人物（除明确为NPC者）抽象为"调查员"——删除小说主角的内心独白和个人背景，仅保留与场景/事件直接相关的行动
3. 保留所有NPC的完整信息（外貌、身份、性格、知识、行为模式、可能提供的线索）
4. 保留所有场景的完整描述（位置、氛围、可见物品、出口、危险）
5. 保留所有可获取物品和线索（位置、获取方式、用途、关联信息）
6. 保留所有敌人信息（外观、属性直觉、攻击方式、弱点、行为模式）
7. 保留所有事件的时间线和触发条件
8. 保留所有结局条件和分支
9. 去除小说化的修辞、心理描写、人物回忆等非模组要素
10. 使用固定的章节标题组织内容

输出格式（严格遵循）:

## module_overview
[模组简介：时代背景、核心设定、调查员动机、整体叙事走向、预计时长。200-400字]

## scenes
[每个场景以场景名开头，后跟完整模组描述]
格式：场景名 — [场景描述（含氛围、可见物品位置、NPC位置、可感知细节）]

## npcs
[每个NPC完整信息]
格式：NPC名 — [外貌、身份、性格、知识范围、行为模式、可提供的线索/互动。若NPC已在某些场景中死亡/不可互动，标注状态]

## enemies
[每个敌人完整信息]
格式：敌人名 — [外观、体型、数量、位置、攻击方式、弱点、触发条件]

## clues_and_items
[所有线索和物品]
格式：物品/线索名 — [描述、所在场景及具体位置、获取方式、用途与关联信息]

## events_summary
[所有重要事件的时间线、触发条件、后果描述]
格式：时间/条件 — [事件描述、触发方式、对世界的影响]

## endings
[所有可能的结局和触发条件]
格式：结局名 — [触发条件、结局描述]

## locations_and_map
[场景间通行关系]
格式：场景A → 场景B（通行方式、前置条件）

转写要求：
- 严格使用上述章节标题，每节内为完整连贯的叙述
- 字数充裕，不压缩信息量
- 所有非人类可交流的怪物/邪教徒归入 enemies 而非 npcs
- NPC 仅在调查员可以与之有意义对话或互动时才列为 npc
- 保留原文中的所有关键细节，仅改变叙述视角和格式
- 仅输出模组文本，不要任何解释性前言或后记"""


def run_step0(input_path: str, output_path: str | None = None):
    # 读取小说
    content = Path(input_path).read_text(encoding="utf-8")
    module_name = Path(input_path).parent.name if Path(input_path).parent.name else "module"
    
    if output_path is None:
        out_dir = Path("data/modules") / module_name
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = out_dir / "module_step0.txt"
    else:
        output_path = Path(output_path)
    
    print(f"输入: {input_path} ({len(content)} 字符)")
    print(f"输出: {output_path}")
    
    # 构建 prompt
    prompt = f"""将以下小说/叙事文本转写为 TRPG 模组文档。

原文：
\"\"\"
{content}
\"\"\"

请按指定格式输出完整模组文档。"""
    
    print(f"Prompt: {len(prompt)} 字符")
    
    # 调用 LLM（非 JSON 模式，因为输出是长文本）
    print("调用 LLM (Step 0 — 小说转模组)...")
    result = call_deepseek(
        prompt,
        json_mode=False,
        system=STEP0_SYSTEM,
        model="deepseek-v4-pro",
        reasoning_effort="max",
        temperature=0.3,
        max_tokens=162840,
    )
    
    # 保存结果
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result, encoding="utf-8")
    print(f"完成: {len(result)} 字符 → {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python run_step0.py <小说路径> [输出路径]")
        sys.exit(1)
    run_step0(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
