"""Combat system — independent turn controller for COC 7th combat."""
from __future__ import annotations
from dataclasses import dataclass, field
import random
import re
from typing import Any

from .messages import CombatInit, CombatResult


# ── Module-level helpers ──

def _roll_damage(formula: str, STR: int, SIZ: int) -> int:
    """Roll damage from formula like '1D6+DB' or '1D3'."""
    from investigator.rules import calc_db
    total = 0
    parts = formula.replace(" ", "").split("+")
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part == "DB":
            db = calc_db(STR, SIZ)
            if db.startswith("+"):
                db = db[1:]
            if db.startswith("-"):
                total += int(db)  # negative number string
            elif "D" in db:
                total += _roll_damage(db, STR, SIZ)
            else:
                total += int(db)
        elif "D" in part:
            m = re.match(r"(\d*)D(\d+)", part)
            if m:
                count = int(m.group(1)) if m.group(1) else 1
                sides = int(m.group(2))
                for _ in range(count):
                    total += random.randint(1, sides)
        else:
            try:
                total += int(part)
            except ValueError:
                pass
    return max(0, total)


def _apply_armor(damage: int, armor: str) -> int:
    """Reduce damage by armor value. armor like '2点厚皮' -> 2."""
    m = re.search(r"(\d+)", armor)
    reduction = int(m.group(1)) if m else 0
    return max(0, damage - reduction)


# ── Data structures ──

@dataclass
class CombatAction:
    """Record of one combat action (player or enemy)."""
    actor: str = ""           # "player" | enemy instance_id
    action_type: str = ""     # "attack" | "dodge" | "flee" | "special"
    weapon: str = ""
    skill_name: str = ""
    skill_value: int = 0
    roll: int = 0
    tier: str = ""            # fumble|failure|regular|hard|extreme
    target: str = ""
    damage: int = 0
    hp_before: int = 0
    hp_after: int = 0
    narrative: str = ""
    success: bool = False


@dataclass
class CombatState:
    """Mutable combat state for one fight."""
    round: int = 1
    enemies: list[Any] = field(default_factory=list)
    player_hp: int = 0
    player_hp_max: int = 0
    player_san: int = 0
    initiative_order: list[str] = field(default_factory=list)
    is_player_turn: bool = True
    finished: bool = False
    log: list[CombatAction] = field(default_factory=list)
    _player_dodging: bool = False


# ── Combat system ──

