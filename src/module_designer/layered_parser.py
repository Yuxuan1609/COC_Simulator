"""
三层解析器：从模组源文档一键生成 L1 + L2 + L3 JSON。

流程：
  source.txt → parse_l1() + parse_l2() + parse_l3() → 三层 JSON
  或
  source.txt → parse_module() → (l1_data, l2_data, l3_data)
"""
from __future__ import annotations
import json
import os
from typing import Tuple


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


# ═══════════════════════════════════════════════════════════════
#  L1 解析
# ═══════════════════════════════════════════════════════════════

L1_SYSTEM = """你是一个 TRPG 模组解析助手，专门提取「玩家可见层」信息。
你的任务是：从模组文档中提取每个场景的**初始感知信息**——玩家进入场景时，无需任何检定即可直接感知的一切。

重要原则：
- 只描述**无条件可见**的内容（外观、声音、气味、氛围）
- 需要检定才能发现的信息 → 不要放在这里（那是 L2 的事）
- NPC 只描述外貌和神态，不写隐藏动机（那是 L2 的事）
- 用沉浸式中文，但保持简洁
- mood 从以下选择：confused / uneasy / tense / terrified / hopeful / desperate
- perceptible type 从以下选择：object / sound / smell / sight / touch / intuition"""


def build_l1_prompt(content: str) -> str:
    """构建 L1 解析 prompt."""
    template = _load_template("l1_template.json")
    return f"""根据以下模组文档，提取每个场景的「玩家初始感知信息」（L1 层）。

输出格式参考：
{template}

要求：
1. 每个场景作为一个顶层 key，key 名为场景名称（如"6号车厢"）
2. entry_narrative：玩家进入该场景时的开场叙事（KP 可直接朗读，80-200字）
3. atmosphere：场景氛围一句话总结（如"昏暗封闭、空气中弥漫霉味"）
4. mood：该场景的目标情绪基调（confused/uneasy/tense/terrified/hopeful/desperate）
5. perceptible：玩家无需检定即可感知的元素列表：
   - type：感知类型（object/sound/smell/sight/touch/intuition）
   - name：元素名称
   - brief：一句话描述
   - linked_interaction：可选，关联的 L2 互动名称（暂可留空，后续 pipeline 会补充）
6. ambient_hints：微妙的环境线索列表（玩家可感知的"直觉"类信息）
7. npc_appearances：当前场景 NPC 的外貌描述（只写外观，不写隐藏信息）

重要：
- 仅输出 JSON，不要任何解释性文字
- 只写**无条件可见**的感知信息
- 需要检定才能发现的内容留给 L2 层
- 原文未描述的内容可以基于上下文合理推测

模组文档：
\"\"\"
{content}
\"\"\""""


def parse_l1(content: str, llm_call) -> dict:
    """
    从模组文档解析 L1 玩家可见层。
    llm_call: 接受 (prompt, system) 返回 dict 的函数（如 call_deepseek_json）
    """
    prompt = build_l1_prompt(content)
    raw = llm_call(prompt, system=L1_SYSTEM)
    return raw


# ═══════════════════════════════════════════════════════════════
#  L2 解析
# ═══════════════════════════════════════════════════════════════

L2_SYSTEM = """你是一个 TRPG 模组解析助手，专门提取「KP 守秘人层」信息。
你的任务是：从模组文档中提取完整的游戏机制信息——场景功能描述、可执行互动、敌人遭遇、隐藏信息、NPC 档案。

重要原则：
- 这是 KP 参考层，包含所有游戏机制真相
- interactions 必须包含 side_effects 数组（如 flag_set/item_gain/spawn_enemy 等）
- encounters 引用 library 中的敌人名（如 Clicker、深潜者 等）
- scene_weapons 只列出**武器**（常规物品如手电筒由 LLM 叙事处理，不需要结构化数据）
- hidden_info 是**被动触发**的信息（暗骰式），与 interaction（玩家主动选择）区分开
- NPC profiles 包含完整 KP 信息（动机、知识、性格）"""


