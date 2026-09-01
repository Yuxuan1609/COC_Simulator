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

from config import PIPELINE_MAX_RETRIES
from utils import normalize_skill_name


# ═══════════════════════════════════════════════════════════════
#  Utility
# ═══════════════════════════════════════════════════════════════

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "templates")


def load_json(filepath: str) -> dict:
    """从文件路径加载 JSON 文件，返回解析后的 dict."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)




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
    """从 entity dict 中提取 Phase 2 需要的字段（含 id 用于精确匹配回原始 entity）."""
    slimmed = {"id": entity.get("id", "")}
    slimmed.update({k: entity.get(k, "") for k in ("name", "scene", "type")})
    slimmed["result"] = entity.get("result", "")
    if entity.get("graded_result"):
        slimmed["graded_result"] = entity["graded_result"]
    slimmed["side_effects"] = entity.get("side_effects", [])
    slimmed["time_condition"] = entity.get("time_condition", [])
    return slimmed


def _merge_phase2_fields(originals: list[dict], phase2_entities: list[dict]) -> list[dict]:
    """将 Phase 2 标准化后的字段合并回完整 entity。

    Phase 2 prompt 传精简字段给 LLM 以节省 token，LLM 返回标准化后的
    type/side_effects/result/graded_result。此函数将这些字段写回原始完整 entity。
    匹配优先: id，回退: (name, scene)。
    """
    by_id = {}
    by_name_scene = {}
    for i, e in enumerate(originals):
        eid = e.get("id", "")
        if eid:
            by_id[eid] = i
        key = (e.get("name", ""), e.get("scene", ""))
        by_name_scene[key] = i

    merged = [dict(e) for e in originals]
    for p2e in phase2_entities:
        eid = p2e.get("id", "")
        if eid and eid in by_id:
            idx = by_id[eid]
        else:
            key = (p2e.get("name", ""), p2e.get("scene", ""))
            idx = by_name_scene.get(key, -1)
        if idx >= 0:
            for field in ("type", "side_effects", "result", "graded_result", "time_condition"):
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
    max_retries: int = PIPELINE_MAX_RETRIES,
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

从以下模组文档中提取结构化信息。

输出格式:
{
  "module_meta": {"title": "模组标题", "author": "原作者（未知则留空）", "era": "年代（如1920s）", "theme": "核心主题", "expected_duration": "预计时长", "player_count": "建议人数", "estimated_duration": 240, "comms_interval": 10, "starting_time_of_day": "夜间"},
  "scenes": ["场景中文名", ...],
   "characters": [
     {
       "name": "角色中文名",
       "id": "NPC_1",
       "role": "身份/职务/别称（如"乘务员"、"调查记者"、"列车长"等。提取模组文本中对该角色的身份定位，用简短中文短语表达，≤10字）",
       "scenes": ["场景A", "场景B"],
       "can_follow": true,
       "follow_condition": "跟随的前置条件（自然语言描述，如"需要先救下该角色""无条件"等）"
     },
     {
       "name": "角色中文名",
       "id": "NPC_2",
       "role": "记者",
       "scenes": ["场景A"],
       "can_follow": false,
       "follow_condition": ""
     }
   ],
  "boss_encounters": [
    {
      "boss_ref": "Boss库中的名称",
      "scene": "出现场景",
      "description": "Boss在故事中的定位"
    }
  ],
  "enemies": [
    {"enemy_ref": "敌人名", "min_count": 0, "max_count": 2}
  ],
  "weapons": [
    {"weapon_ref": "武器名", "min_count": 1, "max_count": 1}
  ]
}

要求：
1. scenes 按玩家可能到达的顺序排列，使用场景中文名
2. characters 列出所有有名字或有重要作用的角色
3. 仅输出 JSON
4. 估算模组剧情的预计总耗时（分钟），综合考虑所有可能的探索路径和对话时长。写入 module_meta.estimated_duration。
5. 推荐通信间隔（分钟）写入 module_meta.comms_interval（短模组≤2h: 6-8min, 中型2-6h: 10-15min, 长型6-24h: 15-20min, 超长≥24h: 60-120min）。
6. 识别模组文档中提到的Boss、大怪、强敌，不为普通怪物——Boss是剧情核心敌人、需要特殊机制或为最终战。boss_ref 必须从 Boss 库中选择，若模组Boss不在库中则选择最接近的库中名称。提取后写入boss_encounters。
7. 设定模组开始时的时段（凌晨/早晨/白天/黄昏/夜间），写入 module_meta.starting_time_of_day。基于模组文本中描述的时间氛围判断。
8. enemy_ref 和 weapon_ref 必须从可用库中选择，不允许自创。数量约束宽松，只需符合背景；若模组未提及敌人/武器，返回空列表。
9. characters[].scenes：该NPC在模组中首次出现或主要所在的场景名（使用scenes列表中的中文名）。只填NPC实际出场的场景，不推测后续可能的去向。
10. characters[].can_follow：判断 NPC 是否可能跟随调查员行动。若NPC行动能力/性格/处境允许（非锁在固定位置、无强制离开理由、愿意协助），设为 true。
11. characters[].follow_condition：can_follow=true 时，描述跟随需满足的具体前置条件（自然语言）。无条件则写"无条件"。can_follow=false 时留空字符串。
"""



def build_step1a_prompt(content: str, weapon_library_names: list[str] = None, enemy_library_names: list[str] = None, boss_library_names: list[str] = None, item_names: list[str] = None, spell_names: list[str] = None) -> str:
    weapons_list = "\n".join(f"- {w}" for w in (weapon_library_names or []))
    enemies_list = "\n".join(f"- {e}" for e in (enemy_library_names or []))
    boss_list = "\n".join(f"- {b}" for b in (boss_library_names or []))
    items_list = "\n".join(f"- {n}" for n in (item_names or []))
    spells_list = "\n".join(f"- {n}" for n in (spell_names or []))
    resource_block = ""
    if items_list or spells_list:
        resource_block = f"""
## 可用物品库（item_gain / requirement 的 item: 可引用）
{items_list if items_list else "（未提供物品库）"}

## 可用法术库（@grant_spell 的 spell_ref 可引用 id 或名称）
{spells_list if spells_list else "（未提供法术库）"}
"""
    return f"""## 可用武器库
{weapons_list if weapons_list else "（未提供武器库，weapons 返回空列表）"}

## 可用敌人库
{enemies_list if enemies_list else "（未提供敌人库，enemies 返回空列表）"}

## Boss 库（boss_ref 必须从此列表中选择）
{boss_list if boss_list else "（未提供Boss库，boss_encounters 返回空列表）"}
{resource_block}
模组文档：
\"\"\"
{content}
\"\"\""""


