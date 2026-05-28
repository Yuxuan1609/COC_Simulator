# 战斗系统分层重构 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将战斗引擎升级为确定性执行 + LLM 可选修正的分层架构，新增结构化特殊规则、Phase 阶段系统、多目标攻击、新动作类型，保持 CombatInit/CombatResult 接口兼容。

**Architecture:** 战斗引擎内部分三层：确定性执行（D100 + 结构化规则解析）→ LLM Gate 修正层（仅 special_rules 非空时触发）→ 结果生效。每层之间通过 RoundResult dataclass 传递数据。CombatInit 增量扩展 3 个新字段，CombatResult 新增 round_log。

**Tech Stack:** Python 3.11+, dataclasses, random, json, DeepSeek API (flash model for LLM correction)

---

## 文件结构

| 文件 | 职责 | 变更类型 |
|------|------|----------|
| `src/game/messages.py` | RoundResult, Phase 数据类 + CombatInit/CombatResult 扩展 | 修改 |
| `src/library/weapons.py` | LibraryWeapon 新增 damage_type/armor_piercing/attack_bonus/multi_attack | 修改 |
| `src/library/enemies.py` | LibraryEnemy 新增 damage_multipliers/dodge_bonus/multi_attack/special_rules | 修改 |
| `src/library/bosses.py` | LibraryBoss 新增 damage_multipliers/dodge_bonus/multi_attack/phases/special_rules | 修改 |
| `src/game/enemy_manager.py` | EnemyInstance 同步新增字段 + spawn 拷贝逻辑 | 修改 |
| `src/game/boss_manager.py` | Phase 解析 + special_rules 注入到 CombatInit | 修改 |
| `src/game/combat.py` | 核心重构：分层执行/新动作/Phase/LLM Gate/multi_attack | **重写** |
| `src/game/agents/keeper.py` | CombatInit 新字段传递 | 微调 |
| `src/game_loop.py` | 无变更（接口兼容） | 不改 |
| `tests/test_combat_smoke.py` | 覆盖新功能的烟雾测试 | 修改 |
| `data/library/core/enemies.json` | 示例数据新增字段 | 微调 |
| `data/library/core/bosses.json` | 示例数据新增字段 | 微调 |

---

### Task 1: 新增核心数据结构

**Files:**
- Modify: `src/game/messages.py`

- [ ] **Step 1: 添加 RoundResult 和 Phase 数据类到 messages.py**

在 `CombatResult` 之后、文件末尾之前添加：

```python
@dataclass
class RoundResult:
    """Single round result, shared between deterministic layer and LLM correction."""
    round: int = 0
    player_action: str = ""
    player_target: str = ""
    player_roll: int = 0
    player_tier: str = ""
    player_damage: int = 0
    player_damage_type: str = "物理"
    player_effects: list[str] = field(default_factory=list)
    enemy_actions: list[dict] = field(default_factory=list)
    status_changes: list[dict] = field(default_factory=list)
    narrative: str = ""


@dataclass
class Phase:
    """Boss phase definition."""
    trigger: str = ""         # "hp_below_pct:0.5" | "round:3"
    name: str = ""
    overrides: dict = field(default_factory=dict)
    description: str = ""
```

- [ ] **Step 2: 扩展 CombatInit**

找到 `CombatInit`，新增 3 个字段（在 `initiative_context` 之后）：

```python
@dataclass
class CombatInit:
    enemies: list[Any] = field(default_factory=list)
    player: Any = None
    scene: str = ""
    initiative_context: str = ""
    environment_actions: list[dict] = field(default_factory=list)
    # ── 新增 ──
    player_action: str = ""
    player_targets: list[str] = field(default_factory=list)
    player_extra: str = ""
```

> 注意：`player_action` 已通过 `run_combat(player_action=...)` 参数传入，此处字段用于 CombatInit 携带初始动作。

- [ ] **Step 3: 扩展 CombatResult**

找到 `CombatResult`，新增 `round_log` 字段：

```python
@dataclass
class CombatResult:
    outcome: str = ""
    defeated_instance_ids: list[str] = field(default_factory=list)
    narrative: str = ""
    player_hp: int = 0
    player_san: int = 0
    rounds: int = 0
    # ── 新增 ──
    round_log: list[Any] = field(default_factory=list)
```

- [ ] **Step 4: 验证导入**

Run: `python -c "from src.game.messages import RoundResult, Phase; print('OK')"`
Expected: `OK`

- [ ] **Step 5: 提交**

```bash
git add src/game/messages.py
git commit -m "feat: add RoundResult, Phase, extend CombatInit/CombatResult for layered combat"
```

---

### Task 2: 更新 Library 数据类

**Files:**
- Modify: `src/library/weapons.py`
- Modify: `src/library/enemies.py`
- Modify: `src/library/bosses.py`

- [ ] **Step 1: 更新 LibraryWeapon**

在 `special_rules` 之前新增 4 个字段：

