"""Supplement pipeline — lightweight module generation triggered by Author StructuralEdit.

Input: player intent + base L3 + entry/exit scenes
Output: l1_supp.json + l2_supp.json + l3_supp.json in supplements/<timestamp>/

Step 1: 3 parallel LLM calls (flash + max reasoning)
  1a: scenes + interactions + auto_triggers
  1b: events + scene_movements
  1c: L1 player-facing layer

Step 2: assemble + cross-validate + @markup standardize (1 call)
"""
from __future__ import annotations
import json
import os
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from llm import call_deepseek


def run_supplement_pipeline(
    player_intent: str,
    reasoning: str,
    base_l3: dict,
    entry_scene: str,
    exit_scene: str = "",
    output_dir: str = "",
    module_name: str = "",
) -> dict:
    """Run lightweight supplement pipeline. Returns {"l1": ..., "l2": ..., "l3": ..., "output_dir": ...}."""

    if not output_dir:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join("data", "modules", module_name, "supplements", ts)
    os.makedirs(output_dir, exist_ok=True)

    l3_summary = _summarize_l3(base_l3)
    shared_context = {
        "player_intent": player_intent,
        "reasoning": reasoning,
        "entry_scene": entry_scene,
        "exit_scene": exit_scene,
        "l3_summary": l3_summary,
    }

    # Step 1: 3 parallel LLM calls
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_step_1a, shared_context): "1a_scenes",
            executor.submit(_step_1b, shared_context): "1b_events",
            executor.submit(_step_1c, shared_context): "1c_l1",
        }
        results = {}
        for future in as_completed(futures):
            name = futures[future]
            results[name] = future.result()

    scenes_data = results.get("1a_scenes", {})
    events_data = results.get("1b_events", {})
    l1_data = results.get("1c_l1", {})

    # Step 2: assemble ∥ @markup standardize (parallel)
    with ThreadPoolExecutor(max_workers=2) as executor:
        f_assemble = executor.submit(_step_2_assemble, scenes_data, events_data, shared_context)
        f_standardize = executor.submit(_step_standardize_entities, scenes_data, events_data)
        l2_data = f_assemble.result()
        standardized = f_standardize.result()
    if standardized:
        _apply_standardized(l2_data, standardized)

    l3_data = _build_l3_supp(base_l3, shared_context)

    # Save
    for name, data in [("l1_supp.json", l1_data), ("l2_supp.json", l2_data),
                        ("l3_supp.json", l3_data)]:
        path = os.path.join(output_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return {"l1": l1_data, "l2": l2_data, "l3": l3_data, "output_dir": output_dir}


def _summarize_l3(l3: dict) -> str:
    """Extract key L3 constraints for supplement generation."""
    tc = l3.get("tone_constraints", {})
    parts = []
    if isinstance(tc, dict):
        parts.append(f"类型：{tc.get('genre', '')}")
        parts.append(f"叙事风格：{tc.get('narrative_style', '')}")
        forbidden = tc.get('forbidden', [])
        if forbidden:
            parts.append(f"禁止：{', '.join(forbidden)}")
        required = tc.get('required', [])
        if required:
            parts.append(f"必须包含：{', '.join(required)}")
    parts.append(f"核心驱动力：{l3.get('driving_force', '')}")
    return "\n".join(parts)


def _step_1a(context: dict) -> dict:
    """Generate new scenes with interactions + auto_triggers."""
    prompt = f"""你是TRPG模组创作者。基于以下信息生成补充场景。

【L3约束】
{context['l3_summary']}

【玩家意图】
意图：{context['player_intent']}
原因：{context['reasoning']}

【出入口】
入口场景：{context['entry_scene']}
出口场景：{context.get('exit_scene') or '由你决定'}

请生成1-3个新场景，每个场景含interactions和auto_triggers。
Entity ID使用S_前缀：SS1=场景1, SI1=interaction1, SAT1=AT1。
requirement字段使用entity ID字符串（如"SI1 AND SI2"），可描述是否需要消耗常见物品及数量。
result可描述结果是否会失去常见消耗品（具体数值由后续标准化处理）。
所有描述性内容（description、trigger、result、name等）必须使用中文。
JSON字段名和ID保持英文。

返回 JSON：
{{
  "scenes": {{
    "SS1_场景名": {{
      "description": "场景描述",
      "interactions": [
        {{"id": "SI1", "entity_type": "interaction", "scene": "SS1_场景名",
          "name": "动作名", "type": "技能名或空", "requirement": "", "trigger": "触发条件",
          "result": "结果描述", "side_effects": [], "graded_result": null, "difficulty": "regular"}}
      ],
      "auto_triggers": [],
      "from_here": [{{"target": "出口场景", "method": "通行方式", "requirement": ""}}],
      "to_here": [{{"source": "{context['entry_scene']}", "method": "通行方式", "requirement": ""}}],
      "extra": {{}}
    }}
  }}
}}

直接输出 JSON。"""
    response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
                             reasoning_effort="max",
                             system="你是TRPG模组创作者。生成结构化的新场景内容。requirement可描述常见物品消耗及数量，result可描述常见物品失去。所有描述必须用中文。",
                             fallback_schema={"scenes": {}})
    return json.loads(response) if isinstance(response, str) else response


