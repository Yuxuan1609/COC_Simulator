"""
四步渐进式管线编排层。

流程编排:
  Step 1a + 1b  并行 (meta+scenes+characters | condensed_text)
  Step 2a       先跑 (interactions)
  Step 2b + 2c  并行 (events + auto_triggers | L1 + L3)
  Step 3a ∥ 2.5 并行 (L2 去重冲突 ∥ NPC 行为描述) → 组装 L2
  Step 3b       L1-L2 交叉核对
  Step 3.5 ∥ Phase 1 并行 (依赖图 ∥ 风格预判) → Phase 2 精简标准化

每步含 retry + fallback 保底策略。
管线完成后运行确定性 cross_validate 做最终验证。

Notebook 入口: run_pipeline(content, llm_json, llm_text)
"""
from __future__ import annotations
import json
import os
from typing import Optional, TYPE_CHECKING

from module_designer.layered_schema import validate_all, SchemaReport
from config import PIPELINE_MAX_RETRIES, INJECT_L3_WR0

if TYPE_CHECKING:
    from library.injector import ContentInjector


# ═══════════════════════════════════════════════════════════════
#  交叉引用验证
# ═══════════════════════════════════════════════════════════════

class CrossRefIssue:
    """交叉引用问题."""
    def __init__(self, layer: str, path: str, message: str, severity: str = "warning"):
        self.layer = layer
        self.path = path
        self.message = message
        self.severity = severity

    def __repr__(self):
        return f"[{self.severity}] {self.layer} {self.path}: {self.message}"


