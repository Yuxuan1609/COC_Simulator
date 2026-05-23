"""Quick roundtrip test for save/load with G9+G10 fixes."""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from game_loop import init_game
from scenario_core import NodeRuntimeState, ScenarioWorld
from game.side_effects import SceneWeapon

game = init_game(
    l2_path="data/modules/常暗之厢/l2_test.json",
    l1_path="data/modules/常暗之厢/l1_test.json",
    l3_path="data/modules/常暗之厢/l3_test.json",
    start_node="测试房间",
)
world = game["keeper"].world
# Load test character
from investigator import load_investigator
char_path = os.path.join(os.path.dirname(__file__), "..", "investigator", "test_character.json")
if os.path.exists(char_path):
    world.set_player(load_investigator(char_path))
else:
    from investigator import Investigator
    from investigator.rules import roll_stats, calc_derived, create_skill_list
    inv = Investigator(name="Test", age=25, gender="M")
    inv.stats = roll_stats()
    inv.skills = create_skill_list()
    inv.derived = calc_derived(inv.stats, inv.age)
    world.set_player(inv)
p = world.player

# Modify state
p.item_manager.add("镇静剂", "急救药品", 2)
p.item_manager.add("手电筒", "", 1)
world.clock.advance_time(30)
world.triggered_events["AT_TEST_AUTO"] = True
world.runtime_state["IT1"] = NodeRuntimeState(completed=True, result_tier="regular", retries=0, escalated_difficulty="")
world.scene_weapons["测试房间"] = [SceneWeapon(weapon_ref="撬棍", scene="测试房间", quantity=1)]
world.npc_states["测试NPC"] = "friendly"
world.memory.note_item("测试物品")
world.memory.add_record("测试输入", "test", "", "测试结果", location="测试房间", success=True)

# Save
with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as f:
    save_path = f.name
world.save_state(save_path)

# Load
world2 = ScenarioWorld.load_state(save_path)
p2 = world2.player

# Verify G9: ItemManager
assert p2.item_manager.has("镇静剂"), "ItemManager: missing 镇静剂"
assert p2.item_manager.has("手电筒"), "ItemManager: missing 手电筒"
assert p2.item_manager.get("镇静剂").quantity == 2, f"quantity: {p2.item_manager.get('镇静剂').quantity}"

# Verify G10: clock
assert world2.clock.game_time == 30, f"clock: {world2.clock.game_time}"

# Verify subsystems exist (may be None if library not available)
assert world2.enemy_manager is not None, "enemy_manager missing"
assert world2.npcs is not None, "npcs missing"

# Verify other state
assert world2.triggered_events.get("AT_TEST_AUTO") == True, "triggered_events"
assert world2.runtime_state["IT1"].completed == True, "runtime_state IT1"
assert len(world2.scene_weapons.get("测试房间", [])) == 1, "scene_weapons"
assert "测试NPC" in world2.npc_states, "npc_states"
assert "测试物品" in world2.memory.key_items, "memory key_items lost"
assert len(world2.memory.raw_history) > 0, "memory raw_history lost"
assert world2.background_story == world.background_story, "background_story"

os.unlink(save_path)
print("ALL ROUNDTRIP ASSERTIONS PASSED")