def _step_1b(context: dict) -> dict:
    """Generate events + scene movements."""
    prompt = f"""你是TRPG模组创作者。基于以下信息生成补充事件和场景连接。

【L3约束】
{context['l3_summary']}

【玩家意图】
意图：{context['player_intent']}
原因：{context['reasoning']}

【出入口】
入口：{context['entry_scene']}
出口：{context.get('exit_scene') or '由你决定'}

生成全局事件（可选）和新场景之间的通行连接。
Event ID使用SE_前缀。requirement可描述是否需要消耗常见物品及数量；result可描述结果是否会失去常见消耗品。
所有描述性内容（name、trigger、result等）必须使用中文。
JSON字段名和ID保持英文。

返回 JSON：
{{
  "events": [
    {{"id": "SE1", "entity_type": "event", "name": "事件名", "type": "",
      "requirement": "", "trigger": "触发条件", "result": "事件结果",
      "side_effects": [], "graded_result": null, "difficulty": "None"}}
  ]
}}

直接输出 JSON。"""
    response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
                             reasoning_effort="max",
                             system="你是TRPG模组创作者。生成事件和场景通行结构。requirement可描述常见物品消耗，result可描述物品失去。所有描述必须用中文。",
                             fallback_schema={"events": []})
    return json.loads(response) if isinstance(response, str) else response


def _step_1c(context: dict) -> dict:
    """Generate L1 player-facing layer."""
    prompt = f"""你是TRPG模组创作者。生成新场景的玩家可见层（L1）。

【L3约束】
{context['l3_summary']}

【玩家意图】
意图：{context['player_intent']}

生成L1格式的场景描述，键名为场景中文名。
每个场景包含：description（场景描述）、atmosphere（氛围）、mood（情绪基调）、
perceptible（可无条件感知的元素列表）、ambient_hints（环境暗示）。
所有描述性内容必须使用中文。JSON字段名保持英文。

返回 JSON：
{{
  "新场景名": {{
    "description": "场景描述",
    "atmosphere": "氛围",
    "mood": "情绪基调",
    "perceptible": ["可感知元素"],
    "ambient_hints": ["环境暗示"],
    "npc_appearances": {{}}
  }}
}}

直接输出 JSON。"""
    response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
                             reasoning_effort="max",
                             system="你是TRPG模组创作者。生成玩家可见的场景描述层。所有描述必须用中文。",
                             fallback_schema={})
    return json.loads(response) if isinstance(response, str) else response


def _step_2_assemble(scenes_data: dict, events_data: dict, context: dict) -> dict:
    """Assemble L2 structure from Step 1 outputs."""
    scenes = scenes_data.get("scenes", {})
    events = events_data.get("events", [])

    # Build minimal dependency_graph
    dep_nodes = {}
    dep_edges = []
    for scene_name, scene_data in scenes.items():
        for entity_list_name in ("interactions", "auto_triggers"):
            for ent in scene_data.get(entity_list_name, []):
                eid = ent.get("id", "")
                etype = ent.get("entity_type", "")
                if eid:
                    dep_nodes[eid] = {"entity_id": eid, "entity_type": etype, "name": ent.get("name", "")}
                    req = ent.get("requirement", "")
                    if req:
                        for req_id in _extract_entity_ids(req):
                            dep_edges.append({
                                "source": eid, "target": req_id,
                                "dep_type": "", "condition": "completed",
                            })

    for ev in events:
        eid = ev.get("id", "")
        if eid:
            dep_nodes[eid] = {"entity_id": eid, "entity_type": "event", "name": ev.get("name", "")}

    # Scene names map (internal ID → Chinese name)
    scene_names = {}
    for sid in scenes:
        scene_names[sid] = sid

    return {
        "scenes": scenes,
        "events": events,
        "npc_profiles": {},
        "dependency_graph": {
            "nodes": dep_nodes,
            "edges": dep_edges,
        },
        "_scene_names": scene_names,
        "_phase1": {},
    }


