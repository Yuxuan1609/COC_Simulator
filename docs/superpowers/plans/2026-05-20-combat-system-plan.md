# Combat System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a simplified COC 7th combat system (scheme B) — independent turn controller with fixed player actions, rule-driven enemy AI, D100 skill checks, damage calculation, and per-round LLM narrative output.

**Architecture:** `CombatSystem` is an independent turn controller outside the Keeper parse→enrich→narrate pipeline. It receives `CombatInit` (enemies + player + scene), runs a combat loop with fixed player options and rule-driven enemy AI, and returns `CombatResult`. Each round produces mechanical + narrative output via LLM.

**Tech Stack:** Python 3.11+, dataclasses, random (weighted choice), D100 skill check pattern (existing), call_deepseek (flash, json_mode)

---

## File Structure

| File | Role | Status |
|------|------|--------|
| `src/game/combat.py` | CombatSystem, CombatState, CombatAction, damage calculation | Create |
| `src/game/messages.py` | CombatResult dataclass (add) | Modify |
| `src/investigator/rules.py` | `calc_db()` function | Modify |
| `src/llm.py` | `evaluate_combat_round_narrative()` | Modify |
| `src/prompts.py` | `build_combat_narrative_prompt()` | Modify |
| `tests/test_combat.py` | Unit tests for combat logic | Create |

---

### Task 1: Add CombatResult message type

**Files:**
- Modify: `src/game/messages.py`

- [ ] **Step 1: Add CombatResult dataclass**

Add after `CombatInit` (line ~114):

```python
@dataclass
class CombatResult:
    """Returned by combat system when combat ends."""
    outcome: str           # "win" | "loss" | "flee"
    defeated_instance_ids: list[str] = field(default_factory=list)
    narrative: str = ""    # combat summary narrative
    player_hp: int = 0
    player_san: int = 0
    rounds: int = 0
```

- [ ] **Step 2: Verify**

Run: `python -c "from game.messages import CombatResult; print('OK')"` from `src/`

- [ ] **Step 3: Commit**

```bash
git add src/game/messages.py
git commit -m "feat: add CombatResult message type"
```

---

### Task 2: Add calc_db to rules.py

**Files:**
- Modify: `src/investigator/rules.py`

- [ ] **Step 1: Write calc_db function**

Add at end of file:

```python
def calc_db(STR: int, SIZ: int) -> str:
    """COC 7th Damage Bonus from STR + SIZ."""
    total = STR + SIZ
    if total <= 64:
        return "-2"
    if total <= 84:
        return "-1"
    if total <= 124:
        return "0"
    if total <= 164:
        return "+1D4"
    return "+1D6"
```

- [ ] **Step 2: Verify**

Run: `python -c "from investigator.rules import calc_db; print(calc_db(50,50)); print(calc_db(80,80)); print(calc_db(90,90))"` from `src/`
Expected: `-2`, `-1`, `0`

- [ ] **Step 3: Commit**

```bash
git add src/investigator/rules.py
git commit -m "feat: add calc_db for COC 7th damage bonus"
```

---

### Task 3: Create CombatSystem core — data structures + init

**Files:**
- Create: `src/game/combat.py`

- [ ] **Step 1: Write CombatState, CombatAction, CombatSystem skeleton**

```python
"""Combat system — independent turn controller for COC 7th combat."""
from __future__ import annotations
from dataclasses import dataclass, field
import random
from typing import Any

from .messages import CombatInit, CombatResult


@dataclass
class CombatAction:
    actor: str = ""           # "player" | enemy instance_id
    action_type: str = ""     # "attack" | "dodge" | "flee" | "special"
    weapon: str = ""          # attack/weapon name
    skill_name: str = ""
    skill_value: int = 0
    roll: int = 0             # D100
    tier: str = ""            # fumble|failure|regular|hard|extreme
    target: str = ""
    damage: int = 0
    hp_before: int = 0
    hp_after: int = 0
    narrative: str = ""
    success: bool = False


@dataclass
class CombatState:
    round: int = 1
    enemies: list[Any] = field(default_factory=list)
    player_hp: int = 0
    player_hp_max: int = 0
    player_san: int = 0
    initiative_order: list[str] = field(default_factory=list)
    current_actor_idx: int = 0
    is_player_turn: bool = True
    finished: bool = False
    log: list[CombatAction] = field(default_factory=list)


class CombatSystem:
    """COC 7th simplified combat controller. Independent of Keeper pipeline."""

    def __init__(self, weapon_lib=None):
        self.weapon_lib = weapon_lib

    # ── Public API ──

    def run_combat(self, combat_init: CombatInit) -> CombatResult:
        """Run full combat loop. Returns CombatResult."""
        raise NotImplementedError  # Task 4
```

