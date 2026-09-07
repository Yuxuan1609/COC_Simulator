"""Task 4：game.html 内联 JS 拆模块后的结构契约 + Node 单测入口。

锁的是落地形态，不是现网内联实现：
- htmx 本地化
- type=module 入口 + 静态文件可服务
- window.* 桥覆盖全部 onclick/onsubmit 具名处理函数
- turn/init 走 FormData（禁止 JSON.stringify）
- 玩家/LLM 文本进 innerHTML 前走 escapeHtml
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
JS_DIR = FRONTEND / "static" / "js"
GAME_HTML = FRONTEND / "templates" / "game.html"
BASE_HTML = FRONTEND / "templates" / "base.html"

MODULE_FILES = (
    "util.js",
    "api.js",
    "state.js",
    "scene.js",
    "combat.js",
    "charcard.js",
    "ws.js",
    "game.js",
)

# markup + 动态拼接的具名处理函数。内联表达式（location.href / classList.toggle）不算。
REQUIRED_WINDOW_HANDLERS = (
    "initGame",
    "toggleSceneCard",
    "toggleCombatPanel",
    "executeCombatRound",
    "toggleInlineChat",
    "sendTurnAction",
    "toggleDebug",
    "toggleAutoWin",
    "sendTurn",
    "toggleCharCard",
    "closeEnemyDetail",
    "talkToNpc",
    "openEnemyDetail",
    "selectCombatAction",
    "selectCombatTarget",
)

_HANDLER_RE = re.compile(
    r"""on(?:click|submit)\s*=\s*["'](?:if\s*\([^)]*\)\s*)?([A-Za-z_$][\w$]*)\s*\(""",
)
_DYNAMIC_ONCLICK_RE = re.compile(
    r"""onclick=["']([A-Za-z_$][\w$]*)\s*\(""",
)
_SKIP_HANDLER_NAMES = frozenset({"if", "document", "location"})


@pytest.fixture
def client():
    from frontend.server import app
    return TestClient(app)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing {path}"
    return path.read_text(encoding="utf-8")


def test_htmx_is_local_not_cdn():
    base = _read(BASE_HTML)
    assert "/static/js/vendor/htmx.min.js" in base
    assert "unpkg.com/htmx" not in base
    assert "cdn.jsdelivr.net/npm/htmx" not in base


def test_htmx_vendor_file_exists():
    vendor = JS_DIR / "vendor" / "htmx.min.js"
    assert vendor.is_file(), f"missing {vendor}"
    text = vendor.read_text(encoding="utf-8", errors="replace")
    assert "htmx" in text.lower()
    assert len(text) > 1000


def test_game_page_loads_module_entry(client):
    html = client.get("/game").text
    assert 'type="module"' in html
    assert "/static/js/game.js" in html


def test_js_modules_are_served(client):
    for name in MODULE_FILES:
        resp = client.get(f"/static/js/{name}")
        assert resp.status_code == 200, name
        assert len(resp.text) > 20, name


def test_htmx_vendor_is_served(client):
    resp = client.get("/static/js/vendor/htmx.min.js")
    assert resp.status_code == 200
    assert "htmx" in resp.text.lower()


def test_game_template_has_no_inline_business_js():
    text = _read(GAME_HTML)
    assert "function sendTurn" not in text
    assert "function initGame" not in text
    assert "let combatSession" not in text
    assert "var DEBUG" not in text
    assert 'src="/static/js/game.js"' in text
    assert 'type="module"' in text


def test_window_bridge_covers_onclick_handlers():
    html = _read(GAME_HTML)
    js_sources = [_read(JS_DIR / name) for name in MODULE_FILES if (JS_DIR / name).is_file()]
    game_js = _read(JS_DIR / "game.js") if (JS_DIR / "game.js").is_file() else ""

    found = set(_HANDLER_RE.findall(html))
    for src in js_sources:
        found.update(_DYNAMIC_ONCLICK_RE.findall(src))
        found.update(re.findall(r"""onclick=["']([A-Za-z_$][\w$]*)\s*\(""", src))
        found.update(re.findall(r"onclick=\"([A-Za-z_$][\w$]*)\(", src))
    found -= _SKIP_HANDLER_NAMES

    missing_required = [n for n in REQUIRED_WINDOW_HANDLERS if n not in game_js]
    assert not missing_required, f"game.js window 桥缺少: {missing_required}"

    uncovered = sorted(
        n for n in found
        if n in REQUIRED_WINDOW_HANDLERS or n[0].islower()
        if n not in _SKIP_HANDLER_NAMES
        if n in REQUIRED_WINDOW_HANDLERS or (
            n[0].islower() and n not in {"hidden"} and n in found
        )
    )
    # 任何 markup 里新出现的具名处理函数也必须进桥
    extra_unbridged = sorted(n for n in found if n not in game_js and n not in _SKIP_HANDLER_NAMES)
    assert not extra_unbridged, f"onclick 具名函数未挂 window: {extra_unbridged}"


def test_turn_and_init_use_formdata_not_json():
    scene = _read(JS_DIR / "scene.js")
    api = _read(JS_DIR / "api.js")
    assert "postForm" in api
    assert "postJSON" in api
    assert "content-type" in api.lower() or "contentType" in api or "get('content-type')" in api.lower() or 'get("content-type")' in api.lower() or "get(`content-type`)" in api or 'get("content-type")' in api or "headers.get(" in api

    assert "postForm" in scene
    assert "/api/game/turn" in scene
    assert "/api/game/init" in scene
    # 禁止把 turn/init 打成 JSON body
    assert "JSON.stringify" not in scene or not re.search(
        r"""JSON\.stringify\([^)]*user_input""", scene
    )
    assert "application/json" not in scene or "player-status" in scene
    # turn/init 不得走 postJSON
    assert not re.search(r"""postJSON\(\s*['"]/api/game/(?:turn|init)""", scene)


def test_escape_html_covers_narrative_innerhtml():
    util = _read(JS_DIR / "util.js")
    scene = _read(JS_DIR / "scene.js")
    combat = _read(JS_DIR / "combat.js")
    assert "export function escapeHtml" in util
    blob = scene + combat
    for field in (
        "data.initial_brief",
        "data.initial_narrative",
        "data.brief",
        "data.narrative",
        "combatData.narrative",
        "endingText",
        "data.round_narrative",
        "data.combat_narrative",
        "data.combat_completed_narrative",
    ):
        assert re.search(rf"escapeHtml\(\s*{re.escape(field)}", blob), field


def test_node_js_unit_suite():
    js_tests = ROOT / "tests" / "js"
    files = sorted(js_tests.glob("*.test.mjs"))
    assert files, "no tests/js/*.test.mjs"
    env = os.environ.copy()
    result = subprocess.run(
        ["node", "--test", *[str(f) for f in files]],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        pytest.fail(
            "node --test failed\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
