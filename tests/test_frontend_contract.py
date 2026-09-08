"""Frontend router consumes PlayerTurnResult correctly."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("ARK_API_KEY", "dummy")
os.environ.setdefault("DEEPSEEK_API_KEY", "dummy")

import json
import pytest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient

from game.messages import (
    TurnStatus, TurnResult, PlayerTurnResult, PendingInteraction,
)


@pytest.fixture
def client():
    from frontend.server import app
    return TestClient(app)


def test_turn_endpoint_forwards_pending_interaction(client):
    fake_result = PlayerTurnResult(
        status=TurnStatus.COMPLETED,
        brief="你发现了手枪。",
        narrative="桌上有一把手枪。是否拾取？",
        pending_interaction=PendingInteraction(
            kind="standoff", question="你要怎么做？",
            interaction_id="standoff"),
        skill_results=[], timestamp="12:00:00",
    )
    fake_game = SimpleNamespace()
    with patch("frontend.routers.game.session.get_game", return_value=fake_game), \
         patch("game_loop.run_turn", return_value=fake_result):
        resp = client.post("/api/game/turn", data={"user_input": "搜索桌子"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["pending_interaction"]["kind"] == "standoff"
    assert data["pending_interaction"]["question"] == "你要怎么做？"
    assert "standoff_prompt" not in data
    assert "full" not in data
    assert "time_agent" not in data


def test_turn_engine_error_html_is_escaped(client):
    """run_turn 抛带 <script> 的异常 → HTML 响应转义，不原样插入。"""
    fake_game = {"keeper": SimpleNamespace()}
    with patch("frontend.routers.game.session.get_game", return_value=fake_game), \
         patch("game_loop.run_turn", side_effect=RuntimeError("<script>alert(1)</script>")):
        resp = client.post("/api/game/turn", data={"user_input": "搜索桌子"})
    assert resp.status_code == 200
    assert "text/html" in (resp.headers.get("content-type") or "")
    text = resp.text
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


# ── 统一资源层:player-status / character-card 的 MP 与已知法术接线 ──

def _fake_game_with_spells():
    derived = SimpleNamespace(HP=10, HP_MAX=12, MP=8, MP_MAX=11, SAN=55,
                              SAN_MAX=88, MOV=8, DB="1D4", BUILD=1, DODGE=50)
    player = SimpleNamespace(
        name="张三", age=30, gender="男", occupation=None, avatar_url="",
        derived=derived, known_spells=["HEART_ARREST", "GHOST"],
        stats=SimpleNamespace(STR=60, CON=65, SIZ=55, DEX=70, APP=50,
                              INT=75, POW=70, EDU=80, LUCK=50),
        skills={"侦查": SimpleNamespace(name="侦查", value=60, category="感知")},
        weapons=[SimpleNamespace(name="小刀", damage="1D4")],
        appearance="", personal_description="",
        item_manager=SimpleNamespace(describe=lambda: "无"),
    )
    _spells = {"HEART_ARREST": SimpleNamespace(name="心脏骤停", category="combat")}
    world = SimpleNamespace(
        player=player,
        spell_library=SimpleNamespace(get=lambda sid: _spells.get(sid)),
        current_location="书房",
        get_current_description=lambda: "一间书房。",
        get_possible_exits=lambda: [SimpleNamespace(target="走廊", method="推门")],
        runtime_state={},
        triggered_events=[],
    )
    world.set_player = lambda inv: setattr(world, "player", inv)
    return {"keeper": SimpleNamespace(world=world, turn_number=1)}


def test_player_status_json_includes_mp_and_known_spells(client):
    with patch("frontend.routers.game.session.get_game", return_value=_fake_game_with_spells()):
        resp = client.get("/api/game/player-status?format=json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mp"] == 8
    assert data["mp_max"] == 11
    # 库内 id 解析为中文名,库外 id 原样保留
    assert data["known_spells"] == ["心脏骤停", "GHOST"]


_CHAR_CARD_KEYS = {
    "name", "age", "gender", "occupation", "avatar_url",
    "appearance", "personal_description",
    "stats", "hp", "hp_max", "san", "san_max", "mp", "mp_max",
    "mov", "db", "build", "dodge",
    "skills", "weapons", "spells", "items",
}


def test_character_card_shows_mp_max_and_spells(client):
    with patch("frontend.routers.game.session.get_game", return_value=_fake_game_with_spells()):
        resp = client.get("/api/game/character-card")
    assert resp.status_code == 200
    assert "application/json" in (resp.headers.get("content-type") or "")
    data = resp.json()
    missing = _CHAR_CARD_KEYS - data.keys()
    assert not missing, missing
    assert data["name"] == "张三"
    assert data["hp"] == 10
    assert data["hp_max"] == 12
    assert data["mp"] == 8
    assert data["mp_max"] == 11
    assert data["san"] == 55
    assert data["san_max"] == 88
    assert data["stats"]["STR"] == 60
    spells = data["spells"]
    by_id = {s["id"]: s for s in spells}
    assert by_id["HEART_ARREST"]["name"] == "心脏骤停"
    assert by_id["GHOST"]["name"] == "GHOST"
    assert by_id["GHOST"]["category"] in (None, "")
    assert data["skills"][0]["name"] == "侦查"
    assert data["weapons"][0]["name"] == "小刀"
    assert data["items"] == "无"


def test_character_card_no_investigator(client):
    fake = _fake_game_with_spells()
    fake["keeper"].world.player = None
    with patch("frontend.routers.game.session.get_game", return_value=fake):
        resp = client.get("/api/game/character-card")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] is None


# ── F2:SAN bar 分母接线 san_max(SAN_MAX=99-克苏鲁神话,非硬编码 99)──
# _fake_game_with_spells 的 derived 带 SAN=55/SAN_MAX=88 → san_pct 应为 62.5%。

def test_player_status_json_includes_san_max(client):
    """F2:player-status JSON 暴露 san_max(SAN bar 分母数据来源)。"""
    with patch("frontend.routers.game.session.get_game", return_value=_fake_game_with_spells()):
        resp = client.get("/api/game/player-status?format=json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["san_max"] == 88
    assert data["san_max"] >= data["san"]


def test_game_state_includes_san_max(client, monkeypatch):
    """F2:/api/game/state 暴露 san_max。peek `_game_instance`，不走 get_game lazy 建局。"""
    from frontend.routers.game import session as game_session
    monkeypatch.setattr(game_session, "_game_instance", _fake_game_with_spells())
    monkeypatch.setattr(game_session, "_game_quit", False)
    game_session._combat_sessions.clear()
    resp = client.get("/api/game/state")
    assert resp.status_code == 200
    assert resp.json()["san_max"] == 88


def test_character_card_san_bar_uses_san_max(client):
    """F2:角色卡 JSON 暴露 san / san_max（55/88）；bar 宽度由前端用这两数计算。"""
    with patch("frontend.routers.game.session.get_game", return_value=_fake_game_with_spells()):
        resp = client.get("/api/game/character-card")
    assert resp.status_code == 200
    data = resp.json()
    assert data["san"] == 55
    assert data["san_max"] == 88


def test_combat_state_frontend_serialization_includes_san_max():
    """F2:战斗 state 前端序列化含 player_san_max;CombatState 默认 99。"""
    from game.combat import CombatState
    from frontend.routers.game.combat import _serialize_combat_state_for_frontend
    st = CombatState(player_san=50, player_san_max=80)
    assert _serialize_combat_state_for_frontend(st)["player_san_max"] == 80
    assert _serialize_combat_state_for_frontend(CombatState())["player_san_max"] == 99


def test_combat_state_init_uses_player_san_max():
    """F2:_init_combat 从 player.derived.SAN_MAX 接线 CombatState.player_san_max。"""
    from investigator.models import Investigator, Stats, DerivedStats
    from game.combat import CombatSystem, CombatState
    from game.messages import CombatInit
    inv = Investigator()
    inv.stats = Stats(STR=50, CON=50, DEX=50, APP=50, INT=50, POW=50, EDU=50, LUCK=50)
    inv.derived = DerivedStats(HP=12, HP_MAX=12, SAN=55, SAN_MAX=88, MP=14,
                               DB="0", BUILD=0, DODGE=25)
    inv.skills = {}
    state = CombatSystem()._init_combat(CombatInit(enemies=[], player=inv))
    assert state.player_san == 55
    assert state.player_san_max == 88


def test_run_single_round_dict_includes_san_max():
    """F2:run_single_round 返回 dict 含 player_san_max(前端战斗轮结果数据源)。"""
    from investigator.models import Investigator, Stats, DerivedStats
    from game.combat import CombatSystem, CombatState
    from game.messages import CombatInit
    inv = Investigator()
    inv.stats = Stats(STR=50, CON=50, DEX=50, APP=50, INT=50, POW=50, EDU=50, LUCK=50)
    inv.derived = DerivedStats(HP=12, HP_MAX=12, SAN=55, SAN_MAX=88, MP=14,
                               DB="0", BUILD=0, DODGE=25)
    inv.skills = {}
    cs = CombatSystem()
    state = CombatState(enemies=[], player_hp=12, player_hp_max=12,
                        player_san=55, player_san_max=88)
    result = cs.run_single_round(CombatInit(enemies=[], player=inv), state, "punch", [])
    assert result["player_san"] == 55
    assert result["player_san_max"] == 88


# ── 34 端点契约防护网（2026-09-06 frontend-upgrade §1）──
# 副作用端点只测失败路径；游戏端点 patch get_game。

_TURN_KEYS = {
    "brief", "narrative", "turn_dynamic_text", "player_snapshot",
    "skill_results", "combat_init", "pending_interaction",
    "game_over", "ending",
}


class TestLauncherContract:
    def test_launcher_page(self, client):
        assert client.get("/").status_code == 200

    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_tabs(self, client):
        for tab in ("config", "step0", "game-start", "module-gen"):
            r = client.get(f"/launcher/tabs/{tab}")
            assert r.status_code == 200, tab

    def test_unknown_tab_404(self, client):
        assert client.get("/launcher/tabs/nope").status_code == 404

    def test_config_roundtrip(self, client, tmp_path, monkeypatch):
        cfg = tmp_path / "config.json"
        monkeypatch.setattr("frontend.routers.launcher._config_path", lambda: cfg)
        r = client.post("/api/config/save", data={
            "model": "test-model",
            "thinking": "on",
            "reasoning_effort": "high",
            "flash_model": "flash",
            "llm_timeout_ms": "120000",
            "llm_slow_threshold_ms": "30000",
            "combat_llm_enhancement": "off",
            "debug_mode": "off",
        })
        assert r.status_code == 200
        loaded = client.get("/api/config/load").json()
        assert loaded["model"] == "test-model"
        assert loaded["thinking"] is True
        assert "llm_timeout_ms" in loaded

    def test_step0_missing_source_400(self, client):
        r = client.post("/api/step0/start", data={
            "source": "no_such_source.txt", "module_name": "x",
        })
        assert r.status_code == 400

    def test_pipeline_missing_source_400(self, client):
        r = client.post("/api/pipeline/start", data={
            "source": "no_such_source.docx", "module_name": "x",
        })
        assert r.status_code == 400

    def test_pipeline_validate(self, client):
        r = client.post("/api/pipeline/validate", data={})
        assert r.status_code == 200
        assert "<" in r.text


class TestCharacterContract:
    def test_character_page(self, client):
        assert client.get("/character").status_code == 200

    def test_steps_1_to_3(self, client):
        for n in (1, 2, 3):
            r = client.get(f"/character/step/{n}")
            assert r.status_code == 200, n

    def test_roll_returns_html(self, client):
        r = client.post("/character/roll")
        assert r.status_code == 200 and "<" in r.text

    def test_skills_list(self, client):
        r = client.get("/character/skills-list")
        assert r.status_code == 200 and "<" in r.text

    def test_export_get_page(self, client):
        r = client.get("/character/export")
        assert r.status_code == 200
        assert "zip" in (r.headers.get("content-type") or "").lower() \
            or r.content[:2] == b"PK"

    def test_export_post(self, client):
        r = client.post("/character/export", data={"name": "测"})
        assert r.status_code == 200
        assert r.content[:2] == b"PK"

    def test_generate_description_missing_fields_422(self, client):
        r = client.post("/character/generate-description")
        assert r.status_code == 422

    def test_upload_avatar_missing_file_422(self, client):
        r = client.post("/character/upload-avatar")
        assert r.status_code == 422


class TestEditorContract:
    def test_editor_page(self, client):
        assert client.get("/editor").status_code == 200

    def test_validate_current_behavior(self, client):
        """锁定现状：Form(path, content)；空 scenes 只警告不拒绝。"""
        r = client.post("/editor/validate",
                        data={"path": "x.json", "content": '{"scenes": {}}'})
        assert r.status_code == 200
        body = r.json()
        assert body["valid"] is True
        assert any("scenes" in w for w in body.get("warnings", []))

    def test_load_missing_file(self, client):
        r = client.get("/editor/load", params={"path": "__no_such__.json"})
        assert r.status_code == 200
        assert "不存在" in r.text

    def test_save_rejects_invalid_json(self, client):
        r = client.post("/editor/save",
                        data={"path": "x.json", "content": "not-json"})
        assert r.status_code == 400


class TestFilesAssetsContract:
    def test_files_listing(self, client):
        r = client.get("/api/files", params={"dir": "data", "format": "json"})
        assert r.status_code == 200
        data = r.json()
        assert "dirs" in data and "files" in data

    def test_assets_list(self, client):
        r = client.get("/api/assets/list")
        assert r.status_code == 200
        data = r.json()
        assert "images" in data and "videos" in data

    def test_assets_random(self, client):
        r = client.get("/api/assets/random")
        assert r.status_code == 200
        assert "url" in r.json()


class TestGameContract:
    def test_game_page(self, client):
        assert client.get("/game").status_code == 200

    def test_turn_contract_keys(self, client):
        fake_result = PlayerTurnResult(
            status=TurnStatus.COMPLETED,
            brief="简报", narrative="叙事",
            skill_results=[], timestamp="12:00:00",
        )
        with patch("frontend.routers.game.session.get_game",
                   return_value=_fake_game_with_spells()), \
             patch("game_loop.run_turn", return_value=fake_result):
            resp = client.post("/api/game/turn", data={"user_input": "看"})
        assert resp.status_code == 200
        data = resp.json()
        missing = _TURN_KEYS - data.keys()
        assert not missing, missing

    def test_scene_and_command(self, client):
        fake = _fake_game_with_spells()
        with patch("frontend.routers.game.session.get_game", return_value=fake):
            scene = client.get("/api/game/scene")
            assert scene.status_code == 200
            assert "书房" in scene.text
            cmd = client.post("/api/game/command", data={"cmd": "/help"})
            assert cmd.status_code == 200
            assert "application/json" in (cmd.headers.get("content-type") or "")
            help_body = cmd.json()
            assert "/scene" in help_body["text"]
            assert "<div" not in help_body["text"]
            scene_cmd = client.post("/api/game/command", data={"cmd": "/scene"})
            assert scene_cmd.status_code == 200
            scene_body = scene_cmd.json()
            assert "书房" in scene_body["text"]
            assert "<div" not in scene_body["text"]

    def test_turn_slash_returns_plain_text(self, client):
        with patch("frontend.routers.game.session.get_game",
                   return_value=_fake_game_with_spells()):
            resp = client.post("/api/game/turn", data={"user_input": "/help"})
        assert resp.status_code == 200
        data = resp.json()
        assert "narrative_html" not in data
        assert set(data["slash"]) == {"text"}
        assert data["brief"] == ""
        assert data["slash"]["text"]
        assert "/scene" in data["narrative"]
        assert data["narrative"] == data["slash"]["text"]

    def test_turn_when_game_none_returns_plain_narrative(self, client):
        with patch("frontend.routers.game.session.get_game", return_value=None):
            resp = client.post("/api/game/turn", data={"user_input": "看"})
        assert resp.status_code == 200
        data = resp.json()
        assert "游戏已退出" in data["narrative"]
        assert "<div" not in data["narrative"]
        html = data.get("narrative_html")
        assert not html or "<div" not in html

    def test_command_when_game_none_returns_plain_text(self, client):
        with patch("frontend.routers.game.session.get_game", return_value=None):
            resp = client.post("/api/game/command", data={"cmd": "/help"})
        assert resp.status_code == 200
        data = resp.json()
        assert "游戏已退出" in data["text"]
        assert "<div" not in data["text"]

    def test_turn_frozen_returns_plain_narrative(self, client):
        fake_result = PlayerTurnResult(
            status=TurnStatus.FROZEN,
            brief="", narrative="系统异常\n详情",
            skill_results=[], timestamp="12:00:00",
        )
        with patch("frontend.routers.game.session.get_game",
                   return_value=_fake_game_with_spells()), \
             patch("game_loop.run_turn", return_value=fake_result):
            resp = client.post("/api/game/turn", data={"user_input": "看"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["game_frozen"] is True
        assert data["frozen_message"] == "系统异常\n详情"
        assert "系统异常" in data["narrative"]
        html = data.get("narrative_html")
        assert not html or "<div" not in html

    def test_autowin_toggle(self, client):
        r = client.post("/api/game/autowin", json={"enabled": True})
        assert r.status_code == 200
        assert r.json()["auto_win"] is True
        r2 = client.post("/api/game/autowin", json={"enabled": False})
        assert r2.json()["auto_win"] is False

    def test_combat_start_requires_session(self, client):
        with patch("frontend.routers.game.session.get_game", return_value=None):
            r = client.post("/api/combat/start", json={"combat_init": {}})
        assert r.status_code == 400

    def test_combat_round_missing_session(self, client):
        r = client.post("/api/combat/round", json={"session_id": "nope"})
        assert r.status_code == 409
        assert r.json()["error"] == "combat_session_lost"

    def test_init_missing_module_500(self, client):
        r = client.post("/api/game/init", data={
            "l2_path": "__no_such_mod__/l2.json",
            "l1_path": "__no_such_mod__/l1.json",
            "l3_path": "__no_such_mod__/l3.json",
        })
        assert r.status_code == 500
        assert "error" in r.json()

    def test_progress_ws_connects(self, client):
        with client.websocket_connect("/api/game/progress"):
            pass


def test_init_char_load_failure_surfaces_warning(client, tmp_path, monkeypatch):
    """B19：角色卡加载失败不再静默——init 响应带 warning。"""
    fake_game = _fake_game_with_spells()
    fake_result = PlayerTurnResult(
        status=TurnStatus.COMPLETED, brief="", narrative="",
        skill_results=[], timestamp="00:00:00",
    )
    monkeypatch.setattr("game_loop.init_game", lambda **k: fake_game)
    monkeypatch.setattr("game_loop.setup_logging", lambda: str(tmp_path))
    monkeypatch.setattr("game_loop.start_autosave", lambda g: None)
    monkeypatch.setattr("game_loop.run_turn", lambda *a, **k: fake_result)
    monkeypatch.setattr("frontend.routers.game.session._init_libraries", lambda *a, **k: None)
    monkeypatch.setattr("frontend.routers.game.session._resolve_start_scene", lambda *a, **k: "书房")

    import os
    real_exists = os.path.exists

    def _exists(p):
        if "broken_char" in str(p):
            return True
        return real_exists(p)

    monkeypatch.setattr(os.path, "exists", _exists)

    def _boom(path):
        raise ValueError("bad character card")

    monkeypatch.setattr("investigator.load_investigator", _boom)
    r = client.post("/api/game/init", data={
        "l2_path": "x/l2.json",
        "l1_path": "x/l1.json",
        "l3_path": "x/l3.json",
        "char_path": "broken_char.json",
    })
    assert r.status_code == 200
    data = r.json()
    assert data.get("warning")
    assert "默认" in data["warning"]


# ── Task 8: GET /api/game/debug 聚合端点 ──

_DEBUG_KEYS = {"recent_turns", "state_snapshot", "scene_entities", "llm_records"}


def _debug_game_with_world():
    """真实 ScenarioWorld + Judge，供 _evaluate_requirement 只读检查。"""
    from tests.e2e.helpers import make_scene, make_world
    from game.judge import Judge

    gated = {
        "id": "IT_X", "entity_type": "interaction",
        "name": "开门", "scene": "room_a",
        "type": "无", "requirement": "flag:FLAG_Y",
        "trigger": "开门", "result": "门开了。",
        "side_effects": [], "difficulty": "", "time_condition": [],
    }
    open_at = {
        "id": "AT_BREEZE", "entity_type": "auto_trigger",
        "name": "风吹过", "scene": "room_a",
        "type": "无", "requirement": "",
        "trigger": "", "result": "一阵风。",
        "side_effects": [], "difficulty": "", "time_condition": [],
    }
    world = make_world(
        {"room_a": make_scene(
            interactions=[gated],
            auto_triggers=[open_at],
            scene_items=[{"kind": "item", "ref": "钥匙", "quantity": 2,
                          "hidden": False}],
        )},
        "room_a",
        npc_profiles={"老王": {
            "name": "老王", "attitude_value": 12, "scene": "room_a",
        }},
    )
    derived = SimpleNamespace(HP=10, HP_MAX=12, MP=8, MP_MAX=11,
                              SAN=55, SAN_MAX=88)
    world.set_player(SimpleNamespace(
        name="张三", derived=derived, timed_effects=[]))
    world.mark_completed("SOME_DONE")
    judge = Judge(world)
    keeper = SimpleNamespace(world=world, judge=judge, turn_number=1)
    return {"keeper": keeper}


def test_debug_endpoint_aggregates(client, monkeypatch, tmp_path):
    """debug 端点 = turn_logs 回放 + 状态快照 + 场景实体可用性。"""
    from game.turn_logger import TurnLogger
    from game_loop import set_turn_logger

    marker = "UNIQUE_PLAYER_INPUT_TASK8"
    logger = TurnLogger(log_dir=str(tmp_path))
    logger.log(marker, None, "简报", "叙事")
    (tmp_path / "narrator.txt").write_text(
        "NARRATOR_PREVIEW_TASK8 hello", encoding="utf-8")
    set_turn_logger(logger)
    monkeypatch.setattr("game_loop._turn_logger", logger)

    fake = _debug_game_with_world()
    from frontend.routers.game import session as game_session
    monkeypatch.setattr(game_session, "_game_instance", fake)
    monkeypatch.setattr(game_session, "_game_quit", False)
    resp = client.get("/api/game/debug", params={"turns": 5})

    assert resp.status_code == 200
    data = resp.json()
    missing = _DEBUG_KEYS - data.keys()
    assert not missing, missing
    assert "data/debug/turn_logs" not in resp.text

    turns = data["recent_turns"]
    assert isinstance(turns, list) and turns
    blob = json.dumps(turns, ensure_ascii=False)
    assert marker in blob

    snap = data["state_snapshot"]
    assert snap["location"] == "room_a"
    assert snap["hp"] == 10
    assert snap["san"] == 55
    assert snap["mp"] == 8
    assert "SOME_DONE" in snap.get("flags", [])

    entities = {e["id"]: e for e in data["scene_entities"]}
    assert "IT_X" in entities
    assert entities["IT_X"]["available"] is False
    assert "FLAG_Y" in entities["IT_X"]["reason"]

    records = data["llm_records"]
    assert isinstance(records, list)
    names = [r.get("filename") or r.get("name") for r in records]
    assert any(n and "narrator" in str(n) for n in names)
    assert "NARRATOR_PREVIEW_TASK8" in json.dumps(records, ensure_ascii=False)


def test_debug_endpoint_no_game(client, monkeypatch):
    """_game_instance is None → 400 JSON {error: no_game}。"""
    from frontend.routers.game import session as game_session
    monkeypatch.setattr(game_session, "_game_instance", None)
    monkeypatch.setattr(game_session, "_game_quit", False)
    resp = client.get("/api/game/debug")
    assert resp.status_code == 400
    assert resp.json() == {"error": "no_game"}


def test_debug_empty_instance_not_lazy_init(client, monkeypatch):
    """_game_instance is None → 400 no_game，且不调用 init_game。"""
    from frontend.routers.game import session as game_session
    monkeypatch.setattr(game_session, "_game_instance", None)
    monkeypatch.setattr(game_session, "_game_quit", False)
    with patch("game_loop.init_game") as init_mock:
        resp = client.get("/api/game/debug")
    assert resp.status_code == 400
    assert resp.json() == {"error": "no_game"}
    init_mock.assert_not_called()


# ── Task 10 / F39: GET /api/game/history ──


def _history_game(n=25):
    from collections import deque
    log = deque(
        [{"turn": i, "brief": f"b{i}", "narrative": f"n{i}"} for i in range(1, n + 1)],
        maxlen=200,
    )
    world = SimpleNamespace(
        chronicle=SimpleNamespace(
            narrative_log=log,
            events=[{"turn": 99, "input": "SECRET_AUTHOR_EVENT"}],
        ),
    )
    return {"keeper": SimpleNamespace(world=world, turn_number=n)}


def test_history_endpoint_no_game(client, monkeypatch):
    """_game_instance is None → 400 JSON {error: no_game}。"""
    from frontend.routers.game import session as game_session
    monkeypatch.setattr(game_session, "_game_instance", None)
    monkeypatch.setattr(game_session, "_game_quit", False)
    resp = client.get("/api/game/history")
    assert resp.status_code == 400
    assert resp.json() == {"error": "no_game"}


def test_history_empty_instance_not_lazy_init(client, monkeypatch):
    """_game_instance is None → 400 no_game，且不调用 init_game。"""
    from frontend.routers.game import session as game_session
    monkeypatch.setattr(game_session, "_game_instance", None)
    monkeypatch.setattr(game_session, "_game_quit", False)
    with patch("game_loop.init_game") as init_mock:
        resp = client.get("/api/game/history")
    assert resp.status_code == 400
    assert resp.json() == {"error": "no_game"}
    init_mock.assert_not_called()


def test_history_endpoint_pagination(client, monkeypatch):
    """newest-first；before_turn 过滤更早页；next_before 为本页最小 turn。"""
    fake = _history_game(25)
    from frontend.routers.game import session as game_session
    monkeypatch.setattr(game_session, "_game_instance", fake)
    monkeypatch.setattr(game_session, "_game_quit", False)
    r1 = client.get("/api/game/history", params={"limit": 5})
    assert r1.status_code == 200
    d1 = r1.json()
    assert set(d1.keys()) == {"items", "next_before"}
    turns = [it["turn"] for it in d1["items"]]
    assert turns == [25, 24, 23, 22, 21]
    for it in d1["items"]:
        assert set(it.keys()) == {"turn", "brief", "narrative"}
        assert it["brief"] == f"b{it['turn']}"
        assert it["narrative"] == f"n{it['turn']}"
    assert d1["next_before"] == 21
    assert "SECRET_AUTHOR_EVENT" not in r1.text

    r2 = client.get("/api/game/history", params={"before_turn": 21, "limit": 5})
    d2 = r2.json()
    assert [it["turn"] for it in d2["items"]] == [20, 19, 18, 17, 16]
    assert d2["next_before"] == 16

    r3 = client.get("/api/game/history", params={"before_turn": 6, "limit": 5})
    d3 = r3.json()
    assert [it["turn"] for it in d3["items"]] == [5, 4, 3, 2, 1]
    assert d3["next_before"] is None

    r4 = client.get("/api/game/history", params={"before_turn": 1, "limit": 5})
    d4 = r4.json()
    assert d4["items"] == []
    assert d4["next_before"] is None


def test_history_endpoint_limit_clamp_and_default(client, monkeypatch):
    fake = _history_game(60)
    from frontend.routers.game import session as game_session
    monkeypatch.setattr(game_session, "_game_instance", fake)
    monkeypatch.setattr(game_session, "_game_quit", False)
    r_hi = client.get("/api/game/history", params={"limit": 999})
    assert len(r_hi.json()["items"]) == 50
    assert r_hi.json()["next_before"] == 11

    r_lo = client.get("/api/game/history", params={"limit": 0})
    assert len(r_lo.json()["items"]) == 1
    assert r_lo.json()["items"][0]["turn"] == 60

    r_def = client.get("/api/game/history")
    assert len(r_def.json()["items"]) == 20
    assert [it["turn"] for it in r_def.json()["items"]] == list(range(60, 40, -1))


# ── Task 12 / F40: 战斗原子化 + 战前快照回滚 ──


def _fake_game_for_combat_snapshot():
    """bootstrap/回滚用：player + 当前场景敌人 + san_seen_sources。"""
    fake = _fake_game_with_spells()
    world = fake["keeper"].world
    e1 = SimpleNamespace(instance_id="e1", hp=20, status="hostile", scene="书房")
    instances = {"e1": e1}
    world.enemies = SimpleNamespace(
        _instances=instances,
        get_by_id=lambda iid, _m=instances: _m.get(iid),
    )
    world.san_seen_sources = {"旧目睹"}
    return fake


def test_state_empty_instance_not_lazy_init(client, monkeypatch):
    """_game_instance is None → in_game=false，且不调用 init_game。"""
    from frontend.routers.game import session as game_session
    monkeypatch.setattr(game_session, "_game_instance", None)
    monkeypatch.setattr(game_session, "_game_quit", False)
    game_session._combat_sessions.clear()
    with patch("game_loop.init_game") as init_mock:
        resp = client.get("/api/game/state")
    assert resp.status_code == 200
    assert resp.json() == {"in_game": False}
    init_mock.assert_not_called()


def test_state_supports_bootstrap(client, monkeypatch):
    """有对局时 state 含 in_game/scene/HUD；无 active_combat 键。"""
    from frontend.routers.game import session as game_session
    monkeypatch.setattr(game_session, "_game_instance", _fake_game_with_spells())
    monkeypatch.setattr(game_session, "_game_quit", False)
    game_session._combat_sessions.clear()
    resp = client.get("/api/game/state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["in_game"] is True
    assert data["location"] == "书房"
    assert data["turn"] == 1
    assert data["hp"] == 10
    assert data["hp_max"] == 12
    assert data["mp"] == 8
    assert data["mp_max"] == 11
    assert data["san"] == 55
    assert data["san_max"] == 88
    assert data["name"] == "张三"
    assert "known_spells" in data
    assert "active_combat" not in data


def test_combat_round_without_session_clean_error(client):
    """无会话 /api/combat/round 返回 409 + combat_session_lost（现网是 400，本 Task 改码，同步改 Task 1 锁的断言）。"""
    from frontend.routers.game import session as game_session
    game_session._combat_sessions.clear()
    r = client.post("/api/combat/round", json={"session_id": "nope"})
    assert r.status_code == 409
    assert r.json() == {"error": "combat_session_lost"}


def test_discard_combat_rolls_back_player_hp(client, monkeypatch):
    """start 后改 HP，丢弃会话 → player HP 回到 start 前。边角字段不锁。"""
    from frontend.routers.game import session as game_session
    from frontend.routers.game.combat import _take_pre_combat_snapshot

    fake = _fake_game_for_combat_snapshot()
    world = fake["keeper"].world
    hp_before = world.player.derived.HP
    monkeypatch.setattr(game_session, "_game_instance", fake)
    monkeypatch.setattr(game_session, "_game_quit", False)
    snap = _take_pre_combat_snapshot(world)
    game_session._combat_sessions.clear()
    game_session._combat_sessions["alive"] = {
        "pre_world": snap,
        "state": object(),
        "combat_init": object(),
    }
    world.player.derived.HP = 3
    world.player.derived.SAN = 1
    world.player.derived.MP = 0

    r = client.post("/api/combat/round", json={"session_id": "nope"})
    assert r.status_code == 409
    assert r.json()["error"] == "combat_session_lost"
    assert world.player.derived.HP == hp_before
    assert game_session._combat_sessions == {}


def test_discard_combat_clears_encounter_latch(monkeypatch):
    """丢弃会话后必须 exit_combat(abort)，否则 _combat_active 卡住无法再遭遇。"""
    from frontend.routers.game import session as game_session
    from frontend.routers.game.combat import (
        _discard_combat_sessions,
        _take_pre_combat_snapshot,
    )

    fake = _fake_game_for_combat_snapshot()
    world = fake["keeper"].world
    e1 = world.enemies._instances["e1"]
    e1.status = "engaged"
    world.enemies._combat_active = True
    world.enemies._combat_enemies = ["e1"]
    exit_calls = []

    def _exit_combat(result):
        exit_calls.append(dict(result))
        outcome = result.get("outcome", "")
        if outcome == "win":
            e1.status = "defeated"
        elif e1.status == "engaged":
            e1.status = "hostile"
        world.enemies._combat_enemies = []
        world.enemies._combat_active = False

    world.enemies.exit_combat = _exit_combat
    monkeypatch.setattr(game_session, "_game_instance", fake)
    monkeypatch.setattr(game_session, "_game_quit", False)
    snap = _take_pre_combat_snapshot(world)
    game_session._combat_sessions.clear()
    game_session._combat_sessions["alive"] = {"pre_world": snap}
    e1.status = "engaged"
    world.enemies._combat_active = True

    _discard_combat_sessions()

    assert world.enemies._combat_active is False
    assert exit_calls == [{"outcome": "abort"}]
    assert e1.status != "defeated"
    assert game_session._combat_sessions == {}


def test_slash_load_clears_combat_sessions_without_apply(monkeypatch):
    """同进程 /load 成功后只清 _combat_sessions，不把旧战前快照写到新档 world。"""
    from frontend.routers.game import session as game_session
    from frontend.routers.game.slash import _handle_slash_command
    from pathlib import Path

    fake = _fake_game_with_spells()
    world = fake["keeper"].world
    hp_before = world.player.derived.HP
    monkeypatch.setattr(game_session, "_game_instance", fake)
    monkeypatch.setattr(game_session, "_game_quit", False)
    game_session._combat_sessions.clear()
    game_session._combat_sessions["stale"] = {
        "pre_world": {
            "hp": 99,
            "san": 1,
            "mp": 0,
            "enemies": {},
            "san_seen_sources": set(),
        },
    }
    monkeypatch.setattr(
        "frontend.routers.game.slash.Path.exists",
        lambda self: Path(self).name == "save_1.json",
    )
    load_called = []

    def _load(game, path):
        load_called.append(path)

    monkeypatch.setattr("game_loop.load_game", _load)
    result = _handle_slash_command("/load 1")

    assert load_called
    assert "读档" in result["text"]
    assert game_session._combat_sessions == {}
    assert world.player.derived.HP == hp_before


