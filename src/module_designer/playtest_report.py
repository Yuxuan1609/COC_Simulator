"""F32 模组试玩报告：单次试玩纯聚合，零 rubric 零 LLM（S3-P2 spec §6）。"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from module_designer.layered_pipeline import _iter_l2_entities


def resolve_player_goal(profile: dict, l3: dict | None) -> str:
    goal = str((profile or {}).get("goal") or "").strip()
    if goal:
        return goal
    l3 = l3 or {}
    meta = l3.get("module_meta") or {}
    pg = str(meta.get("player_goal") or "").strip()
    if pg:
        return pg
    return str(l3.get("driving_force") or "")[:80]


def _entity_difficulty(ent: dict) -> str:
    d = ""
    chk = ent.get("check")
    if isinstance(chk, dict):
        d = chk.get("difficulty") or ""
    d = d or ent.get("difficulty") or ""
    if not d or d in ("None", "none"):
        return "none"
    return str(d)


def _collect_entities(module_l2: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for _scene, _kind, ent in _iter_l2_entities(module_l2):
        eid = ent.get("id") or ""
        if eid and eid not in out:
            out[eid] = _entity_difficulty(ent)
    return out


def _parse_mech_ids(mech: str) -> set[str]:
    ids: set[str] = set()
    if not mech:
        return ids
    for part in str(mech).split("|"):
        part = part.strip()
        if part.startswith("entities="):
            for token in part[len("entities="):].split(","):
                token = token.strip()
                if not token:
                    continue
                eid = token.split(":", 1)[0].strip()
                if eid:
                    ids.add(eid)
        elif part.startswith("at="):
            for token in part[len("at="):].split(","):
                token = token.strip()
                if token:
                    ids.add(token.split(":", 1)[0].strip())
    return ids


def build_report(summary: dict, module_l2: dict, module_l3: dict | None = None) -> dict:
    turns = summary.get("turns_detail") or []
    scenes = set((module_l2.get("scenes") or {}).keys())
    visited: list[str] = []
    seen: set[str] = set()
    for t in turns:
        loc = t.get("location")
        if loc and loc in scenes and loc not in seen:
            seen.add(loc)
            visited.append(loc)

    entities = _collect_entities(module_l2)
    triggered: set[str] = set()
    dist: dict[str, dict[str, int]] = defaultdict(lambda: {"success": 0, "failure": 0})
    for t in turns:
        for sr in t.get("skill_results") or []:
            eid = sr.get("entity_id") or ""
            if eid:
                triggered.add(eid)
                diff = entities.get(eid, "unknown")
                key = "success" if sr.get("success") else "failure"
                dist[diff][key] += 1
        triggered |= _parse_mech_ids(t.get("mech") or "")

    known = set(entities)
    triggered &= known

    reached = None
    ending_turn = None
    for t in turns:
        if t.get("ending"):
            reached = t["ending"]
            ending_turn = t.get("turn")

    ending_ids = []
    for e in (module_l3 or {}).get("ending_conditions") or []:
        if isinstance(e, dict) and e.get("id"):
            ending_ids.append(e["id"])
        elif isinstance(e, str):
            ending_ids.append(e)

    title = ((module_l3 or {}).get("module_meta") or {}).get("title") or summary.get("module") or "未命名"
    n_turns = summary.get("turns")
    if n_turns is None:
        n_turns = len(turns)

    check_distribution = {k: dict(v) for k, v in dist.items()}
    return {
        "title": title,
        "scene_coverage": {
            "visited": len(visited),
            "total": len(scenes),
            "missing": sorted(scenes - seen),
        },
        "endings": {
            "reached": reached,
            "turn": ending_turn,
            "missing": [eid for eid in ending_ids if eid != reached],
        },
        "entity_trigger": {
            "triggered": len(triggered),
            "total": len(entities),
            "missing": sorted(known - triggered),
        },
        "check_distribution": check_distribution,
        "elapsed": {
            "total_elapsed_s": summary.get("total_elapsed_s") or 0,
            "turns": n_turns,
        },
    }


def _fmt_elapsed(seconds) -> str:
    try:
        s = int(round(float(seconds)))
    except (TypeError, ValueError):
        s = 0
    m, sec = divmod(s, 60)
    return f"{m} 分 {sec} 秒"


def render_markdown(report: dict) -> str:
    title = report.get("title") or "未命名"
    cov = report.get("scene_coverage") or {}
    visited, total = cov.get("visited", 0), cov.get("total", 0)
    pct = int(round(100 * visited / total)) if total else 0
    lines = [
        f"# 《{title}》试玩报告",
        f"场景覆盖率：{visited}/{total}（{pct}%）",
    ]
    missing_scenes = cov.get("missing") or []
    if missing_scenes:
        lines.append(f"  未到访：{'、'.join(missing_scenes)}")

    end = report.get("endings") or {}
    reached = end.get("reached")
    if reached:
        turn = end.get("turn")
        turn_s = f"（T{turn}）" if turn is not None else ""
        line = f"结局触达：{reached}{turn_s}"
    else:
        line = "结局触达：无"
    missing_end = end.get("missing") or []
    if missing_end:
        line += f"；未触达：{'、'.join(missing_end)}"
    lines.append(line)

    trig = report.get("entity_trigger") or {}
    lines.append(f"实体触发率：{trig.get('triggered', 0)}/{trig.get('total', 0)}")
    missing_ent = trig.get("missing") or []
    if missing_ent:
        lines.append(f"  未触发：{', '.join(missing_ent)}")

    dist = report.get("check_distribution") or {}
    if dist:
        parts = []
        for diff in sorted(dist):
            s, f = dist[diff].get("success", 0), dist[diff].get("failure", 0)
            parts.append(f"{diff} 成功 {s} / 失败 {f}")
        lines.append("检定分布：" + "；".join(parts))
    else:
        lines.append("检定分布：无")

    elapsed = report.get("elapsed") or {}
    lines.append(f"耗时：{_fmt_elapsed(elapsed.get('total_elapsed_s', 0))} / {elapsed.get('turns', 0)} 回合")
    return "\n".join(lines) + "\n"


def run_report(summary_path: str, module_dir: str, out_path: str | None = None) -> dict:
    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    d = Path(module_dir)
    l2_name = "l2_keeper_test.json" if (d / "l2_keeper_test.json").exists() else "l2_keeper.json"
    l2_path = d / l2_name
    l2 = json.loads(l2_path.read_text(encoding="utf-8"))
    l3_path = d / "l3_designer.json"
    l3 = json.loads(l3_path.read_text(encoding="utf-8")) if l3_path.exists() else None
    report = build_report(summary, l2, l3)
    if out_path is None:
        out_path = str(Path(summary_path).with_name("playtest_report.json"))
    out = Path(out_path)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    out.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    return report


if __name__ == "__main__":
    import sys
    sp, md = sys.argv[1], sys.argv[2]
    op = sys.argv[3] if len(sys.argv) > 3 else None
    run_report(sp, md, op)