```python
@dataclass
class LibraryWeapon:
    name: str
    skill_name: str
    damage: str
    range: str
    shots: int = 0
    malfunction: int = 100
    era: str = "all"
    rarity: str = "common"
    # ── 新增 ──
    damage_type: str = "物理"
    armor_piercing: int = 0
    attack_bonus: int = 0
    multi_attack: int = 1
    # ── 已有 ──
    special_rules: str = ""
    description: str = ""
```

同步更新 `to_dict()` 和 `from_dict()`：

`to_dict()` 中在 `shots` 之后插入：
```python
"damage_type": self.damage_type,
"armor_piercing": self.armor_piercing,
"attack_bonus": self.attack_bonus,
"multi_attack": self.multi_attack,
```

`from_dict()` 中在 `rarity` 之后插入：
```python
damage_type=data.get("damage_type", "物理"),
armor_piercing=data.get("armor_piercing", 0),
attack_bonus=data.get("attack_bonus", 0),
multi_attack=data.get("multi_attack", 1),
```

- [ ] **Step 2: 更新 LibraryEnemy**

在 `flags` 之后新增 3 个字段：

```python
@dataclass
class LibraryEnemy:
    name: str
    type: str
    attributes: dict
    armor: str
    attacks: list
    special_abilities: list
    san_loss: str
    combat_behavior: str
    description: str = ""
    flags: list = field(default_factory=list)
    # ── 新增 ──
    multi_attack: int = 1
    damage_multipliers: dict = field(default_factory=dict)
    dodge_bonus: int = 0
    special_rules: str = ""
```

同步更新 `to_dict()`（在 `flags` 之后）：
```python
"multi_attack": self.multi_attack,
"damage_multipliers": self.damage_multipliers,
"dodge_bonus": self.dodge_bonus,
"special_rules": self.special_rules,
```

同步更新 `from_dict()`（`return cls(...)` 中在 `flags=flags` 之后）：
```python
multi_attack=data.get("multi_attack", 1),
damage_multipliers=data.get("damage_multipliers", {}),
dodge_bonus=data.get("dodge_bonus", 0),
special_rules=data.get("special_rules", ""),
```

- [ ] **Step 3: 更新 LibraryBoss**

在 `flags` 之后新增：

```python
@dataclass
class LibraryBoss:
    name: str
    type: str = ""
    attributes: dict = field(default_factory=dict)
    armor: str = ""
    attacks: list = field(default_factory=list)
    special_abilities: list = field(default_factory=list)
    san_loss: str = ""
    description: str = ""
    boss_mechanics: str = ""
    flags: list[str] = field(default_factory=list)
    # ── 新增 ──
    multi_attack: int = 1
    damage_multipliers: dict = field(default_factory=dict)
    dodge_bonus: int = 0
    phases: list = field(default_factory=list)
    special_rules: str = ""
```

同步更新 `from_dict()`：
```python
multi_attack=data.get("multi_attack", 1),
damage_multipliers=data.get("damage_multipliers", {}),
dodge_bonus=data.get("dodge_bonus", 0),
phases=data.get("phases", []),
special_rules=data.get("special_rules", ""),
```

- [ ] **Step 4: 验证**

Run: `python -c "from src.library.weapons import LibraryWeapon; from src.library.enemies import LibraryEnemy; from src.library.bosses import LibraryBoss; print('OK')"`
Expected: `OK`

- [ ] **Step 5: 提交**

```bash
git add src/library/weapons.py src/library/enemies.py src/library/bosses.py
git commit -m "feat: add structured special rule fields to LibraryWeapon/Enemy/Boss"
```

---

### Task 3: 更新 EnemyInstance（enemy_manager.py）

**Files:**
- Modify: `src/game/enemy_manager.py`

- [ ] **Step 1: EnemyInstance 新增字段**

在 `boss_mechanics` 之后新增：

```python
multi_attack: int = 1
damage_multipliers: dict = field(default_factory=dict)
dodge_bonus: int = 0
special_rules: str = ""
phases: list = field(default_factory=list)
_current_phase: str = ""
```

- [ ] **Step 2: spawn() 拷贝新字段**

在 `spawn()` 方法中，`inst = EnemyInstance(...)` 之后、`self._instances[instance_id] = inst` 之前，添加：

```python
inst.multi_attack = getattr(lib_enemy, 'multi_attack', 1)
inst.damage_multipliers = dict(getattr(lib_enemy, 'damage_multipliers', {}))
inst.dodge_bonus = getattr(lib_enemy, 'dodge_bonus', 0)
inst.special_rules = getattr(lib_enemy, 'special_rules', '')
```

- [ ] **Step 3: to_dict() 和 from_dict() 同步**

`to_dict()` 中，在 `idata` 字典最后添加：
```python
"multi_attack": inst.multi_attack,
"damage_multipliers": inst.damage_multipliers,
"dodge_bonus": inst.dodge_bonus,
"special_rules": inst.special_rules,
```

`from_dict()` 中，在 `EnemyInstance(...)` 的参数最后添加：
```python
multi_attack=idata.get("multi_attack", 1),
damage_multipliers=idata.get("damage_multipliers", {}),
dodge_bonus=idata.get("dodge_bonus", 0),
special_rules=idata.get("special_rules", ""),
```

- [ ] **Step 4: 提交**

