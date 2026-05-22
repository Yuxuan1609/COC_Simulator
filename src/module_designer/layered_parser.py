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
  Phase 1: 风格预判 (与 Step 3.5 并行)
  Phase 2: 精简标准化 (替代原 Step 4)

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


def _join_chapters(chapters: dict[str, str], *keys: str) -> str:
    """拼接指定章节为参考文本。未找到的 key 静默跳过。"""
    parts = []
    for k in keys:
        v = chapters.get(k, "")
        if v:
            parts.append(f"## {k}\n{v}")
    return "\n\n".join(parts)


def _parse_condensed_chapters(markdown_text: str) -> dict[str, str]:
    """按 ## 标题拆分为章节 dict。key 为标题名（去掉 ## 前缀和空格）."""
    chapters = {}
    current_title = "_header"
    current_lines = []
    for line in markdown_text.split("\n"):
        if line.startswith("## "):
            if current_lines:
                chapters[current_title] = "\n".join(current_lines).strip()
            current_title = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        chapters[current_title] = "\n".join(current_lines).strip()
    return chapters


def _slim_entity(entity: dict) -> dict:
    """从 entity dict 中提取 Phase 2 需要的 5-6 个字段（graded_result 可选）."""
    slimmed = {k: entity.get(k, "") for k in ("name", "scene", "type")}
    slimmed["result"] = entity.get("result", "")
    if entity.get("graded_result"):
        slimmed["graded_result"] = entity["graded_result"]
    slimmed["side_effects"] = entity.get("side_effects", [])
    return slimmed


def _merge_phase2_fields(originals: list[dict], phase2_entities: list[dict]) -> list[dict]:
    """将 Phase 2 标准化后的字段合并回完整 entity。

    Phase 2 prompt 只传 6 个字段给 LLM 以节省 token，LLM 返回标准化后的
    type/side_effects/result/graded_result。此函数将这些字段写回原始完整 entity。
    匹配依据: (name, scene)。
    """
    lookup = {}
    for i, e in enumerate(originals):
        key = (e.get("name", ""), e.get("scene", ""))
        lookup[key] = i

    merged = [dict(e) for e in originals]
    for p2e in phase2_entities:
        key = (p2e.get("name", ""), p2e.get("scene", ""))
        if key in lookup:
            idx = lookup[key]
            for field in ("type", "side_effects", "result", "graded_result"):
                if field in p2e:
                    merged[idx][field] = p2e[field]
    return merged


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
你的任务是：从模组文档中提取模组的元信息、场景列表、人物列表、Boss、敌人和武器约束，使用固定的 ID 体系。

重要原则：
- 场景使用原文中的中文名称（不需要 ID）
- 人物 ID 使用 NPC_1, NPC_2... 格式
- 人物名使用原文中的中文名称
- enemy_ref / weapon_ref 必须从可用库中选择，不允许自创
- 约束宽松，只需符合模组背景设定，允许随机性
- 不做场景绑定——跑团中任何场景都可能出现
- min_count 可为 0（表示可能不出现），max_count 为最多出现次数
- 仅输出 JSON，不要任何解释性文字
- 如果模组文档没有出现可以为空，保留占位符
- 注意：不能理智性交互或有意义对话的怪物/邪教徒不属characters
"""



def build_step1a_prompt(content: str, weapon_library_names: list[str] = None, enemy_library_names: list[str] = None, boss_library_names: list[str] = None) -> str:
    weapons_list = "\n".join(f"- {w}" for w in (weapon_library_names or []))
    enemies_list = "\n".join(f"- {e}" for e in (enemy_library_names or []))
    boss_list = "\n".join(f"- {b}" for b in (boss_library_names or []))
    return f"""从以下模组文档中提取结构化信息。

## 可用武器库
{weapons_list if weapons_list else "（未提供武器库，weapons 返回空列表）"}

## 可用敌人库
{enemies_list if enemies_list else "（未提供敌人库，enemies 返回空列表）"}

## Boss 库（boss_ref 必须从此列表中选择）
{boss_list if boss_list else "（未提供Boss库，boss_encounters 返回空列表）"}

输出格式:
{{
  "module_meta": {{"title": "模组标题", "author": "原作者（未知则留空）", "era": "年代（如1920s）", "theme": "核心主题", "expected_duration": "预计时长", "player_count": "建议人数", "estimated_duration": 240, "comms_interval": 10, "starting_time_of_day": "夜间"}},
  "scenes": ["场景中文名", ...],
  "characters": [
    {{"name": "角色中文名", "id": "NPC_1"}},
    {{"name": "角色中文名", "id": "NPC_2"}}
  ],
  "boss_encounters": [
    {{
      "boss_ref": "Boss库中的名称",
      "scene": "出现场景",
      "description": "Boss在故事中的定位"
    }}
  ],
  "enemies": [
    {{"enemy_ref": "敌人名", "min_count": 0, "max_count": 2}}
  ],
  "weapons": [
    {{"weapon_ref": "武器名", "min_count": 1, "max_count": 1}}
  ]
}}

要求：
1. scenes 按玩家可能到达的顺序排列，使用场景中文名
2. characters 列出所有有名字或有重要作用的角色
3. 仅输出 JSON
4. 估算模组剧情的预计总耗时（分钟），综合考虑所有可能的探索路径和对话时长。写入 module_meta.estimated_duration。
5. 推荐通信间隔（分钟）写入 module_meta.comms_interval（短模组≤2h: 6-8min, 中型2-6h: 10-15min, 长型6-24h: 15-20min, 超长≥24h: 60-120min）。
6. 识别模组文档中提到的Boss、大怪、强敌，不为普通怪物——Boss是剧情核心敌人、需要特殊机制或为最终战。boss_ref 必须从 Boss 库中选择，若模组Boss不在库中则选择最接近的库中名称。提取后写入boss_encounters。
7. 设定模组开始时的时段（凌晨/早晨/白天/黄昏/夜间），写入 module_meta.starting_time_of_day。基于模组文本中描述的时间氛围判断。
8. enemy_ref 和 weapon_ref 必须从可用库中选择，不允许自创。数量约束宽松，只需符合背景；若模组未提及敌人/武器，返回空列表。

模组文档：
\"\"\"
{content}
\"\"\""""


