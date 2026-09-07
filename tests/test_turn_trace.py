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

    def test_time_gate_fail_overwrites_parse_match(self):
        """adjudicate 时间门失败 → evaluated.gate=time 且 matched.success=False。"""
        import json
        from game.clock import GameClock
        from game.judge import Judge
        from game.messages import TurnInput
        from game.turn.adjudicate import phase_b_adjudicate
        from game.turn.context import TurnAccumulator, TurnContext

        inter = {
            "id": "IT_NIGHT", "entity_type": "interaction",
            "name": "夜探", "scene": "room_a",
            "type": "无", "requirement": "",
            "trigger": "夜探", "result": "你摸进了暗巷。",
            "side_effects": [], "difficulty": "",
            "time_condition": json.dumps(
                [{"day": "ALL", "times": ["凌晨"]}], ensure_ascii=False),
        }
        world = make_world({"room_a": make_scene(interactions=[inter])}, "room_a")
        world.clock = GameClock(start_time=12 * 60)  # 白天
        entity = world.graph.nodes["room_a"].interactions[0]
        judge = Judge(world)
        judge._turn_trace = [
            {"kind": "matched", "id": "IT_NIGHT", "success": True,
             "reason": "parse匹配"},
        ]
        tools = SimpleNamespace(
            world=world, judge=judge,
            _find_entity_by_id=lambda eid: entity if eid == "IT_NIGHT" else None,
            _pending_side_effects=[],
        )
        ctx = TurnContext(turn_input=TurnInput(raw_text="夜探"), raw="夜探",
                          trace=judge._turn_trace)
        acc = TurnAccumulator()
        acc.parse_result = [{"type": "interaction", "id": "IT_NIGHT"}]
        phase_b_adjudicate(ctx, acc, tools)

        ev = [e for e in _evaluated(judge._turn_trace) if e.get("id") == "IT_NIGHT"]
        assert ev, f"expected time-gate evaluated, got {judge._turn_trace}"
        assert ev[-1]["gate"] == "time"
        assert ev[-1]["available"] is False
        matched = [e for e in _matched(judge._turn_trace) if e.get("id") == "IT_NIGHT"]
        assert matched and matched[-1]["success"] is False

    def test_requirement_fail_overwrites_parse_match(self):
        """requirement 闸门失败覆盖 parse 的 matched.success=True。"""
        from game.judge import Judge

        world = make_world(
            {"room_a": make_scene(interactions=[_gated_inter()])}, "room_a")
        entity = world.graph.nodes["room_a"].interactions[0]
        judge = Judge(world)
        judge._turn_trace = [
            {"kind": "matched", "id": "IT_X", "success": True,
             "reason": "parse匹配"},
        ]
        outcome = judge._execute_entity(entity)
        assert not outcome.success
        matched = [e for e in _matched(judge._turn_trace) if e.get("id") == "IT_X"]
        assert matched and matched[-1]["success"] is False
        ev = [e for e in _evaluated(judge._turn_trace) if e.get("id") == "IT_X"]
        assert ev and ev[-1]["available"] is False
        assert ev[-1].get("gate") == "requirement"
