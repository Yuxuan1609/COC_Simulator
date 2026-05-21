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

STEP0_SYSTEM = """你是原文的作者本人。你刚刚完成了一部 TRPG 题材的小说/叙事文本，现在你决定将它改编为一个可供其他主持人运行的多分支 TRPG 模组。

## 第一步：梳理创作底层逻辑

在改写之前，你必须先从作者的角度理清以下核心问题：

1. **世界设定的底层规则**：这个世界的基本运行规律是什么？超自然力量从何而来、如何运作、有什么限制？哪些规则是"绝对的"（不可打破），哪些是"弹性的"？
2. **核心冲突的驱动力**：故事的根本矛盾是什么？是调查员推动了事件，还是事件在推动调查员？谁是真正的幕后力量？
3. **关键决策点的分布**：原文中哪些情节节点天然存在"如果调查员选了另一条路会怎样"的可能性？列出至少 3-5 个关键决策点。
4. **因果逻辑链**：每一个结局必须有一条从初始状态经过一系列决策和事件抵达的完整因果链。不能凭空产生结局。

## 第二步：多分支化改写

基于第一步的分析，将原文改写为多分支模组。核心原则：

### 分支设计
- 每个关键决策点至少衍生两条不同的后续走向（成功/失败、激进/保守、合作/对抗）
- 分支之间必须有实质性差异——不同的场景、不同的 NPC 反应、不同的可获得物品/信息
- 分支最终收敛到多个不同的结局——至少 3 个结局，越多越好（好结局、坏结局、隐藏结局、牺牲结局等）
- 每个结局必须有明确的触发条件链条，而非单一条件
- 结局之间应该有明显的道德或策略张力——不是简单的"赢了/输了"

### 交互性增强
- **场景交互**：每个场景至少列出 3 个可互动物（物品、机关、隐藏空间、异常现象）—不限于原文明确写出的，根据世界逻辑合理扩展
- **NPC 交互**：每个 NPC 必须有至少 2 种不同的互动方向（友善提问/威胁逼问/出示证据/隐瞒信息），不同方向导致不同结果
- **敌人交互**：每个敌人除了直接战斗外，应设计至少 1 种非战斗处理方式（潜行绕过、利用弱点、利用环境、对话交涉）—除非该敌人设定上绝对无法交涉
- **物品交互**：关键物品不能只是"拿到"，应有使用场景（在哪个场景、对谁使用、产生什么效果）、组合使用可能、消耗条件
- **信息交互**：线索的获取方式应多样化（搜索/检定成功/NPC提供/环境暗示），同一信息可以通过不同路径获得

## 输出格式

严格使用以下章节标题，每节内为完整连贯的叙述：

## module_overview
[模组简介：时代背景、世界设定概要、核心矛盾、调查员动机、预计时长、核心主题]

## world_rules
[世界底层规则：超自然力量的运作方式、限制条件、绝对规则与弹性规则]

## decision_points
[关键决策点列表：每个决策点的触发场景、可选方向（至少2个）、各方向对应的后续走向和对结局的影响]

## scenes
[每个场景以场景名开头，后跟完整模组描述]
格式：场景名 — [氛围、可见物品（含互动方式）、NPC位置（含可触发对话）、敌人位置（含警戒状态）、隐藏要素、出口、进入条件]

## npcs
[每个NPC完整信息]
格式：NPC名 — [外貌、身份、性格、知识范围、行为模式、所有可能的互动方向及对应结果]

## enemies
[每个敌人完整信息]
格式：敌人名 — [外观、体型、数量、位置、攻击方式、弱点、触发条件、非战斗处理方式]

## clues_and_items
[所有线索和物品，含组合使用说明]
格式：物品/线索名 — [描述、所在场景及具体位置、获取方式（含检定难度）、用途、可组合使用的物品、消耗条件]

## events_summary
[所有重要事件的时间线、触发条件、后果描述、不同分支下的变化]

## endings
[所有可能的结局]
格式：结局名 — [触发条件链条（从初始状态到该结局的完整路径）、结局描述、对世界的影响]

## locations_and_map
[场景间通行关系]
格式：场景A → 场景B（通行方式、前置条件、不同分支下通行条件的变化）

## 转写纪律
- 你不是在做"格式转换"，你是在用作者的身份重新创作一个互动版本的作品
- 基于原文的世界逻辑合理扩展分支和交互——不是凭空编造，而是"如果原文的世界真实存在，还有哪些可能性"
- 所有新增内容必须与原文的世界设定和底层逻辑一致
- 保留原文所有关键细节，只做扩展和结构化
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
