"""F25：叙事记忆蒸馏（与 memory.compress 同点触发）+ narrator 注入。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tests', 'e2e'))


def _world_with_history(n=3):
    from helpers import make_world, make_scene
    world = make_world({"room_a": make_scene()}, "room_a")
    for i in range(n):
        world.memory.add_record(user_input=f"行动{i}", action="other",
                                target="", result=f"结果{i}", location="room_a")
    return world


class TestDistill:
    def test_distill_appends_entry(self):
        """蒸馏产出 {turn_range, notes} 条目入 narrative_memory。"""
        world = _world_with_history()
        world.distill_narrative_memory(lambda p: "侦探开始怀疑列车员")
        assert len(world.narrative_memory) == 1
        entry = world.narrative_memory[0]
        assert entry["notes"] == "侦探开始怀疑列车员"
        assert entry["turn_range"].startswith("T")

    def test_rolling_cap_five(self):
        """5 条滚动：蒸 6 次只留最新 5。"""
        world = _world_with_history()
        for i in range(6):
            world.memory.add_record(user_input=f"补{i}", action="other",
                                    target="", result="r", location="room_a")
            world.distill_narrative_memory(lambda p: f"要点")
        assert len(world.narrative_memory) == 5

    def test_empty_history_no_call(self):
        """raw_history 为空 → 不调 LLM、不加条目。"""
        from helpers import make_world, make_scene
        world = make_world({"room_a": make_scene()}, "room_a")
        called = []
        world.distill_narrative_memory(lambda p: called.append(p) or "x")
        assert not called and world.narrative_memory == []

    def test_notes_truncated(self):
        """notes 截断 250 字。"""
        world = _world_with_history()
        world.distill_narrative_memory(lambda p: "长" * 300)
        assert len(world.narrative_memory[0]["notes"]) == 250

    def test_turn_range_uses_snapshot_not_live_alias(self):
        """LLM 期间 add_record 不得扩大 turn_range（快照而非 live 引用）。"""
        world = _world_with_history()

        def llm(_p):
            world.memory.add_record(
                user_input="during", action="other",
                target="", result="r", location="room_a")
            return "要点"

        world.distill_narrative_memory(llm)
        assert world.narrative_memory[0]["turn_range"] == "T1-T3"

    def test_empty_llm_return_no_entry(self):
        """空/空白 LLM 返回 → 不加条目。"""
        world = _world_with_history()
        world.distill_narrative_memory(lambda p: "")
        world.distill_narrative_memory(lambda p: "  ")
        assert world.narrative_memory == []


class TestNarratorInjection:
    def test_snapshot_carries_memory(self):
        """build_snapshot 含 narrative_memory 渲染行。"""
        world = _world_with_history()
        world.distill_narrative_memory(lambda p: "伏笔要点")
        snap = world.build_snapshot()
        assert snap["narrative_memory"]
        assert "伏笔要点" in snap["narrative_memory"][0]

    def test_prompt_contains_memory_block(self):
        """build_narrator_prompt 注入【叙事记忆】段；空则没有。"""
        from prompts import build_narrator_prompt
        from game.messages import NarratorBrief, SceneSnapshot
        brief = NarratorBrief(
            action_outcomes=[], ambient_changes=[],
            scene_snapshot=SceneSnapshot(location="room_a", description="d",
                                         exits=[], perceptible_interactions=[],
                                         visible_npcs=[]),
            suggested_emphasis="", enriched_summary="")
        p_empty = build_narrator_prompt(brief, snap={})
        assert "叙事记忆" not in p_empty
        p_full = build_narrator_prompt(
            brief, snap={"narrative_memory": ["T1-T6：伏笔要点"]})
        assert "叙事记忆" in p_full and "伏笔要点" in p_full
