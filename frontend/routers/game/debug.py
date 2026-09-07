"""frontend/routers/game/debug.py — GET /api/game/debug 聚合端点。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

_LLM_PREVIEW_CHARS = 400
_FLAGS_CAP = 50


def _clamp_turns(n: int) -> int:
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 5
    return max(1, min(50, n))


def _resolve_log_dir(game: dict | None = None) -> str | None:
    """日志目录取自当前 TurnLogger / prompts._log_dir，禁止写死路径。"""
    try:
        import game_loop
        tl = getattr(game_loop, "_turn_logger", None)
        d = getattr(tl, "log_dir", None) if tl is not None else None
        if d:
            return str(d)
    except Exception:
        pass
    if isinstance(game, dict):
        d = game.get("_log_dir")
        if d:
            return str(d)
    try:
        from prompts import _log_dir as prompt_dir
        if prompt_dir:
            return str(prompt_dir)
    except Exception:
        pass
    return None


def _read_recent_turn_logs(n: int, game: dict | None = None) -> list:
    log_dir = _resolve_log_dir(game)
    if not log_dir:
        return []
    jsonl = os.path.join(log_dir, "turn_log.jsonl")
    lines: list[str] = []
    if os.path.isfile(jsonl):
        try:
            with open(jsonl, encoding="utf-8") as f:
                for line in f:
                    s = line.strip()
                    if s:
                        lines.append(s)
        except OSError:
            lines = []
    out: list = []
    for raw in lines[-n:]:
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            out.append({"raw": raw})
    if out:
        return out
    try:
        files = sorted(Path(log_dir).glob("turn_*.json"))
    except OSError:
        return []
    for path in files[-n:]:
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def _is_turn_artifact(name: str) -> bool:
    if name == "turn_log.jsonl":
        return True
    return name.startswith("turn_") and name.endswith(".json")


def _recent_llm_logs(n: int, game: dict | None = None) -> list:
    log_dir = _resolve_log_dir(game)
    if not log_dir or not os.path.isdir(log_dir):
        return []
    files: list[Path] = []
    try:
        for p in Path(log_dir).iterdir():
            if not p.is_file():
                continue
            if p.suffix.lower() != ".txt":
                continue
            if _is_turn_artifact(p.name):
                continue
            files.append(p)
    except OSError:
        return []
    files.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    records = []
    for p in files[:n]:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        records.append({"filename": p.name, "preview": text[:_LLM_PREVIEW_CHARS]})
    return records


def _derived_stat(player, *names):
    if player is None:
        return None
    d = getattr(player, "derived", None)
    if d is None:
        return None
    for name in names:
        if isinstance(d, dict) and name in d:
            return d[name]
        if hasattr(d, name):
            return getattr(d, name)
    return None


def _snapshot(world) -> dict:
    player = getattr(world, "player", None)
    snap: dict = {
        "location": getattr(world, "current_location", None),
        "hp": _derived_stat(player, "HP"),
        "san": _derived_stat(player, "SAN"),
        "mp": _derived_stat(player, "MP"),
    }
    flags: list[str] = []
    rs = getattr(world, "runtime_state", None) or {}
    if isinstance(rs, dict):
        for k, v in rs.items():
            done = getattr(v, "completed", None)
            if done is None and isinstance(v, dict):
                done = v.get("completed")
            if done:
                flags.append(str(k))
            if len(flags) >= _FLAGS_CAP:
                break
    snap["flags"] = flags

    npcs = []
    mgr = getattr(world, "npcs", None)
    values = None
    if isinstance(mgr, dict):
        values = mgr.values()
    elif mgr is not None:
        inner = getattr(mgr, "_npcs", None)
        if isinstance(inner, dict):
            values = inner.values()
        elif isinstance(mgr, (list, tuple)):
            values = mgr
    if values is not None:
        for n in values:
            entry = {"name": getattr(n, "name", None) if not isinstance(n, dict)
                     else n.get("name")}
            if isinstance(n, dict):
                if "attitude_value" in n:
                    entry["attitude_value"] = n["attitude_value"]
                elif "attitude" in n:
                    entry["attitude"] = n["attitude"]
            else:
                if hasattr(n, "attitude_value"):
                    entry["attitude_value"] = n.attitude_value
                elif hasattr(n, "attitude"):
                    entry["attitude"] = n.attitude
            npcs.append(entry)
    snap["npcs"] = npcs

    clock = getattr(world, "clock", None)
    if clock is not None:
        snap["clock"] = {
            "day": getattr(clock, "day", None),
            "time_of_day": getattr(clock, "time_of_day", None),
            "game_time": getattr(clock, "game_time", None),
        }

    if player is not None and hasattr(player, "timed_effects"):
        now = getattr(clock, "game_time", None) if clock is not None else None
        effects = []
        for t in (getattr(player, "timed_effects", None) or []):
            if isinstance(t, dict):
                entry = {
                    "id": t.get("id", ""),
                    "description": t.get("description", ""),
                    "expire_at": t.get("expire_at"),
                }
                if now is not None and t.get("expire_at") is not None:
                    try:
                        entry["remaining"] = max(0, int(t["expire_at"]) - int(now))
                    except (TypeError, ValueError):
                        pass
                effects.append(entry)
        snap["timed_effects"] = effects

    items = getattr(world, "scene_items", None)
    loc = getattr(world, "current_location", None)
    if items is not None:
        raw = items.get(loc, []) if isinstance(items, dict) else items
        scene_items = []
        for i in (raw or []):
            if isinstance(i, dict):
                scene_items.append({
                    "kind": i.get("kind"),
                    "ref": i.get("ref"),
                    "quantity": i.get("quantity", 1),
                    "hidden": i.get("hidden", False),
                })
            else:
                scene_items.append({
                    "kind": getattr(i, "kind", None),
                    "ref": getattr(i, "ref", None),
                    "quantity": getattr(i, "quantity", 1),
                    "hidden": getattr(i, "hidden", False),
                })
        snap["scene_items"] = scene_items
    return snap


def _current_node(world):
    fn = getattr(world, "_current_node", None)
    if callable(fn):
        try:
            return fn()
        except Exception:
            pass
    graph = getattr(world, "graph", None)
    loc = getattr(world, "current_location", None)
    nodes = getattr(graph, "nodes", None) if graph is not None else None
    if isinstance(nodes, dict) and loc in nodes:
        return nodes[loc]
    return None


def _once_blocked(entity, world) -> tuple[bool, str]:
    eid = getattr(entity, "id", "") or ""
    if not eid or not hasattr(world, "is_entity_completed"):
        return False, ""
    try:
        completed = bool(world.is_entity_completed(eid))
    except Exception:
        return False, ""
    if not completed:
        return False, ""
    extra = getattr(entity, "extra", None) or {}
    repeatable = bool(getattr(entity, "repeatable", False)
                      or (isinstance(extra, dict) and extra.get("repeatable")))
    if repeatable:
        return False, ""
    return True, "（该实体已触发过，无法重复执行）"


def _time_ok(entity, world) -> tuple[bool, str]:
    tc = getattr(entity, "time_condition", "") or ""
    if isinstance(tc, list):
        if not tc:
            return True, ""
        tc = json.dumps(tc, ensure_ascii=False)
    if not tc or tc == "[]":
        return True, ""
    clock = getattr(world, "clock", None)
    if clock is None:
        return True, ""
    from scenario_core import check_time_condition
    day = getattr(clock, "day", 0)
    tod = getattr(clock, "time_of_day", "")
    if check_time_condition(tc, day, tod):
        return True, ""
    return False, "当前时间不满足触发条件"


def _eval_entity(entity, world, judge) -> dict:
    eid = getattr(entity, "id", "") or ""
    rec = {
        "id": eid,
        "name": getattr(entity, "name", "") or "",
        "type": getattr(entity, "entity_type", "") or "",
        "available": True,
        "gate": "",
        "reason": "",
    }
    blocked, reason = _once_blocked(entity, world)
    if blocked:
        rec["available"] = False
        rec["gate"] = "once"
        rec["reason"] = reason
        return rec
    ok, reason = _time_ok(entity, world)
    if not ok:
        rec["available"] = False
        rec["gate"] = "time"
        rec["reason"] = reason
        return rec
    req = getattr(entity, "requirement", "") or ""
    if not isinstance(req, str) or not req.strip():
        return rec
    hard, _ = judge._split_requirement(req)
    if not hard:
        return rec
    judge._current_entity_id = eid
    try:
        met, msg = judge._evaluate_requirement(hard)
    finally:
        judge._current_entity_id = None
    if not met:
        rec["available"] = False
        rec["gate"] = "requirement"
        rec["reason"] = msg
    return rec


def _entity_availability(world, judge=None) -> list:
    """当前场景 interactions + auto_triggers 只读可用性（无副作用）。"""
    from game.judge import Judge
    node = _current_node(world)
    if node is None:
        return []
    if judge is None:
        judge = Judge(world)
    prev_trace = getattr(judge, "_turn_trace", None)
    prev_eid = getattr(judge, "_current_entity_id", None)
    judge._turn_trace = None
    out = []
    try:
        entities = list(getattr(node, "interactions", None) or [])
        entities.extend(getattr(node, "auto_triggers", None) or [])
        for ent in entities:
            out.append(_eval_entity(ent, world, judge))
    finally:
        judge._turn_trace = prev_trace
        judge._current_entity_id = prev_eid
    return out


@router.get("/api/game/debug")
def game_debug(turns: int = 5):
    from . import session
    game = session.get_game()
    if game is None:
        return JSONResponse({"error": "no_game"}, status_code=400)
    world = game["keeper"].world
    n = _clamp_turns(turns)
    judge = getattr(game["keeper"], "judge", None)
    return {
        "recent_turns": _read_recent_turn_logs(n, game),
        "state_snapshot": _snapshot(world),
        "scene_entities": _entity_availability(world, judge),
        "llm_records": _recent_llm_logs(n, game),
    }
