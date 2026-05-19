# ============================================================
# 四步渐进式解析 — Notebook 导出（手动调试用）
# 来源: ba77373 notebooks/parser_layered.ipynb
# 运行方式: 将需要的 cell 复制到 Jupyter 中执行
# 注意: 在 Jupyter 中需先执行 import/setup cells
# ============================================================


# ============================================================
# CELL 0 (markdown)
# ============================================================
# # 常暗之厢 — 四步渐进式解析（分步调试版）
#
# **每步单独执行**，中间结果、完整 prompt 和 LLM 响应全部保存到 `data/debug/` 目录。
#
# **流程**：
# 1. Step 1：名称固化 + 精修模组（2 calls 并行）
# 2. Step 2：内容生成 — interactions 先跑 → events + auto_triggers + L1 + L3 并行
# 3. Step 3a ∥ 2.5 → 3b → 3.5 ∥ Phase 1 → Phase 2（7 calls）
#
# **产物**：`data/debug/<timestamp>/` 下每步一个子文件夹，每个 LLM 调用 `prompt.txt` + `response.json`


# ============================================================
# CELL 1 (code)
# ============================================================
# ═══════════════════════════════════════════════════════════════
# 导入 & 环境配置
# ═══════════════════════════════════════════════════════════════
import sys, json, os, re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "../src")

from utils import parser, estimate_and_truncate_context
from llm import call_deepseek
from module_designer import (
    validate_all, save_pipeline_result,
    # Prompt builders
    build_step1a_prompt, build_step1b_prompt,
    build_step2a_prompt, build_step2b_events_prompt, build_step2b_at_prompt,
    build_step2c_l1_prompt, build_step2c_l3_prompt,
    build_step3a_prompt, build_step3b_prompt, build_step35_prompt,
    build_phase1_prompt, build_step4_prompt,
    # Parsers (for cross_validate)
    _is_valid_json_output, _with_fallback,
)
from module_designer.layered_pipeline import cross_validate_layers, CrossRefReport
from module_designer.layered_parser import (
    STEP1A_SYSTEM, STEP1B_SYSTEM,
    STEP2A_SYSTEM, STEP2B_EVENTS_SYSTEM, STEP2B_AT_SYSTEM,
    STEP2C_L1_SYSTEM, STEP2C_L3_SYSTEM,
    STEP3A_SYSTEM, STEP3B_SYSTEM, STEP35_SYSTEM,
    STEP25_SYSTEM, PHASE1_SYSTEM, STEP4_SYSTEM,
)
from library import WeaponLibrary, EnemyLibrary

print("模块导入完成")


# ============================================================
# CELL 2 (code)
# ============================================================
# ═══════════════════════════════════════════════════════════════
# 加载模组 & 初始化库 & 创建调试目录
# ═══════════════════════════════════════════════════════════════

# 加载源文档
content = parser("../常暗之厢（7版规则，简体修正版）.docx")
content = estimate_and_truncate_context(content)
print(f"源文档: {len(content)} 字符 (~{len(content)//2} tokens)")

# 初始化武器/敌人库
wl = WeaponLibrary(); wl.load_core()
el = EnemyLibrary(); el.load_core()
print(f"武器: {[w.name for w in wl.list_all()]}")
print(f"敌人: {[e.name for e in el.list_all()]}")

# 创建调试输出目录 (临时产物，不放在 data/modules/)
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
DEBUG_ROOT = f"../data/debug/{TIMESTAMP}"
os.makedirs(DEBUG_ROOT, exist_ok=True)
print(f"\n调试产物目录: {DEBUG_ROOT}/")


# ============================================================
# CELL 3 (code)
# ============================================================
# ═══════════════════════════════════════════════════════════════
# 辅助函数：保存 LLM 调用的 prompt + response
# ═══════════════════════════════════════════════════════════════