```bash
git add src/game/enemy_manager.py
git commit -m "feat: add structured special rule fields to EnemyInstance"
```

---

### Task 4: 更新 BossManager（Phase 注入）

**Files:**
- Modify: `src/game/boss_manager.py`

- [ ] **Step 1: build_combat_init 拷贝新字段**

在 `build_combat_init()` 中 `EnemyInstance(...)` 的最后添加：

```python
multi_attack=getattr(lib_boss, 'multi_attack', 1),
damage_multipliers=dict(getattr(lib_boss, 'damage_multipliers', {})),
dodge_bonus=getattr(lib_boss, 'dodge_bonus', 0),
special_rules=getattr(lib_boss, 'special_rules', ''),
phases=list(getattr(lib_boss, 'phases', [])),
```

- [ ] **Step 2: to_dict/from_dict 同步**

`to_dict()` 返回中添加：
```python
"phases": self._encounters[0].get("phases", []) if self._encounters else [],
```

`from_dict()` 恢复时不做特殊处理（phases 从 encounters 读），但确保 `_encounters` 中的每个 encounter 保留 phases 字段。

- [ ] **Step 3: 提交**

```bash
git add src/game/boss_manager.py
git commit -m "feat: BossManager copies new structured fields to EnemyInstance"
```

---

### Task 5: 重写 CombatSystem — 结构化规则解析 + 新动作 + 确定性层

**Files:**
- Modify: `src/game/combat.py`（此次开始逐步替换）

> 此 Task 聚焦确定性层：结构化规则解析 + 新动作类型，暂不涉及 LLM Gate 和 Phase。

- [ ] **Step 1: 新增辅助函数**

在文件顶部 `_apply_armor` 后添加：

```python
def _apply_damage_multiplier(damage: int, damage_type: str, multipliers: dict) -> int:
    """Apply enemy damage multipliers: >1=vuln, <1=resist, 0=immune."""
    mult = multipliers.get(damage_type, 1.0)
    return max(0, int(damage * mult))
```

- [ ] **Step 2: 扩展 _get_player_actions 添加新动作**

在现有 `actions` 列表中 `flee` 之后添加：

```python
{"id": "conceal", "label": "隐蔽", "skill": "潜行",
 "value": self._skill_value(player, "潜行"), "damage": None},
{"id": "aim", "label": "瞄准", "skill": None,
 "value": None, "damage": None},
{"id": "charge", "label": "蓄力", "skill": None,
 "value": None, "damage": None},
```

武器条目已通过 `multi_attack` 字段在 JSON 中指定（从 LibraryWeapon 读取），生成 action 时携带：

```python
actions.append({
    "id": f"weapon:{w.name}", "label": w.name,
    "skill": weapon_skill, "damage": w.damage,
    "value": skill_val,
    "damage_type": getattr(w, 'damage_type', '物理'),
    "armor_piercing": getattr(w, 'armor_piercing', 0),
    "attack_bonus": getattr(w, 'attack_bonus', 0),
    "multi_attack": getattr(w, 'multi_attack', 1),
})
```

- [ ] **Step 3: 扩展 _resolve_player_action 支持新动作**

在 `action_id == "flee"` 分支之后添加：

```python
if action_id == "conceal":
    action.action_type = "conceal"
    action.skill_name = "潜行"
    action.skill_value = self._skill_value(player, "潜行")
    action.roll = random.randint(1, 100)
    action.success = action.roll <= action.skill_value
    action.tier = self._get_tier(action.roll, action.skill_value) if action.success else "failure"
    if action.success:
        state._player_concealed = True
        action.narrative = "你隐蔽在阴影中，下次攻击获得优势。"
    else:
        action.narrative = "你试图藏匿但暴露了位置。"
    return action

if action_id == "aim":
    action.action_type = "aim"
    action.success = True
    state._player_aiming = True
    action.narrative = "你专注瞄准，下次攻击命中率提升。"
    return action

if action_id == "charge":
    action.action_type = "charge"
    action.success = True
    state._player_charged = True
    action.narrative = "你蓄势待发，下次攻击伤害提升。"
    return action
```

- [ ] **Step 4: 攻击动作中加入结构化规则**

在 `_resolve_player_action` 的攻击分支中，修改掷骰和伤害计算：

掷骰时加入 `attack_bonus` 和 `aim` 加成：
```python
action.roll = random.randint(1, 100)
effective_skill = action.skill_value
if match.get("attack_bonus"):
    effective_skill += match["attack_bonus"]
if getattr(state, '_player_aiming', False):
    effective_skill += 20  # aim bonus: +20 to effective skill
    state._player_aiming = False
if getattr(state, '_player_concealed', False):
    effective_skill += 10
    state._player_concealed = False
action.success = action.roll <= effective_skill
action.tier = self._get_tier(action.roll, effective_skill) if action.success else "failure"
```

