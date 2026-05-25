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
from utils import get_coc_skill_names


# ═══════════════════════════════════════════════════════════════
#  System Prompts
# ═══════════════════════════════════════════════════════════════

SUPP_STEP1_SYSTEM = """你是TRPG模组创作者。玩家行为超出了当前模组范围，需要扩展。请基于玩家意图和L3设计，规划补充内容的结构化设计。

重要原则:
- 新内容必须与L3的基调约束、世界规则和叙事线保持一致
- 不涉及已有NPC和Boss的修改或新增——敌人仅限普通敌人库中的敌人类型
- 场景名使用 SS1_<中文场景名>, SS2_<中文场景名> 格式

返回 JSON:
{
  "overview": "补充内容综述，说明补充了什么、为什么补充、与L3的一致性（200字以内）",
  "scenes": [
    {
      "name": "SS1_场景名",
      "description": "场景的自然语言描述，包括氛围和关键特征（100字以内）",
      "available_interactions": ["玩家在此场景可执行的互动（自然语言简述），至少列出1个"]
    }
  ],
  "narrative_lines": [
    {"name": "叙事线名称", "outline": "叙事线大纲，含起承转合（100字以内）"}
  ],
  "driving_force": "补充内容的驱动力描述——是什么推动了这些新场景和事件的发生（50字以内）",
  "enemies_involved": ["涉及的敌人名称或空列表"],
  "exit_scene": "玩家最终回流的已有场景名（入口场景名或已有L3场景名）"
}

直接输出 JSON。"""

SUPP_STEP2A_SYSTEM = """你是TRPG模组创作者。基于已有叙事和L3设计，生成新场景的全部entity。

Entity 字段规则:
- id: 全局唯一 (SI1/SI2/SI3...=interaction, SAT1/SAT2...=auto_trigger, SE1/SE2...=event)
- entity_type: interaction / auto_trigger / event
- scene: 所在场景名 (SS1_xxx / SS2_xxx)
- name: 简短动作名
- type: 关联技能名 (从标准技能列表选)，不涉及检定填"无"
- requirement: 硬性前置条件用 entity ID + AND/OR/() (如 SI1 AND SI2)，裸 ID 默认指成功完成。无条件填空字符串。特殊条件在 "||" 后用自然语言。可描述是否需要消耗常见物品及数量
- trigger: 触发场景描述，不要和 requirement 混淆
- result: 直接结果。涉及技能检定时填 "##GRADED##"，side_effects 留空，所有结果文字写入 graded_result。可描述失去常见消耗品。不涉及进入与怪物的战斗/对抗/追捕
- side_effects: 间接后果（与result不重合），使用 @标记 语法:
  @spawn_enemy(enemy_ref="名称", scene="场景", quantity=1)
  @grant_weapon(weapon_ref="名称", scene="场景", quantity=1)
  @stat_change(stat_name="属性", delta=-1, narrative="")
  @item_gain(item_name="物品", quantity=1)
  @consume_item(item_name="物品", quantity=1, narrative="")
  @npc_state_change(npc_name="名称", new_state="状态")
  @npc_follow(npc_name="名称", follow=true)
- difficulty: None / regular / hard / extreme
- graded_result: type不为"无"时填写。四等级: on_failure=检定失败 / on_regular=常规成功 / on_hard=困难成功(≤技能值/2) / on_extreme=极难成功(≤技能值/5)。若原文未区分等级，各等级可描述相同

返回 JSON:
{
  "scenes": {
    "SS1_场景名": {
      "description": "场景描述",
      "interactions": [
        {"id": "SI1", "entity_type": "interaction", "scene": "SS1_场景名",
          "name": "动作名", "type": "侦查", "requirement": "", "trigger": "触发条件",
          "result": "##GRADED##", "side_effects": [],
          "graded_result": {"on_failure": "...", "on_regular": "...", "on_hard": "...", "on_extreme": "..."},
          "difficulty": "regular"}
      ],
      "auto_triggers": [],
      "from_here": [{"target": "出口或下一场景", "method": "通行方式", "requirement": ""}],
      "to_here": [{"source": "入口场景", "method": "通行方式", "requirement": ""}],
      "extra": {}
    }
  },
  "events": [],
  "dependency_graph": {
    "nodes": {},
    "edges": []
  }
}

要求:
- 所有 entity 必须有 type/side_effects/result 字段，若涉及检定 type 不为"无"则必须有 graded_result
- 所有 @标记 直接写在 side_effects 中，不允许自然语言描述副作用
- 所有描述性内容使用中文。JSON字段名和ID保持英文
- 去重: 同一场景内 entity name 不应重复
- dependency_graph 标注所有 entity 间的依赖关系 (source=依赖者, target=被依赖者, condition=completed)
- 直接输出 JSON"""

