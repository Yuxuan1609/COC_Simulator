"""F31 模组体检 lint：cross_validate 扩编 + 可达性 + CLI（S3-P2 spec §5）。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def _entity(eid, name="互动", difficulty="regular", side_effects=None, scene="s1"):
    return {
        "id": eid,
        "entity_type": "interaction",
        "name": name,
        "type": "None",
        "requirement": "",
        "trigger": name,
        "result": "ok",
        "scene": scene,
        "side_effects": side_effects or [],
        "difficulty": difficulty,
    }


def _l1(scenes=("s1",)):
    return {
        s: {
            "description": s,
            "atmosphere": "",
            "perceptible": [],
            "ambient_hints": [],
            "npc_appearances": [],
        }
        for s in scenes
    }


def _l2(scenes_entities, events=None, npc_profiles=None, graph=None):
    scenes = {}
    for sname, ents in scenes_entities.items():
        scenes[sname] = {
            "interactions": list(ents),
            "auto_triggers": [],
            "encounters": [],
            "scene_weapons": [],
            "from_here": [],
            "to_here": [],
            "extra": {},
            "description": sname,
        }
    data = {"scenes": scenes, "events": events or [], "npc_profiles": npc_profiles or {}}
    if graph is not None:
        data["dependency_graph"] = graph
    return data


def _l3(scenes=("s1",), endings=None, start="s1"):
    return {
        "start_scene": start,
        "module_meta": {"title": "t"},
        "scene_intents": {s: {"purpose": "p"} for s in scenes},
        "ending_conditions": endings or [],
    }


class TestReachability:
    def test_reachable_from_finds_unreachable(self):
        """BFS：起点不可达的节点被报出。"""
        from module_designer.dependency_graph import DependencyGraph
        g = DependencyGraph()
        g.build([
            {"entity_id": "A", "requires": [{"id": "B"}]},
            {"entity_id": "C", "requires": []},
        ])
        unreachable = g.reachable_from("A")
        assert "C" in unreachable and "B" not in unreachable

    def test_no_graph_returns_empty(self):
        from module_designer.dependency_graph import DependencyGraph
        g = DependencyGraph()
        assert g.reachable_from("A") == []


class TestLintChecks:
    def test_duplicate_entity_id_is_error(self):
        """跨场景重复 entity id → error。"""
        from module_designer.layered_pipeline import cross_validate_layers
        l1 = _l1(("s1", "s2"))
        dup = _entity("I_DUP", scene="s1")
        dup2 = _entity("I_DUP", name="另一份", scene="s2")
        l2 = _l2({"s1": [dup], "s2": [dup2]})
        l3 = _l3(("s1", "s2"))
        report = cross_validate_layers(l1, l2, l3)
        joined = " ".join(str(i) for i in report.issues)
        assert report.errors, "重复 entity id 必须是 error"
        assert "I_DUP" in joined

    def test_unknown_markup_ref_is_error(self):
        """markup 内引用不存在的实体/flag → error。"""
        from module_designer.layered_pipeline import cross_validate_layers
        l1 = _l1()
        ent = _entity("I1", side_effects=['@unlock(flag="ghost_flag")'])
        l2 = _l2({"s1": [ent]})
        l3 = _l3()
        report = cross_validate_layers(l1, l2, l3)
        joined = " ".join(str(i) for i in report.issues)
        assert report.errors, "未知 flag/实体引用必须是 error"
        assert "ghost_flag" in joined

    def test_cli_exit_code(self, tmp_path):
        """CLI：有 error → exit 1；干净模组 → exit 0。"""
        from module_designer.lint import run_lint

        clean = tmp_path / "clean"
        clean.mkdir()
        (clean / "l1_player.json").write_text(
            json.dumps(_l1(), ensure_ascii=False), encoding="utf-8")
        (clean / "l2_keeper.json").write_text(
            json.dumps(_l2({"s1": [_entity("I1")]}), ensure_ascii=False), encoding="utf-8")
        (clean / "l3_designer.json").write_text(
            json.dumps(_l3(), ensure_ascii=False), encoding="utf-8")
        assert run_lint(str(clean)) == 0

        dirty = tmp_path / "dirty"
        dirty.mkdir()
        (dirty / "l1_player.json").write_text(
            json.dumps(_l1(("s1", "s2")), ensure_ascii=False), encoding="utf-8")
        (dirty / "l2_keeper.json").write_text(
            json.dumps(_l2({
                "s1": [_entity("I_DUP", scene="s1")],
                "s2": [_entity("I_DUP", name="另一份", scene="s2")],
            }), ensure_ascii=False), encoding="utf-8")
        (dirty / "l3_designer.json").write_text(
            json.dumps(_l3(("s1", "s2")), ensure_ascii=False), encoding="utf-8")
        assert run_lint(str(dirty)) == 1
