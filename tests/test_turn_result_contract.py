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
