"""
Combat Test Harness — LLM mock, 3 parallel instances, ~10 rounds each.
Tests: combat actions, damage calc, trait enhancement, combat narrative.
"""
import sys, os, json, copy
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_ROOT = os.path.join(os.path.dirname(__file__), "..", "data", "debug", "test_combat", TIMESTAMP)


# ═══════════════════════════════════════════════════════════════
#  Mock EnemyInstance — carries LibraryEnemy fields for combat
# ═══════════════════════════════════════════════════════════════

class MockEnemy:
    """Fake enemy with both EnemyInstance and LibraryEnemy fields."""
    def __init__(self, instance_id, enemy_ref, attributes, attacks, armor="",
                 special_abilities=None, combat_behavior="", description="",
                 status="neutral", hp=None):
        self.instance_id = instance_id
        self.enemy_ref = enemy_ref
        self.attributes = attributes  # {"STR": 80, "CON": 70, "SIZ": 65, "DEX": 50, "POW": 60}
        self.attacks = attacks        # [{"name":"噬咬","damage":"1D8+DB","weight":3}, ...]
        self.armor = armor
        self.special_abilities = special_abilities or []
        self.combat_behavior = combat_behavior
        self.description = description
        self.status = status
        self.hp = hp if hp is not None else max(1, attributes.get("SIZ", 50) // 5 + 5)


# ═══════════════════════════════════════════════════════════════
#  Test investigators — different combat setups
# ═══════════════════════════════════════════════════════════════

def _make_investigator(name, stats_dict, skill_dict, weapons, desc=""):
    """Minimal investigator stub for combat testing."""
    from investigator import Investigator
    from investigator.models import Stats, DerivedStats, Skill, Weapon

    inv = Investigator(name=name, age=30, gender="男")
    inv.stats = Stats(
        STR=stats_dict.get("STR", 50), CON=stats_dict.get("CON", 50),
        SIZ=stats_dict.get("SIZ", 60), DEX=stats_dict.get("DEX", 50),
        APP=stats_dict.get("APP", 50), INT=stats_dict.get("INT", 60),
        POW=stats_dict.get("POW", 55), EDU=stats_dict.get("EDU", 60),
        LUCK=stats_dict.get("LUCK", 60),
    )
    inv.derived = DerivedStats(
        HP=stats_dict.get("HP", 12), SAN=stats_dict.get("SAN", 60),
        MP=stats_dict.get("MP", 12),
    )
    inv.skills = [Skill(name=k, base_value=v, value=v) for k, v in skill_dict.items()]
    inv.weapons = [
        Weapon(name=w["name"], skill_name=w["skill"], damage=w["damage"])
        for w in weapons
    ]
    inv.personal_description = desc
    return inv


# ── Investigator A: 格斗型 (高 STR, 格斗技能) ──
INV_A = _make_investigator(
    "格斗家·雷纳德",
    {"STR": 80, "CON": 70, "SIZ": 70, "DEX": 55, "POW": 50, "HP": 14, "SAN": 55},
    {"格斗(拳)": 60, "格斗(脚)": 40, "回避": 35},
    [{"name": "指虎", "skill": "格斗(拳)", "damage": "1D4+DB"}],
    desc="退役拳击手，浑身肌肉，指关节布满老茧。坚信拳头能解决大多数问题。",
)
INV_A_BRIEF = "格斗型·高STR·指虎"

# ── Investigator B: 射击型 (高 DEX, 手枪) ──
INV_B = _make_investigator(
    "私家侦探·艾琳",
    {"STR": 45, "CON": 55, "SIZ": 50, "DEX": 75, "POW": 65, "HP": 11, "SAN": 70},
    {"射击(手枪)": 70, "格斗(拳)": 25, "回避": 50},
    [{"name": ".38 左轮", "skill": "射击(手枪)", "damage": "1D10"}],
    desc="前警探，褪色的风衣下藏着一把.38左轮。眼神锐利但手腕纤细。",
)
INV_B_BRIEF = "射击型·高DEX·左轮"

# ── Investigator C: 生存型 (均衡, 侧重回避) ──
INV_C = _make_investigator(
    "探险家·罗伊",
    {"STR": 60, "CON": 65, "SIZ": 60, "DEX": 65, "POW": 60, "HP": 13, "SAN": 65},
    {"格斗(拳)": 45, "格斗(脚)": 35, "回避": 60},
    [{"name": "猎刀", "skill": "格斗(拳)", "damage": "1D6+DB"},
     {"name": "手电筒", "skill": "格斗(拳)", "damage": "1D4"}],
    desc="经验丰富的探险家，灵活且善于在危险中周旋。随身携带一把猎刀。",
)
INV_C_BRIEF = "均衡型·高回避·猎刀"


# ═══════════════════════════════════════════════════════════════
#  Mock enemies — two types
# ═══════════════════════════════════════════════════════════════

def _make_enemies(preset="standard"):
    """Create mock enemy list. Preset: 'standard', 'boss', 'horde'."""
    if preset == "standard":
        return [
            MockEnemy("deep_a1", "深潜者A", {"STR": 75, "CON": 65, "SIZ": 70, "DEX": 50, "POW": 55},
                      [{"name": "噬咬", "damage": "1D8+DB", "weight": 3},
                       {"name": "利爪", "damage": "1D6+DB", "weight": 2}],
                      armor="2点厚皮", combat_behavior="偏好伏击，受伤后会狂暴",
                      description="克苏鲁神话经典两栖人形生物，散发鱼腥味。",
                      hp=16),
            MockEnemy("deep_a2", "深潜者B", {"STR": 70, "CON": 60, "SIZ": 65, "DEX": 45, "POW": 50},
                      [{"name": "噬咬", "damage": "1D8+DB", "weight": 2},
                       {"name": "利爪", "damage": "1D6+DB", "weight": 1}],
                      armor="1点鳞片", combat_behavior="较弱个体，倾向于退却",
                      description="较小的深潜者，鳞片颜色较浅。",
                      hp=12),
        ]
    elif preset == "boss":
        return [
            MockEnemy("clicker_1", "循声者之王", {"STR": 120, "CON": 100, "SIZ": 90, "DEX": 60, "POW": 80},
                      [{"name": "噬咬", "damage": "2D8+DB", "weight": 4},
                       {"name": "撕裂", "damage": "1D10+DB", "weight": 3}],
                      armor="4点异界甲壳", combat_behavior="优先攻击最近威胁。受伤后狂暴，每轮攻击两次。",
                      description="超大个体的循声者，头部裂口可吞下整个人。",
                      hp=30),
        ]
    elif preset == "horde":
        return [
            MockEnemy(f"cultist_{i}", f"疯狂信徒{i+1}",
                      {"STR": 50 + i*5, "CON": 50, "SIZ": 55, "DEX": 50, "POW": 45},
                      [{"name": "匕首", "damage": "1D4+DB", "weight": 1},
                       {"name": "拳脚", "damage": "1D3+DB", "weight": 1}],
                      armor="",
                      combat_behavior="狂热的邪教徒，不顾一切地攻击。",
                      description="身穿黑袍的邪教徒，眼神疯狂。",
                      hp=8 + i*2)
            for i in range(3)
        ]


# ═══════════════════════════════════════════════════════════════
#  LLM Mocks
# ═══════════════════════════════════════════════════════════════

def _mock_trait_enhancement(inv_desc, skill_name, skill_detail, current_tier,
                             entity_name, graded_tiers=None, search_context=False):
    """Mock trait enhancement — returns plausible results."""
    tier_order = ["failure", "regular", "hard", "extreme"]
    idx = tier_order.index(current_tier) if current_tier in tier_order else 1
    # Simulate enhancement: 30% chance of +1 tier if skilled, 5% if not
    import random
    if "格斗" in skill_name and ("拳击" in inv_desc or "肌肉" in inv_desc):
        if random.random() < 0.3 and idx < 3:
            new_tier = tier_order[idx + 1]
            return {"tier": new_tier, "detail_override": None,
                    "reason": f"格斗经验让{entity_name}变得更容易。"}
    if "射击" in skill_name and "警探" in inv_desc:
        if random.random() < 0.3 and idx < 3:
            new_tier = tier_order[idx + 1]
            return {"tier": new_tier, "detail_override": None,
                    "reason": f"前警探的训练在{entity_name}中发挥了作用。"}
    if "回避" in skill_name and "探险" in inv_desc:
        if random.random() < 0.3 and idx < 3:
            new_tier = tier_order[idx + 1]
            return {"tier": new_tier, "detail_override": None,
                    "reason": f"丰富的探险经验让你在{entity_name}时更加灵活。"}
    return {"tier": current_tier, "detail_override": None, "reason": "无修正"}


def _mock_combat_narrative(round_log, enemies_desc, player_name, scene):
    """Mock combat narrative — deterministic based on log content."""
    hits = sum(1 for a in round_log if a.success and a.action_type == "attack")
    misses = sum(1 for a in round_log if not a.success and a.action_type == "attack")
    parts = [f"【{player_name}】"]
    if hits > misses:
        parts.append("在这一轮的交锋中占据了上风。")
    elif misses > hits:
        parts.append("奋力一搏，但未能占到便宜。")
    else:
        parts.append("与敌人僵持不下，双方都在试探。")
    for a in round_log:
        if a.damage > 0:
            parts.append(f"{'玩家' if a.actor == 'player' else '敌人'}造成了{a.damage}点伤害。")
    return {"narrative": "".join(parts), "scene_hint": ""}


# ═══════════════════════════════════════════════════════════════
#  Instance runner
# ═══════════════════════════════════════════════════════════════

def _run_instance(instance_id: str, inv, enemies, inv_brief: str,
                  rounds: int = 10) -> dict:
    """Run one combat test instance with mocked LLM. Serial rounds."""
    from game.combat import CombatSystem, _roll_damage, _apply_armor
    from game.messages import CombatInit, CombatResult
    from llm import evaluate_trait_enhancement as real_trait_enhance
    from llm import evaluate_combat_round_narrative as real_narrative

    instance_dir = os.path.join(OUT_ROOT, instance_id)
    os.makedirs(instance_dir, exist_ok=True)

    log_path = os.path.join(instance_dir, "_round_log.txt")
    summary_path = os.path.join(instance_dir, "_summary.json")

    with open(log_path, "w", encoding="utf-8") as lf:
        lf.write(f"Instance: {instance_id}\nInvestigator: {inv_brief}\n")
        lf.write(f"Enemies: {[e.enemy_ref for e in enemies]}\n")
        lf.write(f"Rounds: {rounds}\n\n")

    # Apply LLM mocks
    trait_patch = patch('llm.evaluate_trait_enhancement', side_effect=_mock_trait_enhancement)
    narrative_patch = patch('llm.evaluate_combat_round_narrative', side_effect=_mock_combat_narrative)
    deepseek_patch = patch('llm.call_deepseek', return_value={"actions": []})

    trait_patch.start()
    narrative_patch.start()
    deepseek_patch.start()

    try:
        combat_init = CombatInit(
            enemies=enemies, player=inv,
            scene="测试战场", initiative_context="",
        )
        cs = CombatSystem()
        state = cs._init_combat(combat_init)

        round_results = []

        for r in range(1, rounds + 1):
            if state.finished:
                lf = open(log_path, "a", encoding="utf-8")
                lf.write(f"\n=== Round {r}: Combat already finished ===\n")
                lf.close()
                round_results.append({"round": r, "finished": True})
                break

            actions = cs._get_player_actions(inv)
            alive = [e for e in state.enemies
                    if getattr(e, 'hp', 1) > 0 and getattr(e, 'status', '') != 'dead']
            if not alive:
                state.finished = True
                round_results.append({"round": r, "all_dead": True})
                break

            # Choose action: attack with best available weapon
            attack_actions = [a for a in actions if a["damage"] is not None]
            chosen = attack_actions[0] if attack_actions else actions[0]
            target = alive[0].instance_id

            # ── Trait enhancement mock (for player attack skill) ──
            skill_val = chosen["value"]
            trait_result = _mock_trait_enhancement(
                inv.personal_description, chosen["skill"],
                f"D100={skill_val//2}/{skill_val}", "regular",
                chosen["label"],
            )
            if trait_result.get("tier", "regular") != "regular":
                # Simulate trait enhancement effect on skill value
                pass  # combat system doesn't directly consume trait result yet

            # ── Process round ──
            round_log = cs._process_round(state, inv, chosen["id"], target)

            # ── Combat narrative mock ──
            enemies_desc = ", ".join(
                f"{e.enemy_ref}(HP:{getattr(e,'hp','?')},status:{getattr(e,'status','?')})"
                for e in enemies)
            narrative = _mock_combat_narrative(round_log, enemies_desc, inv.name, "测试战场")

            # ── Log round ──
            round_data = {
                "round": r,
                "action_id": chosen["id"],
                "action_label": chosen["label"],
                "skill": chosen["skill"],
                "skill_value": skill_val,
                "trait_tier": trait_result.get("tier", ""),
                "trait_reason": trait_result.get("reason", ""),
                "player_hp": state.player_hp,
                "player_hp_max": state.player_hp_max,
                "enemies_state": [
                    {"enemy_ref": e.enemy_ref, "hp": getattr(e, 'hp', '?'),
                     "status": getattr(e, 'status', 'neutral')}
                    for e in state.enemies
                ],
                "actions": [
                    {"actor": a.actor, "type": a.action_type, "weapon": a.weapon,
                     "roll": a.roll, "tier": a.tier, "damage": a.damage,
                     "success": a.success, "narrative": a.narrative}
                    for a in round_log
                ],
                "narrative": narrative.get("narrative", ""),
                "finished": state.finished,
            }
            round_results.append(round_data)

            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"--- Round {r} ---\n")
                lf.write(f"  Action: {chosen['label']} (skill={skill_val})\n")
                for a in round_log:
                    lf.write(f"  {'✓' if a.success else '✗'} [{a.actor}] {a.weapon or a.action_type}"
                           f" roll={a.roll} dmg={a.damage} — {a.narrative}\n")
                lf.write(f"  Player HP: {state.player_hp}/{state.player_hp_max}\n")
                lf.write(f"  Narrative: {narrative.get('narrative', '')}\n\n")

        # ── Build summary ──
        outcome = "win"
        if state.player_hp <= 0:
            outcome = "loss"
        elif all(getattr(e, 'hp', 1) <= 0 or getattr(e, 'status', '') == 'dead'
                for e in enemies):
            outcome = "win"

        summary = {
            "instance_id": instance_id,
            "investigator": inv_brief,
            "outcome": outcome,
            "total_rounds": len(round_results),
            "final_hp": state.player_hp,
            "final_hp_max": state.player_hp_max,
            "enemy_summary": [
                {"enemy_ref": e.enemy_ref, "final_hp": getattr(e, 'hp', '?'),
                 "status": getattr(e, 'status', 'neutral')}
                for e in state.enemies
            ],
            "rounds": round_results,
        }

    finally:
        trait_patch.stop()
        narrative_patch.stop()
        deepseek_patch.stop()

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return summary


