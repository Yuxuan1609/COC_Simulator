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

    # Step 2: assemble + validate
    l2_data = _step_2_assemble(scenes_data, events_data, shared_context)
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
requirement字段使用entity ID字符串（如"SI1 AND SI2"）。

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
                             system="你是TRPG模组创作者。生成结构化的新场景内容。",
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
Event ID使用SE_前缀。

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
                             system="你是TRPG模组创作者。生成事件和场景通行结构。",
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
                             system="你是TRPG模组创作者。生成玩家可见的场景描述层。",
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
    }


def _extract_entity_ids(req_str: str) -> list[str]:
    """Extract entity IDs (I1, AT2, E3, etc.) from a requirement string."""
    return re.findall(r'[ISEA]+\d+[a-z]?', req_str)