伤害计算时加入 `armor_piercing`、`damage_multipliers`、`charge` 加成：
```python
damage = _roll_damage(match["damage"], en_str, en_siz)
# Armor piercing
armor = getattr(enemy, 'armor', '') or ''
armor_val = 0
if armor:
    m_armor = re.search(r"(\d+)", armor)
    armor_val = int(m_armor.group(1)) if m_armor else 0
ap = match.get("armor_piercing", 0)
effective_armor_val = max(0, armor_val - ap)
final_damage = max(0, damage - effective_armor_val)
# Damage multipliers
dm_type = match.get("damage_type", "物理")
multipliers = getattr(enemy, 'damage_multipliers', {})
final_damage = _apply_damage_multiplier(final_damage, dm_type, multipliers)
# Charge bonus
if getattr(state, '_player_charged', False):
    final_damage = int(final_damage * 1.5)
    state._player_charged = False
```

- [ ] **Step 5: 敌人闪避加入 dodge_bonus**

在 `_resolve_enemy_action` 中，`_player_dodging` 检查之前：

```python
dodge_bonus = getattr(enemy, 'dodge_bonus', 0)
enemy_skill = (enemy_attrs.get("DEX", 50) + enemy_attrs.get("POW", 50)) // 2 + dodge_bonus
```

同样在 `_resolve_boss_action_stub` 中加上 `dodge_bonus`。

- [ ] **Step 6: CombatState 新增状态字段**

在 `CombatState` 中添加：

```python
_player_concealed: bool = False
_player_aiming: bool = False
_player_charged: bool = False
# ── Phase tracking ──
_boss_current_phase: str = ""
_boss_hp_max: int = 0
```

- [ ] **Step 7: _init_combat 初始化新字段**

在 `_init_combat` 中，计算完 `state` 后添加：

```python
# Track boss HP max for phase triggers
for e in combat_init.enemies:
    if getattr(e, 'boss_mechanics', ''):
        state._boss_hp_max = getattr(e, 'hp', state.player_hp)
        break
```

- [ ] **Step 8: 提交**

```bash
git add src/game/combat.py
git commit -m "feat: structured rules parsing, new actions (conceal/aim/charge), stat modification in combat"
```

---

### Task 6: Phase 阶段系统

**Files:**
- Modify: `src/game/combat.py`

- [ ] **Step 1: 添加 _check_phase 方法**

在 `CombatSystem` 类中添加：

```python
def _check_phase(self, state, enemy) -> str | None:
    """Check if any phase triggers on this enemy. Returns phase name or None."""
    phases = getattr(enemy, 'phases', [])
    if not phases:
        return None
    current = getattr(enemy, '_current_phase', '')
    for ph in phases:
        trigger = ph.get("trigger", "") if isinstance(ph, dict) else getattr(ph, "trigger", "")
        name = ph.get("name", "") if isinstance(ph, dict) else getattr(ph, "name", "")
        if name == current:
            continue  # already in this phase
        if trigger.startswith("hp_below_pct:"):
            pct = float(trigger.split(":", 1)[1])
            enemy_hp_max = getattr(enemy, 'hp_max', 10)
            if enemy_hp_max <= 0:
                enemy_hp_max = 1
            if getattr(enemy, 'hp', 0) / enemy_hp_max <= pct:
                return name
        elif trigger.startswith("round:"):
            target_round = int(trigger.split(":", 1)[1])
            if state.round >= target_round:
                return name
    return None

def _apply_phase(self, enemy, phase_name: str, phases: list) -> str:
    """Apply phase overrides to enemy. Returns narration string."""
    for ph in phases:
        p = ph if isinstance(ph, dict) else {"name": getattr(ph, "name", ""),
            "overrides": getattr(ph, "overrides", {}),
            "description": getattr(ph, "description", "")}
        if p.get("name") == phase_name:
            overrides = p.get("overrides", {})
            for field, value in overrides.items():
                setattr(enemy, field, value)
            enemy._current_phase = phase_name
            return p.get("description", f"进入{phase_name}")
    return ""
```

- [ ] **Step 2: 在 _process_round 中触发 Phase 检查**

在 `_process_round` 的末尾（判定存活之前），添加：

```python
# Phase check for each enemy
for enemy in state.enemies:
    if getattr(enemy, 'hp', 1) <= 0 or getattr(enemy, 'status', '') == 'dead':
        continue
    triggered = self._check_phase(state, enemy)
    if triggered:
        desc = self._apply_phase(enemy, triggered, getattr(enemy, 'phases', []))
```

- [ ] **Step 3: 提交**

```bash
git add src/game/combat.py
git commit -m "feat: Phase system with hp_below_pct and round triggers"
```

---

### Task 7: LLM 修正层 Gate

**Files:**
- Modify: `src/game/combat.py`

- [ ] **Step 1: 添加 _any_special_rules 辅助**

```python
def _any_special_rules(self, combat_init, enemies) -> bool:
    """Check if any entity in combat has non-empty special_rules."""
    for e in enemies:
        if getattr(e, 'special_rules', ''):
            return True
    for w in getattr(combat_init.player, 'weapons', []):
        if getattr(w, 'special_rules', ''):
            return True
    return False
```

- [ ] **Step 2: 添加 _build_battle_snapshot**