def save_llm_call(step_name, call_name, prompt_text, system_text, response, is_json):
    """
    将一个 LLM 调用的 prompt 和 response 保存到调试目录。
    路径: {DEBUG_ROOT}/{step_name}/{call_name}/
      prompt.txt   — 完整 prompt（含 system）
      response.json / response.txt — LLM 返回
    """
    call_dir = os.path.join(DEBUG_ROOT, step_name, call_name)
    os.makedirs(call_dir, exist_ok=True)

    # 保存 prompt
    with open(os.path.join(call_dir, "prompt.txt"), "w", encoding="utf-8") as f:
        if system_text:
            f.write(f"=== SYSTEM ===\n{system_text}\n\n=== USER PROMPT ===\n{prompt_text}")
        else:
            f.write(prompt_text)

    # 保存 response
    ext = "json" if is_json else "txt"
    with open(os.path.join(call_dir, f"response.{ext}"), "w", encoding="utf-8") as f:
        if is_json:
            json.dump(response, f, ensure_ascii=False, indent=2)
        else:
            f.write(str(response))

def do_json_call(step_name, call_name, prompt_fn, *args, system_prompt="", **kwargs):
    """
    执行一次 JSON 模式 LLM 调用：构建 prompt → 保存 → 调用 → 保存响应。
    参数:
        step_name: 步骤文件夹名 (如 'step_1')
        call_name: 本次调用名 (如 '1a_structured_extraction')
        prompt_fn: build_*_prompt 函数
        *args, **kwargs: 传给 prompt_fn
        system_prompt: 系统提示词
    返回: LLM 响应 (dict)
    """
    prompt_text = prompt_fn(*args, **kwargs)
    response = call_deepseek(prompt_text, system=system_prompt, json_mode=True)
    save_llm_call(step_name, call_name, prompt_text, system_prompt, response, is_json=True)
    return response

def do_text_call(step_name, call_name, prompt_fn, *args, system_prompt="", **kwargs):
    """文本模式 LLM 调用。用于 Step 1b（返回 markdown）。"""
    prompt_text = prompt_fn(*args, **kwargs)
    response = call_deepseek(prompt_text, system=system_prompt, json_mode=False)
    save_llm_call(step_name, call_name, prompt_text, system_prompt, response, is_json=False)
    return response

print("辅助函数就绪")
print(f"  save_llm_call(step_name, call_name, prompt, system, response, is_json)")
print(f"  do_json_call(step_name, call_name, prompt_fn, *args, system_prompt=, **kwargs)")
print(f"  do_text_call(step_name, call_name, prompt_fn, *args, system_prompt=, **kwargs)")


# ============================================================
# CELL 4 (markdown)
# ============================================================
# ---
# ## Step 1：名称固化 + 精修模组（2 calls 并行）
#
# **Step 1a** 提取场景/NPC ID → **Step 1b** 生成精修叙事文本。两者独立，可并行。


# ============================================================
# CELL 5 (code)
# ============================================================
# ═══ Step 1a: 结构化提取 ═══
# 输入: 原始模组文档
# 输出: module_meta + scenes[name, ...] + characters[{name,id}]
with ThreadPoolExecutor(max_workers=2) as ex:
    f1a = ex.submit(do_json_call,
        "step_1", "1a_structured_extraction",
        build_step1a_prompt, content,
        system_prompt=STEP1A_SYSTEM
    )
    f1b = ex.submit(do_text_call,
        "step_1", "1b_condensed_text",
        build_step1b_prompt, content,
        system_prompt=STEP1B_SYSTEM
    )
    step1a = f1a.result()
    step1b_raw = f1b.result()

# Step 1b 返回的是 markdown 字符串，包裹为 dict
step1b = {"condensed_text": step1b_raw} if isinstance(step1b_raw, str) else step1b_raw

scenes = step1a.get("scenes", [])
characters = step1a.get("characters", [])
condensed_text = step1b.get("condensed_text", "")
from module_designer.layered_parser import _parse_condensed_chapters
chapters = _parse_condensed_chapters(condensed_text) if condensed_text else {}

print(f"Chapters key: {list(chapters.keys())}")
for k, v in chapters.items():
    print(f"  {k}: {len(v)} 字符")

# 保存 Step 1 汇总
with open(f"{DEBUG_ROOT}/step_1/_summary.json", "w", encoding="utf-8") as f:
    json.dump({
        "meta": step1a.get("module_meta", {}),
        "scenes": scenes,
        "characters": characters,
        "condensed_text_length": len(condensed_text),
    }, f, ensure_ascii=False, indent=2)

print(f"Step 1a: {len(scenes)} 场景, {len(characters)} 角色")
for s in scenes:
    print(f"  {s['id']}: {s['name']}")
print(f"Step 1b: condensed_text {len(condensed_text)} 字符")
print(f"产物: {DEBUG_ROOT}/step_1/1a_*/ 和 1b_*/")


