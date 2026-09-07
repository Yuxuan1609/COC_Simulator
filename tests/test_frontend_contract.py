"""Frontend router consumes PlayerTurnResult correctly."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

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


# ── 统一资源层:player-status / character-card 的 MP 与已知法术接线 ──

def _fake_game_with_spells():
    derived = SimpleNamespace(HP=10, HP_MAX=12, MP=8, MP_MAX=11, SAN=55,
                              SAN_MAX=88, MOV=8, DB="1D4", BUILD=1, DODGE=50)
    player = SimpleNamespace(
        name="张三", age=30, gender="男", occupation=None, avatar_url="",
        derived=derived, known_spells=["HEART_ARREST", "GHOST"],
        stats=SimpleNamespace(STR=60, CON=65, SIZ=55, DEX=70, APP=50,
                              INT=75, POW=70, EDU=80, LUCK=50),
        skills={}, weapons=[], appearance="", personal_description="",
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


def test_character_card_shows_mp_max_and_spells(client):
    with patch("frontend.routers.game.session.get_game", return_value=_fake_game_with_spells()):
        resp = client.get("/api/game/character-card")
    assert resp.status_code == 200
    html = resp.text
    assert "8/11" in html                      # MP 当前/上限
    assert "已知法术" in html                  # 法术列表区
    assert "心脏骤停" in html                  # 库内法术名
    assert "GHOST" in html                     # 库外引用降级展示


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


def test_game_state_includes_san_max(client):
    """F2:/api/game/state 暴露 san_max。"""
    with patch("frontend.routers.game.session.get_game", return_value=_fake_game_with_spells()):
        resp = client.get("/api/game/state")
    assert resp.status_code == 200
    assert resp.json()["san_max"] == 88


def test_character_card_san_bar_uses_san_max(client):
    """F2:角色卡 SAN bar 分母用 SAN_MAX 而非硬编码 99(55/88→62.5%)。"""
    with patch("frontend.routers.game.session.get_game", return_value=_fake_game_with_spells()):
        resp = client.get("/api/game/character-card")
    assert resp.status_code == 200
    assert "62.5%" in resp.text


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
            assert "/scene" in cmd.text or "help" in cmd.text.lower() or "<" in cmd.text

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
        assert r.status_code == 400

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