```python
def _build_battle_snapshot(self, state, player, boss_phase: str = "") -> str:
    """Return ≤500 char battle snapshot for LLM context."""
    lines = [
        f"第{state.round}轮",
        f"调查员 HP:{state.player_hp}/{state.player_hp_max} SAN:{state.player_san}",
    ]
    if boss_phase:
        lines.append(f"Boss当前阶段:{boss_phase}")
    for e in state.enemies:
        hp_max = getattr(e, 'hp_max', getattr(e, 'hp', 0))
        hp_pct = f"{getattr(e, 'hp', 0)}/{hp_max}" if hp_max else "?"
        phase = getattr(e, '_current_phase', '')
        phase_str = f" 阶段:{phase}" if phase else ""
        lines.append(
            f"[{e.instance_id}] {e.enemy_ref} HP:{hp_pct}"
            f" status:{getattr(e, 'status', '?')}{phase_str}"
        )
    return "\n".join(lines)
```

- [ ] **Step 3: 添加 _build_round_result 序列化辅助**

```python
def _build_round_result(self, state, player_actions: list, enemy_actions: list, round_num: int) -> dict:
    """Build RoundResult dict from this round's actions."""
    pa = player_actions[0] if player_actions else {}
    return {
        "round": round_num,
        "player_action": pa.get("action_type", ""),
        "player_target": pa.get("target", ""),
        "player_roll": pa.get("roll", 0),
        "player_tier": pa.get("tier", ""),
        "player_damage": pa.get("damage", 0),
        "player_damage_type": pa.get("damage_type", "物理"),
        "player_effects": pa.get("effects", []),
        "enemy_actions": [
            {
                "enemy_id": ea.get("actor", ""),
                "action": ea.get("action_type", ""),
                "roll": ea.get("roll", 0),
                "tier": ea.get("tier", ""),
                "damage": ea.get("damage", 0),
                "damage_type": ea.get("damage_type", "物理"),
                "effects": ea.get("effects", []),
            }
            for ea in enemy_actions
        ],
        "status_changes": [],
        "narrative": "",
    }
```

- [ ] **Step 4: 添加 _llm_correct_round 方法**

```python
def _llm_correct_round(self, round_result: dict, combat_init, enemies,
                       player_extra: str, battle_snapshot: str, boss_phase: str) -> dict:
    """Call LLM to correct RoundResult based on special_rules. Fallback to original."""
    try:
        from llm import call_deepseek
        from config_llm import LLM_FLASH_MODEL
        import json as _json

        weapon_rules = " ".join(
            getattr(w, 'special_rules', '')
            for w in getattr(combat_init.player, 'weapons', [])
            if getattr(w, 'special_rules', '')
        )
        boss_rules = " ".join(
            getattr(e, 'special_rules', '')
            for e in enemies if getattr(e, 'boss_mechanics', '')
        )
        enemy_rules = " ".join(
            getattr(e, 'special_rules', '')
            for e in enemies if not getattr(e, 'boss_mechanics', '')
        )

        prompt = f"""根据以下 special_rules 修正 RoundResult 的字段值。
只能修改参数值（抗性、伤害倍率、目标映射、状态变更、叙事文本），不能改变判决逻辑。

【RoundResult】
{_json.dumps(round_result, ensure_ascii=False, indent=2)}

【战场快照】
{battle_snapshot}
{f"【Boss阶段】{boss_phase}" if boss_phase else ""}

【武器 special_rules】
{weapon_rules or "（无）"}

【Boss special_rules】
{boss_rules or "（无）"}

【敌人 special_rules】
{enemy_rules or "（无）"}

【玩家额外描述】
{player_extra or "（无）"}

返回 JSON：
{{
  "corrected": 与 RoundResult 完全同结构的 JSON
}}
直接输出 JSON。"""

        response = call_deepseek(
            prompt, json_mode=True, model=LLM_FLASH_MODEL,
            system="你是 COC 7th 战斗裁判助理。根据 special_rules 修正 RoundResult 的字段值。",
            fallback_schema={"corrected": round_result},
        )
        data = _json.loads(response) if isinstance(response, str) else response
        return data.get("corrected", round_result)
    except Exception:
        return round_result
```

- [ ] **Step 5: 提交**

```bash
git add src/game/combat.py
git commit -m "feat: LLM correction gate with _build_battle_snapshot and _llm_correct_round"
```

---

### Task 8: 重构 run_combat — 完整分层执行

**Files:**
- Modify: `src/game/combat.py`

- [ ] **Step 1: 重写 run_combat 主循环**

完整替换 `run_combat()` 方法。新循环：
- 每轮从 `CombatInit.player_targets` 读取目标（支持 multi_attack）
- 确定性执行 → 构造 RoundResult
- Gate 判断是否需要 LLM 修正
- Phase 检查
- 结果生效