class CrossRefReport:
    """交叉引用验证报告."""
    def __init__(self):
        self.issues: list[CrossRefIssue] = []

    def add(self, layer: str, path: str, message: str, severity: str = "warning"):
        self.issues.append(CrossRefIssue(layer, path, message, severity))

    @property
    def errors(self) -> list[CrossRefIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        if not self.issues:
            return "交叉引用验证通过。"
        lines = [f"交叉引用验证：{len(self.issues)} 个问题"]
        for i in self.issues:
            lines.append(f"  {i}")
        return "\n".join(lines)

    def __bool__(self):
        return self.is_valid


def _collect_interaction_names(l2_data: dict) -> dict[str, set[str]]:
    """从 L2 数据收集所有 interaction name，按场景组织。返回 {scene_name: {interaction_name, ...}}."""
    names: dict[str, set[str]] = {}
    scenes = l2_data.get("scenes", {})
    for scene_name, scene_data in scenes.items():
        names[scene_name] = set()
        for inter in scene_data.get("interactions", []):
            if isinstance(inter, dict) and inter.get("name"):
                names[scene_name].add(inter["name"])
    return names


def _collect_library_names(lib, kind: str = "weapon") -> set[str]:
    """从 library 收集所有名称。kind: 'weapon' or 'enemy'."""
    if lib is None:
        return set()
    try:
        items = lib.list_all()
        return {item.name for item in items}
    except Exception:
        return set()


def cross_validate_layers(
    l1_data: dict,
    l2_data: dict,
    l3_data: dict,
    weapon_lib=None,
    enemy_lib=None,
) -> CrossRefReport:
    """
    跨层引用验证。

    检查项：
    1. L1 perceptible.linked_interaction → L2 interactions[].name
    2. L2 encounters[].enemy_ref → enemy library
    3. L2 scene_weapons[].weapon_ref → weapon library
    4. L3 logic_chains[].branches[].condition 中引用的 flag 格式
    5. L3 scene_intents 的 key 与 L1/L2 场景名一致性
    """
    report = CrossRefReport()

    # ── 1. L1 → L2 引用检查 ──
    l2_interaction_names = _collect_interaction_names(l2_data)
    for scene_name, scene_data in l1_data.items():
        perceptibles = scene_data.get("perceptible", [])
        for i, p in enumerate(perceptibles):
            if not isinstance(p, dict):
                continue
            linked = p.get("linked_interaction")
            if linked:
                # 检查是否在任何场景的 interaction 中存在
                found = any(
                    linked in names
                    for names in l2_interaction_names.values()
                )
                if not found:
                    report.add(
                        "L1→L2",
                        f"{scene_name}.perceptible[{i}].linked_interaction",
                        f"引用的互动 '{linked}' 在 L2 中不存在",
                        "warning",
                    )

    # ── 2. L2 encounters → enemy library ──
    if enemy_lib is not None:
        enemy_names = _collect_library_names(enemy_lib, "enemy")
        if enemy_names:
            for scene_name, scene_data in l2_data.get("scenes", {}).items():
                encounters = scene_data.get("encounters", [])
                for i, enc in enumerate(encounters):
                    if not isinstance(enc, dict):
                        continue
                    ref = enc.get("enemy_ref", "")
                    if ref and ref not in enemy_names:
                        report.add(
                            "L2→Library",
                            f"{scene_name}.encounters[{i}].enemy_ref",
                            f"敌人 '{ref}' 不在敌人库中。可用：{sorted(enemy_names)}",
                            "error",
                        )

    # ── 3. L2 scene_weapons → weapon library ──
    if weapon_lib is not None:
        weapon_names = _collect_library_names(weapon_lib, "weapon")
        if weapon_names:
            for scene_name, scene_data in l2_data.get("scenes", {}).items():
                weapons = scene_data.get("scene_weapons", [])
                for i, sw in enumerate(weapons):
                    if not isinstance(sw, dict):
                        continue
                    ref = sw.get("weapon_ref", "")
                    if ref and ref not in weapon_names:
                        report.add(
                            "L2→Library",
                            f"{scene_name}.scene_weapons[{i}].weapon_ref",
                            f"武器 '{ref}' 不在武器库中。可用：{sorted(weapon_names)}",
                            "error",
                        )

    # ── 4. L3 scene_intents → L1/L2 场景 ──
    l1_scenes = set(l1_data.keys())
    l2_scenes = set(l2_data.get("scenes", {}).keys())
    all_scenes = l1_scenes | l2_scenes
    l3_intent_scenes = set(l3_data.get("scene_intents", {}).keys())
    if l3_intent_scenes and all_scenes:
        missing_in_l3 = all_scenes - l3_intent_scenes
        extra_in_l3 = l3_intent_scenes - all_scenes
        for s in missing_in_l3:
            report.add(
                "L3→L1/L2",
                f"scene_intents",
                f"场景 '{s}' 在 L1/L2 中存在但在 L3.scene_intents 中缺失",
                "warning",
            )
        for s in extra_in_l3:
            report.add(
                "L3→L1/L2",
                f"scene_intents",
                f"场景 '{s}' 在 L3.scene_intents 中存在但在 L1/L2 中不存在",
                "warning",
            )

    return report


def _get_pipeline_version() -> str:
    """返回管线版本标识（git HEAD commit hash），用于追溯生成模块的 prompt 版本。

    非 git 仓库时回退到文件修改时间的 MD5。
    """
    import hashlib
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        )
        if result.returncode == 0 and result.stdout.strip():
            return f"git:{result.stdout.strip()[:8]}"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    # Fallback: hash of the prompt source file modification time
    parser_path = os.path.join(os.path.dirname(__file__), "layered_parser.py")
    try:
        mtime = str(os.path.getmtime(parser_path))
        return f"mtime:{hashlib.md5(mtime.encode()).hexdigest()[:8]}"
    except OSError:
        return "unknown"




def _bind_npc_entities(interactions: list[dict], auto_triggers: list[dict],
                       npc_profiles: dict) -> tuple[list[dict], list[dict], dict]:
    """Scan entities for NPC name references -> strip from scene -> bind to NPC profile.
    Preserves entity IDs. Tags each bound entity with source_scene.
    """
    npc_names = set(npc_profiles.keys())
    if not npc_names:
        return interactions, auto_triggers, npc_profiles

    def _references_npc(entity: dict) -> str | None:
        fields = " ".join([
            entity.get("name", ""), entity.get("trigger", ""), entity.get("result", ""),
        ])
        for name in npc_names:
            if name in fields:
                return name
        return None

    def _is_follow_event(entity: dict) -> bool:
        combined = " ".join([
            entity.get("name", ""), entity.get("trigger", ""), entity.get("result", ""),
        ])
        follow_kw = ("跟随", "跟着", "加入队伍", "离开队伍", "开始跟随", "停止跟随")
        return any(kw in combined for kw in follow_kw)

    filtered_interactions = []
    filtered_auto_triggers = []

    for e in interactions:
        if _is_follow_event(e):
            continue
        npc_name = _references_npc(e)
        if npc_name:
            e_copy = dict(e)
            e_copy["source_scene"] = e.get("scene", "")
            npc_profiles.setdefault(npc_name, {})
            npc_profiles[npc_name].setdefault("bound_interactions", [])
            npc_profiles[npc_name]["bound_interactions"].append(e_copy)
        else:
            filtered_interactions.append(e)

    for e in auto_triggers:
        if _is_follow_event(e):
            continue
        npc_name = _references_npc(e)
        if npc_name:
            e_copy = dict(e)
            e_copy["source_scene"] = e.get("scene", "")
            npc_profiles.setdefault(npc_name, {})
            npc_profiles[npc_name].setdefault("bound_auto_triggers", [])
            npc_profiles[npc_name]["bound_auto_triggers"].append(e_copy)
        else:
            filtered_auto_triggers.append(e)

    return filtered_interactions, filtered_auto_triggers, npc_profiles