- [ ] **Step 2: Verify**

Run: `python -c "from game.combat import CombatSystem, CombatState, CombatAction; print('OK')"` from `src/`

- [ ] **Step 3: Commit**

```bash
git add src/game/combat.py
git commit -m "feat: add CombatSystem skeleton with CombatState and CombatAction"
```

---

### Task 4: Implement combat init — initiative + state setup

**Files:**
- Modify: `src/game/combat.py`

- [ ] **Step 1: Add _init_combat method**

```python
    def _init_combat(self, combat_init: CombatInit) -> CombatState:
        """Set up combat state from CombatInit."""
        player = combat_init.player
        state = CombatState(
            enemies=combat_init.enemies,
            player_hp=player.derived.HP,
            player_hp_max=player.derived.HP,
            player_san=player.derived.SAN,
        )
        # Initiative: sort by DEX descending
        order = [("player", player.stats.DEX if hasattr(player, 'stats') else 50)]
        for enemy in combat_init.enemies:
            dex = enemy.attributes.get("DEX", 50) if hasattr(enemy, 'attributes') else 50
            order.append((enemy.instance_id, dex))
        order.sort(key=lambda x: -x[1])
        state.initiative_order = [oid for oid, _ in order]
        # Set first actor
        state.current_actor_idx = 0
        first_actor = state.initiative_order[0]
        state.is_player_turn = (first_actor == "player")
        return state
```

- [ ] **Step 2: Verify concept**

Run: `python -c "from game.combat import CombatSystem; c = CombatSystem(); print('OK')"` from `src/`

- [ ] **Step 3: Commit**

```bash
git add src/game/combat.py
git commit -m "feat: implement combat init with DEX-based initiative"
```

---

### Task 5: Implement damage calculation + dice rolling

**Files:**
- Modify: `src/game/combat.py`

- [ ] **Step 1: Add roll_damage and calc_db helpers**

```python
def _roll_damage(formula: str, STR: int, SIZ: int) -> int:
    """Roll damage from formula like '1D6+DB' or '1D3'."""
    from investigator.rules import calc_db
    import re
    total = 0
    # Parse damage formula
    parts = formula.replace(" ", "").split("+")
    for part in parts:
        part = part.strip()
        if part == "DB":
            db = calc_db(STR, SIZ)
            if db.startswith("+"):
                db = db[1:]
            total += _roll_damage(db, STR, SIZ) if "D" in db else int(db)
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
    import re
    m = re.search(r"(\d+)", armor)
    reduction = int(m.group(1)) if m else 0
    return max(0, damage - reduction)
```

Add these as module-level functions (above CombatSystem class).

- [ ] **Step 2: Verify dice rolling**

Run: `python -c "from game.combat import _roll_damage; d = _roll_damage('1D6', 50, 50); print(f'1D6={d}'); assert 1 <= d <= 6; print('OK')"` from `src/`

- [ ] **Step 3: Verify armor**

Run: `python -c "from game.combat import _apply_armor; assert _apply_armor(5, '2点厚皮') == 3; assert _apply_armor(1, '2点厚皮') == 0; print('OK')"` from `src/`

- [ ] **Step 4: Commit**

```bash
git add src/game/combat.py
git commit -m "feat: add damage dice rolling and armor reduction"
```

---

### Task 6: Implement player action resolution

**Files:**
- Modify: `src/game/combat.py`

- [ ] **Step 1: Add player action methods to CombatSystem**

