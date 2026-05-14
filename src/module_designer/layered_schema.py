"""三层 JSON Schema 定义 + 验证."""
from __future__ import annotations
from typing import List, Optional


# ═══════════════════════════════════════════════════════════════
#  L1 玩家可见层 Schema
# ═══════════════════════════════════════════════════════════════

L1_MOODS = {"confused", "uneasy", "tense", "terrified", "hopeful", "desperate"}
L1_PERCEPTIBLE_TYPES = {"object", "sound", "smell", "sight", "touch", "intuition"}

L1_PERCEPTIBLE_SCHEMA = {
    "type": {"required": True, "values": L1_PERCEPTIBLE_TYPES},
    "name": {"required": True},
    "brief": {"required": True},
    "linked_interaction": {"required": False},
}

L1_NPC_APPEARANCE_SCHEMA = {
    "name": {"required": True},
    "brief": {"required": True},
    "demeanor": {"required": False},
}

L1_SCENE_SCHEMA = {
    "entry_narrative": {"required": False},
    "atmosphere": {"required": False},
    "mood": {"required": False, "values": L1_MOODS},
    "perceptible": {"required": False, "list_of": L1_PERCEPTIBLE_SCHEMA},
    "ambient_hints": {"required": False},
    "npc_appearances": {"required": False, "list_of": L1_NPC_APPEARANCE_SCHEMA},
}


# ═══════════════════════════════════════════════════════════════
#  L2 KP 守秘人层 Schema
# ═══════════════════════════════════════════════════════════════

L2_DIFFICULTIES = {"regular", "hard", "extreme"}

L2_INTERACTION_SCHEMA = {
    "type": {"required": True},
    "name": {"required": True},
    "requirement": {"required": False},
    "trigger": {"required": False},
    "result": {"required": False},
    "clue": {"required": False},
    "side_effects": {"required": False},
    "skill_name": {"required": False},
    "difficulty": {"required": False, "values": L2_DIFFICULTIES},
}

L2_ENCOUNTER_SCHEMA = {
    "enemy_ref": {"required": True},
    "trigger_condition": {"required": False},
    "initial_behavior": {"required": False},
    "quantity": {"required": False},
    "notes": {"required": False},
    "extra": {"required": False},
}

L2_SCENE_WEAPON_SCHEMA = {
    "weapon_ref": {"required": True},
    "location": {"required": False},
    "discovery_method": {"required": False},
    "extra": {"required": False},
}

L2_HIDDEN_INFO_SCHEMA = {
    "info": {"required": True},
    "trigger_condition": {"required": True},
    "reveal_narrative": {"required": False},
    "linked_skill": {"required": False},
    "extra": {"required": False},
}

L2_EVENT_SCHEMA = {
    "id": {"required": True},
    "name": {"required": True},
    "trigger": {"required": False},
    "irreversible_impact": {"required": False},
    "requirement": {"required": False},
    "extra": {"required": False},
}

L2_NPC_PROFILE_SCHEMA = {
    "name": {"required": True},
    "role": {"required": False},
    "motivation": {"required": False},
    "knowledge": {"required": False},
    "personality": {"required": False},
    "voice_notes": {"required": False},
    "notes": {"required": False},
    "extra": {"required": False},
}

L2_SCENE_SCHEMA = {
    "description": {"required": False},
    "from_here": {"required": False},
    "to_here": {"required": False},
    "interactions": {"required": False, "list_of": L2_INTERACTION_SCHEMA},
    "encounters": {"required": False, "list_of": L2_ENCOUNTER_SCHEMA},
    "scene_weapons": {"required": False, "list_of": L2_SCENE_WEAPON_SCHEMA},
    "hidden_info": {"required": False, "list_of": L2_HIDDEN_INFO_SCHEMA},
    "extra": {"required": False},
}


# ═══════════════════════════════════════════════════════════════
#  L3 设计者层 Schema
# ═══════════════════════════════════════════════════════════════

L3_MODULE_META_SCHEMA = {
    "title": {"required": False},
    "author": {"required": False},
    "era": {"required": False},
    "theme": {"required": False},
    "expected_duration": {"required": False},
    "player_count": {"required": False},
}

L3_WORLD_RULE_SCHEMA = {
    "id": {"required": True},
    "name": {"required": True},
    "rule": {"required": True},
    "scope": {"required": False},
    "is_absolute": {"required": False},
}

L3_SCENE_INTENT_SCHEMA = {
    "purpose": {"required": False},
    "key_threat": {"required": False},
    "notes": {"required": False},
}

L3_ENDING_CONDITION_SCHEMA = {
    "id": {"required": True},
    "condition": {"required": False},
    "narrative": {"required": False},
}

L3_TONE_CONSTRAINTS_SCHEMA = {
    "genre": {"required": False},
    "forbidden": {"required": False},
    "recommended": {"required": False},
    "narrative_style": {"required": False},
}

L3_TOP_SCHEMA = {
    "module_meta": {"required": False, "nested": L3_MODULE_META_SCHEMA},
    "world_rules": {"required": False, "list_of": L3_WORLD_RULE_SCHEMA},
    "scene_intents": {"required": False},
    "ending_conditions": {"required": False, "list_of": L3_ENDING_CONDITION_SCHEMA},
    "tone_constraints": {"required": False, "nested": L3_TONE_CONSTRAINTS_SCHEMA},
    "driving_force": {"required": False},
}


# ═══════════════════════════════════════════════════════════════
#  验证引擎
# ═══════════════════════════════════════════════════════════════

class SchemaViolation:
    """单条验证违规."""
    def __init__(self, path: str, message: str, severity: str = "error"):
        self.path = path
        self.message = message
        self.severity = severity  # error / warning / info

    def __repr__(self):
        return f"[{self.severity}] {self.path}: {self.message}"


