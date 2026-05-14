"""
四步渐进式解析器：从模组源文档逐步生成 L1 + L2 + L3 JSON。

流程:
  Step 1a: 结构化提取 (meta + scenes + characters)
  Step 1b: 精修模组 (condensed_text)
  Step 2a: interactions (先跑)
  Step 2b: events + auto_triggers (并行，注入 interaction IDs)
  Step 2c: L1 + L3 (并行)
  Step 3a: L2 依赖解析
  Step 3b: L1 ↔ L2 交叉核对
  Step 4:  Library 匹配 enemies/weapons

保底策略: 每步格式/内容失败 → 重调 (最多 N 次) → 仍失败则基于可解析内容写 JSON。
"""
from __future__ import annotations
import json
import os
from typing import Callable


# ═══════════════════════════════════════════════════════════════
#  Utility
# ═══════════════════════════════════════════════════════════════

def _load_template(name: str) -> str:
    """加载模板文件并格式化为示例 JSON 字符串."""
    template_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "templates")
    path = os.path.join(template_dir, name)
    with open(path, "r", encoding="utf-8") as f:
        template = json.load(f)
    return json.dumps(template, ensure_ascii=False, indent=2)


def _clean_json(raw: str) -> str:
    """清理 LLM 返回的 JSON 字符串（去除 markdown 包裹等）."""
    raw = raw.strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    return raw.strip()


def _safe_parse_json(raw: str) -> dict:
    """安全解析 JSON，失败返回空 dict."""
    try:
        return json.loads(_clean_json(raw))
    except json.JSONDecodeError:
        return {}


def _is_valid_json_output(data: dict, required_keys: list[str]) -> bool:
    """检查 JSON 输出是否格式合法且含必需的非空字段."""
    if not isinstance(data, dict):
        return False
    for key in required_keys:
        val = data.get(key)
        if val is None or (isinstance(val, (str, list, dict)) and len(val) == 0):
            return False
    return True


# ═══════════════════════════════════════════════════════════════
#  Fallback wrapper
# ═══════════════════════════════════════════════════════════════

def _with_fallback(
    parse_fn: Callable[[], dict],
    required_keys: list[str],
    fallback_data: dict,
    max_retries: int = 3,
    verbose: bool = True,
    step_name: str = "",
) -> dict:
    """
    包装一次 LLM 调用，含重试 + 保底策略。

    1. 调用 parse_fn()
    2. 检查 _is_valid_json_output → 通过返回
    3. 失败则重试 parse_fn() 最多 max_retries 次
    4. 全部失败 → 用 fallback_data + 标记 _fallback: True
    """
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            result = parse_fn()
            if _is_valid_json_output(result, required_keys):
                return result
            last_error = f"内容校验失败（缺失必需字段 {required_keys}）"
        except Exception as e:
            last_error = str(e)
        if verbose:
            print(f"  [{step_name}] 第 {attempt}/{max_retries} 次尝试失败: {last_error}")

    if verbose:
        print(f"  [{step_name}] 重调用尽，使用保底输出")
    fallback_data["_fallback"] = True
    fallback_data["_fallback_reason"] = last_error
    return fallback_data


# ═══════════════════════════════════════════════════════════════
#  Step 1a: 结构化提取
# ═══════════════════════════════════════════════════════════════

STEP1A_SYSTEM = """你是一个 TRPG 模组结构化解析助手。
你的任务是：从模组文档中提取模组的元信息、场景列表和人物列表，使用固定的 ID 体系。

重要原则：
- 场景 ID 使用 S1, S2, S3... 格式
- 人物 ID 使用 NPC_1, NPC_2... 格式
- 场景名和人物名使用原文中的中文名称
- 仅输出 JSON，不要任何解释性文字"""


def build_step1a_prompt(content: str) -> str:
    return f"""从以下模组文档中提取结构化信息。

输出格式:
{{
  "module_meta": {{"title": "模组标题", "era": "年代（如1920s）", "theme": "核心主题"}},
  "scenes": [
    {{"name": "场景中文名", "id": "S1"}},
    {{"name": "场景中文名", "id": "S2"}}
  ],
  "characters": [
    {{"name": "角色中文名", "id": "NPC_1"}},
    {{"name": "角色中文名", "id": "NPC_2"}}
  ]
}}

要求：
1. scenes 按玩家可能到达的顺序排列
2. characters 列出所有有名字或有重要作用的角色
3. 仅输出 JSON

模组文档：
\"\"\"
{content}
\"\"\""""


def parse_step1a(content: str, llm_call) -> dict:
    """从模组文档提取结构化元信息."""
    prompt = build_step1a_prompt(content)
    return llm_call(prompt, system=STEP1A_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 1b: 精修模组
# ═══════════════════════════════════════════════════════════════

STEP1B_SYSTEM = """你是一个 TRPG 模组编辑助手。
你的任务是：将模组文档整理为完整、流畅的半结构化叙事文本。

重要原则：
- 输出是一篇可直接阅读的完整模组文本，不是摘要或碎片列表
- 保留所有关键叙事细节，不压缩信息量
- 去除原作者备注、创作说明等非模组本体内容
- 原文模糊、不连贯或不合理处 → 基于上下文扩写和衔接
- 使用固定的 markdown 章节标题组织内容"""


def build_step1b_prompt(content: str) -> str:
    return f"""将以下模组文档整理为完整流畅的半结构化叙事文本。

输出格式（固定章节标题，每节内为完整叙事文本）:

## module_overview
[模组全局概述：核心设定、时代背景、整体叙事走向]

## scenes
[每个场景的完整叙事信息，以场景名开头]
例如: 6号车厢 — [场景的完整叙事描述，包含氛围、关键物品位置、可感知细节]

## npcs
[每个 NPC 的完整信息]
例如: 京山人吉 — [角色的完整描述，包含外貌、身份、行为模式]

## clues_and_items
[所有关键线索和物品的完整描述，包含位置、获取方式、关联信息]

## events_summary
[所有重要事件的时间线和触发条件描述]

要求：
1. 以完整叙事行文呈现，确保阅读流畅
2. 不压缩信息量，不简化关键细节
3. 去除原作者备注等非模组内容，但原文信息不能丢失
4. 原文模糊处可基于上下文合理扩写
5. 整个 condensed_text 应该可以作为后续 LLM 提取信息的唯一来源
6. 仅输出以上 markdown 格式文本，不要 JSON 包裹

模组文档：
\"\"\"
{content}
\"\"\""""


def parse_step1b(content: str, llm_call) -> dict:
    """从模组文档生成精修模组文本."""
    prompt = build_step1b_prompt(content)
    raw = llm_call(prompt, system=STEP1B_SYSTEM)
    if isinstance(raw, str):
        return {"condensed_text": raw}
    if isinstance(raw, dict):
        return raw
    return {"condensed_text": str(raw)}
