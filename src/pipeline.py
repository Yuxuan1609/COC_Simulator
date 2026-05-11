"""
后处理管线：需求解析 → 交叉验证修订 → 文学性扩充。
"""

import json
from llm import call_deepseek_json, call_deepseek_write


def resolve_requirements(
    events_path: str = "res_event.json",
    scenes_path: str = "scene_output.json",
    content: str = "",
) -> dict:
    """
    根据已解析的事件列表和场景数据，为所有 interaction 和 event 的
    requirement 字段进行结构化交叉匹配。
    """
    with open(events_path, "r", encoding="utf-8") as f:
        events = json.load(f)
    with open(scenes_path, "r", encoding="utf-8") as f:
        scenes = json.load(f)

    event_name_to_id = {}
    for ev in events:
        eid = ev.get("id", "")
        ename = ev.get("name", "")
        if eid and ename:
            event_name_to_id[ename] = eid

    interaction_index = {}
    for scene_name, scene_data in scenes.items():
        names = []
        for inter in scene_data.get("interactions", []):
            iname = inter.get("name", "")
            if iname:
                names.append(iname)
        interaction_index[scene_name] = names

    scenes_str = json.dumps(scenes, ensure_ascii=False, indent=2)
    events_str = json.dumps(events, ensure_ascii=False, indent=2)
    event_index_str = json.dumps(event_name_to_id, ensure_ascii=False, indent=2)
    interaction_index_str = json.dumps(interaction_index, ensure_ascii=False, indent=2)

    prompt = f"""你是一个精确的数据匹配助手。你的任务是为所有场景互动（interaction）和不可逆事件（event）的 requirement 数组进行结构化校对和填充。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【背景】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
requirement 数组中每个元素是一个结构化引用，格式为：
- 事件引用：{{"ref_type": "event", "ref_id": "事件ID", "ref_name": "事件名称"}}
- 互动引用：{{"ref_type": "interaction", "ref_scene": "场景名", "ref_name": "互动名称"}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【可引用的事件列表（名称 → ID 映射）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{event_index_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【可引用的互动列表（场景 → 互动名称）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{interaction_index_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【当前场景数据（待校对）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{scenes_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【当前事件数据（待校对）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{events_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【原文内容（参考）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
\"\"\"
{content[:6000]}
\"\"\"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【任务要求】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

对每个 event 的 requirement 和每个 scene interaction 的 requirement，检查并修正：

1. **事件引用补全**：如果 requirement 中某个 ref_type="event" 的元素 ref_id 为空字符串 ""，请根据 ref_name 在上方事件映射表中查找匹配的事件名称，将 ref_id 填充为正确的 ID（如 E1, E2 等）。如果名称无法精确匹配任何事件，保持 ref_id 为空。

2. **事件引用修正**：如果 requirement 中引用了某事件但 ref_name 与事件映射表中的实际名称有偏差，请修正 ref_name 为映射表中的精确名称。

3. **互动引用精确化**：如果 requirement 中 ref_type="interaction" 的元素，请根据上方互动索引表将 ref_scene 和 ref_name 与真实数据精确匹配。若有偏差请修正。

4. **移除无效引用**：如果某个引用无法匹配到任何已知事件或互动，且原文中也找不到依据，请从 requirement 数组中移除该项。

5. **补充遗漏**：如果某个 event 或 interaction 根据原文逻辑明显需要先完成其他事件/互动，但 requirement 为空数组，请根据原文逻辑补充（必须能在上方索引表中找到对应的条目）。

6. **保持排序**：requirement 数组中的引用应按逻辑先后顺序排列（先完成的事件/互动排在前面）。

7. **严格保持 JSON 结构不变**：除了 requirement 数组内部元素的修改外，不得新增或删除任何 event 或 interaction、不得修改任何其他字段。

请输出修订后的完整数据，格式如下（确保是合法 JSON）：
{{
    "events": [/* 修订后的事件数组 */],
    "scenes": {{/* 修订后的场景对象 */}}
}}"""

    print("=" * 50)
    print("[需求解析] 正在进行 requirement 结构化校对与精确匹配...")
    resolved = call_deepseek_json(prompt)

    if len(events) != len(resolved.get("events", [])):
        raise ValueError(
            f"事件数量不匹配: 原始 {len(events)}, 修订后 {len(resolved.get('events', []))}"
        )

    resolved_scenes = resolved.get("scenes", {})
    if set(scenes.keys()) != set(resolved_scenes.keys()):
        missing = set(scenes.keys()) - set(resolved_scenes.keys())
        extra = set(resolved_scenes.keys()) - set(scenes.keys())
        raise ValueError(f"场景集合不匹配: 缺失={missing}, 多余={extra}")

    for name in scenes:
        orig_count = len(scenes[name].get("interactions", []))
        new_count = len(resolved_scenes[name].get("interactions", []))
        if orig_count != new_count:
            raise ValueError(
                f"场景 '{name}' interactions 数量不匹配: "
                f"原始 {orig_count}, 修订后 {new_count}"
            )

    with open(events_path.replace(".json", "_resolved.json"), "w", encoding="utf-8") as f:
        json.dump(resolved["events"], f, ensure_ascii=False, indent=2)
    print(f"已保存精确匹配后事件: {events_path.replace('.json', '_resolved.json')}")

    with open(scenes_path.replace(".json", "_resolved.json"), "w", encoding="utf-8") as f:
        json.dump(resolved["scenes"], f, ensure_ascii=False, indent=2)
    print(f"已保存精确匹配后场景: {scenes_path.replace('.json', '_resolved.json')}")

    print("[需求解析] 完成 —— 所有 event 和 interaction 的 requirement 已精确匹配")
    print(f"  事件: {len(resolved['events'])} 个")
    print(f"  场景: {len(resolved['scenes'])} 个")

    return resolved


