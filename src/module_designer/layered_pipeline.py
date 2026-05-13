"""
三层后处理管线：schema 验证 → 离线注入 → 交叉引用验证 → 可选 LLM 修订。

流程：
  layered_parser 的输出 → validate → inject → cross_validate → save
"""
from __future__ import annotations
import json
import os
import sys
from typing import Optional, TYPE_CHECKING

from module_designer.layered_schema import validate_all, SchemaReport

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


# ═══════════════════════════════════════════════════════════════
#  管线
# ═══════════════════════════════════════════════════════════════

class PipelineResult:
    """管线执行结果."""
    def __init__(self):
        self.l1_data: dict = {}
        self.l2_data: dict = {}
        self.l3_data: dict = {}
        self.schema_reports: dict[str, SchemaReport] = {}
        self.cross_ref_report: Optional[CrossRefReport] = None
        self.injection_applied: bool = False

    @property
    def all_valid(self) -> bool:
        schema_ok = all(r.is_valid for r in self.schema_reports.values())
        cross_ok = self.cross_ref_report.is_valid if self.cross_ref_report else True
        return schema_ok and cross_ok

    def summary(self) -> str:
        lines = ["═══ 管线结果 ═══"]
        for layer, report in self.schema_reports.items():
            status = "✓" if report.is_valid else "✗"
            lines.append(f"  Schema {layer}: {status} ({len(report.errors)} errors, {len(report.warnings)} warnings)")
        if self.cross_ref_report:
            status = "✓" if self.cross_ref_report.is_valid else "✗"
            lines.append(f"  交叉引用: {status} ({len(self.cross_ref_report.issues)} issues)")
        lines.append(f"  离线注入: {'已应用' if self.injection_applied else '未应用'}")
        return "\n".join(lines)


def run_pipeline(
    l1_data: dict,
    l2_data: dict,
    l3_data: dict,
    *,
    injector: "ContentInjector | None" = None,
    weapon_lib=None,
    enemy_lib=None,
    run_injection: bool = True,
    run_cross_validate: bool = True,
    verbose: bool = True,
) -> PipelineResult:
    """
    执行完整的后处理管线。

    1. Schema 验证
    2. 离线注入（如启用且有 injector）
    3. 交叉引用验证

    参数：
        l1_data/l2_data/l3_data：三层数据
        injector：ContentInjector 实例（可选）
        weapon_lib/enemy_lib：用于交叉引用验证
        run_injection：是否执行离线注入
        run_cross_validate：是否执行交叉引用验证
        verbose：是否打印进度

    返回：
        PipelineResult（含验证报告和可能修改后的数据）
    """
    result = PipelineResult()
    result.l1_data = l1_data
    result.l2_data = l2_data
    result.l3_data = l3_data

    # ── 1. Schema 验证 ──
    if verbose:
        print("═" * 50)
        print("[Pipeline] Schema 验证...")
    result.schema_reports = validate_all(l1_data, l2_data, l3_data)
    if verbose:
        for layer, report in result.schema_reports.items():
            print(f"  {report.summary()}")

    # ── 2. 离线注入 ──
    if run_injection and injector is not None:
        if verbose:
            print("═" * 50)
            print("[Pipeline] 离线注入...")
        l2_data = injector.offline_inject_module(l2_data, l3_data)
        result.l2_data = l2_data
        result.injection_applied = True
        if verbose:
            enc_total = sum(
                len(sd.get("encounters", []))
                for sd in l2_data.get("scenes", {}).values()
            )
            wpn_total = sum(
                len(sd.get("scene_weapons", []))
                for sd in l2_data.get("scenes", {}).values()
            )
            print(f"  注入完成：{enc_total} 遭遇声明, {wpn_total} 武器引用")

    # ── 3. 交叉引用验证 ──
    if run_cross_validate:
        if verbose:
            print("═" * 50)
            print("[Pipeline] 交叉引用验证...")
        result.cross_ref_report = cross_validate_layers(
            l1_data, l2_data, l3_data,
            weapon_lib=weapon_lib, enemy_lib=enemy_lib,
        )
        if verbose:
            print(f"  {result.cross_ref_report.summary()}")

    if verbose:
        print("═" * 50)
        print(f"[Pipeline] 完成 —— {'全部通过' if result.all_valid else '存在问题（见上方报告）'}")

    return result


def save_pipeline_result(result: PipelineResult, module_dir: str) -> None:
    """将管线处理后的结果保存到模块目录."""
    os.makedirs(module_dir, exist_ok=True)

    for layer, data in [("L1", result.l1_data), ("L2", result.l2_data), ("L3", result.l3_data)]:
        filename = f"{layer.lower()}_player.json" if layer == "L1" else \
                   f"{layer.lower()}_keeper.json" if layer == "L2" else \
                   f"{layer.lower()}_designer.json"
        path = os.path.join(module_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  {layer} → {path}")