def parse_step1a(content: str, llm_call, weapon_library_names: list[str] = None, enemy_library_names: list[str] = None, boss_library_names: list[str] = None, item_names: list[str] = None, spell_names: list[str] = None) -> dict:
    """从模组文档提取结构化元信息（含敌人/武器/Boss约束）."""
    prompt = build_step1a_prompt(content, weapon_library_names, enemy_library_names, boss_library_names, item_names, spell_names)
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

将以下模组文档整理为完整流畅的半结构化叙事文本。

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

## locations_and_map
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
"""

def build_step1b_prompt(content: str) -> str:
    return f"""模组文档：
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
- time_condition: 实体触发的时间约束。格式为 JSON 数组，每项 {"day": ">=N|<=N|N|ALL", "times": ["时段",...]}。数组内多项为 OR 关系，每项内 day 与 times 为 AND 关系，times 内各时段为 OR 关系。ALL 表示该维度不做限制。时段仅限：凌晨/早晨/白天/黄昏/夜间，天数从 1 开始。例：[{"day":">=2","times":["夜间"]}] 第2天及之后夜间触发，[] 表示无约束。大部分情况仅一个子项即可，多子项用于复杂时间要求
- side_effects 是间接后果：与 result 不重合的附带影响。如 "开抽屉的声响吸引了隔壁车厢的怪物"。自然语言字符串列表
- 互动完成即代表状态变更，不需要单独的 flag
- type 涉及技能鉴定时，填入 graded_result（分级检定后果），此时 result 填 "##GRADED##"（占位标记），side_effects 留空。所有结果描述写入 graded_result 各等级中；type 为"无"时不填 graded_result
- **type 必须从标准 COC 7th 技能列表中选择，严禁使用属性名（如"灵感""幸运""力量"等不是技能名）。不涉及检定的填"无"**
- based_on 始终为 null（Step 2b 会给派生实体填值）
- 通行路径记录每个场景的出边（from_here）和入边（to_here），包含通行方式和前置条件
- entity 的 result/side_effects/graded_result 不涉及进入与怪物的战斗/对抗/追捕的情况（怪物遭遇和战斗由 game loop 运行时统一管理）。可以声明怪物出现，但不描述进入和怪物的对砍/战斗
- **模组中提到的可获取物品（clues_and_items 章节：clues 为剧情关键物品/线索，items 为非剧情普通物品，需结合精修模组原文和常识判断）必须在对应场景的 entity 中通过 result 或 graded_result 明确表达为可获取状态，确保每个物品都有对应的 entity 承载其获取路径**
- **entity 的 result/trigger/side_effects 中涉及 NPC 名称时，必须使用已知角色列表中的名称，不允许自创或使用别名**
- NPC互动是否生成 entity 的判断标准：entity 必须有可感知的游戏机制后果——技能检定、物品给予/消耗、属性变化、NPC状态变更（受伤/死亡等）、触发新的事件、场景永久性变化。单纯的NPC对话/交谈/打听消息（无机制后果的信息传递）不生成 entity，由运行时 NPC 对话系统处理。
- **双路径 entity**：如果某个互动的结果或难度取决于前方某个关键事件的完成状态（如 NPC 是否已被救醒），可以为同一目标创建两个 entity：一个用于前置条件未满足时（更高难度或不同方式），一个用于前置条件已满足时（更低难度或 NPC 辅助）。两个 entity 通过不同的 requirement 区分，互为平行路径而非重复。
- NPC 跟随/离开实体由管线根据 Step 1a 的 can_follow 字段自动生成，你不要手动创建。
- 仅输出 JSON，不要任何解释性文字

从精修模组文本中提取每个场景的全部可执行互动，以及场景间的通行路径。

输出格式:
{
  "interactions": [
    {
      "id": "I1",
      "scene": "6号车厢",
      "type":  关联技能鉴定如"侦察"、"急救"等，不涉及则为"无",
      "name": "互动名称",
      "requirement": "硬性前置条件（entity ID + AND/OR/() 表达复合关系，裸 ID 默认指成功完成）||软性前置条件（特殊状态如实体检定失败、调查员理智极度崩溃等，无条件填空字符串）",
      "trigger": "触发场景（描述什么情况下玩家可以执行此互动），如：玩家检查抽屉时",
      "result": "直接结果（互动直接产生的结果），如：抽屉打开了，里面有一把钥匙",
      "side_effects": ["间接后果（与result不重合的附带影响），如：开抽屉的声响吸引了隔壁车厢的怪物。无条件则为空列表"],
      "graded_result": {"on_failure": "...", "on_regular": "...", "on_hard": "...", "on_extreme": "..."},
      "difficulty": "regular",
      "time_condition": [],
      "based_on": null
    }
  ],
  "scene_movements": {
    "6号车厢": {
      "from_here": [
        {"target": "7号车厢", "method": "步行通过车门", "requirement": "门未上锁"}
      ],
      "to_here": [
        {"source": "5号车厢", "method": "步行通过车门", "requirement": ""}
      ]
    },
    "7号车厢": { ... }
  }
}

要求：
1. id 全局唯一 (I1, I2, I3...)
2. scene 使用场景中文名
3. requirement: 硬性前置条件用 entity ID + AND/OR/() 表达复合关系（如 I1 AND I2、(I1 OR I2) AND I3），裸 entity ID 默认指该实体成功完成。无条件填空字符串。需要特殊条件（如实体检定失败、调查员理智极度崩溃等）在 "||" 后用自然语言描述。不要和 trigger 混淆
4. trigger 是触发场景：描述什么情况下玩家可以执行此互动。不要和 requirement 混淆
4a. time_condition: 时间触发约束，格式为 JSON 数组 [{"day": ">=2", "times": ["夜间"]}]。无约束填 []
5. result 是直接结果：互动直接产生的可感知结果，不含间接影响。如果此互动会直接触发游戏结局，result 必须以 ##END_结局名称:结局简述## 开头（如 "##END_真结局:电车冲出梦境##"），后续再写正常结果文本
6. side_effects 是间接后果：与 result 不重合的附带影响。自然语言字符串列表。无条件则为空列表
7. type 是涉及的技能鉴定名，不涉及则为"无"
8. difficulty 从以下选择：None/regular/hard/extreme；不涉及鉴定则为 None
9. graded_result：type 不为"无"时填写。此时 result 必须填 "##GRADED##"（占位标记），side_effects 必须留空。所有结果文字写入 graded_result 的四等级中。四等级含义：on_failure=检定失败、on_regular=常规成功、on_hard=困难成功、on_extreme=极难成功。若原文未区分等级结果，各等级可描述相同内容
10. 提取原文中提到的所有互动，即使描述简略也要列出
11. scene_movements 必须覆盖所有已知场景
12. 通行路径的 target/source 使用场景中文名，method 描述通行方式，requirement 描述硬性通行前置条件
13. 严格依据精修模组内容，基于场景氛围合理补充，不要和原文冲突
14. based_on 始终填 null（派生关系由 Step 2b 标注）
15. 模组 clues_and_items 章节中提到的可获取物品（clues=剧情物品/线索，items=非剧情普通物品，需结合精修模组原文和常识判断），必须在对应场景的 entity 中通过 result 或 graded_result 表达为可获取/可发现状态。每个物品都应有对应的 entity 承载其获取路径，不可遗漏
"""


def _format_char_list(characters: list[dict]) -> str:
    """Format character list with role/identity info in parentheses."""
    lines = []
    for c in (characters or []):
        name = c.get("name", "?")
        role = (c.get("role", "") or "").strip()
        entry = f"- {c.get('id', '?')}: {name}"
        if role:
            entry += f"（{role}）"
        lines.append(entry)
    return "\n".join(lines) if lines else "（无）"


def build_step2a_prompt(chapters: dict[str, str], scenes: list[dict], characters: list[dict] = None, skill_names: list[str] = None) -> str:
    scene_list = "\n".join(f"- {s}" for s in scenes)
    char_list = _format_char_list(characters)
    skills_str = "\n".join(f"- {s}" for s in (skill_names or []))
    return f"""已知场景列表:
{scene_list}