def parse_step1a(content: str, llm_call, weapon_library_names: list[str] = None, enemy_library_names: list[str] = None, boss_library_names: list[str] = None) -> dict:
    """从模组文档提取结构化元信息（含敌人/武器/Boss约束）."""
    prompt = build_step1a_prompt(content, weapon_library_names, enemy_library_names, boss_library_names)
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
- requirement: 硬性前置条件用 entity ID + AND/OR/() 表达复合关系（如 I1 AND I2、(I1 OR I2) AND I3），裸 entity ID 默认指该实体成功完成（检定通过或无检定完成）。无条件填空字符串。需要特殊条件（如某实体检定失败、调查员理智极度崩溃等）在 "||" 后用自然语言描述
- trigger 是触发场景描述：什么情况下玩家可以执行此互动。如 "玩家检查抽屉时"、"玩家进入此场景时"
- result 是直接结果：互动直接产生的结果。如 "抽屉打开了，里面有一把钥匙"。如果此互动会导致游戏结局，result 必须以 ##END_结局名称:结局简述## 开头，如 "##END_真结局:电车冲出梦境## 调查员们成功..."
- requirement 可描述是否需要消耗常见非剧情物品及数量（如"需要消耗1个急救包"）；result 可描述结果是否会失去常见消耗品（如"失去一个手电筒"）。具体数值由 Phase 2 标准化为 @consume_item
- side_effects 是间接后果：与 result 不重合的附带影响。如 "开抽屉的声响吸引了隔壁车厢的怪物"。自然语言字符串列表
- 互动完成即代表状态变更，不需要单独的 flag
- type 涉及技能鉴定时，填入 graded_result（分级检定后果），此时 result 填 "##GRADED##"（占位标记），side_effects 留空。所有结果描述写入 graded_result 各等级中；type 为"无"时不填 graded_result
- based_on 始终为 null（Step 2b 会给派生实体填值）
- 通行路径记录每个场景的出边（from_here）和入边（to_here），包含通行方式和前置条件
- entity 的 result/side_effects/graded_result 不涉及进入与怪物的战斗/对抗/追捕的情况（怪物遭遇和战斗由 game loop 运行时统一管理）。可以声明怪物出现，但不描述进入和怪物的对砍/战斗
- **模组中提到的可获取物品（clues_and_items 章节：clues 为剧情关键物品/线索，items 为非剧情普通物品，需结合精修模组原文和常识判断）必须在对应场景的 entity 中通过 result 或 graded_result 明确表达为可获取状态，确保每个物品都有对应的 entity 承载其获取路径**
- **entity 的 result/trigger/side_effects 中涉及 NPC 名称时，必须使用已知角色列表中的名称，不允许自创或使用别名**
- 仅输出 JSON，不要任何解释性文字"""


def build_step2a_prompt(chapters: dict[str, str], scenes: list[dict], characters: list[dict] = None) -> str:
    scene_list = "\n".join(f"- {s}" for s in scenes)
    char_list = "\n".join(f"- {c['id']}: {c['name']}" for c in (characters or []))
    return f"""从精修模组文本中提取每个场景的全部可执行互动，以及场景间的通行路径。

已知场景列表:
{scene_list}

已知角色列表（entity 中涉及 NPC 名称时，必须使用下表中的名称）:
{char_list if char_list else "（无）"}

输出格式:
{{
  "interactions": [
    {{
      "id": "I1",
      "scene": "6号车厢",
      "type":  关联技能鉴定如“侦察”、“急救”等，不涉及则为“无”,
      "name": "互动名称",
      "requirement": "硬性前置条件（entity ID + AND/OR/() 表达复合关系，裸 ID 默认指成功完成）||软性前置条件（特殊状态如实体检定失败、调查员理智极度崩溃等，无条件填空字符串）",
      "trigger": "触发场景（描述什么情况下玩家可以执行此互动），如：玩家检查抽屉时",
      "result": "直接结果（互动直接产生的结果），如：抽屉打开了，里面有一把钥匙",
      "side_effects": ["间接后果（与result不重合的附带影响），如：开抽屉的声响吸引了隔壁车厢的怪物。无条件则为空列表"],
      "graded_result": {{"on_failure": "...", "on_regular": "...", "on_hard": "...", "on_extreme": "..."}},
      "difficulty": "regular",
      "based_on": null
    }}
  ],
  "scene_movements": {{
    "6号车厢": {{
      "from_here": [
        {{"target": "7号车厢", "method": "步行通过车门", "requirement": "门未上锁"}}
      ],
      "to_here": [
        {{"source": "5号车厢", "method": "步行通过车门", "requirement": ""}}
      ]
    }},
    "7号车厢": {{ ... }}
  }}
}}

