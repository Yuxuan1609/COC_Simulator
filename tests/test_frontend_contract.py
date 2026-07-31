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
