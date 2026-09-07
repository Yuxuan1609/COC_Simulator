"""frontend/routers/game/session.py — 全局态、get_game、init。"""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, Request, Form
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from frontend._paths import PROJECT_ROOT, FRONTEND_DIR

router = APIRouter()
TEMPLATES_DIR = FRONTEND_DIR / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ── Game instance (lazy init) ──
_game_instance: dict | None = None
_game_quit: bool = False  # prevents auto-reinit after /quit
_weapon_lib = None
_enemy_lib = None
_injector = None

_progress_queues: dict[str, object] = {}

# ── Combat session storage (in-memory, per-process) ──
# Each entry: {"state": CombatState, "combat_init": CombatInit}
_combat_sessions: dict[str, dict] = {}
_auto_win: bool = False


def _init_libraries(weapon_path="", enemy_path="", boss_path=""):
    global _weapon_lib, _enemy_lib, _injector
    if _weapon_lib is not None:
        return
    from library.weapons import WeaponLibrary
    from library.enemies import EnemyLibrary
    from library.injector import ContentInjector

    _weapon_lib = WeaponLibrary()
    if weapon_path:
        _weapon_lib.load_core(str(PROJECT_ROOT / weapon_path))
    else:
        _weapon_lib.load_core()
    _enemy_lib = EnemyLibrary()
    if enemy_path:
        _enemy_lib.load_core(str(PROJECT_ROOT / enemy_path))
    else:
        _enemy_lib.load_core()
    _enemy_ext_dir = PROJECT_ROOT / "data" / "library" / "extensions" / "enemies"
    if _enemy_ext_dir.is_dir():
        for _f in sorted(_enemy_ext_dir.glob("*.json")):
            _enemy_lib.load_extension(str(_f))
    _injector = ContentInjector(_weapon_lib, _enemy_lib)


def get_game() -> dict | None:
    global _game_instance, _game_quit
    if _game_quit:
        return None
    if _game_instance is None:
        from game_loop import init_game
        from game_loop import setup_logging
        log_dir = setup_logging()

        _init_libraries()

        g = init_game(
            l2_path=str(PROJECT_ROOT / "data/modules/测试模组0528v2/l2_keeper_test.json"),
            l1_path=str(PROJECT_ROOT / "data/modules/测试模组0528v2/l1_player.json"),
            l3_path=str(PROJECT_ROOT / "data/modules/测试模组0528v2/l3_designer.json"),
            start_node="测试房间",
        )
        char_path = str(PROJECT_ROOT / "investigator/test_character.json")
        inv, warning = _load_character_or_default(char_path)
        g["_char_load_warning"] = warning
        g["keeper"].world.set_player(inv)
        # 应用 AT_WORLD 中延后的 item_gain
        for item_gain in g.get("pending_world_items", []):
            if hasattr(inv, 'item_manager'):
                inv.item_manager.add(item_gain.item_name, quantity=item_gain.quantity)
        _game_instance = g
    return _game_instance