SUPP_STEP2B_SYSTEM = """你是TRPG模组创作者。生成新场景的玩家可见层（L1）。

每个场景包含: description（场景描述）、atmosphere（氛围）、mood（情绪基调）、
perceptible（可无条件感知的元素列表，含 name/brief/linked_interaction）、
ambient_hints（环境暗示）、npc_appearances（NPC出场，含 name/brief/demeanor）

所有描述性内容使用中文。JSON字段名保持英文。

返回 JSON:
{
  "场景中文名": {
    "description": "场景描述",
    "atmosphere": "氛围",
    "mood": "情绪基调",
    "perceptible": [
      {"name": "物品名", "brief": "简短描述", "linked_interaction": "关联entity ID或空"}
    ],
    "ambient_hints": ["环境暗示"],
    "npc_appearances": []
  }
}

直接输出 JSON。"""

SUPP_STEP2C_SYSTEM = """你是TRPG模组设计者。为新场景生成L3设计层。

为每个新场景生成 scene_intents 条目（purpose=场景目的, key_threat=关键威胁, notes=设计备注）。
如果新场景引入新的世界规则或需要调整基调约束，在 new_rules 和 tone_adjustments 中说明。

返回 JSON:
{
  "scene_intents": {
    "SS1_场景中文名": {
      "purpose": "场景目的",
      "key_threat": "关键威胁",
      "notes": "设计备注"
    }
  },
  "new_rules": [],
  "tone_adjustments": {}
}

直接输出 JSON。"""