要求：
1. id 全局唯一 (I1, I2, I3...)
2. scene 使用场景中文名
3. requirement: 硬性前置条件用 entity ID + AND/OR/() 表达复合关系（如 I1 AND I2、(I1 OR I2) AND I3），裸 entity ID 默认指该实体成功完成。无条件填空字符串。需要特殊条件（如实体检定失败、调查员理智极度崩溃等）在 "||" 后用自然语言描述。不要和 trigger 混淆
4. trigger 是触发场景：描述什么情况下玩家可以执行此互动。不要和 requirement 混淆
5. result 是直接结果：互动直接产生的可感知结果，不含间接影响。如果此互动会直接触发游戏结局，result 必须以 ##END_结局名称:结局简述## 开头（如 “##END_真结局:电车冲出梦境##”），后续再写正常结果文本
6. side_effects 是间接后果：与 result 不重合的附带影响。自然语言字符串列表。无条件则为空列表
7. type 是涉及的技能鉴定名，不涉及则为”无”
8. difficulty 从以下选择：None/regular/hard/extreme；不涉及鉴定则为 None
9. graded_result：type 不为”无”时填写。此时 result 必须填 “##GRADED##”（占位标记），side_effects 必须留空。所有结果文字写入 graded_result 的四等级中。四等级含义：on_failure=检定失败、on_regular=常规成功、on_hard=困难成功、on_extreme=极难成功。若原文未区分等级结果，各等级可描述相同内容
10. 提取原文中提到的所有互动，即使描述简略也要列出
11. scene_movements 必须覆盖所有已知场景
12. 通行路径的 target/source 使用场景中文名，method 描述通行方式，requirement 描述硬性通行前置条件
13. 严格依据精修模组内容，基于场景氛围合理补充，不要和原文冲突
14. based_on 始终填 null（派生关系由 Step 2b 标注）
15. 模组 clues_and_items 章节中提到的可获取物品（clues=剧情物品/线索，items=非剧情普通物品，需结合精修模组原文和常识判断），必须在对应场景的 entity 中通过 result 或 graded_result 表达为可获取/可发现状态。每个物品都应有对应的 entity 承载其获取路径，不可遗漏
精修模组（参考上下文）：
\"\"\"
{_join_chapters(chapters, 'module_overview', 'scenes', 'clues_and_items', 'events_summary')}
\"\"\""""
def parse_step2a(chapters: dict[str, str], scenes: list[dict], llm_call, characters: list[dict] = None) -> dict:
    """从精修模组提取所有 interactions."""
    prompt = build_step2a_prompt(chapters, scenes, characters)
    return llm_call(prompt, system=STEP2A_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 2b: Events
# ═══════════════════════════════════════════════════════════════

STEP2B_EVENTS_SYSTEM = """你是一个 TRPG 模组解析助手，专门提取全局事件。
你的任务是：从精修模组文本和已知互动中派生全局事件。事件是跨场景的的世界级变化。

术语：interaction、auto_trigger、event 三者统称为 entity（实体）。

重要原则：
- 事件使用与 interaction 相同的统一字段模型，除了事件无 scene 字段（全局事件不绑定特定场景）
- based_on 指向派生的 interaction ID（非派生事件则留空字符串）
- requirement: 硬性前置条件用 entity ID + AND/OR/() 表达复合关系（如 I1 AND I2、(I1 OR I2) AND I3），裸 entity ID 默认指该实体成功完成。无条件填空字符串。需要特殊条件（如实体检定失败等）在 "||" 后用自然语言描述；trigger 是触发场景描述，两者不可混淆
- result 是直接结果（含不可逆性标注）。如果此事件会导致游戏结局，result 必须以 ##END_结局名称:结局简述## 开头
- requirement 可描述是否需要消耗常见非剧情物品及数量；result 可描述结果是否会失去常见消耗品（具体数值由 Phase 2 标准化为 @consume_item）
- side_effects 是与 result 不重合的间接后果
- type 涉及技能鉴定时填写 graded_result，此时 result 填 "##GRADED##"，side_effects 留空。四等级对应检定失败/常规成功/困难成功/极难成功
- entity 的 result/side_effects/graded_result 不涉及进入与怪物的战斗/对抗/追捕的情况（怪物遭遇和战斗由 game loop 运行时统一管理）。可以声明怪物出现，但不描述进入和怪物的对砍/战斗
- **entity 的 result/trigger/side_effects 中涉及 NPC 名称时，必须使用已知角色列表中的名称**
- 仅输出 JSON，不要任何解释性文字"""


def build_step2b_events_prompt(
    chapters: dict[str, str],
    scenes: list[dict],
    interactions: list[dict],
    characters: list[dict] = None,
) -> str:
    scene_list = "\n".join(f"- {s}" for s in scenes)
    interaction_list = "\n".join(
        f"- {i['id']}: {i['name']} → {i.get('result', '')} (场景 {i['scene']})"
        for i in interactions
    )
    char_list = "\n".join(f"- {c['id']}: {c['name']}" for c in (characters or []))
    return f"""从精修模组文本中提取所有全局事件。

已知场景:
{scene_list}

已知角色列表（entity 中涉及 NPC 名称时，必须使用下表中的名称）:
{char_list if char_list else "（无）"}

已知互动（事件可基于这些互动派生，based_on 指向其 ID；非派生事件留空）:
{interaction_list}

输出格式:
{{
  "events": [
    {{
      "id": "E1",
      "type": "关联技能名，不涉及填\"无\"",
      "name": "事件名称",
      “requirement”: “硬性前置条件（entity ID + AND/OR/() 表达复合关系，裸 ID 默认指成功完成）||软性前置条件（特殊状态如实体检定失败等，无条件填空字符串）”,
      “trigger”: “触发场景（描述什么情况下此事件触发），如：调查员试图折返会之前的一个场景时”,
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
2. based_on 指向派生的 interaction ID，非派生事件则填空字符串
3. requirement 是前置条件；trigger 是触发场景描述，两者不可混淆
4. result 是直接结果：不可逆事件需明确标注”不可逆：”。如果此事件会导致游戏结局，result 必须以 ##END_结局名称:结局简述## 开头（如 “##END_坏结局:电车坠入黑暗## 不可逆：调查员们永远被困在噩梦中”）
5. side_effects 是间接后果：与 result 不重合的附带影响。无条件则为空列表
6. type 是关联技能名，不涉及填”无”；涉及鉴定时填写 graded_result。此时 result 填 “##GRADED##”，side_effects 留空。四等级对应检定失败/常规成功/困难成功/极难成功。若原文未区分等级，各等级可描述相同
7. difficulty 从以下选择：None/regular/hard/extreme；不涉及检定则为 None
8. 事件是全局的，不绑定特定场景（无 scene 字段）

精修模组（参考上下文）：
\"\"\"
{_join_chapters(chapters, 'module_overview', 'scenes', 'clues_and_items', 'events_summary')}
\"\"\""""


def parse_step2b_events(
    chapters: dict[str, str],
    scenes: list[dict],
    interactions: list[dict],
    llm_call,
    characters: list[dict] = None,
) -> dict:
    prompt = build_step2b_events_prompt(chapters, scenes, interactions, characters)
    return llm_call(prompt, system=STEP2B_EVENTS_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 2b: Auto-triggers
# ═══════════════════════════════════════════════════════════════

STEP2B_AT_SYSTEM = """你是一个 TRPG 模组解析助手，专门生成自动触发事件。
你的任务是：基于精修模组和已知互动，生成所有被动触发事件（auto_trigger）。

术语：interaction、auto_trigger、event 三者统称为 entity（实体）。

重要原则：
- auto_trigger 使用与 interaction 相同的统一字段模型
- auto_trigger 绑定特定场景（scene 字段必填）
- based_on 指向派生的 interaction ID（非派生 AT 则留空字符串）
- requirement: 硬性前置条件用 entity ID + AND/OR/() 表达复合关系（如 I1 AND I2、(I1 OR I2) AND I3），裸 entity ID 默认指该实体成功完成。无条件填空字符串。需要特殊条件（如实体检定失败等）在 "||" 后用自然语言描述；trigger 是触发场景描述，两者不可混淆
- result 是直接结果：如果此自动触发会导致游戏结局，必须以 ##END_结局名称:结局简述## 开头
- requirement 可描述是否需要消耗常见非剧情物品及数量；result 可描述结果是否会失去常见消耗品（具体数值由 Phase 2 标准化为 @consume_item）
- side_effects 是与 result 不重合的间接后果
- type 涉及技能鉴定时填写 graded_result，此时 result 填 "##GRADED##"，side_effects 留空。四等级对应检定失败/常规成功/困难成功/极难成功
- 只生成被动触发的事件，不要生成玩家主动互动
- entity 的 result/side_effects/graded_result 不涉及进入与怪物的战斗/对抗/追捕的情况（怪物遭遇和战斗由 game loop 运行时统一管理）。可以声明怪物出现，但不描述进入和怪物的对砍/战斗
- **模组 clues_and_items（clues=剧情物品/线索，items=非剧情普通物品，需结合精修模组原文和常识判断）中标记为初始可见/场景内放置的物品，必须生成为进入场景时的 auto_trigger（requirement 留空），trigger 为"玩家进入此场景时"，result 描述玩家自动感知到该物品的存在。无需检定即可获取的物品直接以 result 表达获取；需要检定的以 graded_result 表达**
- **entity 的 result/trigger/side_effects 中涉及 NPC 名称时，必须使用已知角色列表中的名称**
- **必须生成一个 AT_WORLD（id="AT_WORLD", scene="world", type="无", difficulty="None", based_on=""）用于世界初始化。trigger 为"模组开始时自动触发"，result 为"世界环境初始化"。side_effects 中使用 @标记 声明初始配置：
  · 描述：1调查员初始时身上带着什么
         2哪个场景散布着什么武器
         3哪个场景可能会有什么敌人，有多少
- 仅输出 JSON，不要任何解释性文字"""


def build_step2b_at_prompt(
    chapters: dict[str, str],
    scenes: list[dict],
    interactions: list[dict],
    characters: list[dict] = None,
    enemies: list[dict] = None,
    weapons: list[dict] = None,
) -> str:
    scene_list = "\n".join(f"- {s}" for s in scenes)
    interaction_list = "\n".join(
        f"- {i['id']}: {i['name']} → {i.get('result', '')} (场景 {i['scene']})"
        for i in interactions
    )
    char_list = "\n".join(f"- {c['id']}: {c['name']}" for c in (characters or []))
    enemy_list = "\n".join(f"- {e['enemy_ref']} (max {e.get('max_count',1)})" for e in (enemies or []))
    weapon_list = "\n".join(f"- {w['weapon_ref']} (max {w.get('max_count',1)})" for w in (weapons or []))
    return f"""从精修模组文本中生成所有自动触发事件，包括一个世界初始化自动触发（AT_WORLD）。

已知场景:
{scene_list}

已知角色列表（entity 中涉及 NPC 名称时，必须使用下表中的名称）:
{char_list if char_list else "（无）"}

已知互动（auto_trigger 可基于这些互动派生，based_on 指向其 ID；非派生 AT 留空）:
{interaction_list}

## 敌人约束
{enemy_list if enemy_list else "（无约束）"}

## 武器约束
{weapon_list if weapon_list else "（无约束）"}

输出格式:
{{
  "auto_triggers": [
    {{
      "id": "AT1",
      "scene": "6号车厢",
      "type": "关联技能名，不涉及填\"无\"",
      "name": "自动触发名称",
      "requirement": "硬性前置条件（entity ID + AND/OR/() 表达复合关系，裸 ID 默认指成功完成）||软性前置条件（特殊状态如实体检定失败、调查员理智极度崩溃等，无条件填空字符串）",
      "trigger": "触发场景（描述什么情况下此被动事件触发），如：玩家进入场景且 I1 已完成",
      "result": "直接结果（被动触发直接产生的结果）",
      "side_effects": ["间接后果（与result不重合的附带影响），无条件则为空列表"],
      "graded_result": {{"on_failure": "...", "on_regular": "...", "on_hard": "...", "on_extreme": "..."}},
      "difficulty": "None/regular/hard/extreme",
      "based_on": "I1"
    }}
  ]
}}

要求：
1. id 全局唯一 (AT1, AT2, AT3...)
2. scene 使用场景中文名
3. based_on 指向派生的 interaction ID，非派生 AT 则留空字符串
4. requirement: 硬性前置条件用 entity ID + AND/OR/() 表达复合关系（如 I1 AND I2、(I1 OR I2) AND I3），裸 entity ID 默认指该实体成功完成。无条件填空字符串。需要特殊条件（如实体检定失败等）在 "||" 后用自然语言描述；trigger 是触发场景描述，两者不可混淆
5. result 是直接结果：如果会触发游戏结局，必须以 ##END_结局名称:结局简述## 开头；side_effects 是间接后果（与 result 不重合）
6. type 是关联技能名，不涉及填"无"；涉及鉴定时填写 graded_result。此时 result 填 "##GRADED##"，side_effects 留空。四等级含义同上，原文未区分时各等级可相同
7. difficulty 从以下选择：None/regular/hard/extreme；不涉及检定则为 None
8. 每个场景生成 0-2 个 auto_trigger
9. **必须**生成 AT_WORLD 世界初始化自动触发。AT_WORLD 的 side_effects 使用 @spawn_enemy / @grant_weapon / @item_gain 标记初始配置。enemy_ref 和 weapon_ref 必须来自约束列表，@spawn_enemy / @grant_weapon 的总调用次数不得超过对应 max_count。@item_gain 用于纯文本物品名

精修模组（参考上下文）：
\"\"\"
{_join_chapters(chapters, 'module_overview', 'scenes', 'clues_and_items', 'events_summary')}
\"\"\""""


def parse_step2b_at(
    chapters: dict[str, str],
    scenes: list[dict],
    interactions: list[dict],
    llm_call,
    characters: list[dict] = None,
    enemies: list[dict] = None,
    weapons: list[dict] = None,
) -> dict:
    prompt = build_step2b_at_prompt(chapters, scenes, interactions, characters, enemies, weapons)
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
- NPC 只描述外貌和神态（name, brief, demeanor），不写隐藏动机、对话内容或互动逻辑
- NPC 的互动由 L2 层通过 entity（interaction/auto_trigger/event）承载
- 你是模组叙述者，你只负责描述玩家”现在”能见到/感受到的信息
"""


def build_step2c_l1_prompt(chapters: dict[str, str], scenes: list[dict], characters: list[dict]) -> str:
    template = _load_template("l1_template.json")
    scene_list = "\n".join(f"- {s}" for s in scenes)
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
7. l1层的信息必须是玩家在不做任何鉴定的尝试下就可见的，你可以基于这一原则做合理的推测

重要：
- 仅输出 JSON，不要任何解释性文字
- 只写无条件可见的感知信息
- 需要检定才能发现的内容留给 L2 层
- 场景 key 名必须与给定列表中的 name 一致
- 只列出当前场景确实在场的 NPC

精修模组（参考上下文）：
\"\"\"
{_join_chapters(chapters, 'module_overview', 'scenes', 'clues_and_items', 'events_summary', 'enemies')}
\"\"\""""


def parse_step2c_l1(chapters: dict[str, str], scenes: list[dict], characters: list[dict], llm_call) -> dict:
    prompt = build_step2c_l1_prompt(chapters, scenes, characters)
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


def build_step2c_l3_prompt(chapters: dict[str, str], scenes: list[dict], characters: list[dict], step1_meta: dict = None) -> str:
    template = _load_template("l3_template.json")
    meta_ref = json.dumps(step1_meta, ensure_ascii=False, indent=2) if step1_meta else "（无）"
    scene_list = "\n".join(f"- {s}" for s in scenes)
    char_list = "\n".join(f"- {c['id']}: {c['name']}" for c in characters) if characters else "（无）"
    return f"""从精修模组文本中提取「设计者层」信息（L3 层）。

已知场景列表:
{scene_list}

已知角色列表（characters 的 id 和 name 必须来自此列表）:
{char_list}

输出格式参考：
{template}

## Step 1a 已提取的元信息（优先使用，仅补充缺失字段）
{meta_ref}

要求：
1. module_meta：模组元信息。优先使用 Step 1a 已提取的值（title/era/theme），仅补充 Step 1a 中为空的字段（author/expected_duration/player_count）
2. world_rules：描述世界运行规则列表，每个含 id (WR1, WR2...), name, rule, scope, is_absolute
    - 例如: 当前模组基于梦境展开，所以使用现代科技对抗是不可能的
3. scene_intents：每个场景的设计意图，key 为已知场景列表，value 含 purpose / key_threat (可选) / notes (可选)
4. ending_conditions：结局条件列表，每个含 id / condition / narrative
5. tone_constraints：全局叙事护栏，含 genre / forbidden / recommended / narrative_style
6. characters：每个 NPC 的设计意图，含 id (使用已知角色列表中的 ID), name (使用已知角色列表中的名称), behavior (行为逻辑 + 叙事作用)
7. driving_force：一切事件的底层驱动力
8. narrative_lines：故事大纲和整体叙事线（可有多条）。每条含 name（叙事线名称）、outline（大纲描述，含起承转合和关键转折点）、key_scenes（涉及的关键场景列表）、type（main=主线 / branch=支线 / optional=可选支线）。至少需要一条 main 类型的主线。
9. time_pressure（可选）：基于模组内容判断是否存在时间压力（如倒计时、追逐、环境吞噬等）。如果有，根据模板格式填写。不要无中生有——只有模组确实有明确的时间威胁时才填写。
10. 你是高层叙事者，你的工作应该关注于一切为什么是这样/这个场景为什么要这么写。不要过度关注具体的规则和信息。

重要：
- 仅输出 JSON，不要任何解释性文字
- 从原文中推断设计意图，即使原文没有明确声明
- scene_intents 的 key 必须覆盖所有已知场景
- characters 必须覆盖已知角色列表中的所有角色

精修模组：
\"\"\"
{"\n\n".join(chapters.values())}
\"\"\""""


def parse_step2c_l3(chapters: dict[str, str], scenes: list[dict], characters: list[dict], llm_call, step1_meta: dict = None) -> dict:
    prompt = build_step2c_l3_prompt(chapters, scenes, characters, step1_meta)
    return llm_call(prompt, system=STEP2C_L3_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 2.5: NPC 行为描述
# ═══════════════════════════════════════════════════════════════

STEP25_SYSTEM = """你是一个 TRPG NPC 行为描述助手。
你的任务是：基于 L3 角色设计意图、L1 外貌描述和 L2 entity 互动信息，为每个 NPC 生成行为描述档案。

核心问题：这个 NPC 能/会干什么？在什么情况下会触发什么互动？

重要原则：
- 只使用提供的信息，不要编造新角色或新能力
- 描述侧重于 NPC 的能力和行动（what they can/will do），而非静态属性
- 如果某个 NPC 在 L2 entity 中没有对应互动，只基于 L3/L1 信息描述
- 仅输出 JSON，不要任何解释性文字"""


def build_step25_prompt(
    l3_characters: list[dict],
    l1_data: dict,
    interactions: list[dict],
    auto_triggers: list[dict],
) -> str:
    # Collect NPC-related entities from L2
    npc_entities = []
    for e in interactions + auto_triggers:
        name = e.get("name", "")
        result = e.get("result", "")[:100]
        trigger = e.get("trigger", "")[:100]
        npc_entities.append({"name": name, "result": result, "trigger": trigger})

    # Extract NPC appearances from L1
    npc_appearances = []
    for scene_name, sdata in l1_data.items():
        for npc in sdata.get("npc_appearances", []):
            npc_appearances.append({
                "name": npc.get("name", ""),
                "brief": npc.get("brief", ""),
                "demeanor": npc.get("demeanor", ""),
                "scene": scene_name,
            })

    return f"""为以下 NPC 生成行为描述档案。

## L3 角色设计意图（NPC 为什么会这样做）
{json.dumps(l3_characters, ensure_ascii=False, indent=2)}

## L1 NPC 外貌（玩家第一印象）
{json.dumps(npc_appearances, ensure_ascii=False, indent=2)}

## L2 Entity 互动（NPC 参与的动作）
{json.dumps(npc_entities, ensure_ascii=False, indent=2)}

输出格式:
{{
  "npc_profiles": {{
    "NPC名称": {{
      "name": "NPC名称",
      "role": "一句话角色定位",
      "what_they_can_do": "NPC能做什么、在什么条件下会做什么（核心字段）",
      "interaction_triggers": ["什么情况下玩家可以与NPC互动"],
      "personality_notes": "性格和说话风格",
      "appearance": "外貌描述（来自L1）",
      "initial_state": "alive",
      "initial_attitude": "neutral",
      "initial_following": false
    }}
  }}
}}

要求：
1. 必须覆盖 L3 characters 中的所有角色
2. what_they_can_do 是核心字段，描述 NPC 的能力和行动模式
3. interaction_triggers 基于 L2 entity 信息，列出 NPC 参与的互动触发条件
4. 仅输出 JSON"""


def parse_step25(
    l3_characters: list[dict],
    l1_data: dict,
    interactions: list[dict],
    auto_triggers: list[dict],
    llm_call,
) -> dict:
    prompt = build_step25_prompt(l3_characters, l1_data, interactions, auto_triggers)
    return llm_call(prompt, system=STEP25_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 2 Boss: Boss 遭遇实体生成
# ═══════════════════════════════════════════════════════════════

STEP2_BOSS_SYSTEM = """你是一个 TRPG 模组解析助手，专门生成 Boss 遭遇实体。
你的任务是：基于 Step 1 的 Boss 识别结果和已知 L2 entity，生成结构化的 Boss Encounter 实体。

术语：interaction、auto_trigger、event、boss_encounter 统称为 entity（实体）。

重要原则：
- boss_ref 必须从 Boss 库中选择，不允许自创
- requirements 使用 (entity ID + AND/OR/()) || 软性条件 格式，硬性部分引用已知 entity ID
- engage_type 判定: 进入场景自动触发→"at", 玩家主动操作→"interaction", 全局条件满足→"event"
- description 是进入战斗时的情境描述，基于精修模组内容扩写
- entity 的 result/side_effects 不涉及战斗/对抗的详细过程（战斗由 game loop 运行时统一管理），但可以声明怪物出现和情境
- 仅输出 JSON，不要任何解释性文字"""


def build_step2_boss_prompt(
    boss_hints: list[dict],
    boss_library_names: list[str],
    interactions: list[dict],
    auto_triggers: list[dict],
    scenes: list[str],
    chapters: dict[str, str],
) -> str:
    import json as _json

    # Slim entity references for prompt: id, name, scene, trigger summary
    entity_refs = []
    for e in interactions:
        entity_refs.append({"id": e.get("id",""), "name": e.get("name",""), "scene": e.get("scene",""), "trigger": e.get("trigger","")[:80]})
    for e in auto_triggers:
        entity_refs.append({"id": e.get("id",""), "name": e.get("name",""), "scene": e.get("scene",""), "trigger": e.get("trigger","")[:80]})

    scene_names = "\n".join(f"- {s}" for s in scenes)
    boss_names = "\n".join(f"- {n}" for n in boss_library_names)

    return f"""根据以下 Boss 识别结果，生成结构化的 Boss Encounter 实体。

## Boss 库（boss_ref 必须从此列表中选择）
{boss_names if boss_names else "（无可用Boss库）"}

## Step 1 Boss 识别
{_json.dumps(boss_hints, ensure_ascii=False, indent=2)}

## 统一场景名
{scene_names}

## 已知 Entity（可用于 requirements 硬性条件引用）
{_json.dumps(entity_refs, ensure_ascii=False, indent=2)}

## 精修模组（参考上下文）
\"\"\"
{chapters.get('module_overview','')}

{chapters.get('enemies','')}
\"\"\"

输出格式:
{{
  "boss_encounters": [
    {{
      "id": "BOSS_1",
      "type": "boss_encounter",
      "engage_type": "at|interaction|event",
      "boss_ref": "Boss库中的名称",
      "scene": "所在场景",
      "requirements": "(entity ID + AND/OR/()) || 软性描述条件",
      "description": "进入战斗时的情境描述"
    }}
  ]
}}

要求:
1. engage_type 判定: 进入场景自动触发→"at", 玩家主动操作→"interaction", 全局条件满足→"event"
2. requirements 使用 (hard) || soft 格式。hard 部分引用已知 entity 的 ID（如 I2、AT3），soft 部分用自然语言描述（如"玩家下到地下室"）
3. boss_ref 必须从 Boss 库中选择。若 Step 1 识别的 boss_name 不在库中，选择最接近的库中名称
4. scene 使用统一场景名
5. description 基于精修模组内容扩写为一段紧张的情境叙述（50-150字），从玩家视角描述进入战斗的瞬间
6. 仅输出 JSON"""


def parse_step2_boss(
    boss_hints: list[dict],
    boss_library_names: list[str],
    interactions: list[dict],
    auto_triggers: list[dict],
    scenes: list[str],
    chapters: dict[str, str],
    llm_call,
) -> dict:
    """从 Boss 提示和 L2 entity 生成结构化 boss_encounter 实体."""
    if not boss_hints:
        return {"boss_encounters": []}
    prompt = build_step2_boss_prompt(
        boss_hints, boss_library_names, interactions, auto_triggers, scenes, chapters
    )
    return llm_call(prompt, system=STEP2_BOSS_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 3a: L2 依赖解析
# ═══════════════════════════════════════════════════════════════

STEP3A_SYSTEM = """你是一个 TRPG 逻辑验证助手，专门做模组信息的去重和冲突解决。
你的任务是：检查所有 interaction/event/auto_trigger，基于 based_on 去重，验证 graded_result，修剪 result/side_effects 重合，解决冲突，验证结局标记。

重要原则：
- interaction/event/auto_trigger统称为entity
- based_on 已标注派生关系。若两个 entity 的 based_on 指向同一 interaction，或者一个entity和其based_on指向的entity
  描述的是同一个事件（判断标准：指代同一件事情的发生，而非仅仅文字相似），合并为一个。
- 合并时优先保留auto_trigger和interaction
- graded_result 在 type != "无" 时强制填写至少1条；type == "无" 时删除空 graded_result
- result 和 side_effects 信息重合时修剪一方。result 为 "##GRADED##" 时跳过此检查
- requirement/trigger 冲突以 精修模组（参考上下文） 为准修正
- ##END_## 标记与 L3 ending_conditions 相互补齐
- 不删改实质信息，只修正名称和引用
- 互动完成即代表状态变更，不需要单独的 flag
- 仅输出 JSON，不要任何解释性文字"""


def build_step3a_prompt(
    chapters: dict[str, str],
    interactions: list[dict],
    events: list[dict],
    auto_triggers: list[dict],
    ending_conditions: list[dict],
) -> str:
    return f"""对以下模组中的所有 L2 内容做去重、冲突解决和结局验证。

## 精修模组（参考上下文）
\"\"\"
{_join_chapters(chapters, 'module_overview', 'scenes', 'clues_and_items', 'events_summary')}
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
1. **Based_on 去重**: based_on 已标注派生关系。若两个 entity 的 based_on 指向同一 interaction，或者一个 entity 和其 based_on 指向的 entity 描述的是同一个事件（判断标准：指代同一件事情的发生，而非仅仅文字相似），合并为一个。
2. **合并时优先保留 auto_trigger 和 interaction（即优先合并 event）。
3. **Graded_result 检查**: type != "无" 时填写 graded_result 中至少一条；type == "无" 时删除空 graded_result。
4. **Result / Side_effects 去重**: 若 result 为 "##GRADED##" 跳过此检查。否则若 side_effects 中的某条内容已在 result 中体现，移除该条。
5. **冲突解决**: requirement/trigger 矛盾以 精修模组（参考上下文） 为准修正。
6. **结局标记验证**: 扫描 ##END_## 标记与 L3 ending_conditions 做语义匹配。标记缺失则基于L3信息补齐。

输出格式:
{{
  "interactions": [{{ ...原字段... }}],
  "events": [{{ ...原字段... }}],
  "auto_triggers": [{{ ...原字段... }}]
}}
注意 interaction/event/auto_trigger统称为entity 
仅输出 JSON。"""


def parse_step3a(
    chapters: dict[str, str],
    interactions: list[dict],
    events: list[dict],
    auto_triggers: list[dict],
    ending_conditions: list[dict],
    llm_call,
) -> dict:
    prompt = build_step3a_prompt(chapters, interactions, events, auto_triggers, ending_conditions)
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
    chapters: dict[str, str],
    l1_data: dict,
    l2_completed: dict,
    l3_data: dict,
    step1_scenes: list[dict],
) -> str:
    scene_names = ", ".join(step1_scenes)
    return f"""核对 L1 与 L2 的交叉引用。

## 模组概述（参考上下文）
\"\"\"
{chapters.get('module_overview', '')}
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
    chapters: dict[str, str],
    l1_data: dict,
    l2_completed: dict,
    l3_data: dict,
    step1_scenes: list[dict],
    llm_call,
) -> dict:
    prompt = build_step3b_prompt(chapters, l1_data, l2_completed, l3_data, step1_scenes)
    return llm_call(prompt, system=STEP3B_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 3.5: 依赖图构建
# ═══════════════════════════════════════════════════════════════

STEP35_SYSTEM = """你是一个 TRPG 依赖关系解析助手。
你的任务是：检查所有 interaction/event/auto_trigger 的 requirement 字段，将其中描述的依赖关系标准化为结构化 JSON。

重要原则：
- interaction/event/auto_trigger统称为entity
- 从 requirement 中提取依赖关系。requirement 格式：硬性条件（entity ID + AND/OR/()）|| 软性条件（自然语言）
- 硬性条件中裸 entity ID（如 I3）默认指该实体完成 → {{"type": "interaction", "id": "I3"}}
- 硬性条件中 AND/OR 连接的每个 entity ID 各提取为一条依赖
- 软性条件（|| 之后）中如提到其他 entity ID 依赖 → 同样提取
- trigger 中如提到 "E1 已触发" → {{"type": "event", "id": "E1"}}
- 每条 entity 的 requires 列出所有提取到的依赖（可为空列表）
- 仅提取 entity 之间的依赖关系，不提取物品持有/技能/flag 等其他条件
- 仅输出 JSON，不要任何解释性文字"""


def build_step35_prompt(
    chapters: dict[str, str],
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
{_join_chapters(chapters, 'module_overview', 'scenes', 'events_summary')}
\"\"\"

## Interactions
{interaction_list}

## Events
{events_list}

## Auto-triggers
{at_list}

任务:
1. 扫描每个 entity 的 requirement 字段。格式为：硬性条件（entity ID + AND/OR/()）|| 软性条件（自然语言）
2. 提取其中描述的依赖关系，标准化为:
   - 硬性条件中裸 entity ID（如 I3）默认指该实体完成 → {{"type": "interaction", "id": "I3"}}
     AND/OR 连接的每个 entity ID 各提取为一条独立依赖
   - 软性条件（|| 之后）中如提到其他 entity ID → 同样提取为 {{"type": "interaction", "id": "I4"}}
   - trigger 中如提到 "E1 已触发" → {{"type": "event", "id": "E1"}}
     每条 entity 的 requires 列出所有提取到的依赖（可为空列表）
   - 依赖仅表示"必须完成目标 entity"，不区分成功/失败/触发等条件（requirement 语义由 runtime 解析）

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
        {{"type": "interaction", "id": "I1"}}
      ]
    }},
    {{
      "entity_id": "I5",
      "requires": [
        {{"type": "interaction", "id": "I3"}},
        {{"type": "interaction", "id": "I4"}}
      ]
    }}
  ]
}}

仅输出 JSON。"""


def parse_step35(
    chapters: dict[str, str],
    interactions: list[dict],
    events: list[dict],
    auto_triggers: list[dict],
    llm_call,
) -> dict:
    prompt = build_step35_prompt(chapters, interactions, events, auto_triggers)
    return llm_call(prompt, system=STEP35_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Phase 1: 风格预判
# ═══════════════════════════════════════════════════════════════

# Phase 命名说明：Phase 1/2 不同于 Step 1-4。Step 是管线串行步骤，
# Phase 1 与 Step 3.5 并行，Phase 2 串行在 Phase 1 之后，是更细粒度的阶段划分。
PHASE1_SYSTEM = """你是一个 TRPG 模组风格分析助手。
你的任务是：根据模组精修文本，判断敌人和武器的风格方向和数量范围，用于后续约束生成。

重要原则：
- 约束宽松，只需符合模组背景设定，允许随机性
- 不做场景绑定——跑团中任何场景都可能出现
- min_count 可为 0（表示可能不出现），max_count 为最多出现次数
- 仅输出 JSON，不要任何解释性文字"""


def build_phase1_prompt(
    chapters: dict[str, str],
    scene_intents: dict,
    weapon_library_names: list[str],
    enemy_library_names: list[str],
) -> str:
    weapons_list = "\n".join(f"- {w}" for w in weapon_library_names)
    enemies_list = "\n".join(f"- {e}" for e in enemy_library_names)
    return f"""根据模组背景确定敌人和武器的风格方向与数量范围。

## 可用武器库
{weapons_list}

## 可用敌人库
{enemies_list}

## L3 Scene Intents（设计意图参考）
{json.dumps(scene_intents, ensure_ascii=False, indent=2)}

## 精修模组
\"\"\"
{"\n\n".join(chapters.values())}
\"\"\"

输出格式:
{{
  "enemies": [
    {{"enemy_ref": "敌人名", "min_count": 0, "max_count": 2}}
  ],
  "weapons": [
    {{"weapon_ref": "武器名", "min_count": 1, "max_count": 1}}
  ]
}}

要求：
1. enemy_ref 和 weapon_ref 必须从可用库中选择，不允许自创
2. 数量约束宽松，只需符合背景；若模组未提及敌人/武器，返回空列表
3. 仅输出 JSON"""


def parse_phase1(
    chapters: dict[str, str],
    scene_intents: dict,
    weapon_library_names: list[str],
    enemy_library_names: list[str],
    llm_call,
) -> dict:
    """从精修模组判断敌人和武器的风格方向与数量范围."""
    prompt = build_phase1_prompt(chapters, scene_intents, weapon_library_names, enemy_library_names)
    return llm_call(prompt, system=PHASE1_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Phase 2: 精简标准化（替代原 Step 4）
# ═══════════════════════════════════════════════════════════════

STEP4_SYSTEM = """你是一个 TRPG 游戏资源配置助手。
你的任务是：将 entity 中的 type 标准化为技能名，并将 side_effects / result / graded_result 中的自然语言转化为 @函数(参数) 标记。

术语：interaction、auto_trigger 统称为 entity（实体）。

重要原则：
- type 必须从标准技能列表中选择，不涉及检定保持"无"
- side_effects / result / graded_result 中的关键信息用 @函数(参数=值) 标记替代自然语言描述
- @标记可嵌入任何文本字段中，与普通文本混合
- spawn_enemy 和 grant_weapon 的 enemy_ref/weapon_ref 必须来自 Phase 1 约束列表，且总调用次数不超过对应 max_count
- stat_change 的 stat_name 必须来自标准属性列表
- @item_gain 用于纯文本物品，不做库匹配
- 无法归入 @函数的自然语言保留原样
- 仅输出 JSON，不要任何解释性文字"""


def build_step4_prompt(
    interactions: list[dict],
    auto_triggers: list[dict],
    l2_descriptions: dict[str, str],
    scene_intents: dict,
    chapters: dict[str, str],
    phase1_constraints: dict,
    skill_names: list[str],
    stat_names: list[str],
) -> str:
    skills_list = "\n".join(f"- {s}" for s in skill_names)
    stats_list = "\n".join(f"- {s}" for s in stat_names)
    desc_list = "\n".join(f"- {name}: {desc}" for name, desc in l2_descriptions.items())

    # Slim entities to 6 fields only
    slim_interactions = json.dumps(
        [_slim_entity(i) for i in interactions], ensure_ascii=False, indent=2
    )
    slim_at = json.dumps(
        [_slim_entity(a) for a in auto_triggers], ensure_ascii=False, indent=2
    )

    scene_names = "\n".join(f"- {name}" for name in l2_descriptions.keys())

    return f"""标准化 type，将 side_effects/result/graded_result 转为 @函数(参数) 标记。

## Phase 1 约束（spawn_enemy / grant_weapon 必须在约束范围内）
{json.dumps(phase1_constraints, ensure_ascii=False, indent=2)}

## 标准场景名称列表（@标记中的 scene 必须使用下表中的名称）
{scene_names}

## 标准时段名称（time_of_day 必须使用下表中的名称）
凌晨、早晨、白天、黄昏、夜间

## 标准技能列表（type 必须从此列表中选择）
{skills_list}

## 标准属性列表（stat_change 的 stat_name 必须从此列表中选择）
{stats_list}

## 场景描述（参考上下文）
{desc_list}

## L3 Scene Intents
{json.dumps(scene_intents, ensure_ascii=False, indent=2)}

## 模组概述（参考上下文）
\"\"\"
{chapters.get('module_overview','')}
\"\"\"

## Interactions (仅含需标准化的字段，side_effects 待结构化)
{slim_interactions}

## Auto-triggers (仅含需标准化的字段，side_effects 待结构化)
{slim_at}

任务:
1. **type 标准化**: 从标准技能列表中选择最匹配的技能名。不涉及检定的保持"无"。
2. **@标记转化**: 将 side_effects / result / graded_result 中的自然语言转化为 @函数(参数=值) 标记:

   @spawn_enemy(enemy_ref="敌人名", scene="场景名", quantity=1)
   @grant_weapon(weapon_ref="武器名", scene="场景名", quantity=1)
   @stat_change(stat_name="属性名", delta=-1, narrative="角色经历（可选）")
   @item_gain(item_name="物品名", quantity=1)
   @consume_item(item_name="物品名", quantity=1, narrative="消耗原因（可选）")
   @npc_state_change(npc_name="NPC名", new_state="新状态")
   @npc_follow(npc_name="NPC名", follow=true)

   无法归入以上类型的保留原自然语言。

3. **数量约束**: spawn_enemy / grant_weapon 的总调用次数不得超过 Phase 1 约束中对应条目的 max_count。
4. **结果嵌入**: @标记可嵌入 result / graded_result 各等级 / side_effects 等任何字段。graded_result 各等级为独立字符串，可独立含 @标记。
5. 不允许自创 enemy_ref / weapon_ref / stat_name。
6. type 为"无"的 entity 若无实质 side_effects 则保持原样。

输出格式:
{{
  "interactions": [{{ ...entity 字段..., "type": "标准技能名" }}],
  "auto_triggers": [{{ ...entity 字段..., "type": "标准技能名" }}]
}}

仅输出 JSON。"""


def parse_step4(
    interactions: list[dict],
    auto_triggers: list[dict],
    l2_descriptions: dict[str, str],
    scene_intents: dict,
    chapters: dict[str, str],
    phase1_constraints: dict,
    skill_names: list[str],
    stat_names: list[str],
    llm_call,
) -> dict:
    prompt = build_step4_prompt(
        interactions, auto_triggers, l2_descriptions,
        scene_intents, chapters,
        phase1_constraints, skill_names, stat_names,
    )
    return llm_call(prompt, system=STEP4_SYSTEM)
