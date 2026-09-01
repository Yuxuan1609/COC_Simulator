"""F31 模组体检 lint CLI（S3-P2 spec §5）。薄壳：加载三件套→复用管线验证函数。"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from module_designer.dependency_graph import DependencyEdge, DependencyGraph, DependencyNode
from module_designer.layered_pipeline import _iter_l2_entities, cross_validate_layers
from module_designer.layered_schema import validate_all


def _scene_graph(l1: dict, l2: dict) -> DependencyGraph:
    g = DependencyGraph()
    names = set(l1.keys()) | set((l2.get("scenes") or {}).keys())
    for s in names:
        g.nodes[s] = DependencyNode(entity_id=s, entity_type="scene", name=s)
    for sname, sdata in (l2.get("scenes") or {}).items():
        if not isinstance(sdata, dict):
            continue
        for fh in sdata.get("from_here") or []:
            if not isinstance(fh, dict):
                continue
            target = fh.get("target") or ""
            if not target:
                continue
            g.edges.append(DependencyEdge(source=sname, target=target, dep_type="scene"))
            if target not in g.nodes:
                g.nodes[target] = DependencyNode(entity_id=target, entity_type="scene", name=target)
    return g


def _difficulty_counts(l2: dict) -> Counter:
    counts: Counter = Counter()
    for _scene, _kind, ent in _iter_l2_entities(l2):
        d = ""
        chk = ent.get("check")
        if isinstance(chk, dict):
            d = chk.get("difficulty") or chk.get("type") or ""
        d = d or ent.get("difficulty") or ""
        if not d or d in ("None", "none"):
            continue
        counts[str(d)] += 1
    return counts


def run_lint(module_dir: str) -> int:
    """返回 exit code：有 error=1，否则 0。"""
    d = Path(module_dir)
    l1 = json.loads((d / "l1_player.json").read_text(encoding="utf-8"))
    l2 = json.loads((d / "l2_keeper.json").read_text(encoding="utf-8"))
    l3 = json.loads((d / "l3_designer.json").read_text(encoding="utf-8"))
    reports = validate_all(l1, l2, l3)
    cross = cross_validate_layers(l1, l2, l3)

    lines: list[tuple[str, str]] = []
    n_error = n_warn = n_info = 0

    def _add(sev: str, msg: str) -> None:
        nonlocal n_error, n_warn, n_info
        lines.append((sev, msg))
        if sev == "error":
            n_error += 1
        elif sev == "warning":
            n_warn += 1
        else:
            n_info += 1

    for layer, report in reports.items():
        for v in report.violations:
            _add(v.severity, f"{layer} {v.path}: {v.message}")
    for i in cross.issues:
        _add(i.severity, f"{i.layer} {i.path}: {i.message}")

    start = l3.get("start_scene") or next(iter(l1), "")
    sg = _scene_graph(l1, l2)
    if start and sg.nodes:
        for nid in sg.reachable_from(start):
            _add("warning", f"场景「{nid}」从起点不可达（依赖图 BFS）")
        inbound = {e.target for e in sg.edges if e.source != e.target}
        for nid in sg.nodes:
            if nid != start and nid not in inbound:
                _add("warning", f"场景「{nid}」无任何入口指向（孤立场景）")

    raw_graph = l2.get("dependency_graph")
    if isinstance(raw_graph, dict) and raw_graph.get("nodes"):
        eg = DependencyGraph.from_dict(raw_graph)
        seeds: set[str] = set()
        if start in eg.nodes:
            seeds.add(start)
        for scene_name, _kind, ent in _iter_l2_entities(l2):
            eid = ent.get("id") or ""
            if eid in eg.nodes and (scene_name == start or ent.get("scene") == start):
                seeds.add(eid)
        for be in l2.get("boss_encounters") or []:
            if not isinstance(be, dict):
                continue
            eid = be.get("id") or ""
            if eid in eg.nodes and be.get("scene") == start:
                seeds.add(eid)
        if seeds:
            reached: set[str] = set()
            for seed in seeds:
                unreach = set(eg.reachable_from(seed))
                reached |= set(eg.nodes) - unreach
            for nid in eg.nodes:
                if nid not in reached:
                    _add("warning", f"实体「{nid}」从起点不可达（依赖图 BFS）")

    counts = _difficulty_counts(l2)
    if counts:
        parts = " / ".join(f"{k}×{v}" for k, v in sorted(counts.items()))
        _add("info", f"检定难度分布：{parts}")

    print(f"验证完成：{n_error} 错误, {n_warn} 警告, {n_info} 信息")
    tag = {"error": "error", "warning": "warn", "info": "info"}
    for sev, msg in lines:
        print(f"  [{tag.get(sev, sev)}] {msg}")
    return 1 if n_error else 0


if __name__ == "__main__":
    sys.exit(run_lint(sys.argv[1] if len(sys.argv) > 1 else "."))
