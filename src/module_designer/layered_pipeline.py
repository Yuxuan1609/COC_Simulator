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
from utils import load_skill_config

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
    spell_lib=None,
    item_lib=None,
) -> CrossRefReport:
    """
    跨层引用验证。

    检查项：
    1. L1 perceptible.linked_interaction -> L2 interactions[].name
    2. L2 encounters[].enemy_ref -> enemy library
    3. L2 scene_weapons[].weapon_ref -> weapon library
    4. L3 logic_chains[].branches[].condition 中引用的 flag 格式
    5. L3 scene_intents 的 key 与 L1/L2 场景名一致性
    6. L2 side_effects @grant_spell.spell_ref -> spell library（统一资源层）
    7. entity id 跨场景唯一性（error）
    8. markup 内 flag/ref 引用存在性（error）
    9. npc_profiles 场景引用存在性（error）
    10. ending_conditions 引用的 flag/实体存在（error）
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
    # ── 统一资源层：L2 side_effects @grant_spell -> spell library ──
    if spell_lib is not None:
        import re as _re
        for scene_name, scene_data in l2_data.get("scenes", {}).items():
            entities = (scene_data.get("interactions", [])
                        + scene_data.get("auto_triggers", []))
            for ent in entities:
                if not isinstance(ent, dict):
                    continue
                for se in (ent.get("side_effects") or []):
                    m = _re.search(r'spell_ref="([^"]+)"', str(se))
                    if m and not spell_lib.get(m.group(1)):
                        report.add(
                            "L2->Library",
                            f"{scene_name}.{ent.get('id', '?')}.side_effects",
                            f"@grant_spell 引用未知法术: {m.group(1)}",
                            "warning",
                        )

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

    # ── 7. entity id 跨场景唯一性 ──
    id_places: dict[str, list[str]] = {}
    known_entities: set[str] = set()
    for scene_name, kind, ent in _iter_l2_entities(l2_data):
        eid = ent.get("id") or ""
        ename = ent.get("name") or ""
        if eid:
            id_places.setdefault(eid, []).append(scene_name or kind)
            known_entities.add(eid)
        if ename:
            known_entities.add(ename)
    for eid, places in id_places.items():
        if len(places) > 1:
            report.add(
                "L2",
                f"entity[{eid}]",
                f"entity id「{eid}」在场景 {'/'.join(places)} 重复定义",
                "error",
            )

    # ── 8. markup 内 flag/ref 引用存在性 ──
    import re as _re_lint
    for scene_name, kind, ent in _iter_l2_entities(l2_data):
        for se in (ent.get("side_effects") or []):
            for m in _re_lint.finditer(r'(\w+)="([^"]+)"', str(se)):
                key, val = m.group(1), m.group(2)
                if key in ("flag", "ref") and val and val not in known_entities:
                    label = "flag" if key == "flag" else "实体"
                    report.add(
                        "L2",
                        f"{scene_name or kind}.{ent.get('id', '?')}.side_effects",
                        f"引用不存在的{label}「{val}」",
                        "error",
                    )

    # ── 9. npc_profiles 场景引用 ──
    npc_profiles = l2_data.get("npc_profiles") or {}
    if isinstance(npc_profiles, dict):
        for npc_name, profile in npc_profiles.items():
            if not isinstance(profile, dict):
                continue
            scene = profile.get("scene") or ""
            if scene and scene not in all_scenes:
                report.add(
                    "L2→L1/L2",
                    f"npc_profiles.{npc_name}.scene",
                    f"NPC '{npc_name}' 引用不存在的场景 '{scene}'",
                    "error",
                )
            for s in profile.get("all_scenes") or []:
                if s and s not in all_scenes:
                    report.add(
                        "L2→L1/L2",
                        f"npc_profiles.{npc_name}.all_scenes",
                        f"NPC '{npc_name}' 引用不存在的场景 '{s}'",
                        "error",
                    )

    # ── 10. ending_conditions 引用的 flag/实体 ──
    _id_tok = _re_lint.compile(r"\b(?:IT|AT|I|E|END|BOSS)_[A-Z0-9_]+\b")
    for i, ec in enumerate(l3_data.get("ending_conditions") or []):
        if not isinstance(ec, dict):
            continue
        refs = []
        for key in ("flag", "entity_id", "entity", "ref"):
            val = ec.get(key)
            if val:
                refs.append(val)
        flags = ec.get("flags")
        if isinstance(flags, list):
            refs.extend(f for f in flags if f)
        cond = str(ec.get("condition") or "")
        own_id = ec.get("id") or ""
        for tok in _id_tok.findall(cond):
            if tok != own_id:
                refs.append(tok)
        for ref in refs:
            if ref not in known_entities:
                report.add(
                    "L3",
                    f"ending_conditions[{i}]",
                    f"结局引用不存在的 flag/实体「{ref}」",
                    "error",
                )

    return report


def _iter_l2_entities(l2_data: dict):
    """Yield (scene_name, kind, entity_dict) for interactions/auto_triggers/events."""
    for scene_name, scene_data in l2_data.get("scenes", {}).items():
        if not isinstance(scene_data, dict):
            continue
        for kind in ("interactions", "auto_triggers"):
            for ent in scene_data.get(kind) or []:
                if isinstance(ent, dict):
                    yield scene_name, kind, ent
    for ent in l2_data.get("events") or []:
        if isinstance(ent, dict):
            yield "", "events", ent


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
                       npc_profiles: dict,
                       entity_bindings: dict | None = None) -> tuple[list[dict], list[dict], dict]:
    """Scan entities for NPC ownership -> strip from scene -> bind to NPC profile.
    Preserves entity IDs. Tags each bound entity with source_scene.

    If entity_bindings is provided (LLM output from Step 2.5b), use it as the
    source of truth for NPC ownership. Fall back to deterministic substring
    matching when bindings is None.
    """
    npc_names = set(npc_profiles.keys())
    if not npc_names:
        return interactions, auto_triggers, npc_profiles

    def _references_npc(entity: dict) -> str | None:
        """Only used as fallback when entity_bindings is not provided."""
        fields = " ".join([
            entity.get("name", ""), entity.get("trigger", ""), entity.get("result", ""),
        ])
        for name in npc_names:
            if name in fields:
                return name
        return None



    filtered_interactions = []
    filtered_auto_triggers = []

    for e in interactions:
        eid = e.get("id", "")
        if entity_bindings and eid in entity_bindings:
            npc_name = entity_bindings[eid]
        else:
            npc_name = _references_npc(e) if entity_bindings is None else None
        if npc_name and npc_name in npc_names:
            e_copy = dict(e)
            e_copy["source_scene"] = e.get("scene", "")
            npc_profiles.setdefault(npc_name, {})
            npc_profiles[npc_name].setdefault("bound_interactions", [])
            npc_profiles[npc_name]["bound_interactions"].append(e_copy)
        else:
            filtered_interactions.append(e)

    for e in auto_triggers:
        eid = e.get("id", "")
        if entity_bindings and eid in entity_bindings:
            npc_name = entity_bindings[eid]
        else:
            npc_name = _references_npc(e) if entity_bindings is None else None
        if npc_name and npc_name in npc_names:
            e_copy = dict(e)
            e_copy["source_scene"] = e.get("scene", "")
            npc_profiles.setdefault(npc_name, {})
            npc_profiles[npc_name].setdefault("bound_auto_triggers", [])
            npc_profiles[npc_name]["bound_auto_triggers"].append(e_copy)
        else:
            filtered_auto_triggers.append(e)

    return filtered_interactions, filtered_auto_triggers, npc_profiles


def _extract_entity_bindings(npc_profiles: dict) -> dict[str, str]:
    """从 npc_profiles 的 bound_entities 字段提取 entity→NPC 绑定映射。"""
    bindings = {}
    for npc_name, profile in npc_profiles.items():
        for eid in profile.pop("bound_entities", []):
            bindings[eid] = npc_name
    return bindings


def _inject_step1a_meta(npc_profiles: dict, step1a_characters: list[dict],
                        verbose: bool = False) -> None:
    """从 Step 1a characters 注入 scene 到 npc_profiles。can_follow / follow_requirements 由 Step 2.5 自主产出，不覆盖。"""
    char_meta = {
        c["name"]: {
            "scenes": c.get("scenes", []),
        }
        for c in step1a_characters if isinstance(c, dict)
    }
    for npc_name, profile in npc_profiles.items():
        meta = char_meta.get(npc_name, {})
        if meta.get("scenes"):
            profile["scene"] = meta["scenes"][0]
            profile["all_scenes"] = list(meta["scenes"])
    if verbose and char_meta:
        assigned = sum(1 for p in npc_profiles.values() if p.get("scene"))
        print(f"  [NPC Scene] {assigned}/{len(npc_profiles)} NPCs assigned scene from Step 1a")


def _inject_npc_special_entities(interactions: list[dict], npc_profiles: dict,
                                  verbose: bool = False) -> None:
    """为每个 NPC 注入 follow_unlock 和 interact_unlock 特殊 entity。
    这些 entity 的 extra 中带有 npc_special 标记，运行时 Judge 走特殊路径（直接修改 NPC 状态，不走 dependency graph）。
    requirement 格式与普通 entity 一致（|| 前硬性 entity ID，|| 后软性自然语言），由 _build_entity_lines 做硬性评估 + Parse 做软性评估。"""
    existing_ids = {e.get("id") for e in interactions}
    for npc_name, profile in npc_profiles.items():
        # ── Follow unlock entity ──
        if profile.get("can_follow"):
            follow_id = f"NPC_FOLLOW_UNLOCK_{npc_name}"
            if follow_id not in existing_ids:
                follow_req = profile.get("follow_requirements", "")
                interactions.append({
                    "id": follow_id,
                    "scene": profile.get("scene", ""),
                    "name": f"请求{npc_name}跟随",
                    "type": "无",
                    "trigger": f"你请求{npc_name}跟随你一起行动",
                    "result": f"{npc_name}开始跟随你",
                    "side_effects": [],
                    "difficulty": "None",
                    "requirement": follow_req if follow_req else "",
                    "extra": {"npc_special": "follow_unlock", "npc_name": npc_name},
                })
                existing_ids.add(follow_id)
                if verbose:
                    print(f"  [NPC Special] 注入 {follow_id} (follow_unlock) req={follow_req[:60] if follow_req else '无条件'}")

        # ── Interact unlock entity ──
        if not profile.get("can_interact", True):
            interact_id = f"NPC_INTERACT_UNLOCK_{npc_name}"
            if interact_id not in existing_ids:
                interact_req = profile.get("interact_requirements", "")
                interactions.append({
                    "id": interact_id,
                    "scene": profile.get("scene", ""),
                    "name": f"与{npc_name}建立对话",
                    "type": "无",
                    "trigger": f"你尝试与{npc_name}交谈",
                    "result": f"{npc_name}愿意与你交谈了",
                    "side_effects": [],
                    "difficulty": "None",
                    "requirement": interact_req if interact_req else "",
                    "extra": {"npc_special": "interact_unlock", "npc_name": npc_name},
                })
                existing_ids.add(interact_id)
                if verbose:
                    print(f"  [NPC Special] 注入 {interact_id} (interact_unlock) req={interact_req[:60] if interact_req else '无条件'}")


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
        scenes[sname]["description"] = l1_scene.get("description", "") or l1_scene.get("atmosphere", "")
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
    item_lib=None,
    spell_lib=None,
    max_retries: int = PIPELINE_MAX_RETRIES,
    verbose: bool = True,
    inject_l3_wr0: bool = INJECT_L3_WR0,
) -> PipelineResult:
    """执行完整的四步渐进式解析管线."""
    from module_designer.layered_parser import (
        _with_fallback,
        parse_step1a, parse_step1b,
        parse_step2a, parse_step2b_combined,
        parse_step2c_l1, parse_step2c_l3,
        parse_step3a, parse_step3b, parse_step4,
        parse_step35, parse_step25_combined,
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
    item_names_step1 = None
    spell_names_step1 = None
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
    try:
        if item_lib:
            item_names_step1 = [f"{i.name}（{i.category}）：{i.description[:30]}"
                                for i in item_lib.list_all()]
    except Exception:
        pass
    try:
        if spell_lib:
            spell_names_step1 = [f"{s.id} {s.name}（{s.category}）：{s.description[:30]}"
                                 for s in spell_lib.list_all()]
    except Exception:
        pass

    # Pre-load skill names for Step 2a type whitelist
    skill_names_all = []
    try:
        skill_names_all = sorted(set(s["name"] for s in load_skill_config()["skills"]))
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
        return parse_step1a(content, llm_json, weapon_names_step1, enemy_names_step1, boss_names_step1,
                            item_names=item_names_step1, spell_names=spell_names_step1)
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
        return parse_step2a(chapters, scenes, llm_json, characters=characters, skill_names=skill_names_all)
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
        print("[Step 2b+2c] Events+AT (合并), L1, L3 (并行)...")

    def _do_step2b():
        step1_enemies = step1a.get("enemies", [])
        step1_weapons = step1a.get("weapons", [])
        return parse_step2b_combined(chapters, scenes, interactions, llm_json,
                                      characters=characters, enemies=step1_enemies,
                                      weapons=step1_weapons)
    def _do_l1():
        return parse_step2c_l1(chapters, scenes, characters, llm_json)
    def _do_l3():
        step1_meta = step1a.get("module_meta", {})
        return parse_step2c_l3(chapters, scenes, characters, llm_json, step1_meta=step1_meta)

    with ThreadPoolExecutor(max_workers=3) as ex:
        f_2b = ex.submit(lambda: _with_fallback(
            _do_step2b, ["events", "auto_triggers"],
            {"events": [], "auto_triggers": []},
            max_retries, verbose, "Step 2b",
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
        step2b_data = f_2b.result()
        l1_data = f_l1.result()
        l3_data = f_l3.result()

    events = step2b_data.get("events", [])
    auto_triggers = step2b_data.get("auto_triggers", [])
    for fb_name, fb_data in [("Step 2b", step2b_data),
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

    # ── Step 3a ∥ Step 2.5 (并行) ─────────────────
    if verbose:
        print("═" * 50)
        print("[Step 3a + Step 2.5] L2 依赖解析 ∥ NPC 档案+实体归属 (并行)...")

    def _do_step3a():
        ending_conditions = l3_data.get("ending_conditions", [])
        return parse_step3a(chapters, interactions, events, auto_triggers, ending_conditions, llm_json)

    def _do_step25():
        l3_characters = l3_data.get("characters", [])
        if not l3_characters:
            return {"npc_profiles": {}}
        step1_characters = step1a.get("characters", [])
        return parse_step25_combined(l3_characters, l1_data, interactions, auto_triggers,
                                      llm_json, step1a_characters=step1_characters)

    n_workers = 1 + (1 if l3_data.get("characters") else 0)
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
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

    entity_bindings = _extract_entity_bindings(npc_profiles)

    _inject_step1a_meta(npc_profiles, step1a.get("characters", []), verbose)

    interactions, auto_triggers, npc_profiles = _bind_npc_entities(
        interactions, auto_triggers, npc_profiles,
        entity_bindings=entity_bindings if entity_bindings else None,
    )
    if verbose:
        bound_count = sum(
            len(p.get("bound_interactions", [])) + len(p.get("bound_auto_triggers", []))
            for p in npc_profiles.values()
        )
        bind_source = "LLM" if entity_bindings else "deterministic"
        print(f"  [NPC Bind] {bound_count} entities bound to NPCs ({bind_source})")

    if step3a.get("_fallback"):
        result.fallbacks.append("Step 3a")
    if step25.get("_fallback"):
        result.fallbacks.append("Step 2.5")

    if verbose:
        print(f"  Step 3a 完成: 去重 + 冲突解决 + 结局验证")
        print(f"  Step 2.5 完成: {len(npc_profiles)} NPC profiles")

    _inject_npc_special_entities(interactions, npc_profiles, verbose)

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

    stat_names = ["STR", "CON", "DEX", "APP", "INT", "POW", "EDU", "SAN", "HP", "LUCK", "MP"]

    l2_descriptions = {}
    for name, sdata in l1_data.items():
        desc = sdata.get("description", "") or sdata.get("atmosphere", "")
        if desc:
            l2_descriptions[name] = desc

    skill_names = []
    try:
        skill_names = sorted(set(s["name"] for s in load_skill_config()["skills"]))
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
            npc_profiles=npc_profiles,
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
    l2_assembled["_phase1"] = {"enemies": phase1_clean.get("enemies", []),
                                "weapons": phase1_clean.get("weapons", [])}

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
    # Auto-populate start_scene if not already set
    if "start_scene" not in result.l3_data or not result.l3_data["start_scene"]:
        # Derive from L2 scenes (first key) or L3 scene_intents (first key)
        l3_si = result.l3_data.get("scene_intents", {})
        l2_scenes = result.l2_data.get("scenes", {})
        candidates = []
        if isinstance(l3_si, dict) and l3_si:
            candidates.append(next(iter(l3_si.keys())))
        if isinstance(l2_scenes, dict) and l2_scenes:
            first = next(iter(l2_scenes.keys()))
            if first not in candidates:
                candidates.append(first)
        if candidates:
            result.l3_data["start_scene"] = candidates[0]
    path = os.path.join(module_dir, "l3_designer.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result.l3_data, f, ensure_ascii=False, indent=2)
    print(f"  L3 → {path}")
