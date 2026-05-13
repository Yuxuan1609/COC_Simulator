"""
文档解析：从模组文本中提取场景和不可逆事件。
"""

import json
from llm import call_deepseek_json


def parse_scenes_from_document(content: str, format_ref_path: str = "../data/templates/scene.json") -> dict:
    """
    从文档内容中解析场景结构。
    """
    with open(format_ref_path, "r", encoding="utf-8") as f:
        format_ref = json.load(f)

    format_example = json.dumps(
        {
            "场景名": {
                "description": "场景的简要描述（基于原文）",
                "from_here": [
                    {"target": "目标场景", "method": "通行方式说明"}
                ],
                "to_here": [
                    {"source": "来源场景", "method": "通行方式说明"}
                ],
                "interactions": [
                    {
                        "type": "搜索/对话/鉴定/战斗/调查/使用物品",
                        "name": "互动名称",
                        "requirement": [
                            {"ref_type": "event", "ref_id": "E1", "ref_name": "事件名称"},
                            {"ref_type": "interaction", "ref_scene": "场景名", "ref_name": "互动名称"}
                        ],
                        "trigger": "触发条件（技能鉴定名/玩家行为等）",
                        "result": "成功/失败的后果描述",
                        "clue": "该互动可能揭示的线索"
                    }
                ]
            }
        },
        ensure_ascii=False,
        indent=2
    )

    prompt = f"""根据以下文档内容，解析故事中出现的所有地点/场景。

输出格式参考（保留所有现有字段，新增 interactions 字段）：
{format_example}

要求：
1. 每个场景作为一个最高级 key
2. 必须包含现有字段：description、from_here、to_here（与参考格式一致）
3. 新增 interactions 字段：描述当前场景下玩家可以进行的互动操作，包括但不限于：
   - 可搜索/调查的物品或线索（注明技能鉴定）
   - 可对话的 NPC 及可能获得的信息
   - 需要技能鉴定的行动（标注技能名和难度影响）
   - 可能触发的事件及其条件
   - 战斗相关互动（如有）
4. 每个 interaction 必须包含 requirement 字段，是一个数组，每个元素为 {{"ref_type": "event", "ref_id": "事件ID", "ref_name": "事件名称"}} 或 {{"ref_type": "interaction", "ref_scene": "场景名", "ref_name": "互动名称"}} 的结构化引用，描述该互动的硬性前置条件（必须先完成哪些互动或先触发哪些事件）。若无前置条件则为空数组 []
5. 由于事件 ID 此时尚未确定，若前置条件涉及事件，请先用事件名称填写 ref_name，ref_id 留空字符串 ""，后续步骤会补充
6. 原文未说明的内容可基于上下文合理推测，并在 method/result 中标注"推测"
7. 仅输出 JSON，不要包含任何解释性文字

文档内容：
\"\"\"
{content}
\"\"\""""

    return call_deepseek_json(prompt)


def parse_events_from_document(content: str, event_ref_path: str = "../data/templates/event.json") -> dict:
    """
    从文档内容中解析不可逆事件（单向事件）。
    """
    with open(event_ref_path, "r", encoding="utf-8") as f:
        format_ref = json.load(f)

    format_example = json.dumps(format_ref, ensure_ascii=False, indent=2)

    prompt = f"""根据以下文档内容，判断故事中是否出现了"单向事件"（即某个事件一旦发生则故事世界发生不可逆变化）。
按时间顺序排列这些不可逆事件，逐一指出其触发条件和发生的影响。

输出格式参考：
{format_example}

要求：
1. 返回一个 JSON 数组，每个元素包含 id、name、requirement、trigger、irreversible_impact 字段
2. id 按时间顺序编号（E1, E2, E3...）
3. requirement 是一个数组，每个元素为 {{"ref_type": "event", "ref_id": "", "ref_name": "事件名称"}} 或 {{"ref_type": "interaction", "ref_scene": "", "ref_name": "互动名称"}} 的结构化引用，描述该事件触发所需的硬性前置条件。若无前置条件则为空数组 []
4. 由于事件 ID 和场景互动名称此时可能尚未完全确定，ref_id 和 ref_scene 可先留空字符串 ""，用 ref_name 描述，后续步骤会补充精确匹配
5. 严格按故事时间线排列
6. 仅输出 JSON，不要包含任何解释性文字

文档内容：
\"\"\"
{content}
\"\"\"

"""

    return call_deepseek_json(prompt)
