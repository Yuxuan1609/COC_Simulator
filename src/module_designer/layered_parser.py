"""
四步渐进式解析器：从模组源文档逐步生成 L1 + L2 + L3 JSON。

流程:
  Step 1a: 结构化提取 (meta + scenes + characters)
  Step 1b: 精修模组 (condensed_text)
  Step 2a: interactions + locations (先跑)
  Step 2b: events + auto_triggers (并行，注入 interaction IDs)
  Step 2c: L1 + L3 (并行)
  Step 3a: L2 依赖解析 + L2生成
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

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "templates")


def load_json(filepath: str) -> dict:
    """从文件路径加载 JSON 文件，返回解析后的 dict."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_template(name: str) -> str:
    """加载模板文件并格式化为示例 JSON 字符串."""
    path = os.path.join(TEMPLATE_DIR, name)
    template = load_json(path)
    return json.dumps(template, ensure_ascii=False, indent=2)


# 预加载三个模板文件，供其他模块使用
L1_TEMPLATE = load_json(os.path.join(TEMPLATE_DIR, "l1_template.json"))
L2_TEMPLATE = load_json(os.path.join(TEMPLATE_DIR, "l2_template.json"))
L3_TEMPLATE = load_json(os.path.join(TEMPLATE_DIR, "l3_template.json"))


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
    return {**fallback_data, "_fallback": True, "_fallback_reason": last_error}


# ═══════════════════════════════════════════════════════════════
#  Step 1a: 结构化提取
# ═══════════════════════════════════════════════════════════════

STEP1A_SYSTEM = """你是一个优秀的 TRPG 模组结构化解析助手。
你的任务是：从模组文档中提取模组的元信息、场景列表和人物列表，使用固定的 ID 体系。

重要原则：
- 场景 ID 使用 S1, S2, S3... 格式
- 人物 ID 使用 NPC_1, NPC_2... 格式
- 场景名和人物名使用原文中的中文名称
- 仅输出 JSON，不要任何解释性文字
- 如果模组文档没有出现可以为空，保留占位符
- 注意：不能理智性交互或有意义对话的怪物/邪教徒不属characters
"""



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

STEP1B_SYSTEM = """你是一个优秀的TRPG 模组作者。
你的任务是：将模组文档整理为完整、流畅的半结构化叙事文本。

重要原则：
- 输出是一篇可直接阅读的完整模组文本，不是摘要或碎片列表
- 保留所有关键叙事细节，不压缩信息量
- 去除原作者备注、创作说明等非模组本体内容
- 原文模糊、不连贯或不合理处 → 基于上下文扩写和衔接
- 使用固定的 markdown 章节标题组织内容
- 输出结果应该易于理解同时保留较高的文学性和充足的信息
"""

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
如果模组文档没有出现可以为空，保留章节名即可
注意：不能理智性交互或有意义对话的怪物/邪教徒不属于npcs属于enemies

## enemies
[每个敌人信息]
例如: 深潜者 —敌人的整体设定[体型大小、习惯、攻击方式和攻击条件等]
如果模组文档没有出现可以为空，保留章节名即可
注意：不能理智性交互或有意义对话的怪物/邪教徒不属于npcs属于enemies

## clues_and_items
[所有关键线索和物品的完整描述，包含位置、获取方式、关联信息]

## events_summary
[所有重要事件的时间线和触发条件描述尤其是结局事件和与结局相关的事件]

##locations_and_map
[每个场景可通往的场景，方式、前置条件（如果有）]
例如：场景A（当前场景）可通往场景B,方式是走路或其他常规方式，没有前置条件

要求：
1. 以完整叙事行文呈现，确保阅读流畅
2. 不压缩信息量，不简化关键细节
3. 去除原作者备注等非模组内容，但原文信息不能丢失
4. 原文模糊处可基于上下文合理扩写，扩写时注意逻辑和文学性
5. 整个 condensed_text 应该可以作为后续 LLM 提取信息的唯一来源
6. 仅输出以上 markdown 格式文本，不要 JSON 包裹
7. 命名应该尽可能的统一

模组文档：
\"\"\"
{content}
\"\"\"
"""


def parse_step1b(content: str, llm_call) -> dict:
    """从模组文档生成精修模组文本."""
    prompt = build_step1b_prompt(content)
    raw = llm_call(prompt, system=STEP1B_SYSTEM)
    if isinstance(raw, str):
        return {"condensed_text": raw}
    if isinstance(raw, dict):
        return raw
    return {"condensed_text": str(raw)}


# ═══════════════════════════════════════════════════════════════
#  Step 2a: Interactions
# ═══════════════════════════════════════════════════════════════

STEP2A_SYSTEM = """你是一个 TRPG 模组解析助手，专门提取场景中的可执行互动和通行路径。
你的任务是：从精修模组文本中提取每个场景的全部互动选项，以及场景间的通行路径。

