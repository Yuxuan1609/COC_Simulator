"""turn_trace：实体判定流水埋点（不改判定行为）。"""
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "e2e"))

from helpers import make_scene, make_world


def _gated_inter():
    return {
        "id": "IT_X", "entity_type": "interaction",
        "name": "开门", "scene": "room_a",
        "type": "无", "requirement": "flag:FLAG_Y",
        "trigger": "开门", "result": "门开了。",
        "side_effects": [], "difficulty": "", "time_condition": [],
    }


def _open_inter():
    return {
        "id": "IT_OPEN", "entity_type": "interaction",
        "name": "读信", "scene": "room_a",
        "type": "无", "requirement": "",
        "trigger": "读信", "result": "信上写着地址。",
        "side_effects": [], "difficulty": "", "time_condition": [],
    }


def _evaluated(trace):
    return [e for e in (trace or []) if e.get("kind") != "matched"]


def _matched(trace):
    return [e for e in (trace or []) if e.get("kind") == "matched"]


class TestTurnTrace:
    def test_evaluated_entities_recorded(self):
        """回合后 trace 含：评估过的实体 + 各卡在哪（requirement/attitude/time/once）。"""
        from game.judge import Judge

        world = make_world(
            {"room_a": make_scene(interactions=[_gated_inter()])}, "room_a")
        entity = world.graph.nodes["room_a"].interactions[0]
        judge = Judge(world)
        judge._turn_trace = []
        outcome = judge._execute_entity(entity)
        assert not outcome.success
        hits = [e for e in _evaluated(judge._turn_trace) if e.get("id") == "IT_X"]
        assert hits, f"expected evaluated IT_X, got {judge._turn_trace}"
        hit = hits[0]
        assert hit["available"] is False
        assert hit.get("gate") == "requirement"
        assert "FLAG_Y" in hit["reason"] or "需要满足条件" in hit["reason"]

    def test_matched_entity_recorded(self):
        """玩家输入匹配到实体 → trace.matched 含实体 id 与判定结论。"""
        from game.judge import Judge

        world = make_world(
            {"room_a": make_scene(interactions=[_open_inter()])}, "room_a")
        entity = world.graph.nodes["room_a"].interactions[0]
        judge = Judge(world)
        judge._turn_trace = []
        outcome = judge._execute_entity(entity)
        assert outcome.success
        hits = [e for e in _matched(judge._turn_trace) if e.get("id") == "IT_OPEN"]
        if not hits:
            # 允许：evaluated available True + matched 同实体
            ev = [e for e in _evaluated(judge._turn_trace) if e.get("id") == "IT_OPEN"]
            assert ev and ev[0].get("available") is True
            hits = _matched(judge._turn_trace)
        assert hits, f"expected matched IT_OPEN, got {judge._turn_trace}"
        assert hits[0]["success"] is True

    def test_trace_off_by_default_zero_overhead(self):
        """不开 debug 时不分配 trace 列表（零负载约定）。"""
        from fastapi.testclient import TestClient
        from frontend.server import app
        from game.judge import Judge
        from game.messages import PlayerTurnResult, TurnStatus

        world = make_world(
            {"room_a": make_scene(interactions=[_gated_inter()])}, "room_a")
        entity = world.graph.nodes["room_a"].interactions[0]
        judge = Judge(world)
        assert getattr(judge, "_turn_trace", None) is None
        judge._execute_entity(entity)
        assert getattr(judge, "_turn_trace", None) is None

        # OpenAI 客户端在 import game_loop 时要求非空 key；本测 patch run_turn，不发请求。
        os.environ.setdefault("DEEPSEEK_API_KEY", "dummy")
        client = TestClient(app)
        fake_none = PlayerTurnResult(
            status=TurnStatus.COMPLETED, brief="b", narrative="n", debug=None)
        fake_game = SimpleNamespace()
        with patch("frontend.routers.game.session.get_game", return_value=fake_game), \
             patch("game_loop.run_turn", return_value=fake_none) as mock_run:
            resp = client.post("/api/game/turn", data={"user_input": "看"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("debug") is None
        args, kwargs = mock_run.call_args
        if "debug" in kwargs:
            assert kwargs["debug"] is False
        elif args and args[-1] is True:
            raise AssertionError("debug OFF 不应把 True 传进 run_turn")

        fake_on = PlayerTurnResult(
            status=TurnStatus.COMPLETED, brief="b", narrative="n",
            debug={"evaluated": [], "matched": []})
        with patch("frontend.routers.game.session.get_game", return_value=fake_game), \
             patch("game_loop.run_turn", return_value=fake_on) as mock_run:
            resp = client.post("/api/game/turn",
                               data={"user_input": "看", "debug": "1"})
        assert resp.status_code == 200
        args, kwargs = mock_run.call_args
        assert kwargs.get("debug") is True or (args and args[-1] is True), (
            f"debug=1 应传入 run_turn, got args={args!r} kwargs={kwargs!r}")
        assert resp.json().get("debug") == {"evaluated": [], "matched": []}

    def test_run_turn_copies_trace_onto_player_result(self):
        """debug ON 把 keeper._turn_trace 拷到 PlayerTurnResult.debug；OFF 为 None。"""
        os.environ.setdefault("DEEPSEEK_API_KEY", "dummy")
        from game.messages import PendingInteraction, TurnResult, TurnStatus
        from game_loop import run_turn

        def process_turn(ti, author=None, **_kw):
            keeper._turn_trace = [
                {"kind": "evaluated", "id": "IT_X", "available": False,
                 "gate": "requirement", "reason": "需要满足条件「FLAG_Y」"},
                {"kind": "matched", "id": "IT_X", "success": False,
                 "reason": "需要满足条件「FLAG_Y」"},
            ]
            return TurnResult(
                status=TurnStatus.SUSPENDED, text="？",
                pending_interaction=PendingInteraction(
                    kind="clarify", question="？", interaction_id="clarify"),
            )

        keeper = SimpleNamespace(
            turn_number=1, _standoff_pending=None,
            process_turn=process_turn, world=SimpleNamespace(player=None),
        )
        game = {"keeper": keeper, "narrator": SimpleNamespace(), "author": None}
        on = run_turn(game, "看", debug=True)
        assert on.debug is not None
        assert on.debug["evaluated"][0]["id"] == "IT_X"
        assert on.debug["evaluated"][0]["available"] is False
        assert on.debug["matched"][0]["id"] == "IT_X"
        off = run_turn(game, "看", debug=False)
        assert off.debug is None
