# Boss/剧情敌人 & NPC 机制 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Boss/剧情敌人系统（独立库+L2 Entity+LLM驱动战斗）和 NPC 机制（合并 NPCProfile+运行时状态，对话路由+被动跟随），更新模组管线生成对应数据。

**Architecture:** Boss 走独立 Entity 类型 `boss_encounter`（engage_type 硬性过滤 + requirements `||` 语法）→ BossManager 信息挂钩 → CombatSystem LLM 路径。NPC 走合并后的 `NPC` dataclass（档案+运行时）→ NPCManager 全量管理 → 脱离 Entity graph。

**Tech Stack:** Python dataclasses, DeepSeek LLM API, 现有 CombatSystem/EnemyManager/Judge 框架

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `data/library/core/bosses.json` | Boss 模板库（1-2 条初始数据） |
| `src/library/bosses.py` | BossLibrary — 加载/查询 Boss 库 |
| `src/game/boss_manager.py` | BossManager — 硬性过滤 + CombatInit 构造 + 战后结算 |
| `src/game/npc_manager.py` | NPC dataclass + NPCManager — NPC 全量管理 |
| `tests/test_boss_library.py` | BossLibrary 单元测试 |
| `tests/test_boss_manager.py` | BossManager 单元测试 |
| `tests/test_npc_manager.py` | NPCManager 单元测试 |

### Modified files

| File | Changes |
|------|---------|
| `src/game/enemy_manager.py` | EnemyInstance 扩展 + spawn() 属性桥接 |
| `src/game/combat.py` | Boss LLM 路径 + 环境交互 |
| `src/game/messages.py` | CombatInit + environment_actions |
| `src/game/agents/keeper.py` | BossManager + NPCManager 集成 |
| `src/game_loop.py` | init_game/run_turn Boss+NPC 加载和路由 |
| `src/scenario_core.py` | @npc_follow markup 解析 |
| `src/module_designer/l2_keeper.py` | NPCProfile 替换为 NPC（来自 npc_manager） |
| `src/module_designer/__init__.py` | 更新 exports |
| `src/module_designer/layered_parser.py` | Step 1 boss prompt + Step 2.5 NPC 输出结构 |
| `src/module_designer/layered_pipeline.py` | parse_step2_boss + L2 _assemble_l2 |
| `src/module_designer/layered_schema.py` | boss_encounters schema + NPC schema 更新 |
| `tests/test_module_designer.py` | NPCProfile → NPC 引用更新 |

---

## Task 0: 敌人属性桥接（先决补丁）

### Task 0.1: EnemyInstance 扩展 + spawn() 桥接

**Files:**
- Modify: `src/game/enemy_manager.py:14-23, 33-48`

- [ ] **Step 1: 扩展 EnemyInstance 添加战斗属性字段**

```python
@dataclass
class EnemyInstance:
    instance_id: str
    enemy_ref: str
    scene: str
    quantity: int = 1
    status: str = "neutral"
    flags: list[str] = field(default_factory=list)
    combat_behavior: str = ""
    description: str = ""
    # ── 战斗属性桥接（从 LibraryEnemy 拷贝）──
    attributes: dict = field(default_factory=dict)       # {"STR": 80, "CON": 70, ...}
    armor: str = ""                                       # "2点厚皮"
    attacks: list = field(default_factory=list)           # [{"name": "噬咬", "damage": "1D8+DB"}, ...]
    special_abilities: list = field(default_factory=list) # [{"name": "盲感", "desc": "..."}, ...]
    san_loss: str = ""                                    # "0/1D4 (目睹)"
    hp: int = 0                                           # 运行时血量
```

- [ ] **Step 2: 修改 spawn() 从 LibraryEnemy 拷贝属性**

```python
def spawn(self, enemy_ref: str, scene: str, quantity: int = 1) -> EnemyInstance:
    lib_enemy = self._library.get(enemy_ref)
    if not lib_enemy:
        raise KeyError(f"Enemy '{enemy_ref}' not found in library")
    instance_id = f"{enemy_ref}_{_short_id()}"
    # 默认 HP = (CON + SIZ) / 10 * quantity（COC 7th 惯例）
    attrs = lib_enemy.attributes
    base_hp = (attrs.get("CON", 50) + attrs.get("SIZ", 50)) // 10 * quantity
    inst = EnemyInstance(
        instance_id=instance_id,
        enemy_ref=enemy_ref,
        scene=scene,
        quantity=quantity,
        flags=list(lib_enemy.flags),
        combat_behavior=lib_enemy.combat_behavior,
        description=lib_enemy.description,
        attributes=dict(attrs),
        armor=lib_enemy.armor,
        attacks=list(lib_enemy.attacks),
        special_abilities=list(lib_enemy.special_abilities),
        san_loss=lib_enemy.san_loss,
        hp=base_hp,
    )
    self._instances[instance_id] = inst
    return inst
```

- [ ] **Step 3: 更新 from_dict() 同样加载属性**

```python
@classmethod
def from_dict(cls, data: dict, library: EnemyLibrary) -> "EnemyManager":
    mgr = cls(library)
    for iid, idata in data.get("instances", {}).items():
        lib_enemy = library.get(idata["enemy_ref"])
        if lib_enemy:
            flags = list(lib_enemy.flags)
            behavior = lib_enemy.combat_behavior
            desc = lib_enemy.description
            attrs = dict(lib_enemy.attributes)
            armor = lib_enemy.armor
            attacks = list(lib_enemy.attacks)
            abilities = list(lib_enemy.special_abilities)
            san = lib_enemy.san_loss
            base_hp = (attrs.get("CON", 50) + attrs.get("SIZ", 50)) // 10 * idata.get("quantity", 1)
            hp = idata.get("hp", base_hp)
        else:
            flags, behavior, desc = [], "", ""
            attrs, armor, attacks, abilities, san = {}, "", [], [], ""
            hp = 10
        mgr._instances[iid] = EnemyInstance(
            instance_id=idata["instance_id"],
            enemy_ref=idata["enemy_ref"],
            scene=idata["scene"],
            quantity=idata.get("quantity", 1),
            status=idata.get("status", "neutral"),
            flags=flags,
            combat_behavior=behavior,
            description=desc,
            attributes=attrs,
            armor=armor,
            attacks=attacks,
            special_abilities=abilities,
            san_loss=san,
            hp=hp,
        )
    mgr._combat_active = data.get("combat_active", False)
    mgr._combat_enemies = data.get("combat_enemies", [])
    return mgr
```

- [ ] **Step 4: 更新 to_dict() 序列化新增字段**