def build_l2_prompt(content: str) -> str:
    """构建 L2 解析 prompt."""
    template = _load_template("l2_template.json")
    return f"""根据以下模组文档，提取完整的「KP 守秘人层」信息（L2 层）。

输出格式参考：
{template}

要求：
1. scenes：每个场景包含：
   - description：场景功能性描述（KP 用，区别于 L1 的叙事性 entry_narrative）
   - from_here / to_here：移动边（目标场景 + 通行方式）
   - interactions：可执行动作列表，每个包含：
     * type：互动类型（调查/鉴定/搜索/对话/决策/使用物品/战斗等）
     * name：互动名称
     * trigger：触发条件描述
     * result：结果描述
     * clue：线索（可选）
     * side_effects：副作用数组，每个元素有 type 字段
       - flag_set：{{"type":"flag_set","key":"标记名","value":true}}
       - item_gain：{{"type":"item_gain","item_name":"物品名"}}
       - spawn_enemy：{{"type":"spawn_enemy","enemy_ref":"敌人名","scene":"场景名"}}
       - grant_item：{{"type":"grant_item","item_ref":"武器名"}}
       - npc_state_change：{{"type":"npc_state_change","npc_name":"NPC名","new_state":"状态"}}
       - stat_change：{{"type":"stat_change","stat_name":"SAN","delta":-1}}
     * requirement：前置条件数组
     * skill_name：关联技能名（可选）
     * difficulty：检定难度（regular/hard/extreme）
   - encounters：预设敌人遭遇（引用 library 敌人名）
   - scene_weapons：场景中可获取的武器（只列武器！）
   - hidden_info：被动触发信息（暗骰式），每个包含 info / trigger_condition / reveal_narrative

2. events：全局不可逆事件列表，每个包含 id（E1,E2...）/ name / trigger / irreversible_impact / requirement

3. npc_profiles：NPC 完整档案，每个包含 name / role / motivation / knowledge / personality / voice_notes

重要：
- 仅输出 JSON，不要任何解释性文字
- 根据原文合理推测补充游戏机制细节
- 隐藏信息与主动互动的区别：hidden_info 是系统被动检测条件后自动揭示的

模组文档：
\"\"\"
{content}
\"\"\""""


def parse_l2(content: str, llm_call) -> dict:
    """
    从模组文档解析 L2 KP 守秘人层。
    llm_call: 接受 (prompt, system) 返回 dict 的函数
    """
    prompt = build_l2_prompt(content)
    raw = llm_call(prompt, system=L2_SYSTEM)
    return raw


# ═══════════════════════════════════════════════════════════════
#  L3 解析
# ═══════════════════════════════════════════════════════════════

L3_SYSTEM = """你是一个 TRPG 模组设计分析师，专门提取「设计者层」信息。
你的任务是：从模组文档中提取模组的设计意图、世界规则、剧情逻辑链、场景设计目的和基调约束。

重要原则：
- 这是设计者层，描述**为什么**这个模组这样设计，而非**有什么**内容
- world_rules 是世界运行的物理/超自然法则（玩家和 KP 都必须遵守）
- logic_chains 是剧情骨架，不是线性流程——包含分支节点和条件
- scene_intents 描述每个场景的**设计目的**（为什么存在这个场景），而非场景内容
- driving_force 是一切事件的根本驱动力（为什么这一切在发生）
- tone_constraints 是跨场景的叙事护栏"""


