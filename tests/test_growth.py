"""P0-2/U4：幕末成长检定 + 版本化导出 + scenario-end 钩子。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tests', 'e2e'))


def _inv_with_checked():
    from investigator import Investigator
    from investigator.models import Skill
    inv = Investigator(name="测试员", age=25, gender="男")
    inv.skills = [Skill(name="侦查", base_value=50),
                  Skill(name="潜行", base_value=60)]
    inv.get_skill("侦查").checked = True
    return inv


class _FakeRng:
    def __init__(self, seq):
        self._seq = list(seq)

    def randint(self, a, b):
        return self._seq.pop(0) if self._seq else b


class TestSettleGrowth:
    def test_growth_on_roll_above_value(self):
        """roll 80 > 50 → +1d10（钉 7）；checked 结算后清零。"""
        from investigator.growth import settle_growth
        inv = _inv_with_checked()
        report = settle_growth(inv, rng=_FakeRng([80, 7]))
        assert report[0]["grown"] and report[0]["gain"] == 7
        assert inv.get_skill("侦查").value == 57
        assert inv.get_skill("侦查").checked is False
        assert inv.get_skill("潜行").checked is False  # 未标不参与

    def test_no_growth_on_roll_below_value(self):
        """roll 30 ≤ 50 → 不成长，checked 仍清零。"""
        from investigator.growth import settle_growth
        inv = _inv_with_checked()
        report = settle_growth(inv, rng=_FakeRng([30]))
        assert not report[0]["grown"]
        assert inv.get_skill("侦查").value == 50
        assert inv.get_skill("侦查").checked is False


class TestExportGrownCard:
    def test_versioned_copy_no_overwrite(self, tmp_path):
        """导出版本化副本 <卡名>_after_<模组>_<日期>.json，原卡不动。"""
        from investigator.growth import export_grown_card
        inv = _inv_with_checked()
        src = tmp_path / "test_character.json"
        src.write_text("{}", encoding="utf-8")
        before = src.read_text(encoding="utf-8")
        out = export_grown_card(inv, str(src), "测试模组", out_dir=str(tmp_path))
        assert out != str(src)
        assert "_after_测试模组_" in os.path.basename(out)
        assert src.read_text(encoding="utf-8") == before, "原卡不得被覆盖"
        data = json.loads(open(out, encoding="utf-8").read())
        assert any(s["name"] == "侦查" for s in data["skills"])


class TestOnScenarioEnd:
    def test_hook_settles_and_exports(self, tmp_path):
        """结局钩子：成长结算 + 导出（有 character_path 时）。"""
        from helpers import make_world, make_scene, StubNarrator
        from game.agents.keeper import Keeper
        from game_loop import on_scenario_end
        inv = _inv_with_checked()
        src = tmp_path / "c.json"
        src.write_text("{}", encoding="utf-8")
        world = make_world({"room_a": make_scene()}, "room_a")
        world.set_player(inv)
        game = {"keeper": Keeper(world), "narrator": StubNarrator(), "author": None}
        report = on_scenario_end(game, character_path=str(src),
                                 module_name="模组X", out_dir=str(tmp_path))
        assert all(not s.checked for s in inv.skills)
        assert any("_after_模组X_" in f for f in os.listdir(tmp_path))

    def test_hook_no_player_no_crash(self):
        """无玩家 → 空报告不炸。"""
        from helpers import make_world, make_scene, StubNarrator
        from game.agents.keeper import Keeper
        from game_loop import on_scenario_end
        world = make_world({"room_a": make_scene()}, "room_a")
        game = {"keeper": Keeper(world), "narrator": StubNarrator(), "author": None}
        assert on_scenario_end(game) == []

    def test_no_export_without_character_path(self):
        """llm_player 通路：无 character_path → 只结算不导出。"""
        from helpers import make_world, make_scene, StubNarrator
        from game.agents.keeper import Keeper
        from game_loop import on_scenario_end
        inv = _inv_with_checked()
        world = make_world({"room_a": make_scene()}, "room_a")
        world.set_player(inv)
        game = {"keeper": Keeper(world), "narrator": StubNarrator(), "author": None}
        report = on_scenario_end(game)
        assert isinstance(report, list)
        assert all(not s.checked for s in inv.skills)