def cross_validate_and_revise(
    events_path: str = "res_event.json",
    scenes_path: str = "scene_output.json",
    content: str = "",
    auto_revise: bool = True,
) -> dict:
    """
    交叉验证事件 JSON 与场景 JSON，以合理性优先的原则进行审查和修订。
    """
    with open(events_path, "r", encoding="utf-8") as f:
        events = json.load(f)
    with open(scenes_path, "r", encoding="utf-8") as f:
        scenes = json.load(f)

    events_str = json.dumps(events, ensure_ascii=False, indent=2)
    scenes_str = json.dumps(scenes, ensure_ascii=False, indent=2)

    # ── 阶段一：交叉验证 ──
    validate_prompt = f"""你是一位资深 TRPG 模组设计师，正在审查一份场景数据和一份不可逆事件数据（均提取自同一份模组文档）。
请以"让跑团体验更流畅、更有沉浸感"为目标进行交叉验证。

**审查方向（优先关注合理性而非严格一致性）**：
1. **逻辑冲突**：两边的描述是否存在让 KP 难以裁决的矛盾（微小措辞差异可忽略）
2. **体验断层**：事件链是否流畅？玩家从一个场景进入下一个时，信息/情绪是否衔接得上
3. **空白补充建议**：原文未提及但合乎逻辑的内容，是否值得补充到场景或事件中
4. **创意空间**：哪些地方可以给 KP 留出自由发挥的余地，目前是否绑得太死

**重要原则**：
- 原文没有提到的内容，只要合理即可视为有效补充，不算"遗漏"
- 优先关注玩法和叙事的连贯性，而非逐字逐句的一致性
- 如果你认为某处补充会让模组更好，请在 issues 中作为 "建议补充" 类型提出

请输出一份 JSON 格式的验证报告：
{{
    "has_issues": true/false,
    "issues": [
        {{
            "severity": "high/medium/low",
            "type": "逻辑冲突/体验断层/建议补充/创意空间",
            "event_id": "关联的事件ID（可选）",
            "scene_name": "关联的场景名（可选）",
            "detail": "具体描述",
            "suggestion": "你的改进建议（具体可操作，可直接写入数据中）"
        }}
    ],
    "summary": "总体评价（1-2句话）"
}}

场景数据：
{scenes_str}

不可逆事件数据：
{events_str}"""

    print("=" * 50)
    print("[阶段一] 正在交叉验证...")
    validation = call_deepseek_json(validate_prompt)
    print(f"验证完成，发现问题: {validation.get('has_issues', 'unknown')}")
    if validation.get("issues"):
        for iss in validation["issues"]:
            print(f"  [{iss.get('severity', '?')}] {iss.get('type', '?')}: {iss.get('detail', '')[:120]}...")

    # ── 阶段二：修订（如需要） ──
    revised = None
    if auto_revise and validation.get("has_issues") and content:
        print("\n[阶段二] 发现问题，正在基于原文修订...")

        issues_str = json.dumps(validation.get("issues", []), ensure_ascii=False, indent=2)

        revise_prompt = f"""你是一位富有创意的 TRPG 模组设计师。以下是一份模组的场景数据、不可逆事件数据以及验证发现的问题。请对数据进行修订和润色。

**核心原则**：
1. 优先保证游戏体验的流畅、合理、沉浸感
2. 原文是你最重要的参考，但不是绝对约束——原文没提到的内容，你可以基于逻辑和 TRPG 常识进行合理的自主补全
3. 如果某处原文模糊，请选择最能让故事推进顺畅的解释
4. 可以适度扩充描述、补充 NPC 细节、添加合理的互动选项，让 KP 更容易直接使用
5. 保持 JSON 结构与修订前一致（字段名、层级不变）
6. 新增或显著修改的内容，请在字段值末尾追加 "(已修订)" 标记；小幅润色无需标记

**验证发现的问题及建议**：
{issues_str}

**原文内容（参考，非绝对约束）**：
\"\"\"
{content}
\"\"\"

**当前场景数据**：
{scenes_str}

**当前事件数据**：
{events_str}

请输出修订后的完整数据，格式如下（确保是合法 JSON）：
{{
    "events": [/* 修订后的事件数组，结构同原 res_event.json */],
    "scenes": {{/* 修订后的场景对象，结构同原 scene_output.json */}}
}}"""

        revised = call_deepseek_json(revise_prompt)

        if revised.get("events"):
            with open(events_path.replace(".json", "_revised.json"), "w", encoding="utf-8") as f:
                json.dump(revised["events"], f, ensure_ascii=False, indent=2)
            print(f"已保存修订后事件: {events_path.replace('.json', '_revised.json')}")
        if revised.get("scenes"):
            with open(scenes_path.replace(".json", "_revised.json"), "w", encoding="utf-8") as f:
                json.dump(revised["scenes"], f, ensure_ascii=False, indent=2)
            print(f"已保存修订后场景: {scenes_path.replace('.json', '_revised.json')}")
    else:
        if not validation.get("has_issues"):
            print("[阶段二] 无问题，跳过修订")
        elif not content:
            print("[阶段二] 未提供原文内容，跳过修订")

    return {"validation": validation, "revised": revised}