已知角色列表（entity 中涉及 NPC 名称时，必须使用下表中的名称）:
{char_list if char_list else "（无）"}

## 标准 COC 7th 技能列表（type 字段必须从此列表中选择，严禁使用属性名如"灵感""幸运"）
{skills_str if skills_str else "（未提供技能列表，请根据 COC 7th 规则常识选择标准技能名）"}

精修模组（参考上下文）：
\"\"\"
{_join_chapters(chapters, 'module_overview', 'scenes', 'clues_and_items', 'events_summary')}
\"\"\""""
def parse_step2a(chapters: dict[str, str], scenes: list[dict], llm_call, characters: list[dict] = None, skill_names: list[str] = None) -> dict:
    """从精修模组提取所有 interactions."""
    prompt = build_step2a_prompt(chapters, scenes, characters, skill_names=skill_names)
    result = llm_call(prompt, system=STEP2A_SYSTEM)
    # 落库归一：interaction 的 type 字段是技能名，旧技能名映射到新名；
    # 属性/伪技能/未识别保留原文（运行时单点兜底）
    for entity in (result or {}).get("interactions", []):
        if not isinstance(entity, dict):
            continue
        etype = entity.get("type")
        if not etype:
            continue
        kind, mapped = normalize_skill_name(etype)
        if kind == "skill" and mapped != etype:
            print(f"  [Step 2a] 技能名归一: {entity.get('id', '?')} type '{etype}' → '{mapped}'")
            entity["type"] = mapped
    return result


# ═══════════════════════════════════════════════════════════════
#  Step 2b: Events + Auto-triggers (合并)
# ═══════════════════════════════════════════════════════════════

STEP2B_COMBINED_SYSTEM = """你是一个 TRPG 模组解析助手，同时提取全局事件和自动触发事件。
你的任务是：从精修模组文本和已知互动中派生两类实体——全局事件（events）和自动触发事件（auto_triggers）。

术语：interaction、auto_trigger、event 三者统称为 entity（实体）。

## 通用原则
- 所有 entity 使用统一的字段模型（id/type/name/requirement/trigger/result/side_effects/graded_result/difficulty/based_on）
- based_on 指向派生的 interaction ID（非派生则留空）
- requirement: 硬性前置用 entity ID + AND/OR/() 表达，裸 ID 默认指成功完成。特殊条件在 "||" 后用自然语言描述；trigger 是触发场景描述，两者不可混淆
- time_condition: 同 Step 2a 格式，JSON 数组，每项 {"day": ">=N|<=N|N|ALL", "times": ["时段",...]}; 时段范围同（凌晨/早晨/白天/黄昏/夜间），天数从1开始。不填或 [] 表示不依赖时间
- type 涉及技能鉴定时填 graded_result（四等级: on_failure/on_regular/on_hard/on_extreme），result 填 "##GRADED##"，side_effects 留空
- result 是直接结果。如导致结局，必须以 ##END_结局名称:结局简述## 开头
- side_effects 是与 result 不重合的间接后果
- difficulty: None/regular/hard/extreme；不涉及检定则为 None
- entity 不涉及进入与怪物的战斗/对抗/追捕（战斗由 game loop 运行时管理）。可声明怪物出现，不描述对砍
- **entity 涉及 NPC 名称时必须使用已知角色列表中的名称**
- 与NPC的纯粹对话/交谈不生成 entity（NPC 对话由运行时 NPC 系统处理）。仅涉及实质性世界影响才生成
- NPC 跟随/离开实体由管线根据 Step 1a 的 can_follow 字段自动生成，你不要手动创建
- 仅输出 JSON，不要任何解释性文字

## 全局事件 (events)
- 跨场景的世界级变化，不绑定特定场景（无 scene 字段）
- 仅需不可逆的世界变化时才生成（结局触发、时间压力事件等）
- result 不可逆事件需标注"不可逆："

## 自动触发事件 (auto_triggers)
- 绑定特定场景（scene 字段必填）
- 被动触发，不生成玩家主动互动
- 每个场景生成 0-2 个
- 必须生成 AT_WORLD（id="AT_WORLD", scene="world", type="无", difficulty="None", based_on=""）用于世界初始化。trigger="模组开始时自动触发"，result="世界环境初始化"。side_effects 中用 @标记 声明：
  1调查员初始时身上带着什么
  2哪个场景散布着什么武器
  3哪个场景可能会有什么敌人，有多少
- clues_and_items 中标记为初始可见/场景内放置的物品，必须生成为进入场景时的 auto_trigger（requirement 留空），trigger="玩家进入此场景时"

**@标记精确语法（必须严格按此格式）:**
@spawn_enemy(enemy_ref="敌人库名", scene="场景名", quantity=数量)
@grant_weapon(weapon_ref="武器库名", scene="场景名", quantity=数量)
@grant_spell(spell_ref="法术库id或名称") -- 授予玩家法术（加入 known_spells）
@item_gain(item_name="物品名", quantity=数量)
示例: ["@spawn_enemy(enemy_ref=\"Clicker\", scene=\"2号车厢\", quantity=3)", "@item_gain(item_name=\"手电筒\", quantity=1)"]
每个 @标记 必须是独立的一条数组元素，格式严格为 @函数(参数=值, ...)
enemy_ref 和 weapon_ref 必须来自约束列表，@spawn_enemy / @grant_weapon 总调用次数不超过对应 max_count
特别说明：@grant_weapon 的 scene 为空字符串（scene=""）表示直接授予调查员，无需放置到场景中。"""