class SchemaReport:
    """验证报告."""
    def __init__(self):
        self.violations: List[SchemaViolation] = []

    def add(self, path: str, message: str, severity: str = "error"):
        self.violations.append(SchemaViolation(path, message, severity))

    @property
    def errors(self) -> List[SchemaViolation]:
        return [v for v in self.violations if v.severity == "error"]

    @property
    def warnings(self) -> List[SchemaViolation]:
        return [v for v in self.violations if v.severity == "warning"]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        if not self.violations:
            return "验证通过，无问题。"
        lines = [f"验证完成：{len(self.errors)} 错误, {len(self.warnings)} 警告"]
        for v in self.violations:
            lines.append(f"  {v}")
        return "\n".join(lines)

    def __bool__(self):
        return self.is_valid


def _validate_value(data: dict, field: str, rules: dict, path: str, report: SchemaReport):
    """验证单个字段的值是否符合 schema 规则."""
    value = data.get(field)

    # 必填检查
    if rules.get("required") and (value is None or (isinstance(value, str) and value == "")):
        report.add(f"{path}.{field}", f"必填字段缺失", "warning")
        return

    if value is None:
        return

    # 枚举值检查
    if "values" in rules and isinstance(value, str):
        if value not in rules["values"]:
            report.add(
                f"{path}.{field}",
                f"'{value}' 不是有效值，允许：{rules['values']}",
                "warning",
            )

    # 嵌套对象检查
    if "nested" in rules and isinstance(value, dict):
        _validate_object(value, rules["nested"], f"{path}.{field}", report)

    # 列表元素检查
    if "list_of" in rules and isinstance(value, list):
        for i, item in enumerate(value):
            if isinstance(item, dict):
                _validate_object(item, rules["list_of"], f"{path}.{field}[{i}]", report)


def _validate_object(data: dict, schema: dict, path: str, report: SchemaReport):
    """验证一个 dict 是否符合 object schema."""
    if not isinstance(data, dict):
        report.add(path, f"应为对象，实际类型：{type(data).__name__}", "error")
        return
    for field, rules in schema.items():
        _validate_value(data, field, rules, path, report)


def validate_l1(data: dict) -> SchemaReport:
    """验证 L1 JSON 数据（顶层为 {scene_name: SceneL1, ...}）."""
    report = SchemaReport()
    if not isinstance(data, dict):
        report.add("L1", "L1 数据应为 dict（scene_name → SceneL1）", "error")
        return report
    for scene_name, scene_data in data.items():
        if not isinstance(scene_data, dict):
            report.add(f"L1.{scene_name}", "场景数据应为 dict", "error")
            continue
        _validate_object(scene_data, L1_SCENE_SCHEMA, f"L1.{scene_name}", report)
    return report


def validate_l2(data: dict) -> SchemaReport:
    """验证 L2 JSON 数据（顶层 scenes + events + npc_profiles）."""
    report = SchemaReport()
    if not isinstance(data, dict):
        report.add("L2", "L2 数据应为 dict", "error")
        return report

    # 验证 scenes
    scenes = data.get("scenes", {})
    if not isinstance(scenes, dict):
        report.add("L2.scenes", "scenes 应为 dict", "error")
    else:
        for scene_name, scene_data in scenes.items():
            if not isinstance(scene_data, dict):
                report.add(f"L2.scenes.{scene_name}", "场景数据应为 dict", "error")
                continue
            _validate_object(scene_data, L2_SCENE_SCHEMA, f"L2.scenes.{scene_name}", report)

    # 验证 events
    events = data.get("events", [])
    if not isinstance(events, list):
        report.add("L2.events", "events 应为 list", "error")
    else:
        for i, ev in enumerate(events):
            if not isinstance(ev, dict):
                report.add(f"L2.events[{i}]", "事件数据应为 dict", "error")
                continue
            _validate_object(ev, L2_EVENT_SCHEMA, f"L2.events[{i}]", report)

    # 验证 npc_profiles
    npc_profiles = data.get("npc_profiles", {})
    if isinstance(npc_profiles, dict):
        for npc_name, npc_data in npc_profiles.items():
            if not isinstance(npc_data, dict):
                report.add(f"L2.npc_profiles.{npc_name}", "NPC 数据应为 dict", "error")
                continue
            _validate_object(npc_data, L2_NPC_PROFILE_SCHEMA, f"L2.npc_profiles.{npc_name}", report)

    return report


def validate_l3(data: dict) -> SchemaReport:
    """验证 L3 JSON 数据."""
    report = SchemaReport()
    if not isinstance(data, dict):
        report.add("L3", "L3 数据应为 dict", "error")
        return report

    _validate_object(data, L3_TOP_SCHEMA, "L3", report)

    # 验证 scene_intents（value 是 dict of SceneIntent）
    scene_intents = data.get("scene_intents", {})
    if isinstance(scene_intents, dict):
        for scene_name, intent_data in scene_intents.items():
            if not isinstance(intent_data, dict):
                report.add(f"L3.scene_intents.{scene_name}", "应为 dict", "error")
                continue
            _validate_object(intent_data, L3_SCENE_INTENT_SCHEMA, f"L3.scene_intents.{scene_name}", report)

    return report


def validate_all(l1_data: dict, l2_data: dict, l3_data: dict) -> dict[str, SchemaReport]:
    """验证全部三层数据."""
    return {
        "L1": validate_l1(l1_data),
        "L2": validate_l2(l2_data),
        "L3": validate_l3(l3_data),
    }


def is_valid(l1_data: dict, l2_data: dict, l3_data: dict) -> bool:
    """三层数据是否全部通过验证."""
    reports = validate_all(l1_data, l2_data, l3_data)
    return all(r.is_valid for r in reports.values())
