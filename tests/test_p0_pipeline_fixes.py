"""P0 pipeline bug reproduction tests — no real LLM calls.

P0-1: Author recursion clears outer turn's pending side effects / move.
P0-2: combat entry with empty in-scene candidates -> NameError (unbound locals).
P0-3: boss pure-hard requirement never validated.
P0-4: boss "event" path skips enemy registration and clobbers existing combat.
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from types import SimpleNamespace

from scenario_core import DirectedGraph, ScenarioWorld
from game.messages import TurnInput, ModulePatch, PreParseResult, TurnStatus
from game.agents.keeper import Keeper
from library.enemies import EnemyLibrary, LibraryEnemy
from library.bosses import BossLibrary


# ── Shared builders ──────────────────────────────────────────────────

def _scene(interactions=None, auto_triggers=None, exits=None, description=""):
    return {
        "interactions": interactions or [],
        "auto_triggers": auto_triggers or [],
        "from_here": exits or [],
        "to_here": [],
        "encounters": [],
        "scene_weapons": [],
        "extra": {},
        "description": description,
    }


def _enemy_library(*names):
    lib = EnemyLibrary()
    for name in names:
        lib._enemies[name] = LibraryEnemy.from_dict({
            "name": name,
            "type": "怪物",
            "attributes": {"CON": 50, "SIZ": 50},
            "armor": "",
            "attacks": [],
            "special_abilities": [],
            "san_loss": "0",
            "description": "测试敌人",
            "combat_behavior": "无差别攻击",
        })
    return lib


def _boss_library(tmp_path, name="测试Boss"):
    path = tmp_path / "bosses.json"
    path.write_text(json.dumps({
        name: {
            "type": "Boss",
            "attributes": {"CON": 100, "SIZ": 100},
            "armor": "",
            "attacks": [],
            "special_abilities": [],
            "san_loss": "1/1d10",
            "description": "测试 Boss",
            "boss_mechanics": "",
            "flags": ["boss"],
        }
    }, ensure_ascii=False), encoding="utf-8")
    return BossLibrary(str(path))


def _stub_llm_paths(keeper, monkeypatch, parse_results=None, combat_entry=None):
    """Stub all LLM entry points reachable in process_turn."""
    parse_calls = list(parse_results or [[{"type": "other", "text": "站着不动"}]])
    keeper.pre_parse.disambiguate = lambda *a, **k: PreParseResult(
        clarity="clear", interpretation="", question="", resolved_text="")
    keeper._parse = lambda raw: parse_calls.pop(0) if len(parse_calls) > 1 else parse_calls[0]
    keeper._enrich = lambda entities, raw: {"results": "", "reasoning": "", "emphasis_hint": ""}
    keeper._run_time_agent = lambda actions, raw: {"time_delta": 0, "narrative_hint": ""}
    ce = combat_entry or {"enter_combat": False, "enemy_instance_ids": [], "reasoning": ""}
    monkeypatch.setattr("game.agents.keeper.call_deepseek",
                        lambda *a, **k: json.dumps(ce, ensure_ascii=False))


# ── P0-2: unbound avoidable_by_ref / hostile_iids ────────────────────

class TestCombatEntryEmptyCandidates:
    def test_enter_combat_with_no_in_scene_candidates_no_nameerror(self, monkeypatch, tmp_path):
        """adjacent_aware enemy in ADJACENT scene gives enemy_ctx, LLM says enter
        combat, but in-scene candidate list is empty -> must not NameError."""
        scenes = {
            "room_a": _scene(exits=[{"target": "room_b", "method": "走", "requirement": ""}]),
            "room_b": _scene(exits=[{"target": "room_a", "method": "走", "requirement": ""}]),
        }
        world = ScenarioWorld(DirectedGraph(scenes=scenes, events=[]),
                              start_node="room_a",
                              enemy_library=_enemy_library("深潜者"))
        inst = world.enemies.spawn("深潜者", "room_b", 1)
        inst.flags = ["adjacent_aware"]  # cross-scene awareness -> non-empty enemy_ctx

        keeper = Keeper(world)
        _stub_llm_paths(keeper, monkeypatch,
                        combat_entry={"enter_combat": True, "enemy_instance_ids": [],
                                      "reasoning": "敌人逼近"})

        result = keeper.process_turn(TurnInput(raw_text="环顾四周"), author=None)
        assert result.status == TurnStatus.COMPLETED
        assert result.combat_init is None


# ── P0-3: boss pure-hard requirement never checked ───────────────────

class TestBossHardRequirement:
    def _keeper(self):
        world = ScenarioWorld(DirectedGraph(scenes={"room_a": _scene()}, events=[]),
                              start_node="room_a")
        return Keeper(world)

    def test_pure_hard_requirement_unmet_blocks_trigger(self):
        keeper = self._keeper()
        boss = {"id": "B1", "boss_ref": "测试Boss", "name": "测试Boss",
                "requirements": "NEVER_TRIGGER"}
        assert keeper._check_boss_requirements(boss, "任何行动") is False

    def test_mixed_hard_failed_blocks_trigger(self):
        keeper = self._keeper()
        boss = {"id": "B2", "boss_ref": "测试Boss", "name": "测试Boss",
                "requirements": "NEVER_TRIGGER||玩家做出了某种仪式动作"}
        assert keeper._check_boss_requirements(boss, "任何行动") is False

    def test_empty_requirement_passes(self):
        keeper = self._keeper()
        boss = {"id": "B3", "boss_ref": "测试Boss", "name": "测试Boss",
                "requirements": ""}
        assert keeper._check_boss_requirements(boss, "任何行动") is True


# ── P0-4: boss "event" path registration + merge ─────────────────────

class TestBossEventPath:
    def test_event_boss_registered_and_merged_with_existing_combat(self, monkeypatch, tmp_path):
        scenes = {"room_a": _scene(description="房间")}
        boss_lib = _boss_library(tmp_path)
        world = ScenarioWorld(
            DirectedGraph(scenes=scenes, events=[]),
            start_node="room_a",
            enemy_library=_enemy_library("深潜者"),
            boss_library=boss_lib,
            boss_encounters=[{
                "id": "BE1", "boss_ref": "测试Boss", "engage_type": "event",
                "requirements": "", "scene": "room_a", "description": "Boss 降临",
            }],
        )
        world.enemies.spawn("深潜者", "room_a", 1)  # hostile in current scene

        keeper = Keeper(world)
        _stub_llm_paths(keeper, monkeypatch,
                        combat_entry={"enter_combat": True, "enemy_instance_ids": [],
                                      "reasoning": "深潜者发起攻击"})

        result = keeper.process_turn(TurnInput(raw_text="四下张望"), author=None)

        combat_init = result.combat_init
        assert combat_init is not None, "combat_init should be produced"
        refs = sorted(getattr(e, "enemy_ref", "") for e in combat_init.enemies)
        assert refs == ["测试Boss", "深潜者"], (
            f"event boss must MERGE into existing combat, got {refs}")

        boss_instances = [i for i in world.enemies._instances.values()
                          if i.enemy_ref == "测试Boss"]
        assert boss_instances, "event boss enemy must be registered in EnemyManager"
        assert boss_instances[0].instance_id in world.enemies._combat_enemies, (
            "event boss must be added to the active combat roster")
        assert world.enemies._combat_active is True


# ── P0-1: Author recursion preserves pending side effects ────────────

class TestAuthorRecursionPreservesPending:
    def test_module_patch_recursion_keeps_item_gain(self, monkeypatch):
        scenes = {
            "room_a": _scene(interactions=[{
                "id": "IT_GAIN", "entity_type": "interaction",
                "name": "拿起急救包", "scene": "room_a",
                "type": "无", "requirement": "", "trigger": "拿起桌上的急救包",
                "result": "你拿到了急救包。",
                "side_effects": ['@item_gain(item_name="急救包", quantity=1)'],
                "difficulty": "None",
            }]),
        }
        world = ScenarioWorld(DirectedGraph(scenes=scenes, events=[]), start_node="room_a")

        from investigator import Investigator
        inv = Investigator(name="测试员", age=25, gender="男")
        world.set_player(inv)

        keeper = Keeper(world)
        _stub_llm_paths(keeper, monkeypatch, parse_results=[
            [{"type": "interaction", "id": "IT_GAIN"}, {"type": "other", "text": "对着墙大喊"}],
            [{"type": "other", "text": "继续"}],
        ])

        # IntentDetector: first call (outer turn) escalates, second (inner) does not
        detect_results = [
            SimpleNamespace(needs_author=True, intent="对着墙大喊", reasoning="r"),
            SimpleNamespace(needs_author=False, intent="", reasoning=""),
        ]
        keeper.intent_detector.detect = lambda *a, **k: (
            detect_results.pop(0) if len(detect_results) > 1 else detect_results[0])

        patch = ModulePatch(
            entities=[{"id": "NEW1", "entity_type": "interaction", "name": "墙壁回音",
                       "scene": "room_a", "type": "无", "requirement": "",
                       "trigger": "听回音", "result": "墙回应了你。",
                       "side_effects": [], "difficulty": "None"}],
            scene_descriptions={}, justification="作者补充了墙壁回音")
        author = SimpleNamespace(time_pressure=None,
                                 handle_request=lambda req, turn: patch)

        keeper.process_turn(TurnInput(raw_text="拿起急救包然后对着墙大喊"), author=author)

        assert inv.item_manager.has("急救包"), (
            "interaction 的 @item_gain 副效果在 Author 递归后丢失（pending 被内层清空）")