```python
def to_dict(self) -> dict:
    return {
        "instances": {
            iid: {
                "instance_id": inst.instance_id,
                "enemy_ref": inst.enemy_ref,
                "scene": inst.scene,
                "quantity": inst.quantity,
                "status": inst.status,
                "hp": inst.hp,
            }
            for iid, inst in self._instances.items()
        },
        "combat_active": self._combat_active,
        "combat_enemies": self._combat_enemies,
    }
```

- [ ] **Step 5: 运行已有测试验证不破坏现有功能**

```bash
pytest tests/test_enemy_manager.py tests/test_combat.py tests/test_combat_entry.py tests/test_combat_harness.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/game/enemy_manager.py
git commit -m "feat(enemy): bridge library combat attributes to EnemyInstance on spawn"
```

---

## Task 1: Boss 库 + BossLibrary

### Task 1.1: Boss 库数据文件

**Files:**
- Create: `data/library/core/bosses.json`

- [ ] **Step 1: 创建 bosses.json（以常暗之厢的吞噬之口为例）**

```json
{
  "吞噬之口": {
    "name": "吞噬之口",
    "type": "神话生物",
    "attributes": {"STR": 200, "CON": 300, "SIZ": 250, "DEX": 10, "POW": 150},
    "armor": "10点厚皮（常规武器无效，需环境交互破解）",
    "attacks": [
      {"name": "吞噬车厢", "damage": "即死", "notes": "环境性攻击，非直接战斗伤害"}
    ],
    "special_abilities": [
      {"name": "不可阻挡", "desc": "常规武器攻击无法造成有效伤害"}
    ],
    "san_loss": "1D10/1D100",
    "description": "来自异界的巨大吞噬之口，不断吞噬列车后方的车厢。任何被吞噬之物永远消失。",
    "boss_mechanics": "弱点为驾驶室控制面板——需同时持有操作面板钥匙并通过电气维修或操作重型机械检定切断其与列车连接。常规武器攻击无效。击败触发END2（列车幸存），被吞噬触发END3，逃离触发END1。",
    "flags": ["boss"]
  }
}
```

- [ ] **Step 2: 从 enemies.json 移除 大嘴吞噬者（它本质是 Boss，非普通敌人）**

在 `data/library/core/enemies.json` 中删除 `"大嘴吞噬者"` 对应的条目（items 数组第二项）。

- [ ] **Step 3: Commit**

```bash
git add data/library/core/bosses.json data/library/core/enemies.json
git commit -m "feat(boss): add bosses.json with 吞噬之口, remove it from enemies.json"
```

### Task 1.2: BossLibrary

**Files:**
- Create: `src/library/bosses.py`
- Create: `tests/test_boss_library.py`

- [ ] **Step 1: 写测试**

```python
# tests/test_boss_library.py
import json
import tempfile
from pathlib import Path
from library.bosses import BossLibrary, LibraryBoss

SAMPLE_BOSS = {
    "name": "测试Boss",
    "type": "神话生物",
    "attributes": {"STR": 100, "CON": 80, "SIZ": 90, "DEX": 40, "POW": 60},
    "armor": "5点",
    "attacks": [{"name": "冲击", "damage": "2D6"}],
    "special_abilities": [{"name": "测试能力", "desc": "测试描述"}],
    "san_loss": "1/1D6",
    "description": "测试用Boss",
    "boss_mechanics": "弱点：测试弱点。击败触发END_TEST。",
    "flags": ["boss"],
}


def test_load_boss_library():
    with tempfile.TemporaryDirectory() as tmp:
        core = Path(tmp) / "bosses.json"
        core.write_text(json.dumps({"测试Boss": SAMPLE_BOSS}, ensure_ascii=False), encoding="utf-8")
        lib = BossLibrary(str(core))
        boss = lib.get("测试Boss")
        assert boss is not None
        assert boss.name == "测试Boss"
        assert boss.type == "神话生物"
        assert boss.attributes["STR"] == 100
        assert len(boss.attacks) == 1
        assert boss.attacks[0]["name"] == "冲击"
        assert boss.boss_mechanics == "弱点：测试弱点。击败触发END_TEST。"
        assert "boss" in boss.flags


def test_get_nonexistent():
    with tempfile.TemporaryDirectory() as tmp:
        core = Path(tmp) / "bosses.json"
        core.write_text("{}", encoding="utf-8")
        lib = BossLibrary(str(core))
        assert lib.get("不存在") is None


def test_list_all():
    with tempfile.TemporaryDirectory() as tmp:
        core = Path(tmp) / "bosses.json"
        core.write_text(json.dumps({"B1": SAMPLE_BOSS, "B2": SAMPLE_BOSS}, ensure_ascii=False), encoding="utf-8")
        lib = BossLibrary(str(core))
        names = lib.list_names()
        assert set(names) == {"B1", "B2"}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_boss_library.py -v
# Expected: ModuleNotFoundError or ImportError
```

- [ ] **Step 3: 实现 BossLibrary**

```python
# src/library/bosses.py
"""Boss library — loads boss templates from JSON."""
from __future__ import annotations
from dataclasses import dataclass, field
import json
from pathlib import Path


@dataclass
class LibraryBoss:
    """Boss template data from bosses.json."""
    name: str
    type: str = ""
    attributes: dict = field(default_factory=dict)
    armor: str = ""
    attacks: list = field(default_factory=list)
    special_abilities: list = field(default_factory=list)
    san_loss: str = ""
    description: str = ""
    boss_mechanics: str = ""   # 自然语言（弱点/环境交互/结局绑定）
    flags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "LibraryBoss":
        return cls(
            name=data.get("name", ""),
            type=data.get("type", ""),
            attributes=data.get("attributes", {}),
            armor=data.get("armor", ""),
            attacks=data.get("attacks", []),
            special_abilities=data.get("special_abilities", []),
            san_loss=data.get("san_loss", ""),
            description=data.get("description", ""),
            boss_mechanics=data.get("boss_mechanics", ""),
            flags=data.get("flags", []),
        )


class BossLibrary:
    """Loads and queries boss templates from bosses.json."""

    def __init__(self, core_path: str, extensions_dir: str | None = None):
        self._bosses: dict[str, LibraryBoss] = {}
        self._load(core_path)
        if extensions_dir:
            self._load_extensions(extensions_dir)

    def _load(self, path: str):
        p = Path(path)
        if not p.exists():
            return
        data = json.loads(p.read_text(encoding="utf-8"))
        for name, bdata in data.items():
            bdata.setdefault("name", name)
            self._bosses[name] = LibraryBoss.from_dict(bdata)

    def _load_extensions(self, extensions_dir: str):
        ext = Path(extensions_dir)
        if ext.is_dir():
            for f in ext.glob("*.json"):
                self._load(str(f))

    def get(self, boss_ref: str) -> LibraryBoss | None:
        return self._bosses.get(boss_ref)

    def list_names(self) -> list[str]:
        return list(self._bosses.keys())

    def __len__(self) -> int:
        return len(self._bosses)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_boss_library.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/library/bosses.py tests/test_boss_library.py
git commit -m "feat(boss): add BossLibrary with LibraryBoss dataclass"
```