@router.post("/api/game/init")
async def init_game_api(
    request: Request,
    l1_path: str = Form(""),
    l2_path: str = Form(""),
    l3_path: str = Form(""),
    char_path: str = Form(""),
    weapon_path: str = Form(""),
    enemy_path: str = Form(""),
    boss_path: str = Form(""),
):
    global _game_instance, _game_quit
    _game_quit = False
    from game_loop import init_game
    from prompts import set_prompt_log_dir
    from llm import set_llm_log_dir

    # Default paths if empty
    if not l2_path:
        l2_path = "data/modules/测试模组0528v2/l2_keeper_test.json"
    if not l1_path:
        l1_path = "data/modules/测试模组0528v2/l1_player.json"
    if not l3_path:
        l3_path = "data/modules/测试模组0528v2/l3_designer.json"

    # Initialize libraries with user-specified paths
    _init_libraries(weapon_path, enemy_path, boss_path)

    from game_loop import setup_logging
    log_dir = setup_logging()

    # Determine start scene: L3.start_scene > L3.scene_intents first key > L2 first scene
    start_node = _resolve_start_scene(l2_path, l3_path)

    try:
        g = init_game(
            l2_path=str(PROJECT_ROOT / l2_path),
            l1_path=str(PROJECT_ROOT / l1_path),
            l3_path=str(PROJECT_ROOT / l3_path),
            start_node=start_node,
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    inv, warning = _load_character_or_default(char_path)
    g["_char_load_warning"] = warning

    g["keeper"].world.set_player(inv)
    # 应用 AT_WORLD 中延后的 item_gain
    for item_gain in g.get("pending_world_items", []):
        if hasattr(inv, 'item_manager'):
            inv.item_manager.add(item_gain.item_name, quantity=item_gain.quantity)
    _game_instance = g

    from game_loop import start_autosave
    start_autosave(g)

    # Fire initial turn to trigger scene auto_triggers
    initial_brief = ""
    initial_narrative = ""
    try:
        from game_loop import run_turn
        initial = run_turn(g, "[游戏开始]", _weapon_lib, _enemy_lib, _injector)
        initial_brief = initial.brief if initial else ""
        initial_narrative = initial.narrative if initial else ""
    except Exception:
        pass

    return {
        "success": True,
        "location": g["keeper"].world.current_location,
        "hp": inv.derived.HP,
        "hp_max": inv.derived.HP_MAX,
        "mp": inv.derived.MP,
        "mp_max": inv.derived.MP_MAX,
        "san": inv.derived.SAN,
        "san_max": inv.derived.SAN_MAX,
        "name": inv.name,
        "known_spells": _spell_names(g["keeper"].world, inv),
        "initial_brief": initial_brief,
        "initial_narrative": initial_narrative,
        "warning": warning,
    }


def _resolve_start_scene(l2_path: str, l3_path: str) -> str:
    """Determine the starting scene for game init.

    Priority:
    1. L3 JSON top-level 'start_scene' field
    2. L3 JSON module_meta.start_scene
    3. First key in L3 scene_intents dict
    4. First key in L2 scenes dict
    5. Fallback: "测试房间"
    """
    import json as _json
    l2_full = PROJECT_ROOT / l2_path
    l3_full = PROJECT_ROOT / l3_path

    # Try L3 first
    if l3_full.exists():
        try:
            l3 = _json.loads(l3_full.read_text(encoding="utf-8"))
            # Check top-level start_scene
            if isinstance(l3, dict):
                if "start_scene" in l3 and l3["start_scene"]:
                    return l3["start_scene"]
                # Check module_meta.start_scene
                meta = l3.get("module_meta", {})
                if isinstance(meta, dict) and meta.get("start_scene"):
                    return meta["start_scene"]
                # First scene_intents key
                si = l3.get("scene_intents", {})
                if isinstance(si, dict) and si:
                    return next(iter(si.keys()))
        except Exception:
            pass

    # Try L2 scenes dict
    if l2_full.exists():
        try:
            l2 = _json.loads(l2_full.read_text(encoding="utf-8"))
            scenes = l2.get("scenes", {})
            if isinstance(scenes, dict) and scenes:
                return next(iter(scenes.keys()))
        except Exception:
            pass

    return "测试房间"


def _make_default_inv():
    from investigator import Investigator
    from investigator.rules import roll_stats, calc_derived, create_skill_list
    inv = Investigator(name="调查员", age=25, gender="男")
    inv.stats = roll_stats()
    inv.skills = create_skill_list()
    inv.derived = calc_derived(inv.stats, inv.age)
    return inv


def _load_character_or_default(char_path: str = ""):
    """加载角色卡；失败或缺失则默认卡。返回 (inv, warning|None)。

    仅 load 抛错时带 warning（B19）。路径不存在/未填 = 有意用默认卡，无 warning。
    """
    import os
    from investigator import load_investigator
    if not char_path:
        return _make_default_inv(), None
    full = char_path if os.path.isabs(char_path) else str(PROJECT_ROOT / char_path)
    if not os.path.exists(full):
        return _make_default_inv(), None
    try:
        return load_investigator(full), None
    except Exception:
        return _make_default_inv(), "角色卡加载失败，已使用默认卡"



def _spell_names(world, p):
    from . import charcard
    return charcard._known_spell_names(world, p)