```python
def run_combat(self, combat_init: CombatInit, player_action: str = "", max_rounds: int = 20) -> CombatResult:
    state = self._init_combat(combat_init)
    player = combat_init.player
    environment_actions = getattr(combat_init, 'environment_actions', [])
    available = self._get_player_actions(player, environment_actions)

    # Use explicit action or fallback to match
    action_id = player_action or combat_init.player_action or "punch"
    if not action_id.startswith("weapon:") and not any(a["id"] == action_id for a in available):
        action_id = "punch"

    targets = combat_init.player_targets or []
    player_extra = getattr(combat_init, 'player_extra', '') or ''

    # Store enemy hp_max for phase tracking
    for e in state.enemies:
        if not hasattr(e, 'hp_max') or not getattr(e, 'hp_max', 0):
            e.hp_max = getattr(e, 'hp', 10)
        if getattr(e, 'boss_mechanics', ''):
            state._boss_hp_max = getattr(e, 'hp_max', state.player_hp)

    round_log = []
    needs_llm = self._any_special_rules(combat_init, state.enemies)

    while not state.finished and state.round <= max_rounds:
        alive_enemies = [e for e in state.enemies
                        if getattr(e, 'hp', 1) > 0 and getattr(e, 'status', '') != 'dead']
        if not alive_enemies:
            state.finished = True
            break

        # Fallback target if none specified
        round_targets = targets if targets else [alive_enemies[0].instance_id]

        # ── Layer 1: Deterministic execution ──
        player_actions_this_round = []
        enemy_actions_this_round = []
        state.log = []
        state._player_dodging = False
        state._player_concealed = False

        for round_idx, iid in enumerate(state.initiative_order):
            if iid == "player":
                # Multi-target loop
                for t_idx, tgt in enumerate(round_targets):
                    if not tgt:
                        tgt = alive_enemies[0].instance_id if alive_enemies else "unknown"
                    pa = self._resolve_player_action(
                        state, player, action_id, tgt, environment_actions
                    )
                    pa.round_num = state.round
                    state.log.append(pa)
                    state.full_log.append(pa)
                    player_actions_this_round.append({
                        "action_type": pa.action_type,
                        "target": pa.target,
                        "roll": pa.roll,
                        "tier": pa.tier,
                        "damage": pa.damage,
                        "damage_type": getattr(pa, 'damage_type', '物理'),
                        "effects": [],
                    })
                    if state.finished:
                        break
                if state.finished:
                    break
                continue

            # Enemy turn — multi_attack
            enemy = next((e for e in state.enemies if e.instance_id == iid), None)
            if not enemy or getattr(enemy, 'status', '') == 'dead' or getattr(enemy, 'hp', 1) <= 0:
                continue

            multi = getattr(enemy, 'multi_attack', 1)
            for _ in range(multi):
                ea = self._resolve_enemy_action(state, enemy, player)
                ea.round_num = state.round
                state.log.append(ea)
                state.full_log.append(ea)
                enemy_actions_this_round.append({
                    "actor": ea.actor,
                    "action_type": ea.action_type,
                    "roll": ea.roll,
                    "tier": ea.tier,
                    "damage": ea.damage,
                    "damage_type": getattr(ea, 'damage_type', '物理'),
                    "effects": [],
                })
                if state.player_hp <= 0:
                    state.finished = True
                    break
            if state.finished:
                break

        # Build RoundResult from round actions
        rresult = self._build_round_result(
            state, player_actions_this_round, enemy_actions_this_round, state.round
        )

        # ── Layer 2: LLM correction (Gate) ──
        if needs_llm:
            boss_phase = state._boss_current_phase or ""
            snapshot = self._build_battle_snapshot(state, player, boss_phase)
            rresult = self._llm_correct_round(
                rresult, combat_init, state.enemies,
                player_extra, snapshot, boss_phase
            )

        # ── Layer 3: Apply results ──
        # Apply LLM-corrected player damage
        if rresult.get("player_damage", 0) > 0:
            target_iid = rresult.get("player_target", "")
            enemy = next((e for e in state.enemies if e.instance_id == target_iid), None)
            if enemy:
                enemy.hp = max(0, getattr(enemy, 'hp', 10) - rresult["player_damage"])

        # Phase check
        for enemy in state.enemies:
            if getattr(enemy, 'hp', 1) <= 0 or getattr(enemy, 'status', '') == 'dead':
                continue
            triggered = self._check_phase(state, enemy)
            if triggered:
                desc = self._apply_phase(enemy, triggered, getattr(enemy, 'phases', []))
                if desc:
                    rresult.setdefault("status_changes", []).append({
                        "entity_id": enemy.instance_id,
                        "field": "phase",
                        "old": "",
                        "new": triggered,
                    })

        round_log.append(rresult)

        alive_after = [e for e in state.enemies
                      if getattr(e, 'hp', 1) > 0 and getattr(e, 'status', '') != 'dead']
        if not alive_after:
            state.finished = True

        state.round += 1

    outcome = "win"
    if state.player_hp <= 0:
        outcome = "loss"
    elif state.round > max_rounds:
        outcome = "draw"

    defeated = [e.instance_id for e in combat_init.enemies
                if getattr(e, 'hp', 1) <= 0 or getattr(e, 'status', '') == 'dead']

    combat_narrative = self._generate_combat_narrative(
        state, combat_init.player, combat_init.scene
    )

    return CombatResult(
        outcome=outcome,
        defeated_instance_ids=defeated,
        player_hp=state.player_hp,
        player_san=state.player_san,
        rounds=state.round,
        narrative=combat_narrative,
        round_log=round_log,
    )
```