重要原则：
- enemy_ref 和 weapon_ref 留空（填 null），等待后续步骤匹配
- requirement 是硬性前置条件：必须已完成的 interaction ID 或必须持有的物品。如 "interaction:I3 已完成"、"持有手电筒"。无条件则填空字符串
- trigger 是触发场景描述：什么情况下玩家可以执行此互动。如 "玩家检查抽屉时"、"玩家进入此场景时"
- result 是直接结果：互动直接产生的结果。如 "抽屉打开了，里面有一把钥匙"。如果此互动会导致游戏结局，result 必须以 ##END_结局名称:结局简述## 开头，如 "##END_真结局:电车冲出梦境## 调查员们成功..."
- side_effects 是间接后果：与 result 不重合的附带影响。如 "开抽屉的声响吸引了隔壁车厢的怪物"。自然语言字符串列表
- 互动完成即代表状态变更，不需要单独的 flag
- type 涉及技能鉴定时，填入 graded_result（分级检定后果），此时 result 填 "##GRADED##"（占位标记），side_effects 留空。所有结果描述写入 graded_result 各等级中；type 为"无"时不填 graded_result
- based_on 始终为 null（Step 2b 会给派生实体填值）
- 通行路径记录每个场景的出边（from_here）和入边（to_here），包含通行方式和前置条件
- 仅输出 JSON，不要任何解释性文字"""


def build_step2a_prompt(condensed_text: str, scenes: list[dict]) -> str:
    scene_list = "\n".join(
        f"- {s['id']}: {s['name']}" for s in scenes
    )
    return f"""从精修模组文本中提取每个场景的全部可执行互动，以及场景间的通行路径。

已知场景列表:
{scene_list}

输出格式:
{{
  "interactions": [
    {{
      "id": "I1",
      "scene": "S1",
      "type":  关联技能鉴定如“侦察”、“急救”等，不涉及则为“无”,
      "name": "互动名称",
      "requirement": "硬性前置条件（必须已完成的 interaction ID 或持有特定物品），如：interaction:I3 已完成。无条件填空字符串",
      "trigger": "触发场景（描述什么情况下玩家可以执行此互动），如：玩家检查抽屉时",
      "result": "直接结果（互动直接产生的结果），如：抽屉打开了，里面有一把钥匙",
      "side_effects": ["间接后果（与result不重合的附带影响），如：开抽屉的声响吸引了隔壁车厢的怪物。无条件则为空列表"],
      "graded_result": {{"on_failure": "...", "on_regular": "...", "on_hard": "...", "on_extreme": "..."}},
      "enemy_ref": null,
      "weapon_ref": null,
      "difficulty": "regular",
      "based_on": null
    }}
  ],
  "scene_movements": {{
    "S1": {{
      "from_here": [
        {{"target": "S2", "method": "步行通过车门", "requirement": "门未上锁"}}
      ],
      "to_here": [
        {{"source": "S0", "method": "步行通过车门", "requirement": ""}}
      ]
    }},
    "S2": {{ ... }}
  }}
}}

