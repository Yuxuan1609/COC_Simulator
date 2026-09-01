"""F23 实体可重复策略（S3-P2 spec §2）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tests', 'e2e'))


def _once_inter():
    return {
        "id": "IT_ONCE", "entity_type": "interaction",
        "name": "读信", "scene": "room_a",
        "type": "无", "requirement": "", "trigger": "读信",
        "result": "信上写着地址。", "side_effects": [],
        "difficulty": "", "time_condition": [],
    }


def _repeatable_inter():
    d = _once_inter()
    d["id"] = "IT_REREAD"
    d["name"] = "重读信"
    d["repeatable"] = True
    return d


def _world_with(inter):
    from helpers import make_world, make_scene
    return make_world({"room_a": make_scene(interactions=[inter])}, "room_a")


class TestRepeatable:
    def test_once_entity_blocked_after_completion(self):
        """默认（无 repeatable）实体完成后仍被硬挡——现状保持。"""
        from game.judge import Judge
        world = _world_with(_once_inter())
        entity = world.graph.nodes["room_a"].interactions[0]
        judge = Judge(world)
        first = judge._execute_entity(entity)
        assert first.success
        second = judge._execute_entity(entity)
        assert not second.success
        assert "已触发过" in second.message

    def test_repeatable_entity_reruns(self):
        """repeatable=true 实体完成后可再次执行，runtime_state 仍幂等 mark_completed。"""
        from game.judge import Judge
        world = _world_with(_repeatable_inter())
        entity = world.graph.nodes["room_a"].interactions[0]
        judge = Judge(world)
        first = judge._execute_entity(entity)
        assert first.success
        assert world.is_entity_completed(entity.id)
        second = judge._execute_entity(entity)
        assert second.success
        assert world.is_entity_completed(entity.id)

    def test_repeatable_not_hidden_in_completed_section(self):
        """repeatable 实体不进入 _build_entity_lines 的 completed 段。"""
        from game.judge import Judge
        from prompts import _build_entity_lines
        world = _world_with(_repeatable_inter())
        entity = world.graph.nodes["room_a"].interactions[0]
        Judge(world)._execute_entity(entity)
        (trig_scene, _nontrig_scene, _trig_npc, _nontrig_npc,
         _trig_events, _nontrig_events, completed_scene, completed_npc) = _build_entity_lines(world)
        joined_completed = "\n".join(completed_scene + completed_npc)
        assert entity.id not in joined_completed
        joined_trig = "\n".join(trig_scene)
        assert entity.id in joined_trig

    def test_repeatable_survives_save_load(self, tmp_path):
        """save_state → load_state 后 repeatable 实体仍可再执行。"""
        from game.judge import Judge
        from scenario_core import ScenarioWorld
        world = _world_with(_repeatable_inter())
        entity = world.graph.nodes["room_a"].interactions[0]
        first = Judge(world)._execute_entity(entity)
        assert first.success
        path = str(tmp_path / "save.json")
        world.save_state(path)
        restored = ScenarioWorld.load_state(path)
        entity2 = restored.graph.nodes["room_a"].interactions[0]
        assert entity2.repeatable
        second = Judge(restored)._execute_entity(entity2)
        assert second.success
        assert "已触发过" not in second.message

    def test_keeper_lookup_allows_completed_repeatable_npc_entity(self):
        """完成后 repeatable 的 NPC bound 实体仍可 inject / lookup。"""
        from helpers import make_world, make_scene
        from game.agents.keeper import Keeper
        profile = {
            "name": "列车员", "scene": "room_a", "can_interact": True,
            "bound_interactions": [{
                "id": "IT_NPC_R", "entity_type": "interaction",
                "name": "再问一次", "type": "无", "requirement": "",
                "trigger": "再问列车员", "result": "他还是那句话。",
                "difficulty": "None", "repeatable": True,
            }],
        }
        world = make_world({"room_a": make_scene()}, "room_a",
                           npc_profiles={"列车员": profile})
        world.mark_completed("IT_NPC_R")
        keeper = Keeper(world)
        found = keeper._find_entity_by_id("IT_NPC_R")
        assert found is not None
        assert found.repeatable
        keeper._inject_npc_at()
        node = world.graph.nodes["room_a"]
        assert any(e.id == "IT_NPC_R" for e in node.interactions)