---

## Task 2: BossManager

### Task 2.1: BossManager 实现

**Files:**
- Create: `src/game/boss_manager.py`
- Create: `tests/test_boss_manager.py`

- [ ] **Step 1: 写测试**

```python
# tests/test_boss_manager.py
import json
import tempfile
from pathlib import Path
from game.boss_manager import BossManager
from game.messages import CombatInit
from library.bosses import BossLibrary

SAMPLE_BOSS = {
    "name": "测试Boss",
    "type": "神话生物",
    "attributes": {"STR": 100, "CON": 80, "SIZ": 90, "DEX": 40, "POW": 60},
    "armor": "5点",
    "attacks": [{"name": "冲击", "damage": "2D6"}],
    "special_abilities": [],
    "san_loss": "1/1D6",
    "description": "测试用Boss",
    "boss_mechanics": "弱点：测试弱点。",
    "flags": ["boss"],
}


def _make_library():
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "bosses.json"
        p.write_text(json.dumps({"测试Boss": SAMPLE_BOSS}, ensure_ascii=False), encoding="utf-8")
        return BossLibrary(str(p))


def test_check_by_engage_type_at():
    lib = _make_library()
    encounters = [
        {"id": "BOSS_1", "type": "boss_encounter", "engage_type": "at",
         "boss_ref": "测试Boss", "scene": "6号车厢",
         "requirements": "I1 || 软性条件", "description": "测试"}
    ]
    mgr = BossManager(lib, encounters)

    # engage_type 过滤
    result = mgr.check_by_engage_type("at", scene="6号车厢")
    assert len(result) == 1
    assert result[0]["id"] == "BOSS_1"

    # 不同 scene 不应命中
    result2 = mgr.check_by_engage_type("at", scene="2号车厢")
    assert len(result2) == 0

    # 不同 engage_type 不应命中
    result3 = mgr.check_by_engage_type("interaction")
    assert len(result3) == 0


def test_check_by_engage_type_event():
    lib = _make_library()
    encounters = [
        {"id": "BOSS_E1", "type": "boss_encounter", "engage_type": "event",
         "boss_ref": "测试Boss", "scene": "",
         "requirements": "runtime_state.I_done.completed", "description": "全局事件"}
    ]
    mgr = BossManager(lib, encounters)
    result = mgr.check_by_engage_type("event")
    assert len(result) == 1


def test_build_combat_init():
    lib = _make_library()
    encounters = [
        {"id": "BOSS_1", "type": "boss_encounter", "engage_type": "at",
         "boss_ref": "测试Boss", "scene": "6号车厢",
         "requirements": "", "description": "Boss登场！"}
    ]
    mgr = BossManager(lib, encounters)

    # Mock player
    class MockPlayer:
        class Stats:
            DEX = 50; STR = 50; CON = 50; SIZ = 50; POW = 50; APP = 50; INT = 50; EDU = 50
        class Derived:
            HP = 12; SAN = 60
        stats = Stats(); derived = Derived()
        def get_skill(self, name): return type('s', (), {'value': 50})()

    ci = mgr.build_combat_init(encounters[0], MockPlayer(), "6号车厢")
    assert isinstance(ci, CombatInit)
    assert ci.scene == "6号车厢"
    assert len(ci.enemies) == 1
    enemy = ci.enemies[0]
    assert enemy.enemy_ref == "测试Boss"
    assert enemy.attributes["STR"] == 100
    assert enemy.armor == "5点"
    assert enemy.hp == (80 + 90) // 10  # (CON+SIZ)//10
    assert "boss" in enemy.flags
    assert enemy.boss_mechanics == "弱点：测试弱点。"


def test_get_nonexistent_boss():
    lib = _make_library()
    encounters = [
        {"id": "BOSS_X", "type": "boss_encounter", "engage_type": "at",
         "boss_ref": "不存在", "scene": "6号车厢",
         "requirements": "", "description": ""}
    ]
    mgr = BossManager(lib, encounters)
    try:
        mgr.build_combat_init(encounters[0], None, "6号车厢")
        assert False, "Should have raised"
    except KeyError:
        pass
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_boss_manager.py -v
```

- [ ] **Step 3: 实现 BossManager**

```python
# src/game/boss_manager.py
"""BossManager — 信息挂钩 + 规则整合。不参与 spawn，不参与战斗回合。"""
from __future__ import annotations
from game.messages import CombatInit
from library.bosses import BossLibrary


class BossManager:
    def __init__(self, boss_library: BossLibrary, boss_encounters: list[dict]):
        self.library = boss_library
        self.encounters = boss_encounters
        self.active_boss_id: str | None = None

    def check_by_engage_type(self, engage_type: str, *, scene: str | None = None) -> list[dict]:
        """硬性过滤：返回指定 engage_type、且 scene 匹配的 boss entities。
        注意：仅做 engage_type + scene 硬过滤，requirement 软性判定由 caller 负责。
        """
        results = []
        for enc in self.encounters:
            if enc.get("engage_type") != engage_type:
                continue
            if engage_type in ("at", "interaction") and scene is not None:
                if enc.get("scene") != scene:
                    continue
            results.append(enc)
        return results

    def build_combat_init(self, boss_entity: dict, player, scene: str) -> CombatInit:
        """boss_ref → BossLibrary.get() → 构造带完整属性的 EnemyInstance → CombatInit"""
        from game.enemy_manager import EnemyInstance
        import uuid

        boss_ref = boss_entity["boss_ref"]
        lib_boss = self.library.get(boss_ref)
        if not lib_boss:
            raise KeyError(f"Boss '{boss_ref}' not found in boss library")

        attrs = lib_boss.attributes
        base_hp = (attrs.get("CON", 100) + attrs.get("SIZ", 100)) // 10

        enemy = EnemyInstance(
            instance_id=f"{boss_ref}_{uuid.uuid4().hex[:8]}",
            enemy_ref=boss_ref,
            scene=scene,
            quantity=1,
            status="hostile",
            flags=list(lib_boss.flags),
            combat_behavior=lib_boss.boss_mechanics,
            description=lib_boss.description,
            attributes=dict(attrs),
            armor=lib_boss.armor,
            attacks=list(lib_boss.attacks),
            special_abilities=list(lib_boss.special_abilities),
            san_loss=lib_boss.san_loss,
            hp=base_hp,
        )
        # 将 boss_mechanics 附加到实例上供 CombatSystem LLM 层使用
        enemy.boss_mechanics = lib_boss.boss_mechanics

        return CombatInit(
            enemies=[enemy],
            player=player,
            scene=scene,
            initiative_context=boss_entity.get("description", ""),
        )

    def resolve_outcome(self, combat_result):
        """战后结算：LLM 解读 boss_mechanics + outcome → 返回 story_outcome 字符串。
        Caller 负责根据返回值设置结局标记。
        """
        if not self.active_boss_id:
            return None
        # 当前为占位——实际 LLM 调用由 keeper 触发
        return combat_result.outcome

    def set_active(self, boss_id: str | None):
        self.active_boss_id = boss_id
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_boss_manager.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/game/boss_manager.py tests/test_boss_manager.py
git commit -m "feat(boss): add BossManager with engage_type filtering and CombatInit construction"
```