要求：
1. id 全局唯一 (I1, I2, I3...)
2. scene 使用给定列表中的 ID (S1, S2...)
3. enemy_ref 和 weapon_ref 全部填 null（等后续步骤处理）
4. requirement 是硬性前置条件：必须已完成的 interaction ID 或持有特定物品。无条件填空字符串。不要和 trigger 混淆
5. trigger 是触发场景：描述什么情况下玩家可以执行此互动。不要和 requirement 混淆
6. result 是直接结果：互动直接产生的可感知结果，不含间接影响。如果此互动会直接触发游戏结局，result 必须以 ##END_结局名称:结局简述## 开头（如 "##END_真结局:电车冲出梦境##"），后续再写正常结果文本
7. side_effects 是间接后果：与 result 不重合的附带影响。自然语言字符串列表。无条件则为空列表
8. type 是涉及的技能鉴定名，不涉及则为”无”
9. difficulty 从以下选择：None/regular/hard/extreme；不涉及鉴定则为 None
10. graded_result：type 不为”无”时填写。此时 result 必须填 “##GRADED##”（占位标记），side_effects 必须留空。所有结果文字写入 graded_result 的四等级中。四等级含义：on_failure=检定失败、on_regular=常规成功、on_hard=困难成功、on_extreme=极难成功。若原文未区分等级结果，各等级可描述相同内容
11. 提取原文中提到的所有互动，即使描述简略也要列出
12. scene_movements 必须覆盖所有已知场景
13. 通行路径的 target/source 使用场景 ID，method 描述通行方式，requirement 描述硬性通行前置条件
14. 严格依据精修模组内容，基于场景氛围合理补充，不要和原文冲突
15. based_on 始终填 null（派生关系由 Step 2b 标注）
精修模组：
\"\"\"
{condensed_text}
\"\"\""""
def parse_step2a(condensed_text: str, scenes: list[dict], llm_call) -> dict:
    """从精修模组提取所有 interactions."""
    prompt = build_step2a_prompt(condensed_text, scenes)
    return llm_call(prompt, system=STEP2A_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 2b: Events
# ═══════════════════════════════════════════════════════════════

STEP2B_EVENTS_SYSTEM = """你是一个 TRPG 模组解析助手，专门提取全局不可逆事件。
你的任务是：从精修模组文本和已知互动中派生全局事件。事件是跨场景的、不可逆的世界级变化。

重要原则：
- 事件使用与 interaction 相同的统一字段模型
- 事件无 scene 字段（全局事件不绑定特定场景）
- based_on 只能指向已知的 interaction ID
- requirement 是硬性前置条件（必须已完成的 interaction ID 或持有特定物品）；trigger 是触发场景描述，两者不可混淆
- result 是直接结果（含不可逆性标注）。如果此事件会导致游戏结局，result 必须以 ##END_结局名称:结局简述## 开头
- side_effects 是与 result 不重合的间接后果
- type 涉及技能鉴定时填写 graded_result，此时 result 填 "##GRADED##"，side_effects 留空。四等级对应检定失败/常规成功/困难成功/极难成功
- 仅输出 JSON，不要任何解释性文字"""


def build_step2b_events_prompt(
    condensed_text: str,
    scenes: list[dict],
    interactions: list[dict],
) -> str:
    scene_list = "\n".join(f"- {s['id']}: {s['name']}" for s in scenes)
    interaction_list = "\n".join(
        f"- {i['id']}: {i['name']} → {i.get('result', '')} (场景 {i['scene']})"
        for i in interactions
    )
    return f"""从精修模组文本中提取所有全局不可逆事件。

已知场景:
{scene_list}

已知互动（事件只能基于这些互动派生，based_on 必须指向其 ID）:
{interaction_list}

输出格式:
{{
  "events": [
    {{
      "id": "E1",
      "type": "关联技能名，不涉及填\"无\"",
      "name": "事件名称",
      “requirement”: “硬性前置条件（必须已完成的 interaction ID 或持有特定物品），无条件填空字符串”,
      “trigger”: “触发场景（描述什么情况下此事件触发），如：I5 完成后此事件触发”,
      “result”: “直接结果（事件直接产生的结果，含不可逆标注）”,
      “side_effects”: [“间接后果（与result不重合的附带影响），无条件则为空列表”],
      “graded_result”: {{“on_failure”: “...”, “on_regular”: “...”, “on_hard”: “...”, “on_extreme”: “...”}},
      “difficulty”: “None/regular/hard/extreme”,
      “based_on”: “I1”
    }}
  ]
}}

要求：
1. id 全局唯一 (E1, E2, E3...)
2. based_on 只能指向已知的 interaction ID，非派生事件则填空字符串
3. requirement 是硬性前置条件；trigger 是触发场景描述，两者不可混淆
4. result 是直接结果：不可逆事件需明确标注”不可逆：”。如果此事件会导致游戏结局，result 必须以 ##END_结局名称:结局简述## 开头（如 “##END_坏结局:电车坠入黑暗## 不可逆：调查员们永远被困在噩梦中”）
5. side_effects 是间接后果：与 result 不重合的附带影响。无条件则为空列表
6. type 是关联技能名，不涉及填”无”；涉及鉴定时填写 graded_result。此时 result 填 “##GRADED##”，side_effects 留空。四等级对应检定失败/常规成功/困难成功/极难成功。若原文未区分等级，各等级可描述相同
7. difficulty 从以下选择：None/regular/hard/extreme；不涉及检定则为 None
8. 事件是全局的，不绑定特定场景（无 scene 字段）

精修模组：
\"\"\"
{condensed_text}
\"\"\""""


def parse_step2b_events(
    condensed_text: str,
    scenes: list[dict],
    interactions: list[dict],
    llm_call,
) -> dict:
    prompt = build_step2b_events_prompt(condensed_text, scenes, interactions)
    return llm_call(prompt, system=STEP2B_EVENTS_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 2b: Auto-triggers
# ═══════════════════════════════════════════════════════════════

STEP2B_AT_SYSTEM = """你是一个 TRPG 模组解析助手，专门生成自动触发事件。
你的任务是：基于精修模组和已知互动，生成所有被动触发事件（auto_trigger）。

重要原则：
- auto_trigger 使用与 interaction 相同的统一字段模型
- auto_trigger 绑定特定场景（scene 字段必填）
- based_on 只能指向已知的 interaction ID
- enemy_ref 和 weapon_ref 留空（填 null），等待 Step 4 library 匹配
- requirement 是硬性前置条件；trigger 是触发场景描述，两者不可混淆
- result 是直接结果：如果此自动触发会导致游戏结局，必须以 ##END_结局名称:结局简述## 开头
- side_effects 是与 result 不重合的间接后果
- type 涉及技能鉴定时填写 graded_result，此时 result 填 "##GRADED##"，side_effects 留空。四等级对应检定失败/常规成功/困难成功/极难成功
- 只生成被动触发的事件，不要生成玩家主动互动
- 仅输出 JSON，不要任何解释性文字"""


def build_step2b_at_prompt(
    condensed_text: str,
    scenes: list[dict],
    interactions: list[dict],
) -> str:
    scene_list = "\n".join(f"- {s['id']}: {s['name']}" for s in scenes)
    interaction_list = "\n".join(
        f"- {i['id']}: {i['name']} → {i.get('result', '')} (场景 {i['scene']})"
        for i in interactions
    )
    return f"""从精修模组文本中生成所有自动触发事件。

已知场景:
{scene_list}

已知互动（auto_trigger 只能基于这些互动派生，based_on 必须指向其 ID）:
{interaction_list}

输出格式:
{{
  "auto_triggers": [
    {{
      "id": "AT1",
      "scene": "S1",
      "type": "关联技能名，不涉及填\"无\"",
      "name": "自动触发名称",
      "requirement": "硬性前置条件（必须已完成的 interaction ID 或持有特定物品），无条件填空字符串",
      "trigger": "触发场景（描述什么情况下此被动事件触发），如：玩家进入场景且 I1 已完成",
      "result": "直接结果（被动触发直接产生的结果）",
      "side_effects": ["间接后果（与result不重合的附带影响），无条件则为空列表"],
      "graded_result": {{"on_failure": "...", "on_regular": "...", "on_hard": "...", "on_extreme": "..."}},
      "enemy_ref": null,
      "weapon_ref": null,
      "difficulty": "None/regular/hard/extreme",
      "based_on": "I1"
    }}
  ]
}}

要求：
1. id 全局唯一 (AT1, AT2, AT3...)
2. scene 使用给定列表中的 ID
3. based_on 只能指向已知的 interaction ID
4. enemy_ref 和 weapon_ref 全部填 null
5. requirement 是硬性前置条件；trigger 是触发场景描述，两者不可混淆
6. result 是直接结果：如果会触发游戏结局，必须以 ##END_结局名称:结局简述## 开头；side_effects 是间接后果（与 result 不重合）
7. type 是关联技能名，不涉及填"无"；涉及鉴定时填写 graded_result。此时 result 填 "##GRADED##"，side_effects 留空。四等级含义同上，原文未区分时各等级可相同
8. difficulty 从以下选择：None/regular/hard/extreme；不涉及检定则为 None
9. 每个场景至少生成 0-2 个 auto_trigger

精修模组：
\"\"\"
{condensed_text}
\"\"\""""


def parse_step2b_at(
    condensed_text: str,
    scenes: list[dict],
    interactions: list[dict],
    llm_call,
) -> dict:
    prompt = build_step2b_at_prompt(condensed_text, scenes, interactions)
    return llm_call(prompt, system=STEP2B_AT_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 2c: L1 玩家可见层
# ═══════════════════════════════════════════════════════════════

STEP2C_L1_SYSTEM = """你是一个 TRPG 模组解析助手，专门提取「玩家可见层」信息。
你的任务是：从精修模组文本中提取每个场景的初始感知信息——玩家进入场景时无需任何检定即可直接感知的一切。

重要原则：
- 严格按照输出格式参考输出 json 文件
- 只描述无条件可见的内容（外观、声音、气味、氛围）
- 需要检定才能发现的信息 → 不放在这里（那是 L2 的事）
- NPC 只描述外貌和神态，不写隐藏动机
- 你是模组叙述者，你只负责描述玩家“现在”能见到/感受到的信息
"""


def build_step2c_l1_prompt(condensed_text: str, scenes: list[dict], characters: list[dict]) -> str:
    template = _load_template("l1_template.json")
    scene_list = "\n".join(f"- {s['id']}: {s['name']}" for s in scenes)
    char_list = "\n".join(f"- {c['id']}: {c['name']}" for c in characters) if characters else "（无）"
    return f"""从精修模组文本中提取每个场景的「玩家初始感知信息」。

已知场景列表（必须使用这些场景名作为 JSON key）:
{scene_list}

已知角色列表（npc_appearances 中的 NPC 名称必须来自此列表）:
{char_list}

输出格式参考：
{template}

要求：
1. 每个场景使用其名称作为顶层 key（如"6号车厢"）
2. description：描述场景基本信息的叙事文本（KP 可直接朗读，30-200字）
3. atmosphere：场景氛围一句话总结
4. perceptible：玩家无需检定即可感知的元素列表
5. ambient_hints：微妙的环境线索列表
6. npc_appearances：当前场景 NPC 的外貌描述，NPC 名称必须使用已知角色列表中的名称

重要：
- 仅输出 JSON，不要任何解释性文字
- 只写无条件可见的感知信息
- 需要检定才能发现的内容留给 L2 层
- 场景 key 名必须与给定列表中的 name 一致
- 只列出当前场景确实在场的 NPC

精修模组：
\"\"\"
{condensed_text}
\"\"\""""


def parse_step2c_l1(condensed_text: str, scenes: list[dict], characters: list[dict], llm_call) -> dict:
    prompt = build_step2c_l1_prompt(condensed_text, scenes, characters)
    return llm_call(prompt, system=STEP2C_L1_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 2c: L3 设计者层
# ═══════════════════════════════════════════════════════════════

STEP2C_L3_SYSTEM = """你是一个优秀的 TRPG 模组设计师，专门提取「设计者层」信息。
你的具体任务是：从精修模组文本中提取模组的设计意图、世界规则、场景设计目的、NPC行为逻辑和基调约束。

重要原则：
- 这是设计者层，描述「为什么」这个模组这样设计，而非「有什么」内容
- world_rules 是世界运行的物理/超自然法则
- scene_intents 描述每个场景的设计目的
- characters 描述每个 NPC 的行为逻辑和叙事作用（设计意图，不是具体对话内容）
- driving_force 是一切事件的根本驱动力
- 你作为高层叙事者不必完全拘泥于精修模组的已有内容，可以基于原文进行合理的补充和推测
"""


def build_step2c_l3_prompt(condensed_text: str, scenes: list[dict], characters: list[dict]) -> str:
    template = _load_template("l3_template.json")
    scene_list = "\n".join(f"- {s['id']}: {s['name']}" for s in scenes)
    char_list = "\n".join(f"- {c['id']}: {c['name']}" for c in characters) if characters else "（无）"
    return f"""从精修模组文本中提取「设计者层」信息（L3 层）。

已知场景列表:
{scene_list}

已知角色列表（characters 的 id 和 name 必须来自此列表）:
{char_list}

输出格式参考：
{template}

要求：
1. module_meta：模组元信息
2. world_rules：描述世界运行规则列表，每个含 id (WR1, WR2...), name, rule, scope, is_absolute
    - 例如: 当前模组基于梦境展开，所以使用现代科技对抗是不可能的
3. scene_intents：每个场景的设计意图，key 为已知场景列表，value 含 purpose / key_threat (可选) / notes (可选)
4. ending_conditions：结局条件列表，每个含 id / condition / narrative
5. tone_constraints：全局叙事护栏，含 genre / forbidden / recommended / narrative_style
6. characters：每个 NPC 的设计意图，含 id (使用已知角色列表中的 ID), name (使用已知角色列表中的名称), behavior (行为逻辑 + 叙事作用)
7. driving_force：一切事件的底层驱动力
8. 你是高层叙事者，你的工作应该关注于一切为什么是这样/这个场景为什么要这么写。不要过度关注具体的规则和信息。

重要：
- 仅输出 JSON，不要任何解释性文字
- 从原文中推断设计意图，即使原文没有明确声明
- scene_intents 的 key 必须覆盖所有已知场景
- characters 必须覆盖已知角色列表中的所有角色

精修模组：
\"\"\"
{condensed_text}
\"\"\""""


def parse_step2c_l3(condensed_text: str, scenes: list[dict], characters: list[dict], llm_call) -> dict:
    prompt = build_step2c_l3_prompt(condensed_text, scenes, characters)
    return llm_call(prompt, system=STEP2C_L3_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 3a: L2 依赖解析
# ═══════════════════════════════════════════════════════════════

STEP3A_SYSTEM = """你是一个 TRPG 逻辑验证助手，专门做模组信息的去重和冲突解决。
你的任务是：检查所有 interaction/event/auto_trigger，基于 based_on 去重，验证 graded_result，修剪 result/side_effects 重合，解决冲突，验证结局标记。

重要原则：
- based_on 已标注派生关系。若两个 entity 的 based_on 指向同一 interaction 且语义重复（name/result 高度相似），合并为一个
- graded_result 在 type != "无" 时建议填写但不强制；type == "无" 时删除空 graded_result
- result 和 side_effects 信息重合时修剪一方。result 为 "##GRADED##" 时跳过此检查
- requirement/trigger 冲突以 condensed_text 为准修正
- ##END_## 标记与 L3 ending_conditions 相互补齐
- 不删改实质信息，只修正名称和引用
- 互动完成即代表状态变更，不需要单独的 flag
- 仅输出 JSON，不要任何解释性文字"""


def build_step3a_prompt(
    condensed_text: str,
    interactions: list[dict],
    events: list[dict],
    auto_triggers: list[dict],
    ending_conditions: list[dict],
) -> str:
    return f"""对以下模组中的所有 L2 内容做去重、冲突解决和结局验证。

## 精修模组（参考上下文）
\"\"\"
{condensed_text}
\"\"\"

## L3 结局条件（用于验证 ##END_## 标记）
{json.dumps(ending_conditions, ensure_ascii=False, indent=2)}

## Interactions
{json.dumps(interactions, ensure_ascii=False, indent=2)}

## Events（based_on 指向派生的 interaction，无 scene）
{json.dumps(events, ensure_ascii=False, indent=2)}

## Auto-triggers（based_on 指向派生的 interaction，有 scene）
{json.dumps(auto_triggers, ensure_ascii=False, indent=2)}

任务:
1. **Based_on 去重**: 若两个 entity 的 based_on 指向同一 interaction 且 name/result 语义高度相似，合并为一个（保留较完整的版本，删除重复的）。
2. **Graded_result 检查**: type != "无" 时建议填写 graded_result 但不强制；type == "无" 时删除空 graded_result。
3. **Result / Side_effects 去重**: 若 result 为 "##GRADED##" 跳过此检查。否则若 side_effects 中的某条内容已在 result 中体现，移除该条。
4. **冲突解决**: requirement/trigger 矛盾以 condensed_text 为准修正。
5. **结局标记验证**: 扫描 ##END_## 标记与 L3 ending_conditions 做语义匹配。标记缺失则相互补齐。

输出格式:
{{
  "interactions": [{{ ...原字段... }}],
  "events": [{{ ...原字段... }}],
  "auto_triggers": [{{ ...原字段... }}]
}}

仅输出 JSON。"""


def parse_step3a(
    condensed_text: str,
    interactions: list[dict],
    events: list[dict],
    auto_triggers: list[dict],
    ending_conditions: list[dict],
    llm_call,
) -> dict:
    prompt = build_step3a_prompt(condensed_text, interactions, events, auto_triggers, ending_conditions)
    return llm_call(prompt, system=STEP3A_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 3b: L1 ↔ L2 交叉核对
# ═══════════════════════════════════════════════════════════════

STEP3B_SYSTEM = """你是一个 TRPG 一致性校对助手。
你的任务是：检查 L1 与 L2/L3 的交叉引用和命名一致性，修正不一致。

重要原则：
- linked_interaction 必须指向 L2 中真实存在的 interaction name
- L1 中的 NPC 名称必须与 L3 characters 中的名称一致
- 场景名必须在所有层中一致
- 仅修正名称和引用，不改变实质内容
- 仅输出 JSON，不要任何解释性文字"""


def build_step3b_prompt(
    condensed_text: str,
    l1_data: dict,
    l2_completed: dict,
    l3_data: dict,
    step1_scenes: list[dict],
) -> str:
    scene_names = ", ".join(s['name'] for s in step1_scenes)
    return f"""核对 L1 与 L2 的交叉引用。

## 精修模组（参考上下文）
\"\"\"
{condensed_text}
\"\"\"

## 统一场景名（Step 1 确定）
{scene_names}

## L1 数据
{json.dumps(l1_data, ensure_ascii=False, indent=2)}

## L2 完整数据（已通过 Step 3a 补全依赖）
{json.dumps(l2_completed, ensure_ascii=False, indent=2)}

## L3 数据
{json.dumps(l3_data, ensure_ascii=False, indent=2)}

任务:
1. L1 场景名是否与统一场景名一致 → 不一致则修正
2. L1 linked_interaction 是否指向 L2 中存在的 interaction name → 不存在则修正或清空
3. L1 npc_appearances 中 NPC 名称是否与 L3 characters 中的名称一致 → 不一致则统一为 L3 中的名称
4. 检查 L1 感知元素是否应关联 L2 互动但未关联 → 补充 linked_interaction
5. L3 scene_intents 的 key 是否覆盖所有场景 → 缺失则补充
6. L3 characters 是否覆盖所有在 L1/L2 中出现的 NPC → 缺失则补充
7. 所有层的场景名和角色名统一

输出格式:
{{
  "l1_data": {{ ...修正后的 L1... }},
  "l3_data": {{ ...修正后的 L3... }}
}}

仅输出 JSON。"""


def parse_step3b(
    condensed_text: str,
    l1_data: dict,
    l2_completed: dict,
    l3_data: dict,
    step1_scenes: list[dict],
    llm_call,
) -> dict:
    prompt = build_step3b_prompt(condensed_text, l1_data, l2_completed, l3_data, step1_scenes)
    return llm_call(prompt, system=STEP3B_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 3.5: 依赖图构建
# ═══════════════════════════════════════════════════════════════

STEP35_SYSTEM = """你是一个 TRPG 依赖关系解析助手。
你的任务是：检查所有 interaction/event/auto_trigger 的 requirement 和 trigger 字段，将其中描述的依赖关系标准化为结构化 JSON。

重要原则：
- 从 requirement 和 trigger 的自然语言中提取依赖关系
- requirement 中的 "interaction:I3 已完成" → {{"type": "interaction", "id": "I3", "condition": "completed"}}
- requirement 中的 "持有手电筒" → {{"type": "item", "name": "手电筒", "condition": "possess"}}
- trigger 中的 "E1 已触发" → {{"type": "event", "id": "E1", "condition": "triggered"}}
- 每条 entity 的 requires 列出所有提取到的依赖（可为空列表）
- 仅输出 JSON，不要任何解释性文字"""


def build_step35_prompt(
    condensed_text: str,
    interactions: list[dict],
    events: list[dict],
    auto_triggers: list[dict],
) -> str:
    interaction_list = json.dumps(interactions, ensure_ascii=False, indent=2)
    events_list = json.dumps(events, ensure_ascii=False, indent=2)
    at_list = json.dumps(auto_triggers, ensure_ascii=False, indent=2)
    return f"""从以下 L2 实体的 requirement 和 trigger 字段中提取并标准化所有依赖关系。

## 精修模组（参考上下文）
\"\"\"
{condensed_text}
\"\"\"

## Interactions
{interaction_list}

## Events
{events_list}

## Auto-triggers
{at_list}

任务:
1. 扫描每个 entity 的 requirement 和 trigger 字段
2. 提取其中描述的依赖关系，标准化为:
   - interaction 依赖: {{"type": "interaction", "id": "I3", "condition": "completed"}} 或 "not_completed"
   - event 依赖: {{"type": "event", "id": "E1", "condition": "triggered"}} 或 "not_triggered"
   - auto_trigger 依赖: {{"type": "auto_trigger", "id": "AT1", "condition": "triggered"}}
   - item 依赖: {{"type": "item", "name": "手电筒", "condition": "possess"}} 或 "not_possess"
3. 每条 entity 必须在输出中列出，requires 为空列表表示无依赖
4. 实体 ID 必须精确匹配（如 I3 不能写成 I03）

输出格式:
{{
  "dependencies": [
    {{
      "entity_id": "I1",
      "requires": []
    }},
    {{
      "entity_id": "I3",
      "requires": [
        {{"type": "interaction", "id": "I1", "condition": "completed"}}
      ]
    }}
  ]
}}

仅输出 JSON。"""


def parse_step35(
    condensed_text: str,
    interactions: list[dict],
    events: list[dict],
    auto_triggers: list[dict],
    llm_call,
) -> dict:
    prompt = build_step35_prompt(condensed_text, interactions, events, auto_triggers)
    return llm_call(prompt, system=STEP35_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 4: Library 匹配
# ═══════════════════════════════════════════════════════════════

STEP4_SYSTEM = """你是一个 TRPG 游戏资源配置助手。
你的任务是：根据模组内容和场景需求，统一做所有标准化处理：enemy_ref/weapon_ref 匹配、技能名/属性名标准化、side_effect 结构化。

重要原则：
- 必须从提供的库列表中选择，不允许自创名称
- 若无合适的库条目，填 "none"
- 技能名必须从标准技能列表中选择
- 属性名必须从标准属性列表中选择
- side_effect 从自然语言解析为结构化对象
- 仅输出 JSON，不要任何解释性文字"""


def build_step4_prompt(
    interactions: list[dict],
    auto_triggers: list[dict],
    l2_descriptions: dict[str, str],
    scene_intents: dict,
    condensed_text: str,
    weapon_library_names: list[str],
    enemy_library_names: list[str],
    skill_names: list[str],
    stat_names: list[str],
) -> str:
    weapons_list = "\n".join(f"- {w}" for w in weapon_library_names)
    enemies_list = "\n".join(f"- {e}" for e in enemy_library_names)
    skills_list = "\n".join(f"- {s}" for s in skill_names)
    stats_list = "\n".join(f"- {s}" for s in stat_names)
    desc_list = "\n".join(f"- {sid}: {desc}" for sid, desc in l2_descriptions.items())
    return f"""标准化 enemy_ref/weapon_ref/type/stat_name，并结构化 side_effects。

## 可用武器库
{weapons_list}

## 可用敌人库
{enemies_list}

## 标准技能列表（type 必须从此列表中选择）
{skills_list}

## 标准属性列表（stat_change 的 stat_name 必须从此列表中选择）
{stats_list}

## 场景描述
{desc_list}

## L3 Scene Intents
{json.dumps(scene_intents, ensure_ascii=False, indent=2)}

## 精修模组（参考上下文）
\"\"\"
{condensed_text}
\"\"\"

## Interactions (含空占位符和未结构化的 side_effects)
{json.dumps(interactions, ensure_ascii=False, indent=2)}

## Auto-triggers (含空占位符和未结构化的 side_effects)
{json.dumps(auto_triggers, ensure_ascii=False, indent=2)}

任务:
1. 为每个 enemy_ref 从可用敌人库中选择匹配项。无匹配填 "none"。event（无 scene 字段的实体）跳过。
2. 为每个 weapon_ref 从可用武器库中选择匹配项。无匹配填 "none"。event（无 scene 字段的实体）跳过。
3. 为每个 type 从标准技能列表中选择最匹配的技能名。不涉及检定的 type 保持"无"。
4. **Side_effect 结构化**: 将 side_effects 从自然语言字符串解析为结构化对象:
   - item_gain: {{"type": "item_gain", "item_name": "物品名"}}
   - stat_change: {{"type": "stat_change", "stat_name": "属性名", "delta": -1, "narrative": "角色经历（可选）"}}
   - spawn_enemy: {{"type": "spawn_enemy", "enemy_ref": "敌人名", "scene": "场景ID", "trigger_condition": "...", "quantity": 1}}
   - grant_item: {{"type": "grant_item", "item_ref": "武器/物品名", "scene": "场景ID"}}
   - npc_state_change: {{"type": "npc_state_change", "npc_name": "NPC名", "new_state": "新状态"}}
   无法归入以上类型的保留字符串。
5. stat_change 的 stat_name 必须从标准属性列表中选择。narrative 字段可选，描述角色 fiction 层面的经历。
6. 不允许自创名称。

输出格式:
{{
  "interactions": [{{ ...原字段..., "enemy_ref": "...", "weapon_ref": "...", "type": "标准技能名", "side_effects": [结构化对象或字符串] }}],
  "auto_triggers": [{{ ...原字段..., "enemy_ref": "...", "weapon_ref": "...", "type": "标准技能名", "side_effects": [结构化对象或字符串] }}]
}}

仅输出 JSON。"""


def parse_step4(
    interactions: list[dict],
    auto_triggers: list[dict],
    l2_descriptions: dict[str, str],
    scene_intents: dict,
    condensed_text: str,
    weapon_library_names: list[str],
    enemy_library_names: list[str],
    skill_names: list[str],
    stat_names: list[str],
    llm_call,
) -> dict:
    prompt = build_step4_prompt(
        interactions, auto_triggers, l2_descriptions,
        scene_intents, condensed_text,
        weapon_library_names, enemy_library_names, skill_names, stat_names,
    )
    return llm_call(prompt, system=STEP4_SYSTEM)