# ============================================================
# CELL 6 (code)
# ============================================================
# 查看 condensed_text 前 600 字
print(condensed_text[:600])
print("..." if len(condensed_text) > 600 else "")


# ============================================================
# CELL 7 (markdown)
# ============================================================
# ---
# ## Step 2：内容生成
#
# **2a** interactions 先跑（固化 flag 名称） → **2b** events + auto_triggers **2c** L1 + L3 并行


# ============================================================
# CELL 8 (code)
# ============================================================
# ═══ Step 2a: Interactions ═══
# 输入: condensed_text + scenes 列表
# 输出: interactions 列表（含 ID + 场景中文名）
step2a = do_json_call(
    "step_2", "2a_interactions",
    build_step2a_prompt, chapters, scenes,
    system_prompt=STEP2A_SYSTEM
)
interactions = step2a.get("interactions", [])
scene_movements = step2a.get("scene_movements", {})
print(f"Interactions: {len(interactions)} 个, {len(scene_movements)} 场景通行路径")
for i in interactions[:5]:
    side = i.get('side_effects', [])
    side_preview = side[0][:20] + "..." if side and isinstance(side[0], str) else ""
    print(f"  {i['id']}: {i['name']} (场景 {i.get('scene','?')})" + (f" [{side_preview}]" if side_preview else ""))
if len(interactions) > 5:
    print(f"  ... 共 {len(interactions)} 个")


# ============================================================
# CELL 9 (code)
# ============================================================
# ═══ Step 2b + 2c: 4 calls 并行 ═══
# 2b: events + auto_triggers（注入 interactions 的 ID/flag）
# 2c: L1 + L3（独立）
with ThreadPoolExecutor(max_workers=4) as ex:
    f_ev = ex.submit(do_json_call,
        "step_2", "2b_events",
        build_step2b_events_prompt, chapters, scenes, interactions,
        system_prompt=STEP2B_EVENTS_SYSTEM
    )
    f_at = ex.submit(do_json_call,
        "step_2", "2b_auto_triggers",
        build_step2b_at_prompt, chapters, scenes, interactions,
        system_prompt=STEP2B_AT_SYSTEM
    )
    f_l1 = ex.submit(do_json_call,
        "step_2", "2c_l1",
        build_step2c_l1_prompt, chapters, scenes, characters,
        system_prompt=STEP2C_L1_SYSTEM
    )
    f_l3 = ex.submit(do_json_call,
        "step_2", "2c_l3",
        build_step2c_l3_prompt, chapters, scenes, characters, step1a.get("module_meta", {}),
        system_prompt=STEP2C_L3_SYSTEM
    )
    events_data = f_ev.result()
    at_data = f_at.result()
    l1_data = f_l1.result()
    l3_data = f_l3.result()

events = events_data.get("events", [])
auto_triggers = at_data.get("auto_triggers", [])
# Inject world-generation auto_trigger
auto_triggers.append({
    "id": "AT_WORLD", "name": "世界生成", "scene": "world", "type": "无",
    "requirement": "", "trigger": "模组开始时自动触发",
    "result": "世界环境初始化", "side_effects": [],
    "difficulty": "None", "based_on": "",
})

# 保存 Step 2 汇总
with open(f"{DEBUG_ROOT}/step_2/_summary.json", "w", encoding="utf-8") as f:
    json.dump({
        "interactions_count": len(interactions),
        "events_count": len(events),
        "auto_triggers_count": len(auto_triggers),
        "l1_scenes": list(l1_data.keys()),
        "l3_world_rules": len(l3_data.get("world_rules", [])),
    }, f, ensure_ascii=False, indent=2)

print(f"Events: {len(events)} 个")
for ev in events:
    print(f"  {ev.get('id','?')}: {ev.get('name','?')}")
print(f"\nAuto-triggers: {len(auto_triggers)} 个")
for at in auto_triggers:
    print(f"  {at.get('id','?')}: {at.get('name','?')} → {at.get('type','?')} (场景 {at.get('scene','?')}, based_on={at.get('based_on','')})")
print(f"\nL1: {len(l1_data)} 场景")
print(f"L3: {len(l3_data.get('world_rules',[]))} 世界规则, {len(l3_data.get('scene_intents',{}))} 场景意图")