# ═══════════════════════════════════════════════════════════════
#  Main — 3 parallel instances
# ═══════════════════════════════════════════════════════════════

INSTANCES = [
    {
        "id": "combat_A_fighter",
        "inv": INV_A,
        "enemies": _make_enemies("standard"),
        "brief": INV_A_BRIEF,
        "rounds": 10,
    },
    {
        "id": "combat_B_shooter",
        "inv": INV_B,
        "enemies": _make_enemies("boss"),
        "brief": INV_B_BRIEF,
        "rounds": 10,
    },
    {
        "id": "combat_C_survival",
        "inv": INV_C,
        "enemies": _make_enemies("horde"),
        "brief": INV_C_BRIEF,
        "rounds": 10,
    },
]


def run_all():
    os.makedirs(OUT_ROOT, exist_ok=True)

    print(f"Combat Test Harness — 3 instances, ~10 rounds each")
    print(f"Output: {OUT_ROOT}")
    print()

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {
            ex.submit(_run_instance, inst["id"], inst["inv"], inst["enemies"],
                     inst["brief"], inst["rounds"]): inst["id"]
            for inst in INSTANCES
        }
        for f in as_completed(futures):
            iid = futures[f]
            try:
                summary = f.result()
                print(f"[{iid}] outcome={summary['outcome']} rounds={summary['total_rounds']}"
                      f" final_hp={summary['final_hp']}/{summary['final_hp_max']}")
                for es in summary["enemy_summary"]:
                    print(f"  [{es['enemy_ref']}] hp={es['final_hp']} status={es['status']}")
            except Exception as e:
                print(f"[{iid}] FAILED: {e}")
                import traceback
                traceback.print_exc()

    print(f"\nDone. Output at: {OUT_ROOT}")


if __name__ == "__main__":
    run_all()
