"""F14：技能成长标记（checked）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def _inv_with_spot():
    from investigator import Investigator
    from investigator.models import Skill
    inv = Investigator(name="测试员", age=25, gender="男")
    inv.skills = [Skill(name="侦查", base_value=50)]
    return inv


class TestSkillChecked:
    def test_success_marks_checked(self, monkeypatch):
        """check_skill 成功 → skill.checked=True。"""
        inv = _inv_with_spot()
        monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 30)
        ok, msg, tier = inv.check_skill("侦查", "regular")
        assert ok
        assert inv.get_skill("侦查").checked is True

    def test_failure_does_not_mark(self, monkeypatch):
        """check_skill 失败 → checked 保持 False。"""
        inv = _inv_with_spot()
        monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 80)
        ok, msg, tier = inv.check_skill("侦查", "regular")
        assert not ok
        assert inv.get_skill("侦查").checked is False

    def test_unmastered_skill_not_marked(self, monkeypatch):
        """未掌握技能默认放行 → 无 Skill 对象可标，不报错。"""
        inv = _inv_with_spot()
        monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 30)
        ok, msg, tier = inv.check_skill("考古学", "regular")
        assert ok  # 默认成功放行，不抛异常即锁定行为

    def test_serialization_roundtrip(self):
        """checked 随卡格式序列化回环；旧卡缺省 False。"""
        from investigator.serialization import to_dict, from_dict
        inv = _inv_with_spot()
        inv.get_skill("侦查").checked = True
        inv2 = from_dict(to_dict(inv))
        assert inv2.get_skill("侦查").checked is True
        # 旧卡无 checked 键 → 默认 False
        data = to_dict(inv)
        for s in data["skills"]:
            s.pop("checked", None)
        inv3 = from_dict(data)
        assert inv3.get_skill("侦查").checked is False