def build_l3_prompt(content: str) -> str:
    """构建 L3 解析 prompt."""
    template = _load_template("l3_template.json")
    return f"""根据以下模组文档，提取「设计者层」信息（L3 层）。

输出格式参考：
{template}

要求：
1. module_meta：模组元信息（标题、作者、年代、主题、预计时长、玩家人数）

2. world_rules：世界运行规则列表，每个包含：
   - id：规则编号（WR1, WR2...）
   - name：规则名称
   - rule：规则描述（自然语言，LLM 和 KP 都能理解）
   - scope：影响范围（movement/combat/stealth/investigation/dialogue 等）
   - is_absolute：是否为绝对规则（true=不可违反，false=极端情况可打破）

3. logic_chains：剧情逻辑链列表，每个包含：
   - id：逻辑链编号（LC1, LC2...）
   - name：名称
   - description：一句话描述
   - nodes：逻辑节点（按顺序的里程碑）
   - branches：分支条件列表，每个包含 condition / effect / next_node
   - is_critical：是否为主线

4. scene_intents：每个场景的设计意图，key 为场景名，value 包含：
   - purpose：此场景在模组中的作用（如"苏醒点，建立初始紧张感"）
   - emotion：目标情绪
   - danger_level：危险等级（safe/low/medium/high/extreme）
   - key_info：此场景必须传达的关键信息
   - key_threat：核心威胁（可选）
   - exit_leads_to：离开后可能前往的场景

5. ending_conditions：结局条件列表，每个包含 id / type（escape/trapped/madness/sacrifice/revelation）/ condition / narrative_theme

6. tone_constraints：全局叙事护栏：
   - genre：类型标签
   - forbidden：禁止出现的元素/主题
   - required：必须包含的元素/主题
   - narrative_style：叙事风格指引

7. driving_force：一切事件的底层驱动力——"为什么这一切在发生？"

重要：
- 仅输出 JSON，不要任何解释性文字
- 从原文中推断设计意图，即使原文没有明确声明
- logic_chains 的 nodes 按推进顺序排列
- driving_force 应该是概念层面的，不是具体事件描述

模组文档：
\"\"\"
{content}
\"\"\""""


def parse_l3(content: str, llm_call) -> dict:
    """
    从模组文档解析 L3 设计者层。
    llm_call: 接受 (prompt, system) 返回 dict 的函数
    """
    prompt = build_l3_prompt(content)
    raw = llm_call(prompt, system=L3_SYSTEM)
    return raw


# ═══════════════════════════════════════════════════════════════
#  顶层：一键解析
# ═══════════════════════════════════════════════════════════════

def parse_module(
    content: str,
    llm_call,
    *,
    layers: Tuple[str, ...] = ("L1", "L2", "L3"),
    verbose: bool = True,
) -> dict:
    """
    一键解析模组文档 → 三层 JSON。

    参数：
        content: 模组文档原文
        llm_call: LLM 调用函数 (prompt, system) → dict
        layers: 要解析的层，默认全部
        verbose: 是否打印进度

    返回：
        {"L1": dict, "L2": dict, "L3": dict}
    """
    results = {}

    if "L1" in layers:
        if verbose:
            print("═" * 50)
            print("[L1] 解析玩家可见层...")
        results["L1"] = parse_l1(content, llm_call)
        if verbose:
            print(f"  L1 完成：{len(results['L1'])} 个场景")

    if "L2" in layers:
        if verbose:
            print("═" * 50)
            print("[L2] 解析 KP 守秘人层...")
        results["L2"] = parse_l2(content, llm_call)
        if verbose:
            scenes = results["L2"].get("scenes", {})
            events = results["L2"].get("events", [])
            print(f"  L2 完成：{len(scenes)} 个场景, {len(events)} 个事件")

    if "L3" in layers:
        if verbose:
            print("═" * 50)
            print("[L3] 解析设计者层...")
        results["L3"] = parse_l3(content, llm_call)
        if verbose:
            rules = results["L3"].get("world_rules", [])
            chains = results["L3"].get("logic_chains", [])
            print(f"  L3 完成：{len(rules)} 条世界规则, {len(chains)} 条逻辑链")

    return results


def save_module(results: dict, module_dir: str) -> None:
    """
    将解析结果保存到模块目录。

    参数：
        results: parse_module() 的返回值 {"L1": ..., "L2": ..., "L3": ...}
        module_dir: 目标目录（如 data/modules/常暗之厢/）
    """
    os.makedirs(module_dir, exist_ok=True)

    if "L1" in results:
        path = os.path.join(module_dir, "l1_player.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(results["L1"], f, ensure_ascii=False, indent=2)
        print(f"  L1 → {path}")

    if "L2" in results:
        path = os.path.join(module_dir, "l2_keeper.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(results["L2"], f, ensure_ascii=False, indent=2)
        print(f"  L2 → {path}")

    if "L3" in results:
        path = os.path.join(module_dir, "l3_designer.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(results["L3"], f, ensure_ascii=False, indent=2)
        print(f"  L3 → {path}")