def _assemble_l2(interactions, events, auto_triggers, scene_movements, l1_data,
                 npc_profiles=None, boss_encounters=None) -> dict:
    """将 Step 3a 后的实体按场景分组组装为 L2 结构."""
    scenes: dict[str, dict] = {}
    for inter in interactions:
        sname = inter.get("scene", "")
        if sname:
            scenes.setdefault(sname, {"interactions": [], "auto_triggers": [],
                                        "encounters": [], "scene_weapons": [],
                                        "from_here": [], "to_here": [], "extra": {}})
            scenes[sname]["interactions"].append(inter)
    for at in auto_triggers:
        sname = at.get("scene", "")
        if sname:
            scenes.setdefault(sname, {"interactions": [], "auto_triggers": [],
                                        "encounters": [], "scene_weapons": [],
                                        "from_here": [], "to_here": [], "extra": {}})
            scenes[sname]["auto_triggers"].append(at)
    for sname, movement in scene_movements.items():
        scenes.setdefault(sname, {"interactions": [], "auto_triggers": [],
                                    "encounters": [], "scene_weapons": [],
                                    "from_here": [], "to_here": [], "extra": {}})
        scenes[sname]["from_here"] = movement.get("from_here", [])
        scenes[sname]["to_here"] = movement.get("to_here", [])
    for sname in scenes:
        l1_scene = l1_data.get(sname, {})
        scenes[sname]["description"] = l1_scene.get("entry_narrative", "") or l1_scene.get("atmosphere", "")
    return {
        "scenes": scenes,
        "events": events,
        "boss_encounters": boss_encounters if boss_encounters is not None else [],
        "npc_profiles": npc_profiles if npc_profiles is not None else {},
        "_pipeline_version": _get_pipeline_version(),
    }


# ═══════════════════════════════════════════════════════════════
#  管线
# ═══════════════════════════════════════════════════════════════

class PipelineResult:
    """管线执行结果."""
    def __init__(self):
        self.step1_data: dict = {}
        self.l1_data: dict = {}
        self.l2_data: dict = {}
        self.l3_data: dict = {}
        self.schema_reports: dict = {}
        self.cross_ref_report = None
        self.fallbacks: list[str] = []

    @property
    def all_valid(self) -> bool:
        schema_ok = all(r.is_valid for r in self.schema_reports.values()) if self.schema_reports else False
        cross_ok = self.cross_ref_report.is_valid if self.cross_ref_report else True
        return schema_ok and cross_ok

    def summary(self) -> str:
        lines = ["═══ 管线结果 ═══"]
        if self.fallbacks:
            lines.append(f"保底触发: {len(self.fallbacks)} 处")
            for fb in self.fallbacks:
                lines.append(f"  ⚠ {fb}")
        for layer, report in self.schema_reports.items():
            status = "PASS" if report.is_valid else "FAIL"
            lines.append(f"  Schema {layer}: {status} ({len(report.errors)} errors, {len(report.warnings)} warnings)")
        if self.cross_ref_report:
            status = "PASS" if self.cross_ref_report.is_valid else "FAIL"
            lines.append(f"  交叉引用: {status} ({len(self.cross_ref_report.issues)} issues)")
        return "\n".join(lines)