def run_supplement_pipeline(
    player_intent: str,
    reasoning: str,
    base_l3: dict,
    entry_scene: str,
    exit_scene: str = "",
    world_snapshot: dict | None = None,
    output_dir: str = "",
    module_name: str = "",
    enemy_names: list[str] | None = None,
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
                             entry_scene, exit_scene, world_snapshot,
                             enemy_names=enemy_names or [])
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
    # Step 2: wire parallel calls (2b_l1 and 2c_l3 added in later tasks)
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_step_2a_entities, shared, base_l3): "2a_entities",
            executor.submit(_step_2b_l1, shared, base_l3): "2b_l1",
            executor.submit(_step_2c_l3, shared, base_l3): "2c_l3",
        }
        results = {}
        for future in as_completed(futures):
            name = futures[future]
            results[name] = future.result()

    entities_data = results.get("2a_entities", {})
    l1_data = results.get("2b_l1", {})
    step2c_l3 = results.get("2c_l3", {})

    # Post: assemble L2 + validate
    l2_data = _assemble_l2(entities_data, scene_names)

    # Build L3 supplement: merge base_l3 with new L3 data from Step 2c
    l3_data = {
        "module_meta": {
            **base_l3.get("module_meta", {}),
            "supplement_of": base_l3.get("module_meta", {}).get("name", ""),
            "generated_for": player_intent,
        },
        "world_rules": base_l3.get("world_rules", []),
        "scene_intents": {
            **base_l3.get("scene_intents", {}),
            **step2c_l3.get("scene_intents", {}),
        },
        "ending_conditions": base_l3.get("ending_conditions", []),
        "tone_constraints": base_l3.get("tone_constraints", {}),
        "characters": base_l3.get("characters", {}),
        "driving_force": base_l3.get("driving_force", ""),
        "narrative_lines": base_l3.get("narrative_lines", []),
        "time_pressure": base_l3.get("time_pressure", {}),
    }

    try:
        _validate_supplement(l2_data, l1_data, scene_names)
    except ValueError as e:
        # Log warning but don't block — the LLM output may be imperfect
        print(f"[supplement_pipeline] validation warning: {e}")

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
    enemy_names: list[str] | None = None,
) -> dict:
    """Step 1: structured supplement planning — overview, scenes, narrative lines, driving force."""

    l3_ctx = _build_l3_context(base_l3, current_scene=entry_scene)

    ws_location = world_snapshot.get("location", entry_scene)
    ws_desc = world_snapshot.get("scene_description", "")
    ws_npc = world_snapshot.get("npc_states", {})

    enemy_text = ""
    if enemy_names:
        enemy_text = f"\n【可用敌人库（enemies_involved 必须从此列表选择）】\n{', '.join(enemy_names)}"

    prompt = f"""{l3_ctx}

【当前世界状态】
  位置: {ws_location}
  场景描述: {ws_desc}
  NPC: {json.dumps(ws_npc, ensure_ascii=False)}
{enemy_text}
【玩家意图】
  玩家想做什么: {player_intent}
  升级原因: {reasoning}

【出入口】
  入口场景: {entry_scene}
  出口场景: {exit_scene or '由你决定'}"""
    response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
                             reasoning_effort="max",
                             system=SUPP_STEP1_SYSTEM,
                             fallback_schema={"overview": "", "scenes": [],
                                              "narrative_lines": [], "driving_force": "",
                                              "enemies_involved": [], "exit_scene": exit_scene})
    plan = json.loads(response) if isinstance(response, str) else response

    # Extract scene_names from structured scenes list
    scene_names = [s.get("name", "") for s in plan.get("scenes", []) if s.get("name")]
    exit_scene = plan.get("exit_scene", exit_scene)

    # Assemble markdown story for Step 2 consumers
    story_parts = []
    overview = plan.get("overview", "")
    if overview:
        story_parts.append(f"## 综述\n{overview}")
    for s in plan.get("scenes", []):
        sname = s.get("name", "")
        sdesc = s.get("description", "")
        interactions = s.get("available_interactions", [])
        if sname:
            story_parts.append(f"## {sname}\n{sdesc}")
            for ia in interactions:
                story_parts.append(f"- {ia}")
    nl_lines = plan.get("narrative_lines", [])
    if nl_lines:
        story_parts.append("## 叙事线")
        for nl in nl_lines:
            story_parts.append(f"- **{nl.get('name', '')}**: {nl.get('outline', '')}")
    df = plan.get("driving_force", "")
    if df:
        story_parts.append(f"## 驱动力\n{df}")
    enemies = plan.get("enemies_involved", [])
    if enemies:
        story_parts.append(f"## 涉及敌人\n{', '.join(enemies)}")
    story = "\n\n".join(story_parts)

    plan["scene_names"] = scene_names
    plan["exit_scene"] = exit_scene
    plan["story"] = story
    return plan


def _step_2a_entities(shared: dict, base_l3: dict) -> dict:
    """Step 2a: generate all entities with inline @markup standardization + dependency graph.

    One LLM call covers what the main pipeline does in Step 2 (entity generation)
    + Phase 2 (@markup standardization) + Step 3 (dedup/conflict check).
    """
    skills = "、".join(get_coc_skill_names())

    prompt = f"""【叙事】
{shared['story']}

【场景清单】
{', '.join(shared['scene_names'])}

【出入口】
入口: {shared['entry_scene']}
出口: {shared['exit_scene']}

【玩家意图】
{shared['player_intent']}

标准技能: {skills}"""
    response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
                             reasoning_effort="max",
                             system=SUPP_STEP2A_SYSTEM,
                             fallback_schema={"scenes": {}, "events": [], "dependency_graph": {"nodes": {}, "edges": []}})
    return json.loads(response) if isinstance(response, str) else response


