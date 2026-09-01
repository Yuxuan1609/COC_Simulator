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

    def test_entity_reachability_from_start_scene_seeds(self, tmp_path, capsys):
        """start_scene 实体作种子；图中不可达实体 id 报 warning。"""
        from module_designer.lint import run_lint

        graph = {
            "nodes": {
                "IT_A": {"entity_id": "IT_A", "entity_type": "interaction", "name": "a"},
                "IT_B": {"entity_id": "IT_B", "entity_type": "interaction", "name": "b"},
                "IT_ISOLATED": {"entity_id": "IT_ISOLATED", "entity_type": "interaction", "name": "iso"},
            },
            "edges": [
                {"source": "IT_A", "target": "IT_B", "dep_type": "interaction"},
            ],
        }
        mod = tmp_path / "reach"
        mod.mkdir()
        (mod / "l1_player.json").write_text(
            json.dumps(_l1(("s1", "s2")), ensure_ascii=False), encoding="utf-8")
        (mod / "l2_keeper.json").write_text(
            json.dumps(_l2({
                "s1": [_entity("IT_A", scene="s1")],
                "s2": [_entity("IT_ISOLATED", scene="s2")],
            }, graph=graph), ensure_ascii=False), encoding="utf-8")
        (mod / "l3_designer.json").write_text(
            json.dumps(_l3(("s1", "s2")), ensure_ascii=False), encoding="utf-8")
        run_lint(str(mod))
        out = capsys.readouterr().out
        assert "实体「IT_ISOLATED」从起点不可达" in out
        assert "实体「IT_A」从起点不可达" not in out
        assert "实体「IT_B」从起点不可达" not in out

    def test_ending_ref_known_boss_ok_unknown_errors(self):
        """结局提到已有 boss id 不报错；未知 BOSS_X 报 error。"""
        from module_designer.layered_pipeline import cross_validate_layers
        l1 = _l1()
        l2 = _l2({"s1": [_entity("I1")]})
        l2["boss_encounters"] = [{
            "id": "BOSS_T1",
            "boss_ref": "测试魔像",
            "scene": "s1",
        }]
        report_ok = cross_validate_layers(
            l1, l2, _l3(endings=[{"id": "END_1", "condition": "击败 BOSS_T1 后"}]))
        assert not any("BOSS_T1" in i.message for i in report_ok.errors)
        report_bad = cross_validate_layers(
            l1, l2, _l3(endings=[{"id": "END_1", "condition": "击败 BOSS_X 后"}]))
        joined = " ".join(str(i) for i in report_bad.issues)
        assert report_bad.errors
        assert "BOSS_X" in joined

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