# ============================================================
# CELL 10 (markdown)
# ============================================================
# ---
# ## Step 3：依赖解析 + NPC 行为描述 + 交叉核对
#
# **3a** 去重冲突 ∥ **2.5** NPC 行为描述 (并行) → 组装 L2 → **3b** L1 ↔ L2 校对


# ============================================================
# CELL 11 (code)
# ============================================================
# ═══ Step 3a ∥ Step 2.5 (并行) ═══
ending_conditions = l3_data.get("ending_conditions", [])

l3_characters = l3_data.get("characters", [])
with ThreadPoolExecutor(max_workers=2) as ex:
    f3a = ex.submit(do_json_call,
        "step_3", "3a_dedup_conflict",
        build_step3a_prompt,
        chapters, interactions, events, auto_triggers, ending_conditions,
        system_prompt=STEP3A_SYSTEM
    )
    if l3_characters:
        f25 = ex.submit(do_json_call,
            "step_25", "25_npc_profiles",
            build_step25_prompt,
            l3_characters, l1_data, interactions, auto_triggers,
            system_prompt=STEP25_SYSTEM
        )
    step3a = f3a.result()
    step25 = f25.result() if l3_characters else {"npc_profiles": {}}

interactions = step3a.get("interactions", interactions)
events = step3a.get("events", events)
auto_triggers = step3a.get("auto_triggers", auto_triggers)
npc_profiles = step25.get("npc_profiles", {})
print(f"Step 3a 完成: 去重 + 冲突 + 结局")
print(f"  Interactions: {len(interactions)}, Events: {len(events)}, Auto-triggers: {len(auto_triggers)}")
print(f"Step 2.5 完成: {len(npc_profiles)} NPC profiles")

# ═══ 组装 L2 结构 ═══
from module_designer.layered_pipeline import _assemble_l2
l2_assembled = _assemble_l2(interactions, events, auto_triggers, scene_movements, l1_data, npc_profiles=npc_profiles)
print(f"L2 组装完成: {len(l2_assembled.get('scenes',{}))} 场景")

# 从组装后的 L2 提取平面列表供 Step 3.5/4 使用
step35_interactions = []
step35_at = []
for sdata in l2_assembled.get("scenes", {}).values():
    step35_interactions.extend(sdata.get("interactions", []))
    step35_at.extend(sdata.get("auto_triggers", []))
step35_events = l2_assembled.get("events", [])


# ============================================================
# CELL 12 (code)
# ============================================================
# ═══ Step 3b: L1 ↔ L2 交叉核对 ═══
# 输入: chapters + L1 + assembled L2 + L3 + scenes 列表
# 输出: 修正后的 l1_data + l3_data
step3b = do_json_call(
    "step_3", "3b_cross_check",
    build_step3b_prompt,
    chapters, l1_data, l2_assembled, l3_data, scenes,
    system_prompt=STEP3B_SYSTEM
)
l1_data = step3b.get("l1_data", l1_data)
l3_data = step3b.get("l3_data", l3_data)

# ═══ WR0 注入（默认开启）：创作者豁免 — 在 Step 3b 之后确保写入 ═══
INJECT_WR0 = True
if INJECT_WR0 and not l3_data.get("_fallback"):
    world_rules = l3_data.setdefault("world_rules", [])
    if "WR0" not in {wr.get("id", "") for wr in world_rules if isinstance(wr, dict)}:
        world_rules.insert(0, {"id": "WR0", "name": "创作者豁免",
            "rule": "所有世界规则只约束KP和玩家，模组创作者不受世界规则约束",
            "scope": ["meta"], "is_absolute": True})
        print("  [L3] WR0 已注入（Step 3b 后）")

print(f"交叉核对完成")
print(f"  L1: {len(l1_data)} 场景")
print(f"  L3 scene_intents: {list(l3_data.get('scene_intents', {}).keys())}")


# ============================================================
# CELL 13 (markdown)
# ============================================================
# ---
# ## Step 3.5 + Phase 1 + Phase 2：依赖图 ∥ 风格预判 → 精简标准化
#
# Step 3.5 从 requirement 提取 entity 依赖 ∥ Phase 1 风格预判 → Phase 2 精简标准化


