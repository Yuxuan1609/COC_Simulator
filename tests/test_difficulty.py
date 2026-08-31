"""P0-1：check_skill difficulty 参数生效（COC7：regular=满值/hard=半值/extreme=1/5）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def _inv():
    from investigator import Investigator
    from investigator.models import Skill
    inv = Investigator(name="测试员", age=25, gender="男")
    inv.skills = [Skill(name="侦查", base_value=50)]
    return inv


class TestDifficulty:
    def test_regular_unchanged(self, monkeypatch):
        """regular 维持满值判定：roll 40 ≤ 50 成功。"""
        inv = _inv()
        monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 40)
        ok, msg, tier = inv.check_skill("侦查", "regular")
        assert ok and tier == "regular"

    def test_hard_requires_half(self, monkeypatch):
        """hard 需 ≤25：roll 40 失败。"""
        inv = _inv()
        monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 40)
        ok, msg, tier = inv.check_skill("侦查", "hard")
        assert not ok and tier == "failure"

    def test_hard_success_tier(self, monkeypatch):
        """hard 下 roll 20（≤25）成功，tier=hard。"""
        inv = _inv()
        monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 20)
        ok, msg, tier = inv.check_skill("侦查", "hard")
        assert ok and tier == "hard"

    def test_extreme_requires_fifth(self, monkeypatch):
        """extreme 需 ≤10：roll 20 失败，roll 8 成功 tier=extreme。"""
        inv = _inv()
        monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 20)
        ok, _, _ = inv.check_skill("侦查", "extreme")
        assert not ok
        monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 8)
        ok, _, tier = inv.check_skill("侦查", "extreme")
        assert ok and tier == "extreme"

    def test_unknown_difficulty_falls_back_regular(self, monkeypatch):
        """未知难度串 → regular（优雅放行，与 time_condition 同策略）。"""
        inv = _inv()
        monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 40)
        ok, _, _ = inv.check_skill("侦查", "噩梦")
        assert ok

    def test_attr_check_forwards_difficulty(self, monkeypatch):
        """attr 检定同样吃 difficulty（INT×? 走 stats 满值，hard 减半）。"""
        inv = _inv()
        inv.stats.INT = 50
        monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 40)
        ok, _, _ = inv.check_skill("INT", "hard")
        assert not ok