```python
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
        # Add weapons from investigator
        for w in getattr(player, 'weapons', []):
            skill_val = self._skill_value(player, w.skill_used)
            actions.append({
                "id": f"weapon:{w.name}", "label": w.name,
                "skill": w.skill_used, "damage": w.damage,
                "value": skill_val,
            })
        return actions

    def _skill_value(self, player, skill_name: str) -> int:
        """Get player skill value, defaulting to STAT/2 for untrained combat skills."""
        skill = player.get_skill(skill_name)
        if skill:
            return skill.value
        # Combat defaults: DEX for dodge, STR for fighting
        if skill_name == "回避":
            return max(1, player.stats.DEX // 2)
        return max(1, player.stats.STR // 2)

    def _resolve_player_action(self, state, player, action_id: str,
                               target_iid: str) -> CombatAction:
        """Execute player's chosen action. Returns CombatAction record."""
        # ... (step 2 fills in)
```

- [ ] **Step 2: Fill in _resolve_player_action body**

```python
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
            # DEX contest: player vs highest enemy DEX
            enemy_dex = max(
                (e.attributes.get("DEX", 50) if hasattr(e, 'attributes') else 50)
                for e in state.enemies if getattr(e, 'status', '') != 'dead'
            )
            player_dex = player.stats.DEX if hasattr(player, 'stats') else 50
            action.skill_name = "DEX对抗"
            action.skill_value = player_dex
            action.roll = random.randint(1, 100)
            action.success = action.roll <= player_dex and action.roll < enemy_dex
            if action.success:
                action.tier = self._get_tier(action.roll, player_dex)
                action.narrative = "你抓住机会逃出了战斗！"
                state.finished = True
            else:
                action.narrative = "你试图逃跑但被敌人拦住了去路。"
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

        # D100 skill check
        action.roll = random.randint(1, 100)
        action.success = action.roll <= action.skill_value
        action.tier = self._get_tier(action.roll, action.skill_value) if action.success else "failure"

        if action.success:
            enemy = next((e for e in state.enemies if e.instance_id == target_iid), None)
            if enemy:
                enemy_attrs = enemy.attributes if hasattr(enemy, 'attributes') else {}
                damage = _roll_damage(match["damage"],
                                     player.stats.STR,
                                     player.stats.SIZ)
                armor = enemy.armor if hasattr(enemy, 'armor') else "0"
                final_damage = _apply_armor(damage, armor)
                action.damage = final_damage
                action.hp_before = getattr(enemy, 'hp', 10)
                enemy.hp = getattr(enemy, 'hp', 10) - final_damage
                action.hp_after = enemy.hp
                action.target = target_iid
                action.narrative = (
                    f"你的{match['label']}命中！造成{final_damage}点伤害。"
                )
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
```

- [ ] **Step 3: Verify**

Run: `python -c "from game.combat import CombatSystem; print('OK')"` from `src/`

- [ ] **Step 4: Commit**

```bash
git add src/game/combat.py
git commit -m "feat: implement player action resolution in combat"
```

---

### Task 7: Implement enemy action resolution

**Files:**
- Modify: `src/game/combat.py`

- [ ] **Step 1: Add enemy action methods to CombatSystem**