---

## Task 3: CombatSystem Boss 扩展

### Task 3.1: CombatInit 扩展 + CombatSystem Boss LLM 路径

**Files:**
- Modify: `src/game/messages.py:108-113`
- Modify: `src/game/combat.py:91-371`

- [ ] **Step 1: CombatInit 添加 environment_actions 字段**

```python
# src/game/messages.py
@dataclass
class CombatInit:
    """Passed to pluggable combat system when combat begins."""
    enemies: list[Any] = field(default_factory=list)
    player: Any = None
    scene: str = ""
    initiative_context: str = ""
    environment_actions: list[dict] = field(default_factory=list)  # 环境交互选项
```

- [ ] **Step 2: CombatSystem 扩展 Boss LLM 路径**

在 `src/game/combat.py` 中：

修改 `_get_player_actions` 支持环境交互：

```python
def _get_player_actions(self, player, environment_actions: list[dict] | None = None) -> list[dict]:
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
    # 环境交互选项
    if environment_actions:
        for ea in environment_actions:
            actions.append({
                "id": f"env:{ea['id']}", "label": ea.get("label", ea["id"]),
                "skill": ea.get("skill", ""), "damage": None,
                "value": self._skill_value(player, ea.get("skill", "")) if ea.get("skill") else 50,
            })
    return actions
```

修改 `run_combat` 传递环境交互：

```python
def run_combat(self, combat_init: CombatInit) -> CombatResult:
    state = self._init_combat(combat_init)
    player = combat_init.player
    environment_actions = getattr(combat_init, 'environment_actions', [])

    while not state.finished:
        alive_enemies = [e for e in state.enemies
                       if getattr(e, 'hp', 1) > 0 and getattr(e, 'status', '') != 'dead']
        if not alive_enemies:
            state.finished = True
            break

        target = alive_enemies[0].instance_id
        self._process_round(state, player, "punch", target, environment_actions)

    # ... 其余不变
```

修改 `_process_round` 签名和 `_resolve_player_action` 调用传参：

```python
def _process_round(self, state, player, player_action_id: str,
                   target_iid: str, environment_actions: list[dict] | None = None) -> list[CombatAction]:
    state.log = []
    state._player_dodging = False

    for idx, iid in enumerate(state.initiative_order):
        if iid == "player":
            pa = self._resolve_player_action(state, player, player_action_id, target_iid, environment_actions)
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
```

修改 `_resolve_player_action` 签名添加参数：

```python
def _resolve_player_action(self, state, player, action_id: str,
                           target_iid: str, environment_actions: list[dict] | None = None) -> CombatAction:
```

并在构建 actions 列表时传递 environment_actions：

```python
    # Attack actions
    actions = self._get_player_actions(player, environment_actions)
```

修改 `_resolve_enemy_action`：Boss 检测 flag 走 LLM 路径（先保留确定性路径，Boss 路径返回占位）：

```python
def _resolve_enemy_action(self, state, enemy, player) -> CombatAction:
    # Boss LLM 路径：由 caller 覆盖（当前返回占位）
    if "boss" in getattr(enemy, 'flags', []):
        return self._resolve_boss_action_stub(state, enemy, player)

    attack = self._select_enemy_attack(enemy)
    # ... 其余现有逻辑不变


def _resolve_boss_action_stub(self, state, enemy, player) -> CombatAction:
    """Boss LLM 路径占位——实际 LLM 调用由 keeper 层注入 prompt。"""
    attack = self._select_enemy_attack(enemy)
    action = CombatAction(
        actor=enemy.instance_id,
        action_type="attack",
        weapon=attack["name"],
        skill_name=attack["name"],
        target="player",
    )
    enemy_attrs = getattr(enemy, 'attributes', {})
    enemy_skill = (enemy_attrs.get("DEX", 50) + enemy_attrs.get("POW", 50)) // 2
    action.skill_value = enemy_skill
    action.roll = random.randint(1, 100)

    if getattr(state, '_player_dodging', False):
        action.success = False
        action.narrative = f"{getattr(enemy, 'enemy_ref', 'Boss')}的{attack['name']}被你闪开了。"
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
            f"{getattr(enemy, 'enemy_ref', 'Boss')}用{attack['name']}击中了你！"
            f"造成{damage}点伤害。"
        )
    else:
        action.narrative = f"{getattr(enemy, 'enemy_ref', 'Boss')}的{attack['name']}未能命中你。"

    return action
```

- [ ] **Step 2: 运行已有战斗测试确保不回归**

```bash
pytest tests/test_combat.py tests/test_combat_harness.py -v
```

- [ ] **Step 3: Commit**

```bash
git add src/game/messages.py src/game/combat.py
git commit -m "feat(combat): add boss LLM path stub and environment_actions support to CombatSystem"
```

---

## Task 4: NPC 系统

### Task 4.1: NPC dataclass + NPCManager

**Files:**
- Create: `src/game/npc_manager.py`
- Create: `tests/test_npc_manager.py`

- [ ] **Step 1: 写测试**

