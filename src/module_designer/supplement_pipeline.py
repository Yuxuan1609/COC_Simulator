"""Supplement pipeline — lightweight module generation triggered by Author StructuralEdit.

Input: player intent + base L3 + entry/exit scenes + world_snapshot
Output: l1_supp.json + l2_supp.json + l3_supp.json in supplements/<timestamp>/

Step 1: 1 LLM call (flash + max) — story-driven scene planning
Step 2: 3 parallel LLM calls (flash + max)
  2a: entities (interactions + AT + events + scene_movements) + inline @markup + dependency_graph
  2b: L1 player-facing layer
  2c: L3 designer layer (scene_intents for new scenes)
Post: assemble L2 + validate + write files
"""
from __future__ import annotations
import json, os, re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from llm import call_deepseek


def run_supplement_pipeline(
    player_intent: str,
    reasoning: str,
    base_l3: dict,
    entry_scene: str,
    exit_scene: str = "",
    world_snapshot: dict | None = None,
    output_dir: str = "",
    module_name: str = "",
) -> dict:
    """Run lightweight supplement pipeline. Returns {"l1": ..., "l2": ..., "l3": ..., "output_dir": ...}."""

    if world_snapshot is None:
        world_snapshot = {}

    if not output_dir:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join("data", "modules", module_name, "supplements", ts)
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: narrative-driven scene planning
    plan = _step_1_narrative(player_intent, reasoning, base_l3,
                             entry_scene, exit_scene, world_snapshot)
    scene_names = plan.get("scene_names", [])
    exit_scene = plan.get("exit_scene", exit_scene)
    story = plan.get("story", "")
    if not scene_names:
        return {"l1": {}, "l2": {}, "l3": {}, "output_dir": output_dir}

    # Step 2: 3 parallel generation
    shared = {
        "player_intent": player_intent,
        "reasoning": reasoning,
        "entry_scene": entry_scene,
        "exit_scene": exit_scene,
        "story": story,
        "scene_names": scene_names,
    }
    # Step 2 functions (_step_2a_entities, _step_2b_l1, _step_2c_l3) will be added in subsequent tasks
    # For now, return empty data — subsequent tasks will wire up the parallel calls

    # Post: assemble L2 + validate (TBD in Task 4)
    l2_data = {}
    l1_data = {}
    l3_data = {}

    # Save
    for name, data in [("l1_supp.json", l1_data), ("l2_supp.json", l2_data),
                        ("l3_supp.json", l3_data)]:
        path = os.path.join(output_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return {"l1": l1_data, "l2": l2_data, "l3": l3_data, "output_dir": output_dir}


def _build_l3_context(l3: dict, current_scene: str = "") -> str:
    """Build a natural-language L3 summary for supplement prompts."""
    parts = []
    world_rules = l3.get("world_rules", [])
    if world_rules:
        parts.append("世界规则:")
        for wr in world_rules:
            parts.append(f"  [{wr.get('id','')}] {wr.get('name','')}: {wr.get('rule','')}")
            parts.append(f"    范围: {wr.get('scope','')} | 性质: {wr.get('is_absolute','')}")

    driving_force = l3.get("driving_force", "")
    if driving_force:
        parts.append(f"核心驱动力: {driving_force}")

    narrative_lines = l3.get("narrative_lines", [])
    if narrative_lines:
        parts.append("叙事线:")
        for nl in narrative_lines:
            type_label = {"main": "主线", "branch": "支线", "optional": "可选支线"}.get(
                nl.get("type", ""), nl.get("type", ""))
            parts.append(f"  [{type_label}] {nl.get('name','')}")
            parts.append(f"    大纲: {nl.get('outline','')}")
            parts.append(f"    关键场景: {', '.join(nl.get('key_scenes', []))}")

    tc = l3.get("tone_constraints", {})
    if tc:
        parts.append("基调约束:")
        if tc.get("genre"):
            parts.append(f"  类型: {tc['genre']}")
        if tc.get("narrative_style"):
            parts.append(f"  叙事风格: {tc['narrative_style']}")
        forbidden = tc.get("forbidden", [])
        if forbidden:
            parts.append(f"  禁止: {', '.join(forbidden)}")
        recommended = tc.get("recommended", [])
        if recommended:
            parts.append(f"  推荐: {', '.join(recommended)}")

    scene_intents = l3.get("scene_intents", {})
    if current_scene and scene_intents:
        intent = scene_intents.get(current_scene, {})
        if intent:
            parts.append(f"当前场景设计意图:")
            parts.append(f"  目的: {intent.get('purpose','')}")
            if intent.get("key_threat"):
                parts.append(f"  关键威胁: {intent['key_threat']}")

    return "\n".join(parts)


def _step_1_narrative(
    player_intent: str, reasoning: str, base_l3: dict,
    entry_scene: str, exit_scene: str, world_snapshot: dict,
) -> dict:
    """Step 1: write a module-style narrative, determine scene names + exit."""

    l3_ctx = _build_l3_context(base_l3, current_scene=entry_scene)

    ws_location = world_snapshot.get("location", entry_scene)
    ws_desc = world_snapshot.get("scene_description", "")
    ws_npc = world_snapshot.get("npc_states", {})

    prompt = f"""{l3_ctx}

【当前世界状态】
  位置: {ws_location}
  场景描述: {ws_desc}
  NPC: {json.dumps(ws_npc, ensure_ascii=False)}

【玩家意图】
  玩家想做什么: {player_intent}
  升级原因: {reasoning}

【出入口】
  入口场景: {entry_scene}
  出口场景: {exit_scene or '由你决定'}

你是TRPG模组创作者。玩家行为超出了当前模组范围，需要扩展。请写一段模组风格的叙事文字（最多3个新场景），描述新的展开。叙事应自然融入L3的基调约束、世界规则和叙事线。

同时输出:
- 标准化场景名 (1-3个): SS1_<中文场景名>, SS2_<中文场景名>, SS3_<中文场景名>
- 确认的出口场景: 玩家最终回流的已有场景名

返回 JSON:
{{
  "story": "一段模组风格叙事...",
  "scene_names": ["SS1_镜中世界", "SS2_深渊回廊"],
  "exit_scene": "test_room"
}}

直接输出 JSON。"""
    response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
                             reasoning_effort="max",
                             system="你是TRPG模组创作者。写出自然融入设定基调和世界规则的叙事。",
                             fallback_schema={"story": "", "scene_names": [], "exit_scene": exit_scene})
    return json.loads(response) if isinstance(response, str) else response
