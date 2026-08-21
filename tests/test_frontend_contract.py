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
            kind="weapon_offer", question="是否拾取？（是/否）",
            interaction_id="weapon_offer"),
        skill_results=[], timestamp="12:00:00",
    )
    fake_game = SimpleNamespace()
    with patch("frontend.routers.game.get_game", return_value=fake_game), \
         patch("game_loop.run_turn", return_value=fake_result):
        resp = client.post("/api/game/turn", data={"user_input": "搜索桌子"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["pending_interaction"]["kind"] == "weapon_offer"
    assert data["pending_interaction"]["question"] == "是否拾取？（是/否）"
    assert "standoff_prompt" not in data
    assert "full" not in data
    assert "time_agent" not in data


# ── 统一资源层:player-status / character-card 的 MP 与已知法术接线 ──

def _fake_game_with_spells():
    derived = SimpleNamespace(HP=10, HP_MAX=12, MP=8, MP_MAX=11, SAN=55,
                              MOV=8, DB="1D4", BUILD=1, DODGE=50)
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