```python
# tests/test_npc_manager.py
from game.npc_manager import NPC, NPCManager


def _make_npc(name="京山 人吉", scene="4号车厢"):
    return NPC(
        name=name,
        role="受伤的电车乘务员",
        personality_notes="求生欲强烈，受伤后虚弱无助",
        appearance="三十岁左右男性，身穿标准铁路制服，腿部有严重撕裂伤",
        what_they_can_do="提供关键信息（钥匙位置、怪物弱点）",
        interaction_triggers=["尝试急救", "主动交谈"],
        scene=scene,
    )


def test_npc_creation():
    npc = _make_npc()
    assert npc.name == "京山 人吉"
    assert npc.attitude == "neutral"
    assert npc.following is False
    assert npc.state == "alive"
    assert len(npc.memory) == 0


def test_talk_to_basic():
    mgr = NPCManager()
    profiles = {
        "京山 人吉": {
            "name": "京山 人吉",
            "role": "受伤的乘务员",
            "personality_notes": "虚弱但负责",
            "appearance": "身穿制服，腿部受伤",
            "what_they_can_do": "提供信息",
            "interaction_triggers": ["交谈"],
        }
    }
    mgr.init_from_profiles(profiles)

    def mock_llm(prompt, **kwargs):
        return "（乘务员虚弱地说）钥匙...在3号车厢的挎包里..."

    response = mgr.talk_to("京山 人吉", "钥匙在哪里？", mock_llm)
    assert "钥匙" in response
    assert len(mgr.get("京山 人吉").memory) > 0


def test_following_sync():
    mgr = NPCManager()
    mgr.init_from_profiles({
        "NPC_A": {"name": "NPC_A", "role": "", "personality_notes": "",
                   "appearance": "", "what_they_can_do": "", "interaction_triggers": []},
        "NPC_B": {"name": "NPC_B", "role": "", "personality_notes": "",
                   "appearance": "", "what_they_can_do": "", "interaction_triggers": []},
    })
    mgr.set_scene("NPC_A", "1号车厢")
    mgr.set_scene("NPC_B", "2号车厢")
    mgr.set_following("NPC_A", True)

    assert mgr.get("NPC_A").following is True
    assert mgr.get("NPC_B").following is False

    mgr.sync_followers("3号车厢")
    assert mgr.get("NPC_A").scene == "3号车厢"
    assert mgr.get("NPC_B").scene == "2号车厢"  # 未跟随不移动


def test_get_in_scene():
    mgr = NPCManager()
    mgr.init_from_profiles({
        "A": {"name": "A", "role": "", "personality_notes": "",
               "appearance": "", "what_they_can_do": "", "interaction_triggers": []},
        "B": {"name": "B", "role": "", "personality_notes": "",
               "appearance": "", "what_they_can_do": "", "interaction_triggers": []},
    })
    mgr.set_scene("A", "1号车厢")
    mgr.set_scene("B", "2号车厢")
    assert len(mgr.get_in_scene("1号车厢")) == 1
    assert mgr.get_in_scene("1号车厢")[0].name == "A"


def test_npc_state_changes():
    mgr = NPCManager()
    mgr.init_from_profiles({
        "A": {"name": "A", "role": "", "personality_notes": "",
               "appearance": "", "what_they_can_do": "", "interaction_triggers": []},
    })
    mgr.set_attitude("A", "friendly")
    assert mgr.get("A").attitude == "friendly"
    mgr.set_state("A", "injured")
    assert mgr.get("A").state == "injured"


def test_serialization_roundtrip():
    mgr = NPCManager()
    profiles = {
        "NPC1": {"name": "NPC1", "role": "测试", "personality_notes": "性格",
                  "appearance": "外貌", "what_they_can_do": "能力", "interaction_triggers": ["触发1"]},
    }
    mgr.init_from_profiles(profiles)
    mgr.set_scene("NPC1", "2号车厢")
    mgr.set_attitude("NPC1", "friendly")
    mgr.set_following("NPC1", True)
    mgr.get("NPC1").memory.append("玩家问了钥匙的事")

    data = mgr.to_dict()
    mgr2 = NPCManager()
    mgr2.init_from_profiles(profiles)
    mgr2.from_dict(data, profiles)
    npc = mgr2.get("NPC1")
    assert npc.scene == "2号车厢"
    assert npc.attitude == "friendly"
    assert npc.following is True
    assert "钥匙" in npc.memory[0]
```

- [ ] **Step 2: 实现 NPC dataclass + NPCManager**

```python
# src/game/npc_manager.py
"""NPC dataclass + NPCManager — NPC 全量管理（对话/态度/跟随/状态）"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class NPC:
    # ── 档案字段（Step 2.5 产生，来自 L3 CharacterDesign → LLM 拆解）──
    name: str
    role: str = ""
    personality_notes: str = ""
    appearance: str = ""
    what_they_can_do: str = ""
    interaction_triggers: list[str] = field(default_factory=list)

    # ── 运行时字段（NPCManager 管理）──
    scene: str = ""
    attitude: str = "neutral"              # hostile/wary/neutral/friendly/trusting
    following: bool = False
    memory: list[str] = field(default_factory=list)
    state: str = "alive"                   # alive/injured/dead/left
    extra: dict | None = None              # 预留扩展（含未来 combat_stats 等）


class NPCManager:
    def __init__(self):
        self._npcs: dict[str, NPC] = {}

    # ── 初始化 ──

    def init_from_profiles(self, profiles: dict):
        """从 L2 npc_profiles 批量创建 NPC 实例。"""
        for name, data in profiles.items():
            self._npcs[name] = NPC(
                name=data.get("name", name),
                role=data.get("role", ""),
                personality_notes=data.get("personality_notes", ""),
                appearance=data.get("appearance", ""),
                what_they_can_do=data.get("what_they_can_do", ""),
                interaction_triggers=list(data.get("interaction_triggers", [])),
                scene=data.get("scene", ""),
            )

    # ── 查询 ──

    def get(self, name: str) -> NPC | None:
        return self._npcs.get(name)

    def get_in_scene(self, scene: str) -> list[NPC]:
        return [n for n in self._npcs.values() if n.scene == scene]

    def get_following(self) -> list[NPC]:
        return [n for n in self._npcs.values() if n.following]

    def all_names(self) -> list[str]:
        return list(self._npcs.keys())

    # ── 交互 ──

    def talk_to(self, npc_name: str, player_input: str, llm_call) -> str:
        """对话：注入态度/记忆/档案上下文 → LLM 扮演 NPC → 追加 memory。"""
        npc = self._npcs.get(npc_name)
        if not npc:
            return f"（{npc_name} 不在此处。）"

        system_prompt = (
            f"你是 NPC「{npc.name}」。\n"
            f"角色：{npc.role}\n"
            f"性格：{npc.personality_notes}\n"
            f"外貌：{npc.appearance}\n"
            f"能力：{npc.what_they_can_do}\n"
            f"当前态度：{npc.attitude}\n"
            f"当前状态：{npc.state}\n"
            + (f"对话记忆：{'; '.join(npc.memory[-5:])}" if npc.memory else "")
            + "\n请用符合角色设定的语气回复调查员，回复简洁（1-3句话）。"
        )
        user_prompt = f"调查员对你说：「{player_input}」"

        try:
            response = llm_call(user_prompt, system=system_prompt, json_mode=False)
        except Exception:
            response = f"（{npc.name} 沉默不语。）"

        npc.memory.append(f"玩家：「{player_input}」→ 回复：「{response}」")
        if len(npc.memory) > 20:
            npc.memory = npc.memory[-20:]
        return response

    # ── 状态变更 ──

    def set_attitude(self, name: str, attitude: str):
        if name in self._npcs:
            self._npcs[name].attitude = attitude

    def set_following(self, name: str, following: bool):
        if name in self._npcs:
            self._npcs[name].following = following

    def set_state(self, name: str, state: str):
        if name in self._npcs:
            self._npcs[name].state = state

    def set_scene(self, name: str, scene: str):
        """设置 NPC 位置（手动移动）。"""
        if name in self._npcs:
            self._npcs[name].scene = scene

    # ── 跟随同步 ──

    def sync_followers(self, scene: str):
        """所有 following=True 的 NPC 自动移动到 scene。"""
        for npc in self._npcs.values():
            if npc.following:
                npc.scene = scene

    # ── 序列化 ──

    def to_dict(self) -> dict:
        return {
            name: {
                "scene": npc.scene,
                "attitude": npc.attitude,
                "following": npc.following,
                "memory": list(npc.memory),
                "state": npc.state,
            }
            for name, npc in self._npcs.items()
        }

    def from_dict(self, data: dict, profiles: dict):
        """从序列化数据恢复运行时状态。profiles 用于恢复档案字段。"""
        for name, state_data in data.items():
            profile = profiles.get(name, {})
            self._npcs[name] = NPC(
                name=name,
                role=profile.get("role", ""),
                personality_notes=profile.get("personality_notes", ""),
                appearance=profile.get("appearance", ""),
                what_they_can_do=profile.get("what_they_can_do", ""),
                interaction_triggers=list(profile.get("interaction_triggers", [])),
                scene=state_data.get("scene", ""),
                attitude=state_data.get("attitude", "neutral"),
                following=state_data.get("following", False),
                memory=list(state_data.get("memory", [])),
                state=state_data.get("state", "alive"),
            )

    def __repr__(self):
        return f"NPCManager({len(self._npcs)} NPCs)"
```

