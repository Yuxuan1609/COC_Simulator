"""F5 疯狂体系核心：on_san_loss 钩子 + insanity 字段入档（S3-P2 spec §1）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tests', 'e2e'))


def _world_with_player(san=50, int_val=60):
    from helpers import make_world, make_scene
    from investigator import Investigator
    world = make_world({"room_a": make_scene()}, "room_a")
    inv = Investigator(name="测试员", age=25, gender="男")
    inv.derived.SAN = san
    inv.stats.INT = int_val
    world.set_player(inv)
    return world, inv


def _force_roll(monkeypatch, value):
    monkeypatch.setattr("investigator.models.random.randint", lambda a, b: value)


class TestOnSanLoss:
    def test_accumulates_daily_loss(self):
        world, inv = _world_with_player()
        world.on_san_loss(3, "markup")
        world.on_san_loss(2, "markup")
        assert inv.insanity["san_lost_today"] == 5
        assert inv.insanity["san_day"] == world.clock.day

    def test_lazy_reset_on_day_change(self):
        world, inv = _world_with_player(san=50)
        world.on_san_loss(2, "markup")
        world.advance_time(1440)
        world.on_san_loss(4, "markup")
        assert inv.insanity["san_lost_today"] == 4
        assert inv.insanity["san_at_day_start"] == 50  # 取当日当前 SAN

    def test_single_loss_ge5_triggers_temporary_on_int_fail(self, monkeypatch):
        world, inv = _world_with_player(int_val=60)
        _force_roll(monkeypatch, 100)
        result = world.on_san_loss(5, "markup")
        assert result["temporary"] is True
        assert inv.insanity["temporary"]

    def test_single_loss_ge5_int_success_no_temporary(self, monkeypatch):
        world, inv = _world_with_player(int_val=60)
        _force_roll(monkeypatch, 1)
        result = world.on_san_loss(5, "markup")
        assert result["temporary"] is False
        assert not inv.insanity.get("temporary")

    def test_temporary_not_retriggered(self, monkeypatch):
        world, inv = _world_with_player(int_val=60)
        _force_roll(monkeypatch, 100)
        world.on_san_loss(5, "markup")
        first_text = inv.insanity["temporary"]
        result = world.on_san_loss(6, "markup")
        assert result["temporary"] is False
        assert inv.insanity["temporary"] == first_text

    def test_indefinite_not_retriggered(self, monkeypatch):
        world, inv = _world_with_player(san=50)
        _force_roll(monkeypatch, 1)
        world.on_san_loss(10, "markup")
        first_text = inv.insanity["indefinite"]
        result = world.on_san_loss(6, "markup")
        assert result["indefinite"] is False
        assert inv.insanity["indefinite"] == first_text

    def test_gen_insanity_text_llm_failure_warns_and_falls_back(self, monkeypatch, caplog):
        import logging

        def _boom(prompt):
            raise RuntimeError("llm down")

        world, inv = _world_with_player(san=50)
        _force_roll(monkeypatch, 1)  # INT 检定成功，只走 indefinite 分支
        world.set_insanity_llm(_boom)
        with caplog.at_level(logging.WARNING, logger="scenario_core"):
            world.on_san_loss(10, "markup")
        assert inv.insanity["indefinite"] == "（总结性疯狂）"
        assert any("疯狂文本生成失败" in r.message for r in caplog.records), \
            "LLM 生成失败须 warning 日志，不得静默吞异常"

    def test_cumulative_triggers_indefinite(self, monkeypatch):
        world, inv = _world_with_player(san=50)
        _force_roll(monkeypatch, 1)
        result = world.on_san_loss(10, "markup")
        assert result["indefinite"] is True
        assert inv.insanity["indefinite"]

    def test_cumulative_below_threshold_no_indefinite(self, monkeypatch):
        world, inv = _world_with_player(san=50)
        _force_roll(monkeypatch, 1)
        result = world.on_san_loss(9, "markup")
        assert result["indefinite"] is False

    def test_zero_or_negative_loss_noop(self):
        world, inv = _world_with_player()
        result = world.on_san_loss(0, "markup")
        assert result == {"temporary": False, "indefinite": False}
        assert not inv.insanity

    def test_markup_san_loss_flows_to_hook(self, monkeypatch):
        from game.side_effects import StatChange
        from scenario_core import apply_side_effects
        world, inv = _world_with_player(san=50)
        _force_roll(monkeypatch, 1)
        apply_side_effects(world, [StatChange(stat_name="SAN", delta=-3)])
        assert inv.derived.SAN == 47
        assert inv.insanity["san_lost_today"] == 3

    def test_insanity_serialization_roundtrip(self):
        from investigator.serialization import to_dict, from_dict
        world, inv = _world_with_player()
        inv.insanity = {"temporary": "幻觉丛生", "san_lost_today": 6, "san_day": 1}
        inv2 = from_dict(to_dict(inv))
        assert inv2.insanity["temporary"] == "幻觉丛生"
        assert inv2.insanity["san_lost_today"] == 6

    def test_insanity_default_missing_key(self):
        from investigator.serialization import to_dict, from_dict
        world, inv = _world_with_player()
        data = to_dict(inv)
        data.pop("insanity", None)
        inv2 = from_dict(data)
        assert inv2.insanity == {}


class TestSanLossOutletWiring:
    """SAN 损失出口接线回归：markup [疯狂] 消息选型 / combat 目睹 / judge 施法。"""

    def test_markup_message_shows_newly_triggered_kind(self, monkeypatch):
        from game.side_effects import StatChange
        from scenario_core import apply_side_effects
        world, inv = _world_with_player(san=50)
        _force_roll(monkeypatch, 100)  # INT 检定失败 -> temporary 先触发
        apply_side_effects(world, [StatChange(stat_name="SAN", delta=-5)])
        assert inv.insanity["temporary"]
        # 第二次：temporary 已置(set-once)，新触发的是 indefinite
        msgs = apply_side_effects(world, [StatChange(stat_name="SAN", delta=-6)])
        line = next(m for m in msgs if m.startswith("[疯狂]"))
        assert "总结性疯狂" in line, \
            f"[疯狂] 行须显示本次新触发的 indefinite 文本，实际 {line!r}"

    def test_combat_witness_san_loss_flows_to_hook(self, monkeypatch):
        from game.combat import CombatSystem
        from game.messages import CombatInit
        from test_combat_smoke import _TestEnemy
        world, inv = _world_with_player(san=60)
        # D100=100 检定必败；骰面恒 6 -> 失败组 1D6=6（单次 6>=5 触发疯狂判定）
        monkeypatch.setattr("investigator.models.random.randint",
                            lambda a, b: 100 if b == 100 else 6)
        enemy = _TestEnemy("深潜者", hp=8, armor="0", instance_id="E_F5_WIT",
                           san_loss="0/1D6")
        state = CombatSystem(world=world)._init_combat(CombatInit(
            enemies=[enemy], player=inv, scene="房间", initiative_context="测试"))
        assert state.player_san == 54, "目睹 check 失败 1D6=6，SAN 60->54"
        assert inv.insanity["san_lost_today"] == 6, "战斗目睹损失汇入 on_san_loss"
        assert inv.insanity["temporary"] == "（临时疯狂）"
        assert any("（疯狂侵袭）" in s for s in state.san_log)

    def test_judge_cast_san_cost_counted(self, monkeypatch):
        from game.judge import Judge
        from game.use_parser import UseParseResult
        world, inv = _world_with_player(san=50)
        inv.known_spells = ["X"]
        _force_roll(monkeypatch, 1)
        m = UseParseResult(catalog_kind="spell", material_id="X", name="试咒",
                           matched_text="试咒", impact="L1",
                           cost={"mp": 0, "san": 5})
        out = Judge(world).execute_material(m, "试咒")
        assert out.success
        assert inv.derived.SAN == 45
        assert inv.insanity["san_lost_today"] == 5, "施法 SAN 成本汇入 on_san_loss"

    def test_judge_cast_refund_not_counted(self, monkeypatch):
        from game.judge import Judge
        from game.use_parser import UseParseResult
        world, inv = _world_with_player(san=50)
        inv.known_spells = ["X"]
        _force_roll(monkeypatch, 100)  # 检定必败
        m = UseParseResult(catalog_kind="spell", material_id="X", name="试咒",
                           matched_text="试咒", impact="L1",
                           check={"skill": "INT", "type": "regular"},
                           cost={"mp": 0, "san": 5}, refund_on_fail=True)
        out = Judge(world).execute_material(m, "试咒")
        assert not out.success
        assert inv.derived.SAN == 50, "refund_on_fail 退回 SAN"
        assert not inv.insanity.get("san_lost_today"), "退款不计当日疯狂累计"