def run_pipeline(
    content: str,
    llm_json,
    llm_text=None,
    *,
    weapon_lib=None,
    enemy_lib=None,
    boss_lib=None,
    max_retries: int = PIPELINE_MAX_RETRIES,
    verbose: bool = True,
    inject_l3_wr0: bool = INJECT_L3_WR0,
) -> PipelineResult:
    """执行完整的四步渐进式解析管线."""
    from module_designer.layered_parser import (
        _with_fallback,
        parse_step1a, parse_step1b,
        parse_step2a, parse_step2b_events, parse_step2b_at,
        parse_step2c_l1, parse_step2c_l3,
        parse_step3a, parse_step3b, parse_step4,
        parse_step35, parse_step25,
        parse_step2_boss,
        _merge_phase2_fields, _slim_entity,
    )
    from concurrent.futures import ThreadPoolExecutor

    if llm_text is None:
        llm_text = llm_json

    result = PipelineResult()

    # Pre-extract library name lists for Step 1a (enemy/weapon constraint selection)
    weapon_names_step1 = []
    enemy_names_step1 = []
    try:
        if weapon_lib:
            weapon_names_step1 = [w.name for w in weapon_lib.list_all()]
    except Exception:
        pass
    try:
        if enemy_lib:
            enemy_names_step1 = [e.name for e in enemy_lib.list_all()]
    except Exception:
        pass

    # ── Step 1 ──────────────────────────────────────────────
    if verbose:
        print("═" * 50)
        print("[Step 1] 元信息提取 + 精修模组...")

    boss_names_step1 = []
    try:
        if boss_lib:
            boss_names_step1 = boss_lib.list_names()
    except Exception:
        pass

    def _do_step1a():
        return parse_step1a(content, llm_json, weapon_names_step1, enemy_names_step1, boss_names_step1)
    def _do_step1b():
        return parse_step1b(content, llm_text)

    with ThreadPoolExecutor(max_workers=2) as ex:
        f1a = ex.submit(lambda: _with_fallback(
            _do_step1a, ["scenes", "characters"],
            {"module_meta": {}, "scenes": [], "characters": []},
            max_retries, verbose, "Step 1a",
        ))
        f1b = ex.submit(lambda: _with_fallback(
            _do_step1b, ["condensed_text"],
            {"condensed_text": ""},
            max_retries, verbose, "Step 1b",
        ))
        step1a = f1a.result()
        step1b = f1b.result()

    scenes = step1a.get("scenes", [])
    characters = step1a.get("characters", [])
    condensed_text = step1b.get("condensed_text", "")
    from module_designer.layered_parser import _parse_condensed_chapters
    chapters = _parse_condensed_chapters(condensed_text) if condensed_text else {}

    result.step1_data = {
        "module_meta": step1a.get("module_meta", {}),
        "scenes": scenes,
        "characters": characters,
        "condensed_text": condensed_text,
    }
    if step1a.get("_fallback"):
        result.fallbacks.append("Step 1a")
    if step1b.get("_fallback"):
        result.fallbacks.append("Step 1b")

    if verbose:
        print(f"  Step 1 完成: {len(scenes)} 场景, {len(characters)} 角色")

    # ── Step 2a ──────────────────────────────────────────────
    if verbose:
        print("═" * 50)
        print("[Step 2a] Interactions 提取...")

    def _do_step2a():
        return parse_step2a(chapters, scenes, llm_json, characters=characters)
    step2a = _with_fallback(
        _do_step2a, ["interactions"],
        {"interactions": []},
        max_retries, verbose, "Step 2a",
    )
    interactions = step2a.get("interactions", [])
    scene_movements = step2a.get("scene_movements", {})
    if step2a.get("_fallback"):
        result.fallbacks.append("Step 2a")

    if verbose:
        print(f"  Step 2a 完成: {len(interactions)} interactions, {len(scene_movements)} 场景通行路径")

    # ── Step 2b + 2c ─────────────────────────────────────────
    if verbose:
        print("[Step 2b+2c] Events, Auto-triggers, L1, L3 (并行)...")

    def _do_events():
        return parse_step2b_events(chapters, scenes, interactions, llm_json, characters=characters)
    step1_enemies = step1a.get("enemies", [])
    step1_weapons = step1a.get("weapons", [])

    def _do_at():
        return parse_step2b_at(chapters, scenes, interactions, llm_json,
                               characters=characters, enemies=step1_enemies, weapons=step1_weapons)
    def _do_l1():
        return parse_step2c_l1(chapters, scenes, characters, llm_json)
    def _do_l3():
        step1_meta = step1a.get("module_meta", {})
        return parse_step2c_l3(chapters, scenes, characters, llm_json, step1_meta=step1_meta)

    with ThreadPoolExecutor(max_workers=4) as ex:
        f_ev = ex.submit(lambda: _with_fallback(
            _do_events, ["events"], {"events": []},
            max_retries, verbose, "Step 2b events",
        ))
        f_at = ex.submit(lambda: _with_fallback(
            _do_at, ["auto_triggers"], {"auto_triggers": []},
            max_retries, verbose, "Step 2b auto_triggers",
        ))
        f_l1 = ex.submit(lambda: _with_fallback(
            _do_l1, [], {},
            max_retries, verbose, "Step 2c L1",
        ))
        f_l3 = ex.submit(lambda: _with_fallback(
            _do_l3, ["world_rules", "driving_force"],
            {"world_rules": [], "driving_force": ""},
            max_retries, verbose, "Step 2c L3",
        ))
        events_data = f_ev.result()
        at_data = f_at.result()
        l1_data = f_l1.result()
        l3_data = f_l3.result()

    events = events_data.get("events", [])
    auto_triggers = at_data.get("auto_triggers", [])
    for fb_name, fb_data in [("Step 2b events", events_data),
                              ("Step 2b auto_triggers", at_data),
                              ("Step 2c L1", l1_data),
                              ("Step 2c L3", l3_data)]:
        if fb_data.get("_fallback"):
            result.fallbacks.append(fb_name)

    # ── L3 后处理: 注入 WR0（创作者豁免）──
    if inject_l3_wr0 and not l3_data.get("_fallback"):
        world_rules = l3_data.setdefault("world_rules", [])
        existing_ids = {wr.get("id", "") for wr in world_rules if isinstance(wr, dict)}
        if "WR0" not in existing_ids:
            wr0 = {
                "id": "WR0",
                "name": "创作者豁免",
                "rule": "所有世界规则只约束KP和玩家，模组创作者不受世界规则约束",
                "scope": "绝对全局",
                "is_absolute": "最高规则，高于所有其他世界规则",
            }
            world_rules.insert(0, wr0)
            if verbose:
                print("  [L3] WR0 已注入（创作者豁免）")

    if verbose:
        print(f"  Step 2b 完成: {len(events)} events, {len(auto_triggers)} auto_triggers")
        print(f"  Step 2c 完成: {len(l1_data)} L1 场景, {len(l3_data.get('world_rules',[]))} 世界规则")

    # ── Step 3a ∥ Step 2.5 (并行) ──────────────────────────────
    if verbose:
        print("═" * 50)
        print("[Step 3a + Step 2.5] L2 依赖解析 ∥ NPC 行为描述 (并行)...")

    def _do_step3a():
        ending_conditions = l3_data.get("ending_conditions", [])
        return parse_step3a(chapters, interactions, events, auto_triggers, ending_conditions, llm_json)

    def _do_step25():
        l3_characters = l3_data.get("characters", [])
        if not l3_characters:
            return {"npc_profiles": {}}
        return parse_step25(l3_characters, l1_data, interactions, auto_triggers, llm_json)

    with ThreadPoolExecutor(max_workers=2) as ex:
        f3a = ex.submit(lambda: _with_fallback(
            _do_step3a, ["interactions"],
            {"interactions": interactions, "events": events, "auto_triggers": auto_triggers},
            max_retries, verbose, "Step 3a",
        ))
        f25 = ex.submit(lambda: _with_fallback(
            _do_step25, ["npc_profiles"],
            {"npc_profiles": {}},
            max_retries, verbose, "Step 2.5",
        ))
        step3a = f3a.result()
        step25 = f25.result()

    interactions = step3a.get("interactions", interactions)
    events = step3a.get("events", events)
    auto_triggers = step3a.get("auto_triggers", auto_triggers)
    npc_profiles = step25.get("npc_profiles", {})

    interactions, auto_triggers, npc_profiles = _bind_npc_entities(
        interactions, auto_triggers, npc_profiles,
    )
    if verbose:
        bound_count = sum(
            len(p.get("bound_interactions", [])) + len(p.get("bound_auto_triggers", []))
            for p in npc_profiles.values()
        )
        print(f"  [NPC Bind] {bound_count} entities bound to NPCs")

    if step3a.get("_fallback"):
        result.fallbacks.append("Step 3a")
    if step25.get("_fallback"):
        result.fallbacks.append("Step 2.5")

    if verbose:
        print(f"  Step 3a 完成: 去重 + 冲突解决 + 结局验证")
        print(f"  Step 2.5 完成: {len(npc_profiles)} NPC profiles")

    # ── 生成 Boss Encounter（如果 Step 1 识别到了 Boss）──
    boss_hints = step1a.get("boss_encounters", [])
    if boss_hints:
        boss_library_names = []
        try:
            if boss_lib:
                boss_library_names = boss_lib.list_names()
        except Exception:
            pass
        step2_boss = parse_step2_boss(
            boss_hints, boss_library_names,
            interactions, auto_triggers, scenes, chapters,
            llm_json,
        )
        boss_encounters_data = step2_boss.get("boss_encounters", [])
    else:
        boss_encounters_data = []

    # ── 组装 L2 结构 ──
    l2_assembled = _assemble_l2(interactions, events, auto_triggers, scene_movements, l1_data,
                                npc_profiles=npc_profiles, boss_encounters=boss_encounters_data)
    result.l2_data = l2_assembled

    # Extract flat lists from assembled L2 for Step 3.5/4
    step35_interactions = []
    step35_at = []
    for sdata in l2_assembled.get("scenes", {}).values():
        step35_interactions.extend(sdata.get("interactions", []))
        step35_at.extend(sdata.get("auto_triggers", []))
    step35_events = l2_assembled.get("events", [])

    # ── Step 3b ──────────────────────────────────────────────
    if verbose:
        print("[Step 3b] L1 ↔ L2 交叉核对...")

    def _do_step3b():
        return parse_step3b(chapters, l1_data, l2_assembled, l3_data, scenes, llm_json)
    step3b = _with_fallback(
        _do_step3b, ["l1_data"],
        {"l1_data": l1_data, "l3_data": l3_data},
        max_retries, verbose, "Step 3b",
    )
    l1_data = step3b.get("l1_data", l1_data)
    l3_data = step3b.get("l3_data", l3_data)
    if step3b.get("_fallback"):
        result.fallbacks.append("Step 3b")

    # ── L3 后处理: 重新确保 WR0（Step 3b 可能丢失）──
    if inject_l3_wr0:
        world_rules = l3_data.setdefault("world_rules", [])
        existing_ids = {wr.get("id", "") for wr in world_rules if isinstance(wr, dict)}
        if "WR0" not in existing_ids:
            wr0 = {
                "id": "WR0",
                "name": "创作者豁免",
                "rule": "所有世界规则只约束KP和玩家，模组创作者不受世界规则约束",
                "scope": ["meta"],
                "is_absolute": True,
            }
            world_rules.insert(0, wr0)

    # ── Step 3.5 ──────────────────────────────────────────────
    if verbose:
        print("═" * 50)
        print("[Step 3.5] 依赖图构建...")

    stat_names = ["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "SAN", "HP", "LUCK", "MP"]

    l2_descriptions = {}
    for name, sdata in l1_data.items():
        desc = sdata.get("description", "") or sdata.get("atmosphere", "") or sdata.get("entry_narrative", "")
        if desc:
            l2_descriptions[name] = desc

    skill_names = []
    try:
        import os as _os
        skill_path = _os.path.join(_os.path.dirname(__file__), "..", "..", "data", "skill_checks.json")
        with open(skill_path, "r", encoding="utf-8") as _f:
            skill_checks = json.load(_f)
            skill_names = sorted(set(s["name"] for s in skill_checks))
    except Exception:
        pass

    from module_designer.dependency_graph import DependencyGraph

    def _do_step35():
        """Step 3.5: LLM 解析 → 有向图 → 循环检测."""
        max_tries = 3
        for attempt in range(1, max_tries + 1):
            step35_result = parse_step35(chapters, step35_interactions, step35_events, step35_at, llm_json)
            deps = step35_result.get("dependencies", [])
            if not deps:
                if attempt < max_tries:
                    if verbose:
                        print(f"  [Step 3.5] 第 {attempt} 次解析为空，重试...")
                    continue
                return {"graph": None, "dependencies": []}

            graph = DependencyGraph()
            graph.build(deps)
            cycles = graph.detect_cycles()
            if not cycles:
                if verbose:
                    print(f"  [Step 3.5] 依赖图: {len(graph.nodes)} 节点, {len(graph.edges)} 边, 无循环")
                return {"graph": graph, "dependencies": deps}

            if attempt < max_tries:
                if verbose:
                    cycle_ids = [str(p[0]) for p in cycles[:3]]
                    print(f"  [Step 3.5] 第 {attempt} 次检测到 {len(cycles)} 个循环 ({cycle_ids}...)，重调 LLM...")
                continue

        if verbose:
            print(f"  [Step 3.5] 重调用尽，随机切断一条循环边")
        graph.cut_random_edge_in_cycles()
        return {"graph": graph, "dependencies": deps, "_circular_cut": True}

    step35_result = _do_step35()

    dep_graph = step35_result.get("graph")
    if dep_graph:
        result.l2_data["dependency_graph"] = dep_graph.to_dict()
    if step35_result.get("_circular_cut"):
        result.fallbacks.append("Step 3.5 (circular cut)")

    # Enemy/weapon constraints now come from Step 1a (merged Phase 1)
    phase1_clean = {"enemies": step1a.get("enemies", []),
                    "weapons": step1a.get("weapons", [])}

    if verbose:
        print(f"  Step 1a 约束: {len(phase1_clean.get('enemies',[]))} 敌人类型, {len(phase1_clean.get('weapons',[]))} 武器类型")

    # ── Phase 2 (串行，依赖 Phase 1 约束) ─────────────────────
    if verbose:
        print("[Phase 2] 精简标准化...")

    def _do_phase2():
        return parse_step4(
            step35_interactions, step35_at, l2_descriptions,
            l3_data.get("scene_intents", {}), chapters,
            phase1_clean, skill_names, stat_names, llm_json,
        )

    phase2_result = _with_fallback(
        _do_phase2, ["interactions"],
        {"interactions": step35_interactions, "auto_triggers": step35_at},
        max_retries, verbose, "Phase 2",
    )

    # Merge Phase 2 standardized fields back into complete originals
    p2_interactions = phase2_result.get("interactions", step35_interactions)
    p2_auto_triggers = phase2_result.get("auto_triggers", step35_at)
    interactions = _merge_phase2_fields(step35_interactions, p2_interactions)
    auto_triggers = _merge_phase2_fields(step35_at, p2_auto_triggers)
    if phase2_result.get("_fallback"):
        result.fallbacks.append("Phase 2")

    # Strip based_on from all entities
    for e in interactions:
        e.pop("based_on", None)
    for e in auto_triggers:
        e.pop("based_on", None)
    for e in step35_events:
        e.pop("based_on", None)

    # Re-assemble L2 with Phase 2 standardized entities
    l2_assembled.clear()
    l2_assembled.update(_assemble_l2(interactions, events, auto_triggers, scene_movements, l1_data,
                                     npc_profiles=npc_profiles, boss_encounters=boss_encounters_data))
    if dep_graph:
        l2_assembled["dependency_graph"] = dep_graph.to_dict()
    l2_assembled["_phase1"] = {"enemies": phase1_result.get("enemies", []),
                                "weapons": phase1_result.get("weapons", [])}

    # ── 最终: Schema 验证 + Cross-validate ─────────────────
    if verbose:
        print("═" * 50)
        print("[Final] Schema 验证 + 交叉引用检查...")

    result.schema_reports = validate_all(l1_data, l2_assembled, l3_data)

    result.cross_ref_report = cross_validate_layers(
        l1_data, l2_assembled, l3_data,
        weapon_lib=weapon_lib, enemy_lib=enemy_lib,
    )

    result.l1_data = l1_data
    result.l3_data = l3_data
    result.l2_data = l2_assembled

    if verbose:
        print(result.summary())

    return result


def save_pipeline_result(result: PipelineResult, module_dir: str) -> None:
    """将管线结果保存到模块目录."""
    os.makedirs(module_dir, exist_ok=True)

    # L1
    path = os.path.join(module_dir, "l1_player.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result.l1_data, f, ensure_ascii=False, indent=2)
    print(f"  L1 → {path}")

    # L2 — already assembled
    path = os.path.join(module_dir, "l2_keeper.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result.l2_data, f, ensure_ascii=False, indent=2)
    print(f"  L2 → {path}")

    # L3
    path = os.path.join(module_dir, "l3_designer.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result.l3_data, f, ensure_ascii=False, indent=2)
    print(f"  L3 → {path}")