- [ ] **Step 3: 运行测试确认通过**

```bash
pytest tests/test_npc_manager.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/game/npc_manager.py tests/test_npc_manager.py
git commit -m "feat(npc): add NPC dataclass + NPCManager with dialogue/following/attitude"
```

---

## Task 5: @npc_follow Markup

**Files:**
- Modify: `src/scenario_core.py` (parse_markup 正则 + SpawnEnemy 附近添加跟随效果)

- [ ] **Step 1: 扩展 parse_markup 正则添加 @npc_follow**

在 `src/scenario_core.py` 中找到 parse_markup 的正则模式，添加 `npc_follow`：

```python
# 原模式 (约 line 149):
# r'@(spawn_enemy|grant_weapon|stat_change|item_gain|consume_item|npc_state_change)'
# 改为:
_NPC_FOLLOW_PATTERN = re.compile(r'@(spawn_enemy|grant_weapon|stat_change|item_gain|consume_item|npc_state_change|npc_follow)\(([^)]*)\)')
```

- [ ] **Step 2: 添加 NPCFollow dataclass 和解析函数**

```python
@dataclass
class NPCFollow:
    """NPC 跟随状态变更 — 更新 NPCManager follow 状态"""
    npc_name: str
    follow: bool = True


def _parse_npc_follow(params_str: str) -> NPCFollow:
    kwargs = _parse_keyword_args(params_str)
    follow = kwargs.get("follow", "true").lower() in ("true", "1", "yes")
    return NPCFollow(
        npc_name=kwargs.get("npc_name", ""),
        follow=follow,
    )
```

- [ ] **Step 3: 在 apply_side_effects 中添加 NPCFollow 处理**

在 `ScenarioWorld.apply_side_effects()` 中找 `npc_state_change` 处理逻辑，追加：

```python
elif isinstance(effect, NPCFollow):
    if hasattr(self, 'npc_manager') and self.npc_manager:
        self.npc_manager.set_following(effect.npc_name, effect.follow)
    self.add_memory(f"NPC跟随变更: {effect.npc_name} follow={effect.follow}")
```

- [ ] **Step 4: Commit**

```bash
git add src/scenario_core.py
git commit -m "feat(npc): add @npc_follow markup parsing and side effect handling"
```

---

## Task 6: Game Loop 集成

### Task 6.1: init_game 加载 Boss + NPC

**Files:**
- Modify: `src/game_loop.py`
- Modify: `src/game/agents/keeper.py`

- [ ] **Step 1: game_loop.py — init_game 加载 BossLibrary + NPCManager**

找到 `init_game()` 函数，在加载 WeaponLibrary 附近添加：

```python
from library.bosses import BossLibrary
from game.boss_manager import BossManager
from game.npc_manager import NPCManager

# 在 init_game() 中 (约 EnemyLibrary 加载之后):
boss_library = BossLibrary("data/library/core/bosses.json")
boss_encounters = l2.get("boss_encounters", [])
boss_manager = BossManager(boss_library, boss_encounters)

npc_manager = NPCManager()
npc_profiles = l2.get("npc_profiles", {})
# 从 L2 scenes 中提取 NPC 初始位置
for scene_name, scene_data in l2.get("scenes", {}).items():
    for npc_data in scene_data.get("npcs", []):
        name = npc_data.get("name", "")
        if name in npc_profiles:
            npc_profiles[name] = {**npc_profiles[name], "scene": scene_name}
npc_manager.init_from_profiles(npc_profiles)

# 将 boss_manager 和 npc_manager 传入 Keeper 构造函数
keeper = Keeper(
    world=world,
    npc_profiles=l2.get("npc_profiles"),
    boss_manager=boss_manager,
    npc_manager=npc_manager,
    ...
)
```

- [ ] **Step 2: keeper.py — 接收 BossManager + NPCManager**

修改 Keeper 构造函数：

```python
def __init__(self, world, npc_profiles=None, boss_manager=None, npc_manager=None, ...):
    self.boss_manager = boss_manager
    self.npc_manager = npc_manager
    # ... 其余不变
```

- [ ] **Step 3: keeper.py — process_turn 添加 Boss 检查**

在 `process_turn()` 中，场景切换后（move 处理后）添加：