def expand_scene_descriptions(
    scenes_path: str = "scene_output_revised.json",
    events_path: str = "res_event_revised.json",
    content: str = "",
    output_path: str = "scene_output_expanded.json",
) -> dict:
    """
    对场景数据进行文学性扩充，将功能性描述扩展为沉浸式恐怖叙事段落。
    """
    with open(scenes_path, "r", encoding="utf-8") as f:
        scenes = json.load(f)
    with open(events_path, "r", encoding="utf-8") as f:
        events = json.load(f)

    original_scene_names = set(scenes.keys())
    original_structure = {}
    for name, data in scenes.items():
        original_structure[name] = {
            "from_here_count": len(data.get("from_here", [])),
            "to_here_count": len(data.get("to_here", [])),
            "interactions_count": len(data.get("interactions", [])),
        }

    scenes_str = json.dumps(scenes, ensure_ascii=False, indent=2)
    events_str = json.dumps(events, ensure_ascii=False, indent=2)

    expand_prompt = f"""你是一位经验丰富的恐怖小说作家和克苏鲁神话TRPG模组设计师。你的任务是将一份名为《常暗之厢》的模组场景数据进行"文学性扩充"——把原本功能性、规则导向的描述，改写为沉浸式恐怖小说的叙事片段，供KP在跑团时直接朗读。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【扩充目标】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

对每个场景的 `description` 字段进行大幅度扩充（从现在的1-3句扩展为8-15句的沉浸式段落），同时对 `interactions` 数组中每个互动项的 `trigger` 和 `result` 字段进行文学性润色和细节补充。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【扩充维度（按优先级）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. **感官描写（五感铺陈）**
   - 视觉：光影的明暗层次、车窗外无边的黑暗、车厢内灯具的闪烁频率与色温、物体轮廓在昏暗中的扭曲
   - 听觉：电车行驶的金属摩擦声、从后方传来的低沉咀嚼或撞击声、门扉开合的尖锐吱呀、自己的心跳与呼吸
   - 嗅觉：血腥的铁锈味、霉变的布料味、机油或金属的气味、空气中若有若无的腐臭
   - 触觉：车厢地板传来的颤动、门把手的冰凉、空气中异常的冷或闷热、汗湿的衣领
   - 直觉/第六感：被注视的不安、脊背发凉的预感、时间流逝的扭曲感

2. **心理刻画**
   - 描述调查员在此场景中可能经历的心理过程——从困惑、警觉、恐惧到绝望的渐变
   - 融入克苏鲁神话特有的"SAN值侵蚀"氛围——理性在超自然面前逐渐瓦解
   - 描述孤立感：手机无信号、窗外不可辨认的黑暗隧道壁、同伴的沉默或不安

3. **空间与时间渲染**
   - 丰富车厢的物理特征：低矮的天花板、狭窄的过道、座位上磨损的布料纹理
   - 渲染窗外"隧道"的异常感——它在延展、在扭曲、在逼近
   - 营造时间紧迫感——后方车厢正被吞噬、每一秒都不可浪费

4. **叙事视角**
   - 以"当调查员进入/身处该车厢时"为默认视角，像KP朗读场景开场白一样
   - 维持第二或第三人称全知视角，增强临场感和代入感
   - 可以加入适度的环境"预兆"——暗示该场景即将发生的事件或危险

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【参考素材】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**原文模组文档（理解世界观、原始氛围和设定细节）：**
\"\"\"
{content}
\"\"\"

**不可逆事件列表（了解故事的关键恐怖节点和叙事主线）：**
{events_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【当前场景数据（待扩充）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{scenes_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【严格约束 —— 绝对不可违反】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

❌ 结构不可变：
  - JSON 的 key 名称、嵌套层级、数组长度、数组元素数量必须与输入完全一致
  - 不可新增或删除任何场景（顶层 key）
  - 不可新增或删除任何 from_here / to_here 条目
  - 不可新增或删除任何 interactions 数组中的元素

❌ 游戏逻辑不可变：
  - from_here[].target / to_here[].source 的场景名称必须原样保留
  - interactions[].type 的互动分类必须原样保留
  - interactions[].name 的互动名称必须原样保留
  - interactions[].requirement 是结构化引用数组，每个元素的 ref_type, ref_id, ref_name, ref_scene 必须原样保留，不可修改
  - interactions[].clue 的线索实质内容必须保留（可以微调措辞但不能改变信息点）
  - interactions[].trigger 的基本游戏机制含义不可改变（技能名、检定条件、触发行为必须保留）
  - interactions[].result 的基本后果不可改变（SAN损失值、成/败逻辑、关键道具获取必须保留）
  - from_here[].method / to_here[].method 的通行方向和条件不可改变

✅ 可以且应当修改：
  - `description` 字段：从原来的1-3句大幅扩展为8-15句的沉浸式叙事段落
  - `trigger` 字段：在保留原意的基础上加入环境细节、感官描写、心理铺垫
  - `result` 字段：在保留原意的基础上加入更生动的情景描述、心理反应、氛围渲染
  - `method` 字段（轻量）：可以在不改变通行逻辑的前提下使描述更流畅自然
  - `clue` 字段（轻量）：可以调整措辞使其更连贯，但不可改变或增减线索信息

✅ 创作自由度：
  - 可以基于原文和事件背景合理推演补充细节（NPC的衣着外貌、物体的质感、声音的具体特征等）
  - 可以加入克苏鲁神话式的氛围描写（不可名状、超越常识、理智侵蚀）
  - 各场景之间的氛围和情绪应当有差异化和推进感（从不安到恐惧到绝望的渐变弧线）
  - 赋予每个场景独特的"情绪基调"：6号车厢=诡异与逐渐苏醒的困惑、7号车厢=禁忌知识与本能战栗、5号车厢=时间错乱的悬疑、4号车厢=绝望中一丝希望的微光、3号车厢=与时间赛跑的紧迫、2号车厢=窒息性的潜伏恐惧、先头车厢=终极抉择前的凝重

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【输出格式】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

直接输出完整 JSON，不包含任何解释性文字、markdown 标记或代码块包裹。
输出的 JSON 结构必须与输入完全一致（一个以场景名为 key 的字典），仅描述文本被扩充。"""

    print("=" * 50)
    print("[文学性扩充] 正在调用 DeepSeek 进行场景描述扩充...")
    try:
        expanded = call_deepseek_write(expand_prompt)
    except json.JSONDecodeError as e:
        print(f"[扩充失败] JSON 解析错误: {e}")
        print("建议：尝试减少场景数量或检查 API 返回是否被截断。")
        raise

    expanded_names = set(expanded.keys())
    if original_scene_names != expanded_names:
        missing = original_scene_names - expanded_names
        extra = expanded_names - original_scene_names
        msg_parts = []
        if missing:
            msg_parts.append(f"缺失场景: {missing}")
        if extra:
            msg_parts.append(f"多余场景: {extra}")
        raise ValueError("扩充后场景集合不匹配: " + "; ".join(msg_parts))

    for name in original_scene_names:
        orig = original_structure[name]
        exp = expanded[name]
        for field, count_key in [
            ("from_here", "from_here_count"),
            ("to_here", "to_here_count"),
            ("interactions", "interactions_count"),
        ]:
            expected = orig[count_key]
            actual = len(exp.get(field, []))
            if expected != actual:
                raise ValueError(
                    f"场景 '{name}' 的 '{field}' 数量不匹配: "
                    f"原始 {expected} 项, 扩充后 {actual} 项"
                )

    print("[结构验证] 通过 —— 所有场景、路径、互动的数量和名称与原始一致")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(expanded, f, ensure_ascii=False, indent=2)

    print(f"已保存扩充后场景至: {output_path}")
    print(f"场景数: {len(expanded)}")
    for name in expanded:
        old_len = len(scenes[name].get("description", ""))
        new_len = len(expanded[name].get("description", ""))
        if new_len != old_len:
            growth = f"+{new_len - old_len}"
        else:
            growth = "unchanged"
        print(f"  {name}: description {old_len} -> {new_len} chars ({growth})")

    return expanded