def _step_2b_l1(shared: dict, base_l3: dict) -> dict:
    """Step 2b: generate L1 player-facing layer for new scenes."""
    scene_list = "\n".join(f"- {s}" for s in shared["scene_names"])
    prompt = f"""【叙事】
{shared['story']}

【新场景】
{scene_list}"""
    response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
                             reasoning_effort="max",
                             system=SUPP_STEP2B_SYSTEM,
                             fallback_schema={})
    return json.loads(response) if isinstance(response, str) else response


def _step_2c_l3(shared: dict, base_l3: dict) -> dict:
    """Step 2c: generate L3 designer layer for new scenes — scene_intents + optional adjustments."""
    scene_list = "\n".join(f"- {s}" for s in shared["scene_names"])
    prompt = f"""【叙事】
{shared['story']}

【新场景】
{scene_list}

【出入口】
入口: {shared['entry_scene']}
出口: {shared['exit_scene']}"""
    response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
                             reasoning_effort="max",
                             system=SUPP_STEP2C_SYSTEM,
                             fallback_schema={"scene_intents": {}, "new_rules": [], "tone_adjustments": {}})
    return json.loads(response) if isinstance(response, str) else response


def _assemble_l2(entities_data: dict, scene_names: list[str]) -> dict:
    """Assemble L2 structure from Step 2a output."""
    scenes = entities_data.get("scenes", {})
    events = entities_data.get("events", [])
    dep_graph = entities_data.get("dependency_graph", {"nodes": {}, "edges": []})

    scene_map = {}
    for sid in scenes:
        scene_map[sid] = sid

    return {
        "scenes": scenes,
        "events": events,
        "npc_profiles": {},
        "dependency_graph": dep_graph,
        "_scene_names": scene_map,
        "_phase1": {},
    }


def _validate_supplement(l2: dict, l1: dict, scene_names: list[str]):
    """Deterministic validation: entity ID uniqueness, scene references, dependency cycle check, graded_result consistency."""
    entity_ids = set()

    for scene_name, scene_data in l2.get("scenes", {}).items():
        for ent in scene_data.get("interactions", []) + scene_data.get("auto_triggers", []):
            eid = ent.get("id", "")
            if not eid:
                continue
            if eid in entity_ids:
                raise ValueError(f"Duplicate entity ID: {eid}")
            entity_ids.add(eid)

            if ent.get("type", "") not in ("", "无", "None") and not ent.get("graded_result"):
                raise ValueError(f"Entity {eid} has skill type but no graded_result")
            if ent.get("result") == "##GRADED##" and ent.get("side_effects"):
                raise ValueError(f"Entity {eid}: ##GRADED## result but side_effects non-empty")

    for ev in l2.get("events", []):
        eid = ev.get("id", "")
        if not eid:
            continue
        if eid in entity_ids:
            raise ValueError(f"Duplicate entity ID (event): {eid}")
        entity_ids.add(eid)

    dep_edges = l2.get("dependency_graph", {}).get("edges", [])
    adjacency = {}
    for eid in entity_ids:
        adjacency[eid] = []
    for edge in dep_edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        if src in adjacency and tgt in adjacency:
            adjacency[src].append(tgt)
    visited = set()
    stack = set()
    def _has_cycle(node):
        visited.add(node)
        stack.add(node)
        for neighbor in adjacency.get(node, []):
            if neighbor not in visited:
                if _has_cycle(neighbor):
                    return True
            elif neighbor in stack:
                return True
        stack.discard(node)
        return False
    for eid in entity_ids:
        if eid not in visited:
            if _has_cycle(eid):
                raise ValueError(f"Dependency cycle detected starting at {eid}")

    scene_set = set(l2.get("scenes", {}).keys())
    for scene_name, scene_data in l2.get("scenes", {}).items():
        for ent in scene_data.get("interactions", []) + scene_data.get("auto_triggers", []):
            if ent.get("scene") not in scene_set:
                raise ValueError(f"Entity {ent.get('id')} references unknown scene: {ent.get('scene')}")