```python
# Boss "at" 检查（场景切换后）
if self.boss_manager:
    at_bosses = self.boss_manager.check_by_engage_type("at", scene=self.world.current_node)
    for boss_entity in at_bosses:
        if self._check_boss_requirements(boss_entity):
            combat_init = self.boss_manager.build_combat_init(boss_entity, player, self.world.current_node)
            self.boss_manager.set_active(boss_entity["id"])
            return {"combat_init": combat_init}
```

其中 `_check_boss_requirements` 复用 Judge 的 `parse_hard_requirement`：

```python
def _check_boss_requirements(self, boss_entity: dict) -> bool:
    req_str = boss_entity.get("requirements", "")
    if not req_str:
        return True
    # 分开硬性条件（|| 前）和软性条件（|| 后）
    if "||" in req_str:
        hard_part, soft_part = req_str.split("||", 1)
        hard_ok = self.judge.check_hard_requirements(hard_part.strip(), self.world)
        if not hard_ok:
            return False
        # 软性条件 LLM 判定（轻量）
        return self._llm_check_soft_requirement(soft_part.strip(), boss_entity)
    else:
        return self.judge.check_hard_requirements(req_str.strip(), self.world)
```

- [ ] **Step 4: keeper.py — parse 阶段 NPC 路由**

在 `process_turn()` 的 parse 结果处理中：

```python
parse_result = self._parse(user_input)

# NPC 交互检测：遍历 scene 中的 NPC + 跟随 NPC
if self.npc_manager:
    npcs_present = self.npc_manager.get_in_scene(self.world.current_node)
    npcs_present += self.npc_manager.get_following()
    npc_names = {n.name for n in npcs_present}
    for name in npc_names:
        if name in user_input or self._is_addressing_npc(user_input, name):
            response = self.npc_manager.talk_to(name, user_input, self._call_llm)
            return {"narrative": response}
```

- [ ] **Step 5: keeper.py — Boss "event" 检查**

在 judge 完成后（事件处理完成后）：

```python
if self.boss_manager:
    event_bosses = self.boss_manager.check_by_engage_type("event")
    for boss_entity in event_bosses:
        if self._check_boss_requirements(boss_entity):
            combat_init = self.boss_manager.build_combat_init(boss_entity, player, self.world.current_node)
            self.boss_manager.set_active(boss_entity["id"])
            return {"combat_init": combat_init}
```

- [ ] **Step 6: game_loop.py — run_turn 战后结算 Boss**

在 `run_turn()` 中，CombatSystem.run_combat() 之后：

```python
if combat_init is not None:
    result = combat_system.run_combat(combat_init)
    enemy_manager.exit_combat({
        "defeated_instance_ids": result.defeated_instance_ids,
    })
    # Boss 战后结算
    if boss_manager and boss_manager.active_boss_id:
        boss_manager.resolve_outcome(result)
        boss_manager.set_active(None)
    return {"combat_result": result}
```

- [ ] **Step 7: 场景切换 NPC 同步**

在 `game_loop.py` 中 handle_move 场景切换后：

```python
if npc_manager:
    npc_manager.sync_followers(new_scene)
```

- [ ] **Step 8: Commit**

```bash
git add src/game_loop.py src/game/agents/keeper.py
git commit -m "feat: integrate BossManager + NPCManager into game loop and Keeper"
```

---

## Task 7: 模组管线更新

### Task 7.1: Step 1 Boss prompt + Step 2 Boss entity 生成

**Files:**
- Modify: `src/module_designer/layered_parser.py` (Step 1 和 Step 2 prompts)

- [ ] **Step 1: Step 1a/1b prompt 增加 boss_encounters 输出字段**

在 Step 1 的 JSON 输出 schema 中添加：

```
"boss_encounters": [
  {"id": "BOSS_1", "boss_name": "Boss名称", "associated_scene": "场景名", "mechanics_hint": "简短机制提示"}
]
```

确保 prompt 模板要求 LLM 识别具有特殊机制/故事绑定的对抗实体。

- [ ] **Step 2: Step 2c 新增 parse_step2_boss**

在 `layered_pipeline.py` 中添加 sub-step `parse_step2_boss`：

```python
def parse_step2_boss(boss_hints: list[dict], l1_data: dict, llm_json) -> dict:
    """从 Step 1 的 boss_encounters 生成结构化 boss entities。"""
    if not boss_hints:
        return {"boss_encounters": []}

    prompt = f"""根据以下 Boss 识别结果，生成结构化的 Boss Encounter 实体。

## Step 1 Boss 识别
{json.dumps(boss_hints, ensure_ascii=False, indent=2)}

## L1 场景概要（供场景名/条件参考）
{json.dumps(l1_data, ensure_ascii=False, indent=2)}

输出格式:
{{
  "boss_encounters": [
    {{
      "id": "BOSS_1",
      "type": "boss_encounter",
      "engage_type": "at|interaction|event",
      "boss_ref": "Boss库中的名称",
      "scene": "所在场景",
      "requirements": "(硬性条件) || 软性描述条件",
      "description": "进入战斗时的情境描述"
    }}
  ]
}}

要求:
1. engage_type 判定: 进入场景自动触发→"at", 玩家主动操作→"interaction", 全局条件满足→"event"
2. requirements 使用 (hard) || soft 格式
3. boss_ref 必须与 Step 1 识别的 boss_name 对应
"""
    return llm_json(prompt)
```

- [ ] **Step 3: _assemble_l2 添加 boss_encounters 字段**

```python
def _assemble_l2(interactions, events, auto_triggers, scene_movements, l1_data,
                 npc_profiles=None, boss_encounters=None) -> dict:
    return {
        "scenes": scenes,
        "events": events,
        "boss_encounters": boss_encounters if boss_encounters is not None else [],
        "npc_profiles": npc_profiles if npc_profiles is not None else {},
    }
```

- [ ] **Step 4: run_pipeline 集成 parse_step2_boss**

在 `run_pipeline.py` 的管线程中，Step 2.5 之后或并行添加：

```python
# 如果 Step 1 产生了 boss_encounters
boss_hints = step1.get("boss_encounters", [])
if boss_hints:
    step2_boss = parse_step2_boss(boss_hints, l1_data, llm_json)
    boss_encounters = step2_boss.get("boss_encounters", [])
else:
    boss_encounters = []

l2_assembled = _assemble_l2(
    ..., boss_encounters=boss_encounters
)
```

- [ ] **Step 5: Commit**

```bash
git add src/module_designer/layered_parser.py src/module_designer/layered_pipeline.py run_pipeline.py
git commit -m "feat(pipeline): add boss_encounters detection in Step 1 and parse_step2_boss"
```

### Task 7.2: NPC Profile 结构更新 + 管线对齐

