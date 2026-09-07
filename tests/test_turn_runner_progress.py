"""F42：TurnRunner.on_phase 真实进度 + run_turn 对外步名（零 LLM）。"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("DEEPSEEK_API_KEY", "dummy")

from game.messages import (
    NarratorBrief, PendingInteraction, SceneSnapshot, TurnInput,
    TurnResult, TurnStatus,
)
from game.turn.context import Early
from game.turn.runner import TurnRunner


PHASE_ORDER = ("understand", "adjudicate", "encounter", "enrich", "finalize")


def _mini_keeper():
    return SimpleNamespace(
        judge=None,
        _apply_pending=lambda: None,
        _build_frozen_response=lambda e: TurnResult(
            status=TurnStatus.FROZEN, text=str(e) or "frozen",
            frozen_message=str(e) or "frozen"),
        _process_deterministic_only=lambda ti: TurnResult(
            status=TurnStatus.COMPLETED, text="det"),
        _turn_trace=None,
    )


def _stub_phases(monkeypatch, *, early=None):
    def noop(ctx, acc, tools):
        return None

    def finalize(ctx, acc, tools):
        acc.result = TurnResult(status=TurnStatus.COMPLETED, text="ok")
        return None

    def understand_early(ctx, acc, tools):
        return Early(TurnResult(
            status=TurnStatus.SUSPENDED, text="？",
            pending_interaction=PendingInteraction(
                kind="clarify", question="？", interaction_id="clarify"),
        ))

    monkeypatch.setattr(
        "game.turn.understand.phase_a_understand",
        understand_early if early == "understand" else noop)
    monkeypatch.setattr("game.turn.adjudicate.phase_b_adjudicate", noop)
    monkeypatch.setattr("game.turn.encounter.phase_c_encounter", noop)
    monkeypatch.setattr("game.turn.enrich.phase_d_enrich", noop)
    monkeypatch.setattr("game.turn.finalize.phase_e_finalize", finalize)


def test_phase_callbacks_fire_in_order(monkeypatch):
    """on_phase 按 understand→adjudicate→encounter→enrich→finalize 顺序触发（runner 内部名）。"""
    _stub_phases(monkeypatch)
    seen = []
    runner = TurnRunner(_mini_keeper())
    result = runner.execute(
        TurnInput(raw_text="看"),
        on_phase=lambda name, status: seen.append((name, status)),
    )
    assert result.status == TurnStatus.COMPLETED
    names = [s[0] for s in seen if s[1] == "done"]
    assert names == list(PHASE_ORDER)
    starts = [s[0] for s in seen if s[1] == "start"]
    assert starts == list(PHASE_ORDER)


def test_early_exit_still_completes(monkeypatch):
    """Early/SUSPENDED 早退：只推已执行相位，且 run_turn 层最终推 complete。"""
    _stub_phases(monkeypatch, early="understand")
    seen = []
    runner = TurnRunner(_mini_keeper())
    result = runner.execute(
        TurnInput(raw_text="看"),
        on_phase=lambda name, status: seen.append((name, status)),
    )
    assert result.status == TurnStatus.SUSPENDED
    names = [s[0] for s in seen if s[1] == "done"]
    assert names == ["understand"]
    assert [s[0] for s in seen if s[1] == "start"] == ["understand"]

    from game_loop import run_turn

    events = []
    narrate_calls = []

    def process_turn(ti, author=None, on_phase=None, **_kw):
        if on_phase:
            on_phase("understand", "start")
            on_phase("understand", "done")
        return TurnResult(
            status=TurnStatus.SUSPENDED, text="？",
            pending_interaction=PendingInteraction(
                kind="clarify", question="？", interaction_id="clarify"),
        )

    keeper = SimpleNamespace(
        turn_number=1, _standoff_pending=None,
        process_turn=process_turn, world=SimpleNamespace(player=None, chronicle=None),
    )
    narrator = SimpleNamespace(
        l1_data=None,
        narrate=lambda *a, **k: (narrate_calls.append("narrate") or ("b", "n", None)),
    )
    game = {"keeper": keeper, "narrator": narrator, "author": None}
    out = run_turn(
        game, "看",
        on_progress=lambda step, status: events.append((step, status)),
    )
    assert out.status == TurnStatus.SUSPENDED
    assert narrate_calls == []
    assert events[-1] == ("complete", "")
    done_ext = [s[0] for s in events if s[1] == "done"]
    assert done_ext == ["parse"]
    assert "narrate" not in [s[0] for s in events]
    assert "judge" not in [s[0] for s in events]


def test_narrate_pushed_around_actual_narrate(monkeypatch):
    """对外步名 narrate 在 narrator.narrate 调用期间，不在 finalize/curate 时提前。"""
    from game_loop import run_turn

    log = []
    brief = NarratorBrief(
        action_outcomes=[], ambient_changes=[],
        scene_snapshot=SceneSnapshot(
            location="room_a", description="d", exits=[],
            perceptible_interactions=[], visible_npcs=[]),
        suggested_emphasis="",
    )

    def process_turn(ti, author=None, on_phase=None, **_kw):
        if on_phase:
            for name in PHASE_ORDER:
                on_phase(name, "start")
                on_phase(name, "done")
        return TurnResult(status=TurnStatus.COMPLETED, brief=brief)

    def narrate(*_a, **_k):
        log.append("inside_narrate")
        return "nb", "narrative", None

    keeper = SimpleNamespace(
        turn_number=1, _standoff_pending=None,
        process_turn=process_turn,
        world=SimpleNamespace(
            player=None, npcs=None, enemies=None, chronicle=None,
            current_location="room_a",
            get_current_description=lambda: "",
            get_possible_exits=lambda: [],
            clock=SimpleNamespace(to_dict=lambda: {}),
            memory=SimpleNamespace(add_record=lambda *a, **k: None),
            build_snapshot=lambda: {},
            apply_scene_update=lambda u: None,
        ),
    )
    game = {
        "keeper": keeper,
        "narrator": SimpleNamespace(l1_data=None, narrate=narrate),
        "author": None,
    }
    run_turn(game, "看", on_progress=lambda step, status: log.append((step, status)))

    assert ("narrate", "start") in log
    assert "inside_narrate" in log
    assert ("narrate", "done") in log
    i_start = log.index(("narrate", "start"))
    i_inside = log.index("inside_narrate")
    i_done = log.index(("narrate", "done"))
    assert i_start < i_inside < i_done
    assert log[-1] == ("complete", "")
    assert ("finalize", "start") not in log
    assert ("finalize", "done") not in log
    assert ("curate", "done") in log
    narrate_pairs = [x for x in log if x in (("narrate", "start"), ("narrate", "done"))]
    assert narrate_pairs == [("narrate", "start"), ("narrate", "done")]
    i_curate_done = log.index(("curate", "done"))
    assert i_curate_done < i_start


def test_turn_py_no_fake_burst_progress():
    """turn.py 不得在 executor 返回后一次推完 parse…complete；须 call_soon_threadsafe。"""
    src = Path(__file__).resolve().parents[1] / "frontend" / "routers" / "game" / "turn.py"
    text = src.read_text(encoding="utf-8")
    burst = r"".join(
        rf"""_push_progress\(\s*["']{s}["']\s*,\s*["']done["']\s*\)\s*"""
        for s in ("parse", "judge", "enrich", "combat_entry", "curate", "narrate")
    )
    assert not re.search(burst, text), "假进度连推必须删除"
    assert "call_soon_threadsafe" in text
    assert "on_progress" in text