class CombatSystem:
    """COC 7th simplified combat controller. Independent of Keeper pipeline.

    Receives CombatInit, runs combat loop, returns CombatResult.
    Player actions: fixed options (punch/kick/weapon/dodge/flee).
    Enemy actions: weight-based attack selection, rule-driven targeting.
    """

    def __init__(self, weapon_lib=None):
        self.weapon_lib = weapon_lib

    # ── Public API ──

    def run_combat(self, combat_init: CombatInit) -> CombatResult:
        """Run full combat loop. Returns CombatResult."""
        state = self._init_combat(combat_init)
        player = combat_init.player

        while not state.finished:
            # Build available actions each round (player stats may change)
            actions = self._get_player_actions(player)
            alive_enemies = [e for e in state.enemies
                           if getattr(e, 'hp', 1) > 0 and getattr(e, 'status', '') != 'dead']
            if not alive_enemies:
                state.finished = True
                break

            # Player action resolved by caller (web/CLI) — stub uses simple attack
            target = alive_enemies[0].instance_id
            self._process_round(state, player, "punch", target)

        outcome = "win"
        if state.player_hp <= 0:
            outcome = "loss"

        defeated = [e.instance_id for e in combat_init.enemies
                   if getattr(e, 'hp', 1) <= 0 or getattr(e, 'status', '') == 'dead']

        return CombatResult(
            outcome=outcome,
            defeated_instance_ids=defeated,
            player_hp=state.player_hp,
            player_san=state.player_san,
            rounds=state.round,
        )

    # ── Init ──

    def _init_combat(self, combat_init: CombatInit) -> CombatState:
        """Set up combat state from CombatInit. Initiative by DEX descending."""
        player = combat_init.player
        state = CombatState(
            enemies=combat_init.enemies,
            player_hp=player.derived.HP,
            player_hp_max=player.derived.HP,
            player_san=player.derived.SAN,
        )

        # Build initiative order: (actor_id, DEX)
        order = [("player", player.stats.DEX if hasattr(player, 'stats') else 50)]
        for enemy in combat_init.enemies:
            dex = 50
            if hasattr(enemy, 'attributes'):
                dex = enemy.attributes.get("DEX", 50)
            elif hasattr(enemy, 'dex'):
                dex = enemy.dex
            order.append((enemy.instance_id, dex))
        order.sort(key=lambda x: -x[1])
        state.initiative_order = [oid for oid, _ in order]

        first_actor = state.initiative_order[0]
        state.is_player_turn = (first_actor == "player")
        return state

    # ── Player actions ──

    def _get_player_actions(self, player) -> list[dict]:
        """Build fixed action list from player skills and weapons."""
        actions = [
            {"id": "punch", "label": "拳击", "skill": "格斗(拳)", "damage": "1D3+DB",
             "value": self._skill_value(player, "格斗(拳)")},
            {"id": "kick", "label": "踢击", "skill": "格斗(脚)", "damage": "1D6+DB",
             "value": self._skill_value(player, "格斗(脚)")},
            {"id": "dodge", "label": "回避", "skill": "回避",
             "value": self._skill_value(player, "回避"), "damage": None},
            {"id": "flee", "label": "逃跑", "skill": None, "value": None, "damage": None},
        ]
        for w in getattr(player, 'weapons', []):
            weapon_skill = getattr(w, 'skill_name', '') or getattr(w, 'skill_used', '')
            skill_val = self._skill_value(player, weapon_skill)
            actions.append({
                "id": f"weapon:{w.name}", "label": w.name,
                "skill": weapon_skill, "damage": w.damage,
                "value": skill_val,
            })
        return actions

    def _skill_value(self, player, skill_name: str) -> int:
        """Get player skill value, defaulting to STAT/2 for untrained combat skills."""
        skill = player.get_skill(skill_name)
        if skill:
            return skill.value
        if hasattr(player, 'stats'):
            if "回避" in skill_name:
                return max(1, player.stats.DEX // 2)
            return max(1, player.stats.STR // 2)
        return 25

    def _resolve_player_action(self, state, player, action_id: str,
                               target_iid: str) -> CombatAction:
        """Execute player's chosen action. Returns CombatAction record."""
        action = CombatAction(actor="player")

        if action_id == "dodge":
            action.action_type = "dodge"
            action.success = True
            action.narrative = "你摆出防御姿态，准备闪避攻击。"
            state._player_dodging = True
            return action

        if action_id == "flee":
            action.action_type = "flee"
            enemy_dex = max(
                (e.attributes.get("DEX", 50) if hasattr(e, 'attributes') else 50)
                for e in state.enemies if getattr(e, 'status', '') != 'dead'
            )
            player_dex = player.stats.DEX if hasattr(player, 'stats') else 50
            action.skill_name = "DEX对抗"
            action.skill_value = player_dex
            action.roll = random.randint(1, 100)
            action.success = action.roll <= player_dex and action.roll < enemy_dex
            action.tier = self._get_tier(action.roll, player_dex) if action.success else "failure"
            action.narrative = ("你抓住机会逃出了战斗！" if action.success
                              else "你试图逃跑但被敌人拦住了去路。")
            if action.success:
                state.finished = True
            return action

        # Attack actions
        actions = self._get_player_actions(player)
        match = next((a for a in actions if a["id"] == action_id), None)
        if not match:
            action.narrative = "未知动作。"
            return action

        action.action_type = "attack"
        action.weapon = match["label"]
        action.skill_name = match["skill"]
        action.skill_value = match["value"]
        action.roll = random.randint(1, 100)
        action.success = action.roll <= action.skill_value
        action.tier = self._get_tier(action.roll, action.skill_value) if action.success else "failure"

        if action.success:
            enemy = next((e for e in state.enemies if e.instance_id == target_iid), None)
            if enemy:
                enemy_attrs = enemy.attributes if hasattr(enemy, 'attributes') else {}
                en_str = enemy_attrs.get("STR", 50)
                en_siz = enemy_attrs.get("SIZ", 50)
                damage = _roll_damage(match["damage"], en_str, en_siz)
                armor = enemy.armor if hasattr(enemy, 'armor') else ""
                final_damage = _apply_armor(damage, armor)
                action.damage = final_damage
                action.hp_before = getattr(enemy, 'hp', 10)
                if not hasattr(enemy, 'hp'):
                    enemy.hp = max(1, en_siz // 5)  # rough HP from SIZ
                    action.hp_before = enemy.hp
                enemy.hp = action.hp_before - final_damage
                action.hp_after = enemy.hp
                action.target = target_iid
                action.narrative = f"你的{match['label']}命中！造成{final_damage}点伤害。"
        else:
            action.narrative = f"你的{match['label']}未能命中目标。"

        return action

    def _get_tier(self, roll: int, skill_value: int) -> str:
        """Determine COC 7th success tier from D100 roll vs skill value."""
        if roll == 1:
            return "extreme"
        if roll <= max(1, skill_value // 5):
            return "extreme"
        if roll <= max(1, skill_value // 2):
            return "hard"
        return "regular"

    # ── Enemy actions ──

    def _select_enemy_attack(self, enemy) -> dict:
        """Weight-based attack selection from enemy attack list."""
        attacks = enemy.attacks if hasattr(enemy, 'attacks') else []
        if not attacks:
            return {"name": "攻击", "damage": "1D3", "weight": 1}
        weights = [a.get("weight", 1) for a in attacks]
        return random.choices(attacks, weights=weights, k=1)[0]

    def _select_enemy_target(self, state, enemy) -> str:
        """Enemy targets player (extendable to NPCs later)."""
        return "player"

    def _resolve_enemy_action(self, state, enemy, player) -> CombatAction:
        """Rule-driven enemy action. Returns CombatAction record."""
        attack = self._select_enemy_attack(enemy)
        action = CombatAction(
            actor=enemy.instance_id,
            action_type="attack",
            weapon=attack["name"],
            skill_name=attack["name"],
            target="player",
        )

        enemy_attrs = enemy.attributes if hasattr(enemy, 'attributes') else {}
        enemy_skill = (enemy_attrs.get("DEX", 50) + enemy_attrs.get("POW", 50)) // 2
        action.skill_value = enemy_skill
        action.roll = random.randint(1, 100)

        if getattr(state, '_player_dodging', False):
            action.success = False
            action.narrative = (
                f"{getattr(enemy, 'enemy_ref', '敌人')}的{attack['name']}被你闪开了。"
            )
            state._player_dodging = False
            return action

        action.success = action.roll <= enemy_skill
        action.tier = self._get_tier(action.roll, enemy_skill) if action.success else "failure"

        if action.success:
            en_str = enemy_attrs.get("STR", 50)
            en_siz = enemy_attrs.get("SIZ", 50)
            damage = _roll_damage(attack["damage"], en_str, en_siz)
            action.damage = damage
            action.hp_before = state.player_hp
            state.player_hp = max(0, state.player_hp - damage)
            action.hp_after = state.player_hp
            action.narrative = (
                f"{getattr(enemy, 'enemy_ref', '敌人')}用{attack['name']}击中了你！"
                f"造成{damage}点伤害。"
            )
        else:
            action.narrative = (
                f"{getattr(enemy, 'enemy_ref', '敌人')}的{attack['name']}未能命中你。"
            )

        return action

    # ── Round processing ──

    def _process_round(self, state, player, player_action_id: str,
                       target_iid: str) -> list[CombatAction]:
        """Execute one full combat round. Returns list of CombatActions."""
        state.log = []
        state._player_dodging = False
        player_idx = state.initiative_order.index("player") if "player" in state.initiative_order else 0

        for idx, iid in enumerate(state.initiative_order):
            if iid == "player":
                pa = self._resolve_player_action(state, player, player_action_id, target_iid)
                state.log.append(pa)
                if state.finished:
                    return state.log
                continue

            enemy = next((e for e in state.enemies if e.instance_id == iid), None)
            if not enemy or getattr(enemy, 'status', '') == 'dead' or getattr(enemy, 'hp', 1) <= 0:
                continue

            ea = self._resolve_enemy_action(state, enemy, player)
            state.log.append(ea)

            if state.player_hp <= 0:
                state.finished = True
                return state.log

        alive = [e for e in state.enemies
                if getattr(e, 'hp', 1) > 0 and getattr(e, 'status', '') != 'dead']
        if not alive:
            state.finished = True

        state.round += 1
        return state.log