**Files:**
- Modify: `src/module_designer/l2_keeper.py` (NPCProfile → NPC 引用)
- Modify: `src/module_designer/__init__.py` (exports)
- Modify: `src/module_designer/layered_schema.py` (schema)
- Modify: `tests/test_module_designer.py` (引用更新)
- Modify: `src/module_designer/layered_parser.py` (Step 2.5 output)
- Modify: `src/module_designer/layered_pipeline.py` (_assemble_l2)

- [ ] **Step 1: l2_keeper.py — 替换 NPCProfile 为 NPC**

将 `NPCProfile` dataclass 标记为 deprecated，从 `npc_manager` import `NPC`：

```python
# 在 l2_keeper.py 顶部
from game.npc_manager import NPC as NPCProfile  # 向后兼容别名

# 删除旧的 NPCProfile 类定义，替换为:
# NPCProfile 已迁移到 src/game/npc_manager.py，本模块保留向后兼容引用
```

`load_l2()` 中的 `NPCProfile.from_dict(np)` 调用不变（现有 `NPC` 没有 `from_dict`，通过别名保留兼容）。但需要调整字段映射——新 NPC 字段为 `personality_notes` 而非 `personality`。

实际上，由于管线仍在生成旧格式（Step 2.5 prompt 未修改），我们需要**先更新 Step 2.5 的输出格式**，确保生成的 JSON 字段与 NPC dataclass 一致。

方案：在 `l2_keeper.py` 中保留一个兼容的 `load_l2_npc_profiles` 函数，将旧 JSON 字段映射到新 NPC 字段：

```python
# l2_keeper.py
def _normalize_npc_profile(data: dict) -> dict:
    """将旧字段名映射到新 NPC dataclass 字段。"""
    return {
        "name": data.get("name", ""),
        "role": data.get("role", ""),
        "personality_notes": data.get("personality_notes") or data.get("personality", ""),
        "appearance": data.get("appearance", ""),
        "what_they_can_do": data.get("what_they_can_do", ""),
        "interaction_triggers": data.get("interaction_triggers", []),
    }
```

- [ ] **Step 2: 更新 Step 2.5 prompt 输出格式**（已对齐新结构，prompt 已用 `personality_notes` 字段，确认一致）

当前 Step 2.5 prompt（layered_parser.py line 720-731）已经输出 `personality_notes` 和 `interaction_triggers`，与新 NPC 结构一致。无需改动 prompt 本身。

- [ ] **Step 3: 更新 L2_NPC_PROFILE_SCHEMA**

```python
L2_NPC_PROFILE_SCHEMA = {
    "name": {"required": True},
    "role": {"required": False},
    "personality_notes": {"required": False},
    "appearance": {"required": False},
    "what_they_can_do": {"required": False},
    "interaction_triggers": {"required": False},
}
```

- [ ] **Step 4: 更新 ___init__.py exports**

```python
from .l2_keeper import SceneL2, Encounter, SceneWeapon, AutoTrigger, load_l2, save_l2
# NPCProfile 不再从 l2_keeper 导出（已迁移到 game.npc_manager.NPC）
```

- [ ] **Step 5: 更新 test_module_designer.py 的 NPCProfile 引用**

```python
# 将
from module_designer.l2_keeper import SceneL2, Encounter, SceneWeapon, AutoTrigger, NPCProfile
# 改为
from module_designer.l2_keeper import SceneL2, Encounter, SceneWeapon, AutoTrigger
from game.npc_manager import NPC

# 更新测试中 NPCProfile(...) 为 NPC(...)
```

- [ ] **Step 6: 添加 L2 boss_encounters 验证 schema**

在 `layered_schema.py` 中添加：

```python
L2_BOSS_ENCOUNTER_SCHEMA = {
    "id": {"required": True},
    "type": {"required": False},
    "engage_type": {"required": False, "values": ["at", "interaction", "event"]},
    "boss_ref": {"required": True},
    "scene": {"required": False},
    "requirements": {"required": False},
    "description": {"required": False},
}

# 在 validate_l2 中新增 boss_encounters 验证:
boss_encounters = data.get("boss_encounters", [])
if isinstance(boss_encounters, list):
    for i, be in enumerate(boss_encounters):
        _validate_object(be, L2_BOSS_ENCOUNTER_SCHEMA, f"L2.boss_encounters[{i}]", report)
```

- [ ] **Step 7: 运行管道测试验证**

```bash
pytest tests/test_module_designer.py -v
```

- [ ] **Step 8: Commit**

```bash
git add src/module_designer/l2_keeper.py src/module_designer/__init__.py src/module_designer/layered_schema.py tests/test_module_designer.py src/module_designer/layered_parser.py src/module_designer/layered_pipeline.py
git commit -m "feat(pipeline): align NPC schema with new NPC dataclass, add boss_encounters validation"
```

---

## Task 8: 全量测试 + Prompt Review

### Task 8.1: 运行所有测试

- [ ] **Step 1: 运行全量测试**

```bash
pytest tests/ -v --tb=short
```

- [ ] **Step 2: 记录失败项并逐一修复**

### Task 8.2: Game Loop 集成测试

- [ ] **Step 1: 写 mini 集成测试**

创建 `tests/test_boss_integration.py`：

```python
"""Boss + NPC integration test — 验证 init_game 加载和路由。"""
# 使用 test_l*.json + mock LLM，验证 Keeper 正确路由 Boss/NPC 交互
# （具体测试内容依赖实际的 test JSON 结构，此处为骨架）
```

- [ ] **Step 2: 运行并修复**

```bash
pytest tests/test_boss_integration.py -v
```

### Task 8.3: Prompt Review

- [ ] **Step 1: 检查所有受影响 prompt 不超出上下文窗口**

检查以下 prompt 的新增 token 量：
- Step 1a/1b system prompt（+boss_encounters 输出 schema）
- Step 2.5 prompt（字段对齐确认）
- parse_step2_boss prompt
- NPC talk_to system prompt
- CombatSystem boss action prompt（预留）

- [ ] **Step 2: 如有必要，精简 prompt 或增大 max_tokens**

### Task 8.4: 最终 Commit

```bash
git add -A
git commit -m "feat: complete boss + NPC system integration with pipeline updates and tests"
```

---

## Dependency Order

```
Task 0 (属性桥接) ──→ Task 3 (CombatSystem) ──→ Task 6 (Game Loop)
                  │
Task 1 (BossLibrary) ──→ Task 2 (BossManager) ──→ Task 6
                  │                            │
Task 4 (NPCManager) ──────────────────────────→ Task 6
                  │                            │
Task 5 (@npc_follow) ─────────────────────────→ Task 6
                                                 │
Task 7 (Pipeline) ──────────────────────────────→ Task 8 (Tests)
```