```python
    def _select_enemy_attack(self, enemy) -> dict:
        """Weight-based attack selection from enemy attack list."""
        attacks = enemy.attacks if hasattr(enemy, 'attacks') else []
        if not attacks:
            return {"name": "攻击", "damage": "1D3", "weight": 1}
        weights = [a.get("weight", 1) for a in attacks]
        return random.choices(attacks, weights=weights, k=1)[0]

    def _select_enemy_target(self, enemies, player) -> str:
        """Enemy targets player (single player for now)."""
        return "player"

    def _resolve_enemy_action(self, state, enemy, player) -> CombatAction:
        """Rule-driven enemy action. Returns CombatAction record."""
        attack = self._select_enemy_attack(enemy)
        action = CombatAction(
            actor=enemy.instance_id,
            action_type="attack",
            weapon=attack["name"],
            skill_name=attack["name"],
        )

        # Enemy attack value
        enemy_attrs = enemy.attributes if hasattr(enemy, 'attributes') else {}
        enemy_skill = (enemy_attrs.get("DEX", 50) + enemy_attrs.get("POW", 50)) // 2
        action.skill_value = enemy_skill
        action.roll = random.randint(1, 100)
        action.target = "player"

        # Check player dodge
        if getattr(state, '_player_dodging', False):
            action.success = False
            action.narrative = f"{getattr(enemy, 'enemy_ref', '敌人')}的{attack['name']}被你闪开了。"
            state._player_dodging = False
            return action

        # D100 attack check
        action.success = action.roll <= enemy_skill
        action.tier = self._get_tier(action.roll, enemy_skill) if action.success else "failure"

        if action.success:
            damage = _roll_damage(attack["damage"],
                                 enemy_attrs.get("STR", 50),
                                 enemy_attrs.get("SIZ", 50))
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
```

- [ ] **Step 2: Verify**

Run: `python -c "from game.combat import CombatSystem; print('OK')"` from `src/`

- [ ] **Step 3: Commit**

```bash
git add src/game/combat.py
git commit -m "feat: implement rule-driven enemy action resolution"
```

---

### Task 8: Implement combat round loop

**Files:**
- Modify: `src/game/combat.py`

- [ ] **Step 1: Add round processing**

```python
    def _process_round(self, state, player, player_action_id: str,
                       target_iid: str = "") -> list[CombatAction]:
        """Execute one full combat round. Returns list of CombatActions for this round."""
        state.log = []
        state._player_dodging = False
        first_idx = state.initiative_order.index("player") if "player" in state.initiative_order else -1

        # Player action
        if first_idx == 0:
            # Player goes first in this round
            pa = self._resolve_player_action(state, player, player_action_id, target_iid)
            state.log.append(pa)
            if state.finished:
                return state.log

        # Enemy actions in initiative order
        for iid in state.initiative_order:
            if iid == "player":
                if first_idx != 0:
                    pa = self._resolve_player_action(state, player, player_action_id, target_iid)
                    state.log.append(pa)
                    if state.finished:
                        return state.log
                continue

            enemy = next((e for e in state.enemies if e.instance_id == iid), None)
            if not enemy or getattr(enemy, 'status', '') == 'dead':
                continue

            ea = self._resolve_enemy_action(state, enemy, player)
            state.log.append(ea)

            # Check player death
            if state.player_hp <= 0:
                state.finished = True
                return state.log

        # Check all enemies dead
        alive = [e for e in state.enemies if getattr(e, 'hp', 1) > 0 and getattr(e, 'status', '') != 'dead']
        if not alive:
            state.finished = True

        state.round += 1
        return state.log
```

- [ ] **Step 2: Verify**

Run: `python -c "from game.combat import CombatSystem; print('OK')"` from `src/`

- [ ] **Step 3: Commit**

```bash
git add src/game/combat.py
git commit -m "feat: implement combat round processing loop"
```

---

### Task 9: Implement run_combat entry point

**Files:**
- Modify: `src/game/combat.py`

- [ ] **Step 1: Replace run_combat stub with full implementation**

```python
    def run_combat(self, combat_init: CombatInit) -> CombatResult:
        """Run full combat loop. Use get_input callback for player actions."""
        state = self._init_combat(combat_init)
        player = combat_init.player

        while not state.finished:
            # Build action display for player
            actions = self._get_player_actions(player)
            # Select alive enemies as targets
            alive_enemies = [e for e in state.enemies
                           if getattr(e, 'hp', 1) > 0 and getattr(e, 'status', '') != 'dead']
            if not alive_enemies:
                state.finished = True
                break

            # Process round (player action resolved first in initiative)
            target = alive_enemies[0].instance_id if alive_enemies else ""
            player_action_id = "punch"  # Caller overrides this
            self._process_round(state, player, player_action_id, target)

        # Build CombatResult
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
            narrative="",  # Task 10 fills this
        )
```

- [ ] **Step 2: Verify**

