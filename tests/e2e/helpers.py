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


def _classify_call(system: str) -> str:
    """按 system prompt 推断 LLM 调用标签（无 _label kwarg 时的回退分类）。"""
    s = system or ""
    if "意图匹配" in s and "游戏实体" in s:
        return "01_parse"
    if "解析助手" in s or "KP助理" in s and "意图" in s:
        return "01_parse"
    if "游戏状态监控" in s:
        return "02_detector"
    if "消歧" in s or "清晰明确" in s:
        return "pre_parse"
    if "叙事整合" in s:
        return "07_enrich"
    if "战斗" in s and "进入" in s:
        return "combat_entry"
    if "时间推进" in s or "时间消耗" in s:
        return "time_agent"
    if "匹配到对应技能" in s:
        return "standoff_match"
    if ("KP" in s or "跑团" in s) and "叙事" in s and "整合" not in s:
        return "06_narrator"
    if "模组创作者" in s:
        return "03_author"
    return "08_llm"


def setup_llm_logging(log_dir, stubs=None):
    """真实 LLM 测试：patch 全部 call_deepseek 命名空间，落盘 prompt/response/meta。

    stubs: {label: response | [response, ...]} — 命中 _label（或 system 分类）时
           直接返回固定响应，不发真实请求（"单点 stub + 其余真实"混合模式）；
           list 形式按序弹出，最后一个复用。
    返回 stop() 恢复函数。
    """
    import time as _time
    from unittest.mock import patch as _patch
    import llm as _llm_module
    real_call = _llm_module.call_deepseek

    stub_map = {}
    for k, v in (stubs or {}).items():
        stub_map[k] = list(v) if isinstance(v, (list, tuple)) else [v]

    counter = [0]
    os.makedirs(log_dir, exist_ok=True)

    def _log_text(filename, content):
        with open(os.path.join(log_dir, filename), "w", encoding="utf-8") as f:
            f.write(content)

    def _log_json(filename, data):
        with open(os.path.join(log_dir, filename), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _wrapper(prompt, json_mode=True, model="", system="", reasoning_effort="",
                 fallback_schema=None, **extra):
        label = extra.get("_label") or _classify_call(system)
        counter[0] += 1
        n = counter[0]
        prefix = f"{n:02d}_{label}"
        _log_text(f"{prefix}_prompt.txt", prompt)
        if system:
            _log_text(f"{prefix}_system.txt", system)

        if label in stub_map and stub_map[label]:
            resp = (stub_map[label].pop(0) if len(stub_map[label]) > 1
                    else stub_map[label][0])
            _log_text(f"{prefix}_response_stub.txt",
                      resp if isinstance(resp, str)
                      else json.dumps(resp, ensure_ascii=False, indent=2))
            _log_json(f"{prefix}_meta.json", {"stubbed": True, "call_order": n})
            return resp

        kwargs = {"prompt": prompt, "json_mode": json_mode,
                  "fallback_schema": fallback_schema, **extra}
        if model:
            kwargs["model"] = model
        if system:
            kwargs["system"] = system
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        t0 = _time.perf_counter()
        try:
            response = real_call(**kwargs)
        except Exception as e:
            elapsed = _time.perf_counter() - t0
            _log_text(f"{prefix}_error.txt", f"error: {e}\nelapsed: {elapsed:.1f}s")
            raise
        elapsed = _time.perf_counter() - t0
        ext = "json" if json_mode else "txt"
        _log_text(f"{prefix}_response.{ext}",
                  response if isinstance(response, str)
                  else json.dumps(response, ensure_ascii=False, indent=2))
        _log_json(f"{prefix}_meta.json", {
            "model": model or "default", "json_mode": json_mode,
            "call_order": n, "elapsed_s": round(elapsed, 2), "stubbed": False})
        return response

    targets = [
        "llm", "game.agents.keeper", "game.pre_parse", "game.agents.narrator",
        "game.agents.time_agent", "game.intent_detector", "game.agents.author",
        "module_designer.supplement_pipeline",
    ]
    patches = [_patch(f"{t}.call_deepseek", _wrapper) for t in targets]
    for p in patches:
        p.start()

    def stop():
        for p in patches:
            p.stop()

    return stop


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
