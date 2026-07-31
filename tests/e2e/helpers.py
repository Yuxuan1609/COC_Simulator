"""E2E 测试共享基建：world 工厂、LLM stub、契约审计。"""
import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def load_env():
    """真实 LLM 测试用：加载 .env 中的 API key。"""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))


def make_scene(interactions=None, exits=None, **overrides):
    scene = {
        "interactions": interactions or [], "auto_triggers": [],
        "from_here": exits or [], "to_here": [], "encounters": [],
        "scene_weapons": [], "extra": {}, "description": "",
    }
    scene.update(overrides)
    return scene


def make_world(scenes, start_node, npc_profiles=None, enemy_library=None,
               weapon_library=None):
    from scenario_core import DirectedGraph, ScenarioWorld
    return ScenarioWorld(
        DirectedGraph(scenes=scenes, events=[]),
        start_node=start_node,
        npc_profiles=npc_profiles,
        enemy_library=enemy_library,
        weapon_library=weapon_library,
    )


def stub_keeper_llm(keeper, monkeypatch, parse_results=None, combat_entry=None,
                    time_delta=0):
    """Stub keeper 的全部 LLM 触点（确定性 E2E 用，零 API 调用）。

    parse_results: list of parse 结果（list of entry dict）；多回合时按序弹出，
                   最后一个结果复用。
    combat_entry: dict，覆盖 combat entry 判定响应；默认不进入战斗。
    time_delta: time agent 返回的时间推进分钟数。
    """
    from game.messages import PreParseResult
    calls = list(parse_results if parse_results is not None
                 else [[{"type": "other", "text": "站着不动"}]])
    keeper.pre_parse.disambiguate = lambda *a, **k: PreParseResult(
        clarity="clear", interpretation="", question="", resolved_text="")
    keeper._parse = lambda raw: calls.pop(0) if len(calls) > 1 else calls[0]
    keeper._enrich = lambda e, r: {"results": "", "reasoning": "", "emphasis_hint": ""}
    keeper._run_time_agent = lambda a, r: {
        "time_delta": time_delta, "narrative_hint": ""}
    entry = combat_entry or {"enter_combat": False, "enemy_instance_ids": [],
                             "reasoning": ""}
    monkeypatch.setattr("game.agents.keeper.call_deepseek",
                        lambda *a, **k: json.dumps(entry, ensure_ascii=False))


class StubNarrator:
    """确定性 narrator：不调 LLM，原样回显 brief 文本。"""
    l1_data = None

    def narrate(self, brief, snap=None, user_input=""):
        text = brief.enriched_summary or "\n".join(
            o.message for o in brief.action_outcomes)
        return text, f"【叙事】{text}", ""


def make_game(keeper):
    """run_turn 所需的最小 game dict。"""
    return {"keeper": keeper, "narrator": StubNarrator(), "author": None}


def assert_player_turn_contract(r):
    """PlayerTurnResult 结构审计（硬断言）。"""
    from game.messages import PlayerTurnResult, TurnStatus
    assert isinstance(r, PlayerTurnResult), f"期望 PlayerTurnResult，得到 {type(r)}"
    assert isinstance(r.status, TurnStatus)
    assert isinstance(r.brief, str) and isinstance(r.narrative, str)
    assert isinstance(r.skill_results, list)
    assert isinstance(r.diagnostics, dict)
    for key in ("time_agent", "npc_events", "npcs_visible"):
        assert key in r.diagnostics, f"diagnostics 缺 {key}"
    if r.status == TurnStatus.SUSPENDED:
        assert r.pending_interaction is not None, "SUSPENDED 必须带 pending_interaction"
        assert r.pending_interaction.question
    if r.pending_interaction is not None:
        assert r.pending_interaction.kind in ("weapon_offer", "standoff", "clarify")
        assert r.pending_interaction.question
    if r.game_over:
        assert r.ending is not None, "game_over 必须有 ending"
    return r