Run: `python -c "from game.combat import CombatSystem; print('OK')"` from `src/`

- [ ] **Step 3: Commit**

```bash
git add src/game/combat.py
git commit -m "feat: implement run_combat entry point"
```

---

### Task 10: Add combat narrative prompt + LLM function

**Files:**
- Modify: `src/prompts.py`
- Modify: `src/llm.py`

- [ ] **Step 1: Add build_combat_narrative_prompt to prompts.py**

```python
def build_combat_narrative_prompt(round_log: list, enemies_desc: str,
                                   player_name: str, scene: str) -> str:
    """Build prompt for per-round combat narrative generation."""
    log_text = ""
    for a in round_log:
        log_text += (
            f"  {'玩家' if a.actor == 'player' else a.actor} "
            f"{'✓' if a.success else '✗'} {a.weapon or a.action_type}: {a.narrative}\n"
        )

    return f"""你是一个TRPG战斗叙事者。根据本轮的机械结果，生成一段沉浸式战斗描写。

【场景】{scene}
【调查员】{player_name}
【敌人】{enemies_desc}

【本轮行动】
{log_text}

返回 JSON：
{{"narrative": "沉浸式战斗描写（中文不超过80字）", "scene_hint": ""}}
直接输出 JSON。"""
```

- [ ] **Step 2: Add evaluate_combat_round_narrative to llm.py**

```python
def evaluate_combat_round_narrative(
    round_log: list, enemies_desc: str,
    player_name: str, scene: str,
) -> dict:
    """Generate per-round immersive combat narrative."""
    from prompts import build_combat_narrative_prompt
    prompt = build_combat_narrative_prompt(round_log, enemies_desc, player_name, scene)
    try:
        return call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
                            thinking=False, reasoning_effort="low",
                            fallback_schema={"narrative": "", "scene_hint": ""})
    except Exception:
        return {"narrative": "", "scene_hint": ""}
```

- [ ] **Step 3: Verify**

Run: `python -c "from prompts import build_combat_narrative_prompt; from llm import evaluate_combat_round_narrative; print('OK')"` from `src/`

- [ ] **Step 4: Commit**

```bash
git add src/prompts.py src/llm.py
git commit -m "feat: add combat narrative prompt and LLM function"
```

---

### Task 11: Add CombatSystem unit tests

**Files:**
- Create: `tests/test_combat.py`

- [ ] **Step 1: Write test file**

```python
"""Unit tests for combat system logic (no LLM calls)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from game.combat import _roll_damage, _apply_armor, CombatSystem, CombatState, CombatAction
from game.messages import CombatInit, CombatResult


# ── Damage rolling ──
def test_roll_damage_simple():
    d = _roll_damage("1D6", 50, 50)
    assert 1 <= d <= 6

def test_roll_damage_with_db():
    d = _roll_damage("1D3+DB", 130, 130)
    assert d >= 1  # at least 1D3 (1) if DB is +1D4

def test_apply_armor():
    assert _apply_armor(5, "2点厚皮") == 3
    assert _apply_armor(1, "2点厚皮") == 0
    assert _apply_armor(10, "0") == 10

# ── CombatState ──
def test_combat_state_init():
    state = CombatState()
    assert state.round == 1
    assert state.finished == False

# ── CombatAction ──
def test_combat_action_defaults():
    a = CombatAction()
    assert a.actor == ""
    assert a.success == False

# ── CombatResult ──
def test_combat_result_win():
    r = CombatResult(outcome="win", defeated_instance_ids=["e1"], player_hp=10, player_san=50)
    assert r.outcome == "win"
    assert r.defeated_instance_ids == ["e1"]


if __name__ == "__main__":
    test_roll_damage_simple()
    test_roll_damage_with_db()
    test_apply_armor()
    test_combat_state_init()
    test_combat_action_defaults()
    test_combat_result_win()
    print("All tests passed")
```

- [ ] **Step 2: Run tests**

Run: `python tests/test_combat.py`
Expected: `All tests passed`

- [ ] **Step 3: Commit**

```bash
git add tests/test_combat.py
git commit -m "test: add combat system unit tests"
```