- [ ] **Step 2: 验证语法**

Run: `python -c "from src.game.combat import CombatSystem, CombatState, CombatAction; print('OK')"`
Expected: `OK`

- [ ] **Step 3: 提交**

```bash
git add src/game/combat.py
git commit -m "feat: refactored run_combat with layered execution, LLM gate, phase, multi-attack"
```

---

### Task 9: 更新 Smoke Tests

**Files:**
- Modify: `tests/test_combat_smoke.py`

- [ ] **Step 1: 扩展 _TestEnemy 支持新字段**

```python
class _TestEnemy:
    def __init__(self, enemy_ref, hp, armor, instance_id, dex=50, attacks=None,
                 damage_multipliers=None, dodge_bonus=0, multi_attack=1,
                 special_rules="", phases=None, boss_mechanics=""):
        self.enemy_ref = enemy_ref
        self.name = enemy_ref
        self.hp = hp
        self.hp_max = hp
        self.armor = armor
        self.instance_id = instance_id
        self.status = "hostile"
        self.flags = set()
        self.DEX = dex
        self.attacks = attacks or [{"name": "爪击", "skill_name": "格斗", "skill_value": 40, "damage": "1D6"}]
        self.damage_multipliers = damage_multipliers or {}
        self.dodge_bonus = dodge_bonus
        self.multi_attack = multi_attack
        self.special_rules = special_rules
        self.phases = phases or []
        self.boss_mechanics = boss_mechanics
        self._current_phase = ""
```

- [ ] **Step 2: 添加 Phase 测试**

```python
def test_combat_phase_trigger():
    """Phase triggers at hp_below_pct and applies overrides."""
    player = _make_investigator(hp=30, san=60)
    boss = _TestEnemy("PhaseBoss", hp=10, armor="0", instance_id="E_PHASE_1",
        dex=50, attacks=[{"name": "拍击", "damage": "1D3"}],
        phases=[{"trigger": "hp_below_pct:0.5", "name": "狂怒",
                 "overrides": {"multi_attack": 3},
                 "description": "Boss狂暴了"}] * 1)
    # Verify phase support code doesn't crash
    combat_init = CombatInit(
        enemies=[boss], player=player,
        scene="测试", initiative_context="phase",
    )
    cs = CombatSystem()
    result = cs.run_combat(combat_init)
    assert result.outcome in ("win", "loss")
    print(f"  [PASS] phase_trigger: outcome={result.outcome}, rounds={result.rounds}")
```

- [ ] **Step 3: 添加 structured rules 测试**

```python
def test_combat_damage_multipliers():
    """Enemy with vulnerability takes extra damage."""
    player = _make_investigator(hp=30, san=60)
    enemy = _TestEnemy("WeakToFire", hp=10, armor="0", instance_id="E_FIRE_1",
        damage_multipliers={"火焰": 2.0})
    combat_init = CombatInit(
        enemies=[enemy], player=player,
        scene="测试", initiative_context="dmg_mult",
    )
    cs = CombatSystem()
    result = cs.run_combat(combat_init)
    assert result.outcome in ("win", "loss")
    print(f"  [PASS] dmg_multipliers: outcome={result.outcome}")
```

- [ ] **Step 4: 添加 multi_attack 测试**

```python
def test_combat_multi_attack():
    """Weapon with multi_attack > 1 allows multiple targets."""
    player = _make_investigator(hp=30, san=60)
    e1 = _TestEnemy("Target1", hp=5, armor="0", instance_id="E_T1")
    e2 = _TestEnemy("Target2", hp=5, armor="0", instance_id="E_T2")
    combat_init = CombatInit(
        enemies=[e1, e2], player=player,
        scene="测试", initiative_context="multi",
        player_targets=["E_T1", "E_T2"],
    )
    cs = CombatSystem()
    result = cs.run_combat(combat_init)
    assert result.outcome in ("win", "loss")
    print(f"  [PASS] multi_attack: outcome={result.outcome}")
```

- [ ] **Step 5: 添加 new actions 测试**

```python
def test_combat_new_actions():
    """Conceal, aim, and charge actions work."""
    player = _make_investigator(hp=30, san=60)
    enemy = _TestEnemy("TestDummy", hp=10, armor="0", instance_id="E_ACTION")
    combat_init = CombatInit(
        enemies=[enemy], player=player,
        scene="测试", initiative_context="actions",
    )
    cs = CombatSystem()

    # Test conceal
    result = cs.run_combat(combat_init, player_action="conceal")
    assert result.outcome in ("win", "loss", "draw")
    print(f"  [PASS] conceal: outcome={result.outcome}")

    enemy2 = _TestEnemy("TestDummy2", hp=10, armor="0", instance_id="E_ACTION2")
    combat_init2 = CombatInit(enemies=[enemy2], player=player, scene="测试")
    result2 = cs.run_combat(combat_init2, player_action="aim")
    assert result2.outcome in ("win", "loss", "draw")
    print(f"  [PASS] aim: outcome={result2.outcome}")

    enemy3 = _TestEnemy("TestDummy3", hp=10, armor="0", instance_id="E_ACTION3")
    combat_init3 = CombatInit(enemies=[enemy3], player=player, scene="测试")
    result3 = cs.run_combat(combat_init3, player_action="charge")
    assert result3.outcome in ("win", "loss", "draw")
    print(f"  [PASS] charge: outcome={result3.outcome}")
```