def _build_l3_supp(base_l3: dict, context: dict) -> dict:
    """Build supplement L3 — mostly inherits base L3 with optional adjustments."""
    return {
        "module_meta": {
            **base_l3.get("module_meta", {}),
            "supplement_of": base_l3.get("module_meta", {}).get("name", ""),
            "generated_for": context["player_intent"],
        },
        "world_rules": base_l3.get("world_rules", {}),
        "scene_intents": base_l3.get("scene_intents", {}),
        "ending_conditions": base_l3.get("ending_conditions", []),
        "tone_constraints": base_l3.get("tone_constraints", {}),
        "characters": base_l3.get("characters", {}),
        "driving_force": base_l3.get("driving_force", ""),
        "time_pressure": base_l3.get("time_pressure", {}),
    }


def _extract_entity_ids(req_str: str) -> list[str]:
    """Extract entity IDs (I1, AT2, E3, etc.) from a requirement string."""
    return re.findall(r'[ISEA]+\d+[a-z]?', req_str)


def _step_standardize_entities(scenes_data: dict, events_data: dict) -> dict | None:
    """Phase 2 equivalent: standardize type names and convert natural language to @markup.
    Runs in parallel with _step_2_assemble."""
    all_entities = []
    for scene_name, scene_data in scenes_data.get("scenes", {}).items():
        for ent in scene_data.get("interactions", []) + scene_data.get("auto_triggers", []):
            ent["_scene"] = scene_name
            all_entities.append(_slim_entity(ent))
    for ev in events_data.get("events", []):
        all_entities.append(_slim_entity(ev))

    if not all_entities:
        return None

    skills = "会计、人类学、估价、考古学、魅惑、攀爬、计算机使用、信用评级、克苏鲁神话、乔装、闪避、汽车驾驶、电气维修、电子学、话术、急救、历史、恐吓、跳跃、法律、图书馆使用、聆听、锁匠、机械维修、医学、博物学、导航、神秘学、操作重型机械、说服、驾驶、精神分析、心理学、读唇、潜行、侦查、生存、游泳、投掷、追踪、驯兽"
    stats = "STR、CON、SIZ、DEX、APP、INT、POW、EDU、LUCK、HP、MP、SAN、MOV、DB、BUILD"

    prompt = f"""标准化 entity 的 type、side_effects、result 字段。

标准技能：{skills}
标准属性：{stats}
标准时段：凌晨、早晨、白天、黄昏、夜间

Entities：
{json.dumps(all_entities, ensure_ascii=False, indent=2)}

任务：
1. type 标准化：从标准技能列表选匹配技能名，不涉及检定的填"无"
2. @标记转化：side_effects/result/graded_result 自然语言化为：
   @spawn_enemy(enemy_ref="", scene="", quantity=1)
   @grant_weapon(weapon_ref="", scene="", quantity=1)
   @stat_change(stat_name="", delta=-1, narrative="")
   @item_gain(item_name="", quantity=1)
   @consume_item(item_name="", quantity=1, narrative="")
   @npc_state_change(npc_name="", new_state="")
   @npc_follow(npc_name="", follow=true)

返回 JSON：{{"entities": [{{原entity字段..., type, side_effects, result, graded_result}}]}}"""

    try:
        response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
                                 reasoning_effort="max",
                                 system="你是TRPG模组标准化助手。将entity字段标准化并转换@标记。",
                                 fallback_schema={"entities": all_entities})
        result = json.loads(response) if isinstance(response, str) else response
        return result
    except Exception:
        return None


def _slim_entity(ent: dict) -> dict:
    """Keep only fields needed for standardization."""
    return {k: ent.get(k, "") for k in ("id", "entity_type", "name", "type",
           "result", "side_effects", "graded_result", "_scene")}


def _apply_standardized(l2_data: dict, standardized: dict):
    """Apply standardized entity fields back to assembled L2."""
    std_entities = standardized.get("entities", [])
    if not std_entities:
        return
    by_id = {e["id"]: e for e in std_entities if e.get("id")}
    for scene_data in l2_data.get("scenes", {}).values():
        for lst in ("interactions", "auto_triggers"):
            for ent in scene_data.get(lst, []):
                eid = ent.get("id", "")
                if eid in by_id:
                    std = by_id[eid]
                    for field in ("type", "result", "side_effects", "graded_result"):
                        if field in std:
                            ent[field] = std[field]
    for ev in l2_data.get("events", []):
        eid = ev.get("id", "")
        if eid in by_id:
            std = by_id[eid]
            for field in ("type", "result", "side_effects", "graded_result"):
                if field in std:
                    ev[field] = std[field]
