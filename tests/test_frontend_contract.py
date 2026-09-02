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
    with patch("frontend.routers.game.get_game", return_value=fake_game), \
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
    )
    return {"keeper": SimpleNamespace(world=world, turn_number=1)}


def test_player_status_json_includes_mp_and_known_spells(client):
    with patch("frontend.routers.game.get_game", return_value=_fake_game_with_spells()):
        resp = client.get("/api/game/player-status?format=json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mp"] == 8
    assert data["mp_max"] == 11
    # 库内 id 解析为中文名,库外 id 原样保留
    assert data["known_spells"] == ["心脏骤停", "GHOST"]


def test_character_card_shows_mp_max_and_spells(client):
    with patch("frontend.routers.game.get_game", return_value=_fake_game_with_spells()):
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
    with patch("frontend.routers.game.get_game", return_value=_fake_game_with_spells()):
        resp = client.get("/api/game/player-status?format=json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["san_max"] == 88
    assert data["san_max"] >= data["san"]


def test_game_state_includes_san_max(client):
    """F2:/api/game/state 暴露 san_max。"""
    with patch("frontend.routers.game.get_game", return_value=_fake_game_with_spells()):
        resp = client.get("/api/game/state")
    assert resp.status_code == 200
    assert resp.json()["san_max"] == 88


def test_character_card_san_bar_uses_san_max(client):
    """F2:角色卡 SAN bar 分母用 SAN_MAX 而非硬编码 99(55/88→62.5%)。"""
    with patch("frontend.routers.game.get_game", return_value=_fake_game_with_spells()):
        resp = client.get("/api/game/character-card")
    assert resp.status_code == 200
    assert "62.5%" in resp.text


def test_combat_state_frontend_serialization_includes_san_max():
    """F2:战斗 state 前端序列化含 player_san_max;CombatState 默认 99。"""
    from game.combat import CombatState
    from frontend.routers.game import _serialize_combat_state_for_frontend
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