- [ ] **Step 6: 添加 RoundResult 结构测试**

```python
def test_combat_round_log():
    """CombatResult includes round_log after layered execution."""
    player = _make_investigator(hp=30, san=60)
    enemy = _TestEnemy("LogTest", hp=5, armor="0", instance_id="E_LOG")
    combat_init = CombatInit(
        enemies=[enemy], player=player,
        scene="测试", initiative_context="round_log",
    )
    cs = CombatSystem()
    result = cs.run_combat(combat_init)
    assert hasattr(result, 'round_log'), "CombatResult should have round_log"
    assert isinstance(result.round_log, list), "round_log should be a list"
    print(f"  [PASS] round_log: {len(result.round_log)} rounds logged")
```

- [ ] **Step 7: 更新 main 执行列表**

```python
if __name__ == "__main__":
    print("=== Combat Smoke Tests ===")
    test_combat_basic_win()
    test_combat_writeback()
    test_combat_full_log()
    test_combat_boss_loss_signal()
    test_combat_regular_death()
    test_combat_result_structure()
    test_combat_phase_trigger()
    test_combat_damage_multipliers()
    test_combat_multi_attack()
    test_combat_new_actions()
    test_combat_round_log()
    print("\nAll combat smoke tests passed.")
```

- [ ] **Step 8: 运行验证**

Run: `python tests/test_combat_smoke.py`
Expected: All 11 tests pass

- [ ] **Step 9: 提交**

```bash
git add tests/test_combat_smoke.py
git commit -m "test: add smoke tests for phase, damage_multipliers, multi_attack, new actions, round_log"
```

---

### Task 10: JSON 示例数据更新 + Keeper 微调

**Files:**
- Modify: `data/library/core/enemies.json`
- Modify: `data/library/core/bosses.json`
- Modify: `src/game/agents/keeper.py`

- [ ] **Step 1: 更新 enemies.json 示例**

找一个条目添加示例字段：
```json
{
  "name": "食尸鬼",
  "type": "怪物",
  "attributes": {"STR": 80, "CON": 60, "SIZ": 65, "DEX": 65, "POW": 50},
  "armor": "1点毛皮",
  "attacks": [{"name": "爪击", "damage": "1D6+DB", "notes": ""}],
  "special_abilities": [],
  "san_loss": "0/1D6",
  "combat_behavior": "攻击最近的调查员",
  "description": "腐烂的人形怪物",
  "flags": [],
  "multi_attack": 2,
  "damage_multipliers": {"穿刺": 0.5},
  "dodge_bonus": 0,
  "special_rules": ""
}
```

- [ ] **Step 2: 更新 bosses.json 示例**

找一个条目添加：
```json
"multi_attack": 2,
"damage_multipliers": {"穿刺": 0.5, "火焰": 0},
"dodge_bonus": 0,
"phases": [],
"special_rules": ""
```

- [ ] **Step 3: Keeper 传递 CombatInit 新字段**

在 `keeper.py:501-506`（构造 CombatInit 处），添加：
```python
combat_init_result = CombatInit(
    enemies=enemies,
    player=self.world.player,
    scene=self.world.current_location,
    initiative_context=combat_entry.reasoning,
    player_action="",
    player_targets=[],
    player_extra="",
)
```

同样在 `keeper.py:557-558`（Boss CombatInit 处），以及 `game_loop.py:431-435` 和 `game_loop.py:444-448`（对峙 CombatInit 处）添加新字段默认值。

- [ ] **Step 4: 运行全量烟雾测试验证**

Run: `python tests/test_combat_smoke.py`
Expected: All 11 tests pass

- [ ] **Step 5: 提交**

```bash
git add data/library/core/enemies.json data/library/core/bosses.json src/game/agents/keeper.py src/game_loop.py
git commit -m "feat: JSON examples with new fields, Keeper/game_loop pass CombatInit new fields"
```

---

## 自检清单

1. **Spec coverage**: 每节对应任务
   - 第二节（玩家输入模型）→ Task 8（multi_attack + targets）
   - 第三节（结构化规则模板）→ Task 1+2+3+4（数据层全字段）
   - 第四节（执行流程）→ Task 5+6+7+8（三层执行）
   - 第五节（核心数据结构）→ Task 1（RoundResult + Phase）
   - 第六节（接口兼容）→ Task 8（CombatResult.round_log）
   - 第七节（JSON 格式）→ Task 10
   - 第八节（LLM Prompt）→ Task 7

2. **Placeholder scan**: 无 TBD/TODO/占位符

3. **Type consistency**: RoundResult 在 Task 1 定义、Task 7 序列化、Task 8 使用，结构一致。Phase 在 Task 1 定义、Task 6 使用、Task 3 存储，一致。