# ============================================================
# CELL 14 (code)
# ============================================================
# ═══ Step 3.5 ∥ Phase 1: 依赖图 + 风格预判 (并行) ═══
weapon_names = [f"{w.name} — {w.description}" if w.description else w.name for w in wl.list_all()]
enemy_names = [f"{e.name} — {e.description}" if e.description else e.name for e in el.list_all()]
stat_names = ["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "SAN", "HP", "LUCK", "MP"]

import json as _json
import os as _os
try:
    skill_path = _os.path.join("..", "data", "skill_checks.json")
    with open(skill_path, "r", encoding="utf-8") as _f:
        skill_checks = _json.load(_f)
        skill_names = sorted(set(s["name"] for s in skill_checks))
except Exception:
    skill_names = []

l2_descriptions = {}
for name, sdata in l1_data.items():
    desc = sdata.get("description", "") or sdata.get("atmosphere", "")
    if desc:
        l2_descriptions[name] = desc

from module_designer.dependency_graph import DependencyGraph
from module_designer.layered_parser import _merge_phase2_fields

# Step 3.5: 依赖图（含重试逻辑）
def _run_step35():
    MAX_TRIES = 3
    for attempt in range(1, MAX_TRIES + 1):
        step35 = do_json_call(
            "step_35", "35_dependency_graph",
            build_step35_prompt,
            chapters, step35_interactions, step35_events, step35_at,
            system_prompt=STEP35_SYSTEM
        )
        deps = step35.get("dependencies", [])
        if not deps:
            print(f"  [Step 3.5] 第 {attempt} 次解析为空，重试...")
            continue
        dep_graph = DependencyGraph()
        dep_graph.build(deps)
        cycles = dep_graph.detect_cycles()
        if not cycles:
            print(f"  [Step 3.5] 依赖图: {len(dep_graph.nodes)} 节点, {len(dep_graph.edges)} 边, 无循环")
            return dep_graph
        if attempt < MAX_TRIES:
            print(f"  [Step 3.5] 第 {attempt} 次检测到 {len(cycles)} 个循环，重试...")
        else:
            dep_graph.cut_random_edge_in_cycles()
            print(f"  [Step 3.5] 重调用尽，随机切断循环边")
            return dep_graph
    return None

scene_intents_p1 = l3_data.get("scene_intents", {})
with ThreadPoolExecutor(max_workers=2) as ex:
    f35 = ex.submit(_run_step35)
    f_p1 = ex.submit(do_json_call,
        "phase_1", "phase1_style_preview",
        build_phase1_prompt,
        chapters, scene_intents_p1, weapon_names, enemy_names,
        system_prompt=PHASE1_SYSTEM
    )
    dep_graph = f35.result()
    phase1 = f_p1.result()

phase1_clean = {"enemies": phase1.get("enemies", []),
                "weapons": phase1.get("weapons", [])}
print(f"Phase 1 完成: {len(phase1_clean['enemies'])} 敌人类型, {len(phase1_clean['weapons'])} 武器类型")

# ── Phase 2: 精简标准化 (依赖 Phase 1 约束) ──
scene_intents_s4 = l3_data.get("scene_intents", {})
step4 = do_json_call(
    "phase_2", "phase2_standardization",
    build_step4_prompt,
    step35_interactions, step35_at, l2_descriptions,
    scene_intents_s4, chapters,
    phase1_clean, skill_names, stat_names,
    system_prompt=STEP4_SYSTEM
)
# Merge Phase 2 standardized fields back into complete originals
p2_interactions = step4.get("interactions", step35_interactions)
p2_auto_triggers = step4.get("auto_triggers", step35_at)
interactions = _merge_phase2_fields(step35_interactions, p2_interactions)
auto_triggers = _merge_phase2_fields(step35_at, p2_auto_triggers)
print(f"Phase 2 完成: skill/stat 标准化 + @标记转化")

# Strip based_on
for e in interactions:
    e.pop("based_on", None)
for e in auto_triggers:
    e.pop("based_on", None)
for e in events:
    e.pop("based_on", None)

# ═══ 用 Phase 2 标准化后的实体重新组装 L2 ═══
l2_assembled = _assemble_l2(interactions, events, auto_triggers, scene_movements, l1_data, npc_profiles=npc_profiles)
print(f"L2 重新组装完成: {len(l2_assembled.get('scenes',{}))} 场景")
if dep_graph:
    l2_assembled["dependency_graph"] = dep_graph.to_dict()
l2_assembled["_phase1"] = phase1_clean


# ============================================================
# CELL 15 (markdown)
# ============================================================
# ---
# ## 最终验证 & 保存


# ============================================================
# CELL 16 (code)
# ============================================================
# ═══ Schema 验证 + 交叉引用 ═══
schema_reports = validate_all(l1_data, l2_assembled, l3_data)
print("═══ Schema 验证 ═══")
for layer, report in schema_reports.items():
    status = "PASS" if report.is_valid else "ISSUES"
    print(f"  {layer} [{status}]: {report.summary()}")

# 交叉引用
cross_ref = cross_validate_layers(l1_data, l2_assembled, l3_data, weapon_lib=wl, enemy_lib=el)
print(f"\n═══ 交叉引用 ═══")
print(f"  {cross_ref.summary()}")

# 保存验证报告
with open(f"{DEBUG_ROOT}/_validation_report.json", "w", encoding="utf-8") as f:
    json.dump({
        "schema": {l: {"errors": len(r.errors), "warnings": len(r.warnings), "is_valid": r.is_valid}
                     for l, r in schema_reports.items()},
        "cross_ref": {"errors": len(cross_ref.errors), "warnings": len(cross_ref.issues), "is_valid": cross_ref.is_valid},
    }, f, ensure_ascii=False, indent=2)


# ============================================================
# CELL 17 (code)
# ============================================================
# ═══ 保存最终结果到 data/modules/ ═══
MODULE_DIR = "../data/modules/常暗之厢"
os.makedirs(MODULE_DIR, exist_ok=True)

# L1
with open(f"{MODULE_DIR}/l1_player.json", "w", encoding="utf-8") as f:
    json.dump(l1_data, f, ensure_ascii=False, indent=2)

# L2（已组装，含 scene_movements 和 description）
with open(f"{MODULE_DIR}/l2_keeper.json", "w", encoding="utf-8") as f:
    json.dump(l2_assembled, f, ensure_ascii=False, indent=2)

# L3
with open(f"{MODULE_DIR}/l3_designer.json", "w", encoding="utf-8") as f:
    json.dump(l3_data, f, ensure_ascii=False, indent=2)

print(f"最终结果已保存至 {MODULE_DIR}/")
print(f"调试产物: {DEBUG_ROOT}/")


# ============================================================
# CELL 18 (code)
# ============================================================
print("=" * 60)
print("四步渐进式解析完成")
print("=" * 60)
print(f"Step 1: {len(scenes)} 场景, {len(characters)} 角色, {len(condensed_text)} 字 condensed_text")
print(f"Step 2: {len(interactions)} interactions, {len(events)} events, {len(auto_triggers)} auto_triggers")
print(f"        {len(l1_data)} L1 场景, {len(l3_data.get('world_rules',[]))} 世界规则, {len(npc_profiles)} NPC profiles")
print(f"Step 3a+2.5: 去重+冲突+结局 ∥ NPC 行为描述 (并行)")
print(f"Step 3b: L1 ↔ L2 交叉核对")
print(f"Step 3.5+Phase 1: 依赖图 ∥ 风格预判 (并行)")
print(f"Phase 2: 精简标准化")
print(f"")
print(f"总 LLM 调用: 13 (Step 1:2 + Step 2:5 + Step 2.5:1 + Step 3:2 + 3.5+Phase 1:2 + Phase 2:1)")
print(f"其中并行组: Step 1a∥1b, Step 2b∥2c, Step 3a∥2.5, Step 3.5∥Phase 1")
print(f"调试产物: {DEBUG_ROOT}/")
print(f"├── step_1/   (1a_structured_extraction, 1b_condensed_text)")
print(f"├── step_2/   (2a_interactions, 2b_events, 2b_auto_triggers, 2c_l1, 2c_l3)")
print(f"├── step_25/  (25_npc_profiles)")
print(f"├── step_3/   (3a_dedup_conflict, 3b_cross_check)")
print(f"├── step_35/  (35_dependency_graph)")
print(f"├── phase_1/  (phase1_style_preview)")
print(f"└── phase_2/  (phase2_standardization)")
print(f"")
print(f"最终模组: {MODULE_DIR}/")
print(f"  l1_player.json, l2_keeper.json, l3_designer.json")
print(f"状态: {'PASS' if cross_ref.is_valid else 'HAS_ISSUES'}")