def build_step2b_combined_prompt(
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
    char_list = _format_char_list(characters)
    enemy_list = "\n".join(f"- {e['enemy_ref']} (max {e.get('max_count',1)})" for e in (enemies or []))
    weapon_list = "\n".join(f"- {w['weapon_ref']} (max {w.get('max_count',1)})" for w in (weapons or []))
    return f"""已知场景:
{scene_list}

已知角色列表（entity 中涉及 NPC 名称时，必须使用下表中的名称）:
{char_list if char_list else "（无）"}

已知互动（events 和 auto_triggers 可基于这些互动派生，based_on 指向其 ID）:
{interaction_list}

## 敌人约束
{enemy_list if enemy_list else "（无约束）"}

## 武器约束
{weapon_list if weapon_list else "（无约束）"}

精修模组（参考上下文）：
\"\"\"
{_join_chapters(chapters, 'module_overview', 'scenes', 'clues_and_items', 'events_summary')}
\"\"\""""


def parse_step2b_combined(
    chapters: dict[str, str],
    scenes: list[dict],
    interactions: list[dict],
    llm_call,
    characters: list[dict] = None,
    enemies: list[dict] = None,
    weapons: list[dict] = None,
) -> dict:
    """合并的 Step 2b：单次 LLM 调用同时提取 events 和 auto_triggers。"""
    prompt = build_step2b_combined_prompt(chapters, scenes, interactions,
                                           characters, enemies, weapons)
    return llm_call(prompt, system=STEP2B_COMBINED_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 2c: L1 玩家可见层
# ═══════════════════════════════════════════════════════════════

STEP2C_L1_SYSTEM = f"""你是一个 TRPG 模组解析助手，专门提取「玩家可见层」信息。
你的任务是：从精修模组文本中提取每个场景的初始感知信息——玩家进入场景时无需任何检定即可直接感知的一切。

重要原则：
- 严格按照输出格式参考输出 json 文件
- 只描述无条件可见的内容（外观、声音、气味、氛围）
- 需要检定才能发现的信息 → 不放在这里（那是 L2 的事）
- NPC 只描述外貌和神态（name, brief, demeanor），不写隐藏动机、对话内容或互动逻辑
- NPC 的互动由 L2 层通过 entity（interaction/auto_trigger/event）承载
- 你是模组叙述者，你只负责描述玩家"现在"能见到/感受到的信息

从精修模组文本中提取每个场景的「玩家初始感知信息」。

输出格式参考：
{json.dumps(L1_TEMPLATE, ensure_ascii=False, indent=2)}

要求：
1. 每个场景使用其名称作为顶层 key（如"6号车厢"）
2. description：沉浸式第三人称场景描写，兼顾表达清晰与文学性。不带玩家主观视角，只客观描述场景的环境、光线、声音、气味等感官细节。类似于小说的环境描写，让读者仿佛身临其境。长度 50-200 字。
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
"""


def build_step2c_l1_prompt(chapters: dict[str, str], scenes: list[dict], characters: list[dict]) -> str:
    scene_list = "\n".join(f"- {s}" for s in scenes)
    char_list = _format_char_list(characters)
    return f"""已知场景列表（必须使用这些场景名作为 JSON key）:
{scene_list}

已知角色列表（npc_appearances 中的 NPC 名称必须来自此列表）:
{char_list}

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

STEP2C_L3_SYSTEM = f"""你是一个优秀的 TRPG 模组设计师，专门提取「设计者层」信息。
你的具体任务是：从精修模组文本中提取模组的设计意图、世界规则、场景设计目的、NPC行为逻辑和基调约束。

重要原则：
- 这是设计者层，描述「为什么」这个模组这样设计，而非「有什么」内容
- world_rules 是世界运行的物理/超自然法则
- scene_intents 描述每个场景的设计目的
- characters 描述每个 NPC 的行为逻辑和叙事作用（设计意图，不是具体对话内容）
- driving_force 是一切事件的根本驱动力
- 你作为高层叙事者不必完全拘泥于精修模组的已有内容，可以基于原文进行合理的补充和推测

从精修模组文本中提取「设计者层」信息（L3 层）。

输出格式参考：
{json.dumps(L3_TEMPLATE, ensure_ascii=False, indent=2)}

要求：
1. module_meta：模组元信息。优先使用 Step 1a 已提取的值（title/era/theme），仅补充 Step 1a 中为空的字段（author/expected_duration/player_count）；另填 player_goal（一句话玩家目标，如「调查古宅真相并活着离开」）
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
"""


def build_step2c_l3_prompt(chapters: dict[str, str], scenes: list[dict], characters: list[dict], step1_meta: dict = None) -> str:
    meta_ref = json.dumps(step1_meta, ensure_ascii=False, indent=2) if step1_meta else "（无）"
    scene_list = "\n".join(f"- {s}" for s in scenes)
    char_list = _format_char_list(characters)
    return f"""已知场景列表:
{scene_list}

已知角色列表（characters 的 id 和 name 必须来自此列表）:
{char_list}

## Step 1a 已提取的元信息（优先使用，仅补充缺失字段）
{meta_ref}

精修模组：
\"\"\"
{"\n\n".join(chapters.values())}
\"\"\""""


def parse_step2c_l3(chapters: dict[str, str], scenes: list[dict], characters: list[dict], llm_call, step1_meta: dict = None) -> dict:
    prompt = build_step2c_l3_prompt(chapters, scenes, characters, step1_meta)
    return llm_call(prompt, system=STEP2C_L3_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 2.5: NPC 档案 + 实体归属（合并）
# ═══════════════════════════════════════════════════════════════

STEP25_COMBINED_SYSTEM = """你是一个 TRPG NPC 设计助手。
你的任务有三部分：(1) 为每个 NPC 生成完整行为描述档案；(2) 判断每个 L2 entity 归属于哪个 NPC；(3) 分析 NPC 的跟随和互动解锁条件。

术语：interaction、auto_trigger 统称为 entity。

## 第一部分：NPC 行为档案
- 基于 L3 角色设计意图、L1 外貌描述和 L2 entity 互动信息
- appearance：综合 L1 NPC 外貌描述（brief + demeanor），提炼为一段完整的外貌叙述
- role：一句话角色定位
- what_they_can_do：描述 NPC 的能力、所知信息和互动条件（核心字段）
- personality_notes：性格、说话风格、情绪倾向
- interaction_triggers：什么情况下玩家可与该 NPC 自由对话（自然语言列表，从 entity trigger 中提炼）
- initial_state：NPC 初始存活状态，默认 "alive"
- initial_attitude：NPC 初始态度，默认 "neutral"（可选值：hostile / wary / neutral / friendly / allied）
- initial_following：初始是否已跟随玩家，默认 false
- can_interact：NPC 是否具备互动能力（默认 true）。若 false，表示 NPC 从本质上不能自由对话（如昏迷、充满敌意、只出现于固定演出），需通过 interact_unlock entity 解锁。此字段描述 NPC 的"本质属性"，与 interact_requirements（条件性门禁）互补：两者同时满足时互动才可用
- can_follow：NPC 是否可能跟随调查员行动
- Step 1a 初步判断仅作参考，基于 L1/L2/L3 完整信息做出最终判断
- 只使用提供的信息，不编造新角色或新能力

## 第二部分：Entity 归属
- 若 entity 的触发/结果/名称明确涉及某个 NPC（该 NPC 是互动的对象或主体），标记该 entity 属于该 NPC
- 若 entity 描述的是场景通用互动（不特指某个 NPC），不标记
- 一个 entity 最多属于一个 NPC
- 将标记结果填入对应 NPC 的 bound_entities 列表

## 第三部分：跟随和互动解锁条件
- 基于所有 entity 信息，分析 NPC 的 follow 和 interact 解锁条件
- follow_requirements：NPC 跟随调查员的前置条件
  - 硬性条件（entity ID 引用）放在 || 之前，格式与 requirement 字段一致：entity ID + AND/OR/()，如 I3 AND I5、(I1 OR I2) AND I3。裸 entity ID 默认指该实体成功完成
  - 软性条件（自然语言描述如信任/关系/剧情状态）放在 || 之后
  - 无条件则留空字符串
- interact_requirements：NPC 自由对话的前置条件（即使 can_interact=true 也需满足）
  - 格式同 follow_requirements：硬性 entity ID 条件（|| 前）+ 软性自然语言条件（|| 后）
  - 无条件则留空字符串——NPC 从开局即可自由对话
  - 注：can_interact 是 NPC 本质属性（"能否对话"），interact_requirements 是条件门禁（"何时能对话"）。例如 can_interact=true + interact_requirements="I6" 表示 NPC 有能力对话，但需先完成 I6
  - 注：entity 互动（bound_entities 中的 entity）不受 can_interact 或 interact_requirements 影响，始终可通过正常管线触发

## 输出格式
{
  "npc_profiles": {
    "NPC名称": {
      "name": "NPC名称",
      "role": "一句话角色定位",
      "appearance": "综合外貌描述（50-150字）",
      "what_they_can_do": "NPC能做什么、在什么条件下会做什么",
      "personality_notes": "性格和说话风格",
      "interaction_triggers": ["玩家靠近时NPC主动搭话", "玩家持有某物品时触发对话"],
      "initial_state": "alive",
      "initial_attitude": "neutral",
      "initial_following": false,
      "can_interact": true,
      "can_follow": true,
      "follow_requirements": "I3 AND I5 || NPC信任调查员后愿意跟随",
      "interact_requirements": "I6 || 救治NPC后他愿意交谈",
      "bound_entities": ["I1", "AT2"]
    }
  }
}

规则：
- 必须覆盖 L3 characters 中的所有角色
- can_follow / can_interact 基于完整 L1+L2+L3 信息综合判断，Step 1a 的初步判断仅作参考。can_interact 与 interact_requirements 独立评估：前者是 NPC 的本质互动能力，后者是条件性门禁。两者同时满足时自由对话才可用
- bound_entities：该 NPC 专属的 entity ID 列表（scene 通用 entity 不列入）
- follow_requirements / interact_requirements：|| 前为硬性 entity ID 条件，|| 后为软性自然语言条件；纯硬性或纯软性可省略 || 的另一侧
- 仅输出 JSON，不要任何解释性文字"""


def build_step25_combined_prompt(
    l3_characters: list[dict],
    l1_data: dict,
    interactions: list[dict],
    auto_triggers: list[dict],
    step1a_characters: list[dict] = None,
) -> str:
    # NPC appearances from L1
    npc_appearances = []
    for scene_name, sdata in l1_data.items():
        for npc in sdata.get("npc_appearances", []):
            npc_appearances.append({
                "name": npc.get("name", ""),
                "brief": npc.get("brief", ""),
                "demeanor": npc.get("demeanor", ""),
                "scene": scene_name,
            })

    # Entity list for binding
    entity_list = []
    for e in interactions:
        entity_list.append({
            "id": e.get("id", ""), "scene": e.get("scene", ""),
            "name": e.get("name", ""),
            "trigger": e.get("trigger", "")[:80],
            "result": e.get("result", "")[:120],
        })
    for e in auto_triggers:
        entity_list.append({
            "id": e.get("id", ""), "scene": e.get("scene", ""),
            "name": e.get("name", ""),
            "trigger": e.get("trigger", "")[:80],
            "result": e.get("result", "")[:120],
        })

    # Step 1a character hints (preliminary assessment, for reference only)
    step1a_hints = []
    for c in (step1a_characters or []):
        if isinstance(c, dict):
            step1a_hints.append({
                "name": c.get("name", ""),
                "id": c.get("id", ""),
                "role": c.get("role", ""),
                "scenes": c.get("scenes", []),
                "can_follow_hint": c.get("can_follow"),
                "follow_condition_hint": c.get("follow_condition", ""),
            })

    return f"""## L3 角色设计意图
{json.dumps(l3_characters, ensure_ascii=False, indent=2)}

## L1 NPC 外貌
{json.dumps(npc_appearances, ensure_ascii=False, indent=2) if npc_appearances else "（无）"}

## L2 Entity 列表
{json.dumps(entity_list, ensure_ascii=False, indent=2)}

## Step 1a 初步判断（仅供参考，最终以 L1+L2+L3 综合信息为准）
{json.dumps(step1a_hints, ensure_ascii=False, indent=2) if step1a_hints else "（无）"}"""


def parse_step25_combined(
    l3_characters: list[dict],
    l1_data: dict,
    interactions: list[dict],
    auto_triggers: list[dict],
    llm_call,
    step1a_characters: list[dict] = None,
) -> dict:
    """合并的 Step 2.5：单次 LLM 调用生成 NPC 档案 + entity 归属。"""
    prompt = build_step25_combined_prompt(l3_characters, l1_data, interactions,
                                           auto_triggers, step1a_characters)
    return llm_call(prompt, system=STEP25_COMBINED_SYSTEM)


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
- 仅输出 JSON，不要任何解释性文字

根据以下 Boss 识别结果，生成结构化的 Boss Encounter 实体。

输出格式:
{
  "boss_encounters": [
    {
      "id": "BOSS_1",
      "type": "boss_encounter",
      "engage_type": "at|interaction|event",
      "boss_ref": "Boss库中的名称",
      "scene": "所在场景",
      "requirements": "(entity ID + AND/OR/()) || 软性描述条件",
      "description": "进入战斗时的情境描述"
    }
  ]
}

要求:
1. engage_type 判定: 进入场景自动触发→"at", 玩家主动操作→"interaction", 全局条件满足→"event"
2. requirements 使用 (hard) || soft 格式。hard 部分引用已知 entity 的 ID（如 I2、AT3），soft 部分用自然语言描述（如"玩家下到地下室"）
3. boss_ref 必须从 Boss 库中选择。若 Step 1 识别的 boss_name 不在库中，选择最接近的库中名称
4. scene 使用统一场景名
5. description 基于精修模组内容扩写为一段紧张的情境叙述（50-150字），从玩家视角描述进入战斗的瞬间
6. 仅输出 JSON
"""


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

    return f"""## Boss 库（boss_ref 必须从此列表中选择）
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
\"\"\""""


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
你的任务是：检查所有 interaction/event/auto_trigger，去重，验证 graded_result，修剪 result/side_effects 重合，解决冲突，验证结局标记。

重要原则：
- interaction/event/auto_trigger统称为entity
- **唯一去重条件**：两个 entity 描述的是同一件事情的发生（判断标准：指代同一事件，不仅仅是同一 based_on 源，也不是文字相似）。仅在这种情况下合并为一个。
- **双路径 entity 保护**：如果两个 entity 实现同一目标但前置条件不同（如 I7 无 NPC 帮助 hard 难度，I8 有 NPC 帮助 regular 难度），它们代表不同的游戏路径，不是重复 entity，绝对不应合并。
- 合并时优先保留 auto_trigger 和 interaction（event 的信息合入保留方，不丢失）
- graded_result 在 type != "无" 时强制填写至少1条；type == "无" 时删除空 graded_result
- result 和 side_effects 信息重合时修剪一方。result 为 "##GRADED##" 时跳过此检查
- requirement/trigger 冲突以 精修模组（参考上下文） 为准修正
- **requirement 保护规则**: requirement 中引用的 entity ID 依赖链（如 I8 的 requirement 为 "I7"）即使不是 based_on 关系也绝对不得清除或替换为空格。只修正格式错误（如多余空格、错误大小写），不改变 requirement 的语义内容
- ##END_## 标记与 L3 ending_conditions 相互补齐
- 不删改实质信息，只修正名称和引用
- 互动完成即代表状态变更，不需要单独的 flag
- 仅输出 JSON，不要任何解释性文字

对以下模组中的所有 L2 内容做去重、冲突解决和结局验证。

任务:
1. **去重**: 仅当两个 entity 描述的是同一件事情的发生时才合并。based_on 相同的 entity 不去重——event 和其源 interaction 是不同实体（一个代表玩家行动，一个代表世界变化）。合并时优先保留 interaction/auto_trigger，被合并方的重要信息合入保留方。
2. **Graded_result 检查**: type != "无" 时填写 graded_result 中至少一条；type == "无" 时删除空 graded_result。
3. **Result / Side_effects 去重**: 若 result 为 "##GRADED##" 跳过此检查。否则若 side_effects 中的某条内容已在 result 中体现，移除该条。
4. **冲突解决**: requirement/trigger 矛盾以 精修模组（参考上下文） 为准修正。
5. **结局标记验证**: 扫描 ##END_## 标记与 L3 ending_conditions 做语义匹配。标记缺失则基于L3信息补齐。

输出格式:
{
  "interactions": [{ ...原字段... }],
  "events": [{ ...原字段... }],
  "auto_triggers": [{ ...原字段... }]
}
注意 interaction/event/auto_trigger统称为entity
仅输出 JSON。
"""


def build_step3a_prompt(
    chapters: dict[str, str],
    interactions: list[dict],
    events: list[dict],
    auto_triggers: list[dict],
    ending_conditions: list[dict],
) -> str:
    return f"""## 精修模组（参考上下文）
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
{json.dumps(auto_triggers, ensure_ascii=False, indent=2)}"""


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

def _step3b_deterministic(
    l1_data: dict, l2_completed: dict, l3_data: dict,
    step1_scenes: list[str],
) -> tuple[dict, dict, list[dict]]:
    """Step 3b 确定性部分：场景名/角色名一致性、引用有效性、覆盖完整性。
    Returns (fixed_l1, fixed_l3, link_gaps) where link_gaps are perceptible elements
    that might need linked_interaction (LLM).
    """
    import copy
    l1 = copy.deepcopy(l1_data)
    l3 = copy.deepcopy(l3_data)

    # Collect canonical names
    scene_names = set(step1_scenes)
    l2_interaction_names: set[str] = set()
    l2_npc_names: set[str] = set()
    for sdata in l2_completed.get("scenes", {}).values():
        for i in sdata.get("interactions", []):
            if i.get("name"):
                l2_interaction_names.add(i["name"])
    for npc_name in l2_completed.get("npc_profiles", {}):
        l2_npc_names.add(npc_name)
    l3_char_names: set[str] = set()
    for c in l3.get("characters", []):
        if isinstance(c, dict) and c.get("name"):
            l3_char_names.add(c["name"])
    # Collect NPCs from L1 appearances
    l1_npc_names: set[str] = set()
    for sname, sdata in l1.items():
        for npc in sdata.get("npc_appearances", []):
            if npc.get("name"):
                l1_npc_names.add(npc["name"])
    all_npc_names = l1_npc_names | l2_npc_names

    # ── 1. Scene name consistency ──
    l1_keys = list(l1.keys())
    for key in l1_keys:
        if key not in scene_names:
            # Try to find matching scene (case-insensitive)
            match = next((s for s in scene_names if s.lower() == key.lower()), None)
            if match:
                l1[match] = l1.pop(key)
            # else: keep as-is, can't resolve

    # ── 2. linked_interaction validity ──
    link_gaps = []
    for sname, sdata in l1.items():
        for elem in sdata.get("perceptible", []):
            linked = elem.get("linked_interaction", "")
            if linked and linked not in l2_interaction_names:
                elem["linked_interaction"] = ""  # Clear invalid ref
            if not linked:
                link_gaps.append({
                    "scene": sname,
                    "element_name": elem.get("name", ""),
                    "element_brief": elem.get("brief", ""),
                })

    # ── 3. NPC name consistency ──
    # Collect all L3 character names (canonical source)
    canonical_npc: dict[str, str] = {}  # lowercase → canonical
    for name in l3_char_names:
        canonical_npc[name.lower()] = name
    for sname, sdata in l1.items():
        for npc in sdata.get("npc_appearances", []):
            npc_name = npc.get("name", "")
            if npc_name and npc_name.lower() in canonical_npc:
                canonical = canonical_npc[npc_name.lower()]
                if npc_name != canonical:
                    npc["name"] = canonical

    # ── 5. L3 scene_intents coverage ──
    scene_intents = l3.setdefault("scene_intents", {})
    for sname in scene_names:
        if sname not in scene_intents:
            scene_intents[sname] = ""

    # ── 6. L3 characters coverage ──
    for name in all_npc_names:
        if name and name.lower() not in canonical_npc:
            l3.setdefault("characters", []).append({
                "name": name,
                "personality": "", "role": "",
                "what_they_can_do": "", "character_arc": "",
            })

    return l1, l3, link_gaps


STEP3B_LINK_SYSTEM = """你是一个 TRPG 内容关联助手。
你的任务是：判断 L1 感知元素是否应关联到 L2 互动，补充缺失的 linked_interaction。

判断标准：
- 如果感知元素描述的是玩家能看到/感知到的东西，且 L2 中有对应的互动（如"检查XX"、"搜寻XX"），则应关联
- 如果感知元素是纯氛围描述（如"昏暗的光线"、"空气中有血腥味"），不需要关联

输出格式:
{"links": [{"scene": "场景名", "element_name": "元素名", "linked_interaction": "互动名或空字符串"}]}

仅输出 JSON。"""


def build_step3b_link_prompt(l1_data: dict, l2_completed: dict, link_gaps: list[dict]) -> str:
    # Build compact L2 interaction reference
    l2_refs = []
    for sname, sdata in l2_completed.get("scenes", {}).items():
        for i in sdata.get("interactions", []):
            l2_refs.append({
                "scene": sname, "id": i.get("id", ""),
                "name": i.get("name", ""), "trigger": i.get("trigger", "")[:60],
            })
    return f"""## L2 互动参考
{json.dumps(l2_refs, ensure_ascii=False, indent=2)}

## 需要判断的感知元素
{json.dumps(link_gaps, ensure_ascii=False, indent=2)}"""


def parse_step3b(
    chapters: dict[str, str],
    l1_data: dict,
    l2_completed: dict,
    l3_data: dict,
    step1_scenes: list[dict],
    llm_call,
) -> dict:
    """Step 3b：确定性修复场景名/NPC名/引用/覆盖 → LLM 仅补 linked_interaction gap → key 合并。"""
    scene_names = [s.get("name", s) if isinstance(s, dict) else s for s in step1_scenes]

    # Phase 1: deterministic
    l1, l3, link_gaps = _step3b_deterministic(l1_data, l2_completed, l3_data, scene_names)

    # Phase 2: LLM gap-fill (only if there are gaps)
    if link_gaps:
        try:
            prompt = build_step3b_link_prompt(l1, l2_completed, link_gaps)
            llm_result = llm_call(prompt, system=STEP3B_LINK_SYSTEM)
            for link in llm_result.get("links", []):
                scene = link.get("scene", "")
                elem_name = link.get("element_name", "")
                linked = link.get("linked_interaction", "")
                if linked and scene in l1:
                    for elem in l1[scene].get("perceptible", []):
                        if elem.get("name") == elem_name:
                            elem["linked_interaction"] = linked
                            break
        except Exception:
            pass  # LLM gap-fill is best-effort

    return {"l1_data": l1, "l3_data": l3}


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
- 仅输出 JSON，不要任何解释性文字

从以下 L2 实体的 requirement 和 trigger 字段中提取并标准化所有依赖关系。

任务:
1. 扫描每个 entity 的 requirement 字段。格式为：硬性条件（entity ID + AND/OR/()）|| 软性条件（自然语言）
2. 提取其中描述的依赖关系，标准化为:
   - 硬性条件中裸 entity ID（如 I3）默认指该实体完成 → {{"type": "interaction", "id": "I3"}}
     AND/OR 连接的每个 entity ID 各提取为一条独立依赖
    - 软性条件（|| 之后）中如提到其他 entity ID → 同样提取为 {{"type": "interaction", "id": "I4"}}
    - trigger 中如提到 "E1 已触发" → {{"type": "event", "id": "E1"}}
      每条 entity 的 requires 列出所有提取到的依赖（可为空列表）
    - 依赖仅表示"必须完成目标 entity"，不区分成功/失败/触发等条件（requirement 语义由 runtime 解析）
    - **反向依赖识别**: || 后软性条件可能含反向依赖（如 "I7 检定失败或未进行"），此时 I7 不是本 entity 的前置依赖而是反向条件。含否定词（失败/未进行/未触发/未完成）描述的 entity ID 不提取为依赖，由 runtime 运行时判定

3. 每条 entity 必须在输出中列出，requires 为空列表表示无依赖
4. 实体 ID 必须精确匹配（如 I3 不能写成 I03）

输出格式:
{
  "dependencies": [
    {
      "entity_id": "I1",
      "requires": []
    },
    {
      "entity_id": "I3",
      "requires": [
        {{"type": "interaction", "id": "I1"}}
      ]
    },
    {
      "entity_id": "I5",
      "requires": [
        {{"type": "interaction", "id": "I3"}},
        {{"type": "interaction", "id": "I4"}}
      ]
    }
  ]
}

仅输出 JSON。
"""


def build_step35_prompt(
    chapters: dict[str, str],
    interactions: list[dict],
    events: list[dict],
    auto_triggers: list[dict],
) -> str:
    interaction_list = json.dumps(interactions, ensure_ascii=False, indent=2)
    events_list = json.dumps(events, ensure_ascii=False, indent=2)
    at_list = json.dumps(auto_triggers, ensure_ascii=False, indent=2)
    return f"""## 精修模组（参考上下文）
\"\"\"
{_join_chapters(chapters, 'module_overview', 'scenes', 'events_summary')}
\"\"\"

## Interactions
{interaction_list}

## Events
{events_list}

## Auto-triggers
{at_list}"""


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
- 仅输出 JSON，不要任何解释性文字

根据模组背景确定敌人和武器的风格方向与数量范围。

输出格式:
{
  "enemies": [
    {"enemy_ref": "敌人名", "min_count": 0, "max_count": 2}
  ],
  "weapons": [
    {"weapon_ref": "武器名", "min_count": 1, "max_count": 1}
  ]
}

要求：
1. enemy_ref 和 weapon_ref 必须从可用库中选择，不允许自创
2. 数量约束宽松，只需符合背景；若模组未提及敌人/武器，返回空列表
3. 仅输出 JSON
"""


def build_phase1_prompt(
    chapters: dict[str, str],
    scene_intents: dict,
    weapon_library_names: list[str],
    enemy_library_names: list[str],
) -> str:
    weapons_list = "\n".join(f"- {w}" for w in weapon_library_names)
    enemies_list = "\n".join(f"- {e}" for e in enemy_library_names)
    return f"""## 可用武器库
{weapons_list}

## 可用敌人库
{enemies_list}

## L3 Scene Intents（设计意图参考）
{json.dumps(scene_intents, ensure_ascii=False, indent=2)}

## 精修模组
\"\"\"
{"\n\n".join(chapters.values())}
\"\"\""""


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
- **遇到符合函数说明的情况必须使用@markup函数，不要用自然语言替代**
- 仅输出 JSON，不要任何解释性文字

标准化 type，将 side_effects/result/graded_result 转为 @函数(参数) 标记。

任务:
1. **type 标准化**: 从标准技能列表中选择最匹配的技能名。不涉及检定的保持"无"。
2. **@标记转化**: 将 side_effects / result / graded_result 中的自然语言转化为 @函数(参数=值) 标记:

    @spawn_enemy(enemy_ref="敌人名", scene="场景名", quantity=1)
      用法：在某个场景中生成敌人。enemy_ref 必须来自约束列表。
    @grant_weapon(weapon_ref="武器名", scene="场景名", quantity=1)
      用法：武器放置到场景中（scene 非空），或直接授予调查员（scene=""）。
    @grant_spell(spell_ref="法术库id或名称")
      用法：授予玩家法术（加入 known_spells）。spell_ref 必须来自法术库列表。
    @stat_change(stat_name="属性名", delta=-1, narrative="角色经历（可选）")
      用法：调查员属性变化——包括损失/恢复 HP、SAN、MP，或获得技能点。delta 正数为增加，负数为减少。stat_name 必须来自标准属性列表。
    @item_gain(item_name="物品名", quantity=1)
      用法：调查员获得可携带的剧情/消耗品（非武器）。物品名不做库匹配，自由命名。
    @consume_item(item_name="物品名", quantity=1, narrative="消耗原因（可选）")
      用法：调查员使用或消耗了一个可消耗物品，使用后该物品不可再用（如急救包、火柴、弹药）。注意：仅用于"用完即没"的可消耗品，不用于可重复使用的装备。
    @npc_state_change(npc_name="NPC名", new_state="新状态")
      用法：NPC 本身的状态变化——如从"alive"变为"dead"、从"unconscious"变为"alive"、从"hostile"变为"neutral"等。npc_name 必须与 NPC 列表中精确一致。
    @npc_follow(npc_name="NPC名", follow=true)
      用法：NPC 开始（true）或停止（false）跟随调查员行动。仅用于跟随关系的切换，不使用其他场合。

    特别说明：
    - @npc_state_change 有两个硬编码的特殊状态：
      "dead" — NPC 死亡，此后该 NPC 不再参与对话、跟随和场景互动，其 bound entity 也不会出现在玩家可用的实体列表中。
      "left" — NPC 永久离开模组（如离场、失踪、退场），效果同 dead，但用于非死亡离场场景。
    - 其他状态（alive / unconscious / hostile / neutral / friendly 等）由 LLM 在对话时根据状态值自行发挥，不需硬编码处理。
    - @grant_weapon 的 scene 为空字符串（scene=\"\"）表示直接授予调查员，无需放置到场景中等待搜索发现。scene 有值时，武器放置到对应场景中，由调查员通过搜索发现并拾取。

   无法归入以上类型的保留原自然语言。

3. **数量约束**: spawn_enemy / grant_weapon 的总调用次数不得超过 Phase 1 约束中对应条目的 max_count。
4. **结果嵌入**: @标记可嵌入 result / graded_result 各等级 / side_effects 等任何字段。graded_result 各等级为独立字符串，可独立含 @标记。
5. 不允许自创 enemy_ref / weapon_ref / stat_name。
6. type 为"无"的 entity 若无实质 side_effects 则保持原样。
7. **time_condition 格式校验**: entity 若含 time_condition 字段，校验格式为 [{"day": ">=N|<=N|N|ALL", "times": ["时段",...]}]，时段仅限 凌晨/早晨/白天/黄昏/夜间，天数从1起。无约束则为 []

输出格式:
{
  "interactions": [{ ...entity 字段..., "type": "标准技能名", "time_condition": [] }],
  "auto_triggers": [{ ...entity 字段..., "type": "标准技能名", "time_condition": [] }]
}

仅输出 JSON。
"""


def build_step4_prompt(
    interactions: list[dict],
    auto_triggers: list[dict],
    l2_descriptions: dict[str, str],
    scene_intents: dict,
    chapters: dict[str, str],
    phase1_constraints: dict,
    skill_names: list[str],
    stat_names: list[str],
    npc_profiles: dict = None,
) -> str:
    skills_list = "\n".join(f"- {s}" for s in skill_names)
    stats_list = "\n".join(f"- {s}" for s in stat_names)
    desc_list = "\n".join(f"- {name}: {desc}" for name, desc in l2_descriptions.items())
    npc_names_list = "\n".join(f"- {n}" for n in (npc_profiles or {}).keys()) if npc_profiles else "（无）"

    # Slim entities to 6 fields only
    slim_interactions = json.dumps(
        [_slim_entity(i) for i in interactions], ensure_ascii=False, indent=2
    )
    slim_at = json.dumps(
        [_slim_entity(a) for a in auto_triggers], ensure_ascii=False, indent=2
    )

    scene_names = "\n".join(f"- {name}" for name in l2_descriptions.keys())

    return f"""## Phase 1 约束（spawn_enemy / grant_weapon 必须在约束范围内）
{json.dumps(phase1_constraints, ensure_ascii=False, indent=2)}

## 标准场景名称列表（@标记中的 scene 必须使用下表中的名称）
{scene_names}

## 标准时段名称（time_of_day 必须使用下表中的名称）
凌晨、早晨、白天、黄昏、夜间

## 标准技能列表（type 必须从此列表中选择）
{skills_list}

## 标准属性列表（stat_change 的 stat_name 必须从此列表中选择）
{stats_list}

## NPC 名称列表（@npc_state_change / @npc_follow 的 npc_name 必须精确使用下表中的名称）
{npc_names_list}

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
{slim_at}"""


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
    npc_profiles: dict = None,
) -> dict:
    prompt = build_step4_prompt(
        interactions, auto_triggers, l2_descriptions,
        scene_intents, chapters,
        phase1_constraints, skill_names, stat_names,
        npc_profiles=npc_profiles,
    )
    return llm_call(prompt, system=STEP4_SYSTEM)
