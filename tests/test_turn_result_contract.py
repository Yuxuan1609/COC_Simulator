"""TurnResult / PlayerTurnResult contract unit tests."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from game.messages import (
    TurnStatus, PendingInteraction, EndingInfo, TurnDiagnostics,
    TurnResult, PlayerTurnResult,
)


class TestTurnResultInvariants:
    def test_suspended_requires_pending_interaction(self):
        with pytest.raises(ValueError):
            TurnResult(status=TurnStatus.SUSPENDED, text="问题？")

    def test_suspended_with_pending_ok(self):
        r = TurnResult(
            status=TurnStatus.SUSPENDED,
            text="你要怎么做？",
            pending_interaction=PendingInteraction(
                kind="clarify", question="你要怎么做？", interaction_id="clarify"),
        )
        assert r.status == TurnStatus.SUSPENDED
        assert r.pending_interaction.kind == "clarify"

    def test_brief_none_requires_text(self):
        with pytest.raises(ValueError):
            TurnResult(status=TurnStatus.COMPLETED)

    def test_completed_with_pending_interaction_ok(self):
        """offer/standoff: 回合完成 + 留有追问。"""
        from game.messages import NarratorBrief, SceneSnapshot
        brief = NarratorBrief(
            action_outcomes=[], ambient_changes=[],
            scene_snapshot=SceneSnapshot(
                location="房间", description="", exits=[],
                perceptible_interactions=[], visible_npcs=[]),
            suggested_emphasis="")
        r = TurnResult(
            status=TurnStatus.COMPLETED,
            brief=brief,
            pending_interaction=PendingInteraction(
                kind="weapon_offer", question="是否拾取？",
                interaction_id="weapon_offer"),
        )
        assert r.pending_interaction is not None

    def test_frozen_carries_message(self):
        r = TurnResult(status=TurnStatus.FROZEN,
                       text="系统异常", frozen_message="系统异常")
        assert r.status == TurnStatus.FROZEN
        assert r.text == "系统异常"
        assert r.frozen_message == "系统异常"

    def test_suspended_must_not_carry_brief(self):
        from game.messages import NarratorBrief, SceneSnapshot
        brief = NarratorBrief(
            action_outcomes=[], ambient_changes=[],
            scene_snapshot=SceneSnapshot(
                location="房间", description="", exits=[],
                perceptible_interactions=[], visible_npcs=[]),
            suggested_emphasis="")
        with pytest.raises(ValueError):
            TurnResult(
                status=TurnStatus.SUSPENDED,
                text="问题？",
                brief=brief,
                pending_interaction=PendingInteraction(
                    kind="clarify", question="问题？", interaction_id="clarify"),
            )

    def test_diagnostics_defaults(self):
        r = TurnResult(status=TurnStatus.COMPLETED, text="ok")
        assert r.diagnostics.combat_entry is None
        assert r.diagnostics.time_agent is None
        assert r.npc_events == []


class TestPlayerTurnResult:
    def test_minimal_construction(self):
        r = PlayerTurnResult(status=TurnStatus.COMPLETED, brief="b", narrative="n")
        assert r.game_over is False
        assert r.diagnostics == {}

    def test_ending_info(self):
        e = EndingInfo(name="结局A", narrative="你死了", game_over=True)
        r = PlayerTurnResult(status=TurnStatus.COMPLETED, brief="b",
                             narrative="n", ending=e, game_over=True)
        assert r.ending.name == "结局A"


class TestEnrichedSummary:
    def _make_curator(self, description="黑暗的房间"):
        from game.curator import Curator
        from unittest.mock import MagicMock
        world = MagicMock()
        node = MagicMock()
        node.description = description
        node.interactions = []
        world._current_node.return_value = node
        world.current_location = "房间"
        world.get_possible_exits.return_value = []
        world.completed_interactions = {}
        world.npcs = None
        return Curator(world)

    def test_curator_passes_enriched_summary(self):
        brief = self._make_curator().assemble(
            [], [], emphasis="", enriched_summary="合并叙事文本")
        assert brief.enriched_summary == "合并叙事文本"

    def test_curator_default_empty_summary(self):
        brief = self._make_curator("").assemble([], [], "")
        assert brief.enriched_summary == ""


class TestProcessTurnReturnsContract:
    """process_turn 各返回路径产出合法 TurnResult。"""
    import json as _json

    def _scene(self, interactions=None, exits=None):
        return {
            "interactions": interactions or [], "auto_triggers": [],
            "from_here": exits or [], "to_here": [], "encounters": [],
            "scene_weapons": [], "extra": {}, "description": "",
        }

    def _stub_llm(self, keeper, monkeypatch, parse_results=None):
        from game.messages import PreParseResult
        calls = list(parse_results or [[{"type": "other", "text": "站着不动"}]])
        keeper.pre_parse.disambiguate = lambda *a, **k: PreParseResult(
            clarity="clear", interpretation="", question="", resolved_text="")
        keeper._parse = lambda raw: calls.pop(0) if len(calls) > 1 else calls[0]
        keeper._enrich = lambda e, r: {"results": "", "reasoning": "", "emphasis_hint": ""}
        keeper._run_time_agent = lambda a, r: {"time_delta": 0, "narrative_hint": ""}
        monkeypatch.setattr("game.agents.keeper.call_deepseek",
                            lambda *a, **k: self._json.dumps(
                                {"enter_combat": False, "enemy_instance_ids": [],
                                 "reasoning": ""}, ensure_ascii=False))

    def test_ambiguous_returns_suspended(self, monkeypatch):
        from scenario_core import DirectedGraph, ScenarioWorld
        from game.messages import TurnInput, PreParseResult
        from game.agents.keeper import Keeper
        world = ScenarioWorld(DirectedGraph(
            scenes={"room_a": self._scene()}, events=[]), start_node="room_a")
        keeper = Keeper(world)
        keeper.pre_parse.disambiguate = lambda *a, **k: PreParseResult(
            clarity="ambiguous", interpretation="模糊", question="你想检查哪里？",
            resolved_text="")
        result = keeper.process_turn(TurnInput(raw_text="看看"), author=None)
        assert result.status == TurnStatus.SUSPENDED
        assert result.pending_interaction.kind == "clarify"
        assert result.pending_interaction.question == "你想检查哪里？"

    def test_normal_turn_returns_completed_with_brief(self, monkeypatch):
        from scenario_core import DirectedGraph, ScenarioWorld
        from game.messages import TurnInput
        from game.agents.keeper import Keeper
        world = ScenarioWorld(DirectedGraph(
            scenes={"room_a": self._scene()}, events=[]), start_node="room_a")
        keeper = Keeper(world)
        self._stub_llm(keeper, monkeypatch)
        result = keeper.process_turn(TurnInput(raw_text="四处看看"), author=None)
        assert result.status == TurnStatus.COMPLETED
        assert result.brief is not None
        assert hasattr(result.brief, "action_outcomes")

    def test_move_shortcut_invalid_target_returns_completed_text(self, monkeypatch):
        from scenario_core import DirectedGraph, ScenarioWorld
        from game.messages import TurnInput
        from game.agents.keeper import Keeper
        world = ScenarioWorld(DirectedGraph(
            scenes={"room_a": self._scene()}, events=[]), start_node="room_a")
        keeper = Keeper(world)
        result = keeper.process_turn(
            TurnInput(raw_text="", action_type="move", action_target="不存在的场景"),
            author=None)
        assert result.status == TurnStatus.COMPLETED
        assert result.brief is None
        assert "无法移动" in result.text

    def test_standoff_seeds_pending_and_interaction(self, monkeypatch, tmp_path):
        """standoff 提问：COMPLETED + pending_interaction，且播种 _standoff_pending。"""
        import json
        from scenario_core import DirectedGraph, ScenarioWorld
        from game.messages import TurnInput
        from game.agents.keeper import Keeper
        from library.enemies import EnemyLibrary, LibraryEnemy
        lib = EnemyLibrary()
        lib._enemies["深潜者"] = LibraryEnemy.from_dict({
            "name": "深潜者", "type": "怪物",
            "attributes": {"CON": 50, "SIZ": 50}, "armor": "",
            "attacks": [], "special_abilities": [], "san_loss": "0",
            "description": "", "combat_behavior": "",
        })
        world = ScenarioWorld(DirectedGraph(
            scenes={"room_a": self._scene()}, events=[]),
            start_node="room_a", enemy_library=lib)
        inst = world.enemies.spawn("深潜者", "room_a", 1)
        inst.flags = ["avoidable"]
        keeper = Keeper(world)
        self._stub_llm(keeper, monkeypatch)
        monkeypatch.setattr("game.agents.keeper.call_deepseek",
                            lambda *a, **k: json.dumps(
                                {"enter_combat": True, "enemy_instance_ids": [],
                                 "reasoning": "遭遇"}, ensure_ascii=False))
        result = keeper.process_turn(TurnInput(raw_text="继续前进"), author=None)
        assert result.status == TurnStatus.COMPLETED
        assert result.pending_interaction is not None
        assert result.pending_interaction.kind == "standoff"
        assert keeper._standoff_pending is not None, "必须播种 _standoff_pending"

    def test_standoff_pending_cleared_at_turn_entry(self, monkeypatch):
        """回合入口必须清理 _standoff_pending，避免陈旧状态泄漏到后续回合。"""
        from scenario_core import DirectedGraph, ScenarioWorld
        from game.messages import TurnInput
        from game.agents.keeper import Keeper
        world = ScenarioWorld(DirectedGraph(
            scenes={"room_a": self._scene()}, events=[]), start_node="room_a")
        keeper = Keeper(world)
        self._stub_llm(keeper, monkeypatch)
        keeper._standoff_pending = {"fake": True}
        result = keeper.process_turn(TurnInput(raw_text="四处看看"), author=None)
        assert result.status == TurnStatus.COMPLETED
        assert keeper._standoff_pending is None


class TestRunTurnContract:
    def test_run_turn_returns_player_turn_result(self, monkeypatch):
        """run_turn 产出 PlayerTurnResult；SUSPENDED 透传 pending_interaction。"""
        from types import SimpleNamespace
        from game_loop import run_turn

        fake_keeper = SimpleNamespace(
            turn_number=1,
            _weapon_offer=None,
            _standoff_pending=None,
            process_turn=lambda ti, author=None: TurnResult(
                status=TurnStatus.SUSPENDED,
                text="你想检查哪里？",
                pending_interaction=PendingInteraction(
                    kind="clarify", question="你想检查哪里？",
                    interaction_id="clarify"),
            ),
        )
        fake_world = SimpleNamespace(player=None)
        fake_keeper.world = fake_world
        game = {"keeper": fake_keeper, "narrator": SimpleNamespace(),
                "author": None}
        result = run_turn(game, "看看")
        assert isinstance(result, PlayerTurnResult)
        assert result.status == TurnStatus.SUSPENDED
        assert result.pending_interaction.kind == "clarify"
        assert result.narrative == "你想检查哪里？"

    def test_run_turn_dispatches_pending_standoff(self, monkeypatch):
        """keeper._standoff_pending 存在时，run_turn 路由到 continue_standoff。"""
        from types import SimpleNamespace
        import game_loop
        from game_loop import run_turn

        calls = {}
        def fake_continue(keeper, player_input):
            calls["routed"] = player_input
            return TurnResult(status=TurnStatus.COMPLETED, text="对峙化解。")
        monkeypatch.setattr(game_loop, "continue_standoff", fake_continue)

        fake_keeper = SimpleNamespace(
            turn_number=2,
            _weapon_offer=None,
            _standoff_pending={"group": "深潜者"},
            process_turn=lambda ti, author=None: (_ for _ in ()).throw(
                AssertionError("不应走到 process_turn")),
        )
        fake_keeper.world = SimpleNamespace(
            player=None,
            npcs=None,
            enemies=None,
            current_location="room_a",
            get_current_description=lambda: "",
            get_possible_exits=lambda: [],
            clock=SimpleNamespace(to_dict=lambda: {}),
        )
        game = {"keeper": fake_keeper,
                "narrator": SimpleNamespace(l1_data=None),
                "author": None}
        result = run_turn(game, "我举起双手")
        assert calls.get("routed") == "我举起双手"
        assert result.status == TurnStatus.COMPLETED
        assert "对峙化解" in (result.narrative or result.brief)


class TestStandoffContinuation:
    def _build_standoff_keeper(self, monkeypatch):
        """世界+keeper：room_a 有一只 avoidable 深潜者，process_turn 已产生 standoff。"""
        import json
        from scenario_core import DirectedGraph, ScenarioWorld
        from game.messages import TurnInput, PreParseResult
        from game.agents.keeper import Keeper
        from library.enemies import EnemyLibrary, LibraryEnemy
        from investigator import Investigator

        lib = EnemyLibrary()
        lib._enemies["深潜者"] = LibraryEnemy.from_dict({
            "name": "深潜者", "type": "怪物",
            "attributes": {"CON": 200, "SIZ": 200}, "armor": "",
            "attacks": [], "special_abilities": [], "san_loss": "0",
            "description": "", "combat_behavior": "",
        })
        scene = {
            "interactions": [], "auto_triggers": [], "from_here": [],
            "to_here": [], "encounters": [], "scene_weapons": [],
            "extra": {}, "description": "",
        }
        world = ScenarioWorld(DirectedGraph(
            scenes={"room_a": scene}, events=[]),
            start_node="room_a", enemy_library=lib)
        player = Investigator(name="测试员", age=25, gender="男")
        player.derived.HP = 3
        player.derived.HP_MAX = 3
        world.set_player(player)
        inst = world.enemies.spawn("深潜者", "room_a", 1)
        inst.flags = ["avoidable"]

        keeper = Keeper(world)
        keeper.pre_parse.disambiguate = lambda *a, **k: PreParseResult(
            clarity="clear", interpretation="", question="", resolved_text="")
        keeper._parse = lambda raw: [{"type": "other", "text": raw}]
        keeper._enrich = lambda e, r: {"results": "", "reasoning": "", "emphasis_hint": ""}
        keeper._run_time_agent = lambda a, r: {"time_delta": 0, "narrative_hint": ""}
        monkeypatch.setattr("llm.call_deepseek",
                            lambda *a, **k: json.dumps(
                                {"summary": "战斗结束"}, ensure_ascii=False))
        monkeypatch.setattr("game.agents.keeper.call_deepseek",
                            lambda *a, **k: json.dumps(
                                {"enter_combat": True, "enemy_instance_ids": [],
                                 "reasoning": "遭遇"}, ensure_ascii=False))
        turn = keeper.process_turn(TurnInput(raw_text="前进"), author=None)
        assert turn.pending_interaction is not None
        assert turn.pending_interaction.kind == "standoff"
        monkeypatch.setattr(
            "game.agents.keeper.call_deepseek",
            lambda *a, **k: json.dumps(
                {"matched": False, "skill_name": "", "reason": ""},
                ensure_ascii=False))
        return keeper

    def test_continue_standoff_returns_turn_result(self, monkeypatch):
        """standoff 未匹配 → 内联战斗 → TurnResult：brief 携带战斗结果，combat_init 为 None。"""
        from game_loop import continue_standoff
        keeper = self._build_standoff_keeper(monkeypatch)
        result = continue_standoff(keeper, "我举起双手")
        assert isinstance(result, TurnResult)
        assert result.status == TurnStatus.COMPLETED
        assert result.combat_init is None, "内联战斗已执行，不得再返回 combat_init"
        assert result.brief is not None or result.text
        if result.brief is not None:
            assert any("战斗" in o.message for o in result.brief.action_outcomes)
        else:
            assert "战斗结束" in result.text

    def test_combat_narrative_fallback_when_replay_skipped(self, monkeypatch):
        """complete_combat_turn 无法重放（_last_outcomes 空）时，战斗叙事仍须到达 text。"""
        from game_loop import continue_standoff
        keeper = self._build_standoff_keeper(monkeypatch)
        keeper._last_outcomes = []
        result = continue_standoff(keeper, "我举起双手")
        assert isinstance(result, TurnResult)
        assert result.status == TurnStatus.COMPLETED
        assert result.combat_init is None
        assert result.brief is None
        assert "战斗结束" in result.text
