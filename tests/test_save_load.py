"""B1：存读档统一修复（①吞异常 ②引用重绑 ③注入重复）+ E 簇占坑 + v1 兼容。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tests', 'e2e'))


def _enemy_lib():
    from library.enemies import EnemyLibrary, LibraryEnemy
    lib = EnemyLibrary()
    lib._enemies["测试巡游者"] = LibraryEnemy.from_dict({
        "name": "测试巡游者", "type": "怪物",
        "attributes": {"CON": 30, "SIZ": 30}, "armor": "",
        "attacks": [], "special_abilities": [], "san_loss": "0",
        "description": "", "combat_behavior": "",
    })
    return lib


class TestEnemyRestoreWithLibrary:
    def test_enemies_restored_with_library(self, tmp_path):
        """带库读档：敌人实例恢复（旧行为：库为 None → 吞异常 → enemies=None）。"""
        from helpers import make_world, make_scene
        lib = _enemy_lib()
        world = make_world({"room_a": make_scene()}, "room_a", enemy_library=lib)
        world.enemies.spawn("测试巡游者", "room_a", 1)
        path = str(tmp_path / "save.json")
        world.save_state(path)

        from scenario_core import ScenarioWorld
        restored = ScenarioWorld.load_state(path, enemy_lib=lib)
        assert restored.enemies is not None, "带库读档 enemies 不得为 None"
        active = restored.enemies.get_active_in_scene("room_a")
        assert len(active) == 1, f"敌人实例应恢复，实际 {len(active)}"

    def test_missing_library_warns_not_silent(self, tmp_path):
        """无库读有敌人的档：enemies=None 但 load_warnings 非空（不静默）。"""
        from helpers import make_world, make_scene
        lib = _enemy_lib()
        world = make_world({"room_a": make_scene()}, "room_a", enemy_library=lib)
        world.enemies.spawn("测试巡游者", "room_a", 1)
        path = str(tmp_path / "save.json")
        world.save_state(path)

        from scenario_core import ScenarioWorld
        restored = ScenarioWorld.load_state(path)  # 不传库
        assert restored.enemies is None or not restored.enemies.get_active_in_scene("room_a")
        assert restored.load_warnings, "无库恢复敌人必须产生 warning（不静默）"

    def test_structural_corruption_raises(self, tmp_path):
        """结构性损坏（版本不支持）→ raise（旧世界不动）。"""
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"version": 99}), encoding="utf-8")
        from scenario_core import ScenarioWorld
        import pytest
        with pytest.raises(ValueError):
            ScenarioWorld.load_state(str(path))
