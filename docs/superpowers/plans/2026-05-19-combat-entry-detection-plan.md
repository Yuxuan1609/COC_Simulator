# Combat Entry Detection + Enemy Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace dead SpawnEnemy side effect with live EnemyManager tracking, add LLM-based combat entry detection (parallel with enrich), and standoff phase for avoidable enemies.

**Architecture:** EnemyManager lives on ScenarioWorld as pure state tracker. Combat entry detection is a flash LLM call in Keeper, gated by deterministic range check. Standoff phase is a lightweight semantic-match LLM + D100 skill check loop.

**Tech Stack:** Python dataclasses, deepseek-v4-flash, COC 7th D100 rules

---

### Task 1: Flag parsing in LibraryEnemy.from_dict

**Files:**
- Modify: `src/library/enemies.py`
- Test: `tests/test_library.py`

- [ ] **Step 1: Write failing test for flag extraction**

```python
def test_enemy_flag_parsing():
    """LibraryEnemy.from_dict extracts [flags] from combat_behavior."""
    # Has flags
    raw = {"name": "Test", "type": "test", "attributes": {},
           "combat_behavior": "[adjacent_aware][avoidable] | 会主动攻击",
           "armor": "无", "attacks": [], "special_abilities": [],
           "san_loss": "0/0", "description": ""}
    enemy = LibraryEnemy.from_dict(raw)
    assert enemy.flags == ["adjacent_aware", "avoidable"]
    assert enemy.combat_behavior == "会主动攻击"

    # No flags
    raw2 = {"name": "Test2", "type": "test", "attributes": {},
            "combat_behavior": "看到人就打",
            "armor": "无", "attacks": [], "special_abilities": [],
            "san_loss": "0/0", "description": ""}
    enemy2 = LibraryEnemy.from_dict(raw2)
    assert enemy2.flags == []
    assert enemy2.combat_behavior == "看到人就打"

    # Only flags, no natural lang
    raw3 = {"name": "Test3", "type": "test", "attributes": {},
            "combat_behavior": "[adjacent_aware]",
            "armor": "无", "attacks": [], "special_abilities": [],
            "san_loss": "0/0", "description": ""}
    enemy3 = LibraryEnemy.from_dict(raw3)
    assert enemy3.flags == ["adjacent_aware"]
    assert enemy3.combat_behavior == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_library.py::test_enemy_flag_parsing -v`
Expected: FAIL — `LibraryEnemy` has no `flags` attribute

- [ ] **Step 3: Implement flag parsing in LibraryEnemy.from_dict**

Add to `LibraryEnemy` dataclass at `src/library/enemies.py`:

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
    flags: list = field(default_factory=list)  # NEW
```

Modify `from_dict()`:

```python
@classmethod
def from_dict(cls, data: dict) -> "LibraryEnemy":
    raw_behavior = data.get("combat_behavior", "")
    flags = []
    cleaned_behavior = raw_behavior
    # Extract [flag] markers from prefix
    import re as _re
    flag_pattern = _re.compile(r'\[(\w+)\]')
    while True:
        m = flag_pattern.match(cleaned_behavior)
        if not m:
            break
        flags.append(m.group(1))
        cleaned_behavior = cleaned_behavior[m.end():]
    cleaned_behavior = cleaned_behavior.strip()
    if cleaned_behavior.startswith("|"):
        cleaned_behavior = cleaned_behavior[1:].strip()

    return cls(
        name=data["name"],
        type=data["type"],
        attributes=data["attributes"],
        armor=data.get("armor", "无"),
        attacks=[EnemyAttack.from_dict(a) for a in data.get("attacks", [])],
        special_abilities=[
            SpecialAbility.from_dict(s) for s in data.get("special_abilities", [])
        ],
        san_loss=data.get("san_loss", ""),
        combat_behavior=cleaned_behavior,
        description=data.get("description", ""),
        flags=flags,
    )
```

Also add `flags: list` to `to_dict()` output.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_library.py::test_enemy_flag_parsing -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/library/enemies.py tests/test_library.py
git commit -m "feat: add flag parsing to LibraryEnemy.from_dict — [flag] prefix extraction from combat_behavior"
```

---

### Task 2: Update enemies.json with flags

**Files:**
- Modify: `data/library/core/enemies.json`

- [ ] **Step 1: Add flags to relevant enemies**

Change `深潜者` combat_behavior:
```json
"combat_behavior": "[avoidable] | 偏好伏击，从水中或暗处突袭。受伤后会撤退到水中。"
```

Change `大嘴吞噬者` combat_behavior:
```json
"combat_behavior": "[adjacent_aware] | 不参与常规战斗。它是环境威胁而非可战斗敌人。以固定节奏从后方逼近。"
```

Other enemies (Clicker, 食尸鬼, 疯狂信徒) keep unchanged.

- [ ] **Step 2: Verify EnemyLibrary loads without errors**

Run: `python -c "from library.enemies import EnemyLibrary; lib = EnemyLibrary(); lib.load_core(); print(lib); [print(f'  {e.name}: flags={e.flags}') for e in lib.list_all()]"`
Expected:
```
EnemyLibrary(5 enemies)
  Clicker: flags=[]
  大嘴吞噬者: flags=['adjacent_aware']
  深潜者: flags=['avoidable']
  食尸鬼: flags=[]
  疯狂信徒: flags=[]
```

- [ ] **Step 3: Commit**

```bash
git add data/library/core/enemies.json
git commit -m "data: add [avoidable] to 深潜者, [adjacent_aware] to 大嘴吞噬者"
```

---

### Task 3: EnemyInstance + EnemyManager

**Files:**
- Create: `src/game/enemy_manager.py`
- Test: `tests/test_enemy_manager.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_enemy_manager.py`:

```python
"""Tests for EnemyManager — deterministic, no LLM dependency."""
import pytest
from library.enemies import EnemyLibrary, LibraryEnemy
from game.enemy_manager import EnemyInstance, EnemyManager


@pytest.fixture
def lib():
    l = EnemyLibrary()
    l.load_core()
    return l


@pytest.fixture
def mgr(lib):
    return EnemyManager(lib)


def test_spawn_creates_instance(mgr):
    inst = mgr.spawn("深潜者", "车厢1", quantity=1)
    assert inst.instance_id.startswith("深潜者_")
    assert inst.enemy_ref == "深潜者"
    assert inst.scene == "车厢1"
    assert inst.quantity == 1
    assert inst.status == "neutral"
    assert "avoidable" in inst.flags
    assert inst.combat_behavior  # should have cleaned text


def test_get_active_in_scene_filters_dead(mgr):
    a = mgr.spawn("深潜者", "车厢1")
    b = mgr.spawn("疯狂信徒", "车厢1")
    c = mgr.spawn("Clicker", "车厢2")
    mgr.mark_dead(b.instance_id)

    active = mgr.get_active_in_scene("车厢1")
    assert len(active) == 1
    assert active[0].instance_id == a.instance_id


def test_get_active_in_scene_filters_neutral_and_hostile(mgr):
    a = mgr.spawn("疯狂信徒", "车厢3")
    assert len(mgr.get_active_in_scene("车厢3")) == 1
    mgr.mark_dead(a.instance_id)
    assert len(mgr.get_active_in_scene("车厢3")) == 0


def test_group_by_ref(mgr):
    mgr.spawn("深潜者", "车厢4", quantity=2)
    mgr.spawn("疯狂信徒", "车厢4", quantity=3)
    mgr.spawn("深潜者", "车厢5")  # different scene

    groups = mgr.group_by_ref("车厢4")
    assert len(groups) == 2
    assert len(groups["深潜者"]) == 1
    assert groups["深潜者"][0].quantity == 2
    assert len(groups["疯狂信徒"]) == 1
    assert groups["疯狂信徒"][0].quantity == 3


def test_enter_combat_and_exit(mgr):
    a = mgr.spawn("疯狂信徒", "车厢6")
    b = mgr.spawn("深潜者", "车厢6")

    mgr.enter_combat([a.instance_id, b.instance_id])
    assert a.status == "engaged"
    assert b.status == "engaged"
    assert mgr._combat_active is True

    mgr.exit_combat({
        "outcome": "win",
        "defeated_instance_ids": [a.instance_id],
    })
    assert a.status == "dead"
    assert b.status == "hostile"  # survived, reverts to hostile
    assert mgr._combat_active is False


def test_get_combat_context_no_enemies(mgr):
    ctx = mgr.get_combat_context("空场景")
    assert ctx is None


def test_get_combat_context_with_enemies(mgr):
    mgr.spawn("深潜者", "车厢7")
    mgr.spawn("疯狂信徒", "车厢7", quantity=2)
    ctx = mgr.get_combat_context("车厢7")
    assert ctx is not None
    assert "深潜者" in ctx
    assert "疯狂信徒" in ctx
    assert "neutral" in ctx
    assert "combat_behavior" in ctx or "习性" in ctx or "description" in ctx or "伏击" in ctx
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_enemy_manager.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create EnemyInstance + EnemyManager**

Create `src/game/enemy_manager.py`:

```python
"""EnemyInstance + EnemyManager — runtime enemy tracking."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import uuid

from library.enemies import EnemyLibrary, LibraryEnemy


def _short_id() -> str:
    """8-char unique id suffix."""
    return uuid.uuid4().hex[:8]


@dataclass
class EnemyInstance:
    instance_id: str
    enemy_ref: str
    scene: str
    quantity: int = 1
    status: str = "neutral"      # neutral | hostile | engaged | dead
    flags: list[str] = field(default_factory=list)
    combat_behavior: str = ""    # cleaned natural language
    description: str = ""


class EnemyManager:
    def __init__(self, enemy_library: EnemyLibrary):
        self._library = enemy_library
        self._instances: dict[str, EnemyInstance] = {}
        self._combat_active: bool = False
        self._combat_enemies: list[str] = []

    def spawn(self, enemy_ref: str, scene: str, quantity: int = 1) -> EnemyInstance:
        lib_enemy = self._library.get(enemy_ref)
        if not lib_enemy:
            raise KeyError(f"Enemy '{enemy_ref}' not found in library")
        instance_id = f"{enemy_ref}_{_short_id()}"
        inst = EnemyInstance(
            instance_id=instance_id,
            enemy_ref=enemy_ref,
            scene=scene,
            quantity=quantity,
            flags=list(lib_enemy.flags),
            combat_behavior=lib_enemy.combat_behavior,
            description=lib_enemy.description,
        )
        self._instances[instance_id] = inst
        return inst

    def remove(self, instance_id: str):
        self._instances.pop(instance_id, None)
        if instance_id in self._combat_enemies:
            self._combat_enemies.remove(instance_id)

    def get_active_in_scene(self, scene: str) -> list[EnemyInstance]:
        return [
            i for i in self._instances.values()
            if i.scene == scene and i.status != "dead"
        ]

    def get_active_in_range(self, scene: str, graph) -> list[EnemyInstance]:
        candidates = self.get_active_in_scene(scene)
        adj_scenes = set()
        for inst in self._instances.values():
            if "adjacent_aware" not in inst.flags:
                continue
            if inst.status == "dead":
                continue
            node = graph.nodes.get(inst.scene)
            if not node:
                continue
            for edge in node.edges:
                adj_scenes.add(edge.target)
        for inst in self._instances.values():
            if inst.scene in adj_scenes and inst.status != "dead":
                if inst not in candidates:
                    candidates.append(inst)
        return candidates

    def group_by_ref(self, scene: str) -> dict[str, list[EnemyInstance]]:
        groups: dict[str, list[EnemyInstance]] = {}
        for inst in self.get_active_in_scene(scene):
            groups.setdefault(inst.enemy_ref, []).append(inst)
        return groups

    def set_status(self, instance_id: str, status: str):
        if instance_id in self._instances:
            self._instances[instance_id].status = status

    def mark_dead(self, instance_id: str):
        self.set_status(instance_id, "dead")

    def get_by_id(self, instance_id: str) -> Optional[EnemyInstance]:
        return self._instances.get(instance_id)

    def enter_combat(self, instance_ids: list[str]):
        for iid in instance_ids:
            if iid in self._instances:
                self._instances[iid].status = "engaged"
        self._combat_enemies = list(instance_ids)
        self._combat_active = True

    def exit_combat(self, result: dict):
        defeated = set(result.get("defeated_instance_ids", []))
        for iid in self._combat_enemies:
            inst = self._instances.get(iid)
            if not inst:
                continue
            if iid in defeated:
                inst.status = "dead"
            elif inst.status == "engaged":
                inst.status = "hostile"
        self._combat_enemies.clear()
        self._combat_active = False

    def get_combat_context(self, scene: str, graph=None) -> Optional[str]:
        candidates = self.get_active_in_range(scene, graph) if graph \
                     else self.get_active_in_scene(scene)
        if not candidates:
            return None
        lines = []
        for inst in candidates:
            flags_str = " ".join(f"[{f}]" for f in inst.flags) if inst.flags else ""
            lines.append(
                f"- [{inst.enemy_ref}] x{inst.quantity} | {inst.status}"
                + (f" | {flags_str}" if flags_str else "")
                + f"\n  习性：{inst.combat_behavior}"
                + (f"\n  描述：{inst.description}" if inst.description else "")
            )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "instances": {
                iid: {
                    "instance_id": inst.instance_id,
                    "enemy_ref": inst.enemy_ref,
                    "scene": inst.scene,
                    "quantity": inst.quantity,
                    "status": inst.status,
                }
                for iid, inst in self._instances.items()
            },
            "combat_active": self._combat_active,
            "combat_enemies": self._combat_enemies,
        }

    @classmethod
    def from_dict(cls, data: dict, library: EnemyLibrary) -> "EnemyManager":
        mgr = cls(library)
        for iid, idata in data.get("instances", {}).items():
            lib_enemy = library.get(idata["enemy_ref"])
            flags = list(lib_enemy.flags) if lib_enemy else []
            behavior = lib_enemy.combat_behavior if lib_enemy else ""
            desc = lib_enemy.description if lib_enemy else ""
            mgr._instances[iid] = EnemyInstance(
                instance_id=idata["instance_id"],
                enemy_ref=idata["enemy_ref"],
                scene=idata["scene"],
                quantity=idata.get("quantity", 1),
                status=idata.get("status", "neutral"),
                flags=flags,
                combat_behavior=behavior,
                description=desc,
            )
        mgr._combat_active = data.get("combat_active", False)
        mgr._combat_enemies = data.get("combat_enemies", [])
        return mgr

    def __repr__(self):
        return f"EnemyManager({len(self._instances)} instances, combat={'on' if self._combat_active else 'off'})"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_enemy_manager.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/game/enemy_manager.py tests/test_enemy_manager.py
git commit -m "feat: add EnemyInstance + EnemyManager — runtime enemy tracking"
```

---

### Task 4: CombatEntryCheck + CombatInit messages

**Files:**
- Modify: `src/game/messages.py`

- [ ] **Step 1: Add new dataclasses**

Append to `src/game/messages.py`:

```python
@dataclass
class CombatEntryCheck:
    """Combat entry detection result from LLM."""
    enter_combat: bool
    enemy_instance_ids: list[str] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class StandoffMatch:
    """Semantic match result for standoff phase."""
    matched: bool
    skill_name: str = ""
    reason: str = ""


@dataclass
class CombatInit:
    """Passed to pluggable combat system when combat begins."""
    enemies: list[Any] = field(default_factory=list)  # list[EnemyInstance]
    player: Any = None                   # Investigator
    scene: str = ""
    initiative_context: str = ""
```

- [ ] **Step 2: Verify import**

Run: `python -c "from game.messages import CombatEntryCheck, StandoffMatch, CombatInit; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/game/messages.py
git commit -m "feat: add CombatEntryCheck, StandoffMatch, CombatInit messages"
```

---

### Task 5: ScenarioWorld.enemy_manager + apply_side_effects spawn

**Files:**
- Modify: `src/scenario_core.py`

- [ ] **Step 1: Add enemy_manager to ScenarioWorld.__init__**

In `scenario_core.py`, modify `ScenarioWorld.__init__`:

```python
def __init__(self, graph: DirectedGraph, start_node: str,
             background_story: str = "",
             wr0_enabled: bool = False,
             enemy_library: Any = None):
    self.graph = graph
    self.current_location = start_node
    self.player: 'InvestigatorType | None' = None
    self.background_story = background_story
    self.wr0_enabled = wr0_enabled
    self.triggered_events: Dict[str, bool] = {
        eid: False for eid in graph.get_all_event_ids()
    }
    self.completed_interactions: Dict[str, Set[str]] = {}
    self.runtime_state: Dict[str, NodeRuntimeState] = {}
    self.dependency_graph: Dict[str, Any] = {}
    self.memory = MemoryManager()
    self.npc_states: Dict[str, str] = {}

    # Enemy tracking
    if enemy_library is not None:
        from game.enemy_manager import EnemyManager
        self.enemy_manager = EnemyManager(enemy_library)
    else:
        self.enemy_manager = None
```

- [ ] **Step 2: Modify apply_side_effects SpawnEnemy branch**

Replace lines 1115-1117 in `apply_side_effects()`:

```python
elif isinstance(effect, SpawnEnemy):
    target_scene = effect.scene or world.current_location
    if world.enemy_manager:
        instance = world.enemy_manager.spawn(
            effect.enemy_ref, target_scene, effect.quantity
        )
        msgs.append(
            f"[生成敌人] {effect.enemy_ref} x{effect.quantity} "
            f"在 {target_scene} ({instance.instance_id})"
        )
    else:
        msgs.append(
            f"[生成敌人] {effect.enemy_ref} x{effect.quantity} 在 {target_scene}"
        )
```

- [ ] **Step 3: Verify with a quick smoke test**

Run: `python -c "from scenario_core import ScenarioWorld, DirectedGraph; w = ScenarioWorld(DirectedGraph(scenes={}, events=[]), 'test'); print('enemy_manager:', w.enemy_manager)"`
Expected: `enemy_manager: None`

- [ ] **Step 4: Commit**

```bash
git add src/scenario_core.py
git commit -m "feat: add enemy_manager to ScenarioWorld; SpawnEnemy now instantiates via EnemyManager"
```

---

### Task 6: Combat entry + standoff prompt builders

**Files:**
- Modify: `src/prompts.py`

- [ ] **Step 1: Add build_combat_entry_prompt**

In `src/prompts.py`, add:

```python
def build_combat_entry_prompt(
    player_input: str,
    outcomes_summary: str,
    enemy_context: str,
    current_scene: str,
) -> str:
    return f"""你是 COC 7th KP 助理。根据玩家行为、本轮结果和场景内敌人的习性，判断是否应进入回合制战斗。

玩家输入：{player_input}
本轮结果：{outcomes_summary}
当前位置：{current_scene}

场景内敌人：
{enemy_context}

请判断是否有敌人应进入战斗。输出 JSON：
{{"enter_combat": true/false, "enemy_instance_ids": ["..."], "reasoning": "简述判定理由"}}"""
```

- [ ] **Step 2: Add build_standoff_match_prompt**

In `src/prompts.py`, add:

```python
_COC_SKILL_NAMES = [
    "会计", "人类学", "估价", "考古学", "魅惑", "攀爬", "计算机使用",
    "信用评级", "克苏鲁神话", "乔装", "闪避", "汽车驾驶", "电气维修",
    "电子学", "话术", "急救", "历史", "恐吓", "跳跃", "法律",
    "图书馆使用", "聆听", "锁匠", "机械维修", "医学", "博物学",
    "导航", "神秘学", "操作重型机械", "说服", "驾驶", "精神分析",
    "心理学", "读唇", "潜行", "侦查", "生存", "游泳", "投掷",
    "追踪", "驯兽",
]

def build_standoff_match_prompt(player_input: str) -> str:
    skill_list = "、".join(_COC_SKILL_NAMES)
    return f"""你是 COC 7th KP 助理。玩家在面对敌人时试图避免战斗。

玩家输入："{player_input}"

可用技能：{skill_list}

判断玩家意图对应的技能检定（如果有）：
{{"matched": true/false, "skill_name": "技能名", "reason": "简述为什么匹配"}}

规则：
- matched=false 表示玩家输入无法匹配为任何有意义的避免战斗的尝试（包括"什么都不做"、直接攻击等）
- 魅惑/取悦 → "魅惑"
- 说服/交涉/讲道理 → "说服"
- 潜行/偷偷溜走/绕过去 → "潜行"
- 恐吓/威胁 → "恐吓"
- 其他无法匹配的输出 matched=false"""
```

- [ ] **Step 3: Verify imports**

Run: `python -c "from prompts import build_combat_entry_prompt, build_standoff_match_prompt; print(build_combat_entry_prompt('test', 'test', 'test', 'test')[:50]); print(build_standoff_match_prompt('我尝试说服他')[:50])"`
Expected: prompt text printed

- [ ] **Step 4: Commit**

```bash
git add src/prompts.py
git commit -m "feat: add build_combat_entry_prompt + build_standoff_match_prompt"
```

---

### Task 7: Keeper — combat entry detection (parallel with enrich)

**Files:**
- Modify: `src/game/agents/keeper.py`

- [ ] **Step 1: Add combat entry detection in process_turn**

In `process_turn()`, between Step 2 (Judge) and Step 3 (Enrich), insert combat entry check launch:

After `all_outcomes` construction and before `# Step 3: Enrich (LLM)`, add:

```python
        # Step 2.5: Combat entry detection — deterministic gate + LLM
        combat_future = None
        combat_executor = None
        enemy_ctx = None
        if self.world and self.world.enemy_manager and not self.world.enemy_manager._combat_active:
            enemy_ctx = self.world.enemy_manager.get_combat_context(
                self.world.current_location, self.world.graph
            )
        if enemy_ctx:
            outcomes_summary = "\n".join(
                f"[{o.entity_type}] {o.message}" for o in all_outcomes
            )
            from prompts import build_combat_entry_prompt
            combat_prompt = build_combat_entry_prompt(
                player_input=raw,
                outcomes_summary=outcomes_summary,
                enemy_context=enemy_ctx,
                current_scene=self.world.current_location,
            )
            combat_executor = ThreadPoolExecutor(max_workers=1)
            combat_future = combat_executor.submit(
                call_deepseek,
                combat_prompt,
                json_mode=True,
                model="deepseek-v4-flash",
                reasoning_effort="low",
                system="你是 COC 7th KP 助理，负责判断是否进入战斗。",
                fallback_schema={"enter_combat": False, "enemy_instance_ids": [], "reasoning": ""},
            )
```

- [ ] **Step 2: Collect combat entry result after enrich**

After `# Step 3: Enrich (LLM)` block completes, and before Step 4 (IntentDetector decision point), add:

```python
        # Step 3.5: Collect combat entry result
        combat_entry = None
        if combat_future:
            try:
                raw_result = combat_future.result()
                result = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
                combat_entry = CombatEntryCheck(
                    enter_combat=result.get("enter_combat", False),
                    enemy_instance_ids=result.get("enemy_instance_ids", []),
                    reasoning=result.get("reasoning", ""),
                )
            except Exception:
                combat_entry = None
            finally:
                combat_executor.shutdown(wait=False)
```

Add import for `CombatEntryCheck` at top of file:
```python
from ..messages import (
    ActionIntent, ActionOutcome, NarratorBrief,
    AuthorRequest, StructuralEdit, ModulePatch, TurnInput,
    CombatEntryCheck,  # NEW
)
```

- [ ] **Step 3: Verify no import errors**

Run: `python -c "from game.agents.keeper import Keeper; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add src/game/agents/keeper.py
git commit -m "feat: add combat entry detection LLM call, parallel with enrich"
```

---

### Task 8: Keeper — standoff phase

**Files:**
- Modify: `src/game/agents/keeper.py`

- [ ] **Step 1: Add standoff phase after combat entry check**

After Step 3.5 (collect combat entry result), add standoff phase:

```python
        # Step 3.6: Standoff phase (avoidable enemies)
        combat_init = None  # CombatInit to pass to game loop
        if combat_entry and combat_entry.enter_combat:
            avoidable_iids = []
            for iid in combat_entry.enemy_instance_ids:
                inst = self.world.enemy_manager.get_by_id(iid)
                if inst and "avoidable" in inst.flags and inst.status != "hostile":
                    avoidable_iids.append(iid)

            # Only run standoff for enemies that are still neutral (not already hostile)
            if avoidable_iids:
                # Group by enemy_ref
                groups: dict[str, list[str]] = {}
                for iid in avoidable_iids:
                    inst = self.world.enemy_manager.get_by_id(iid)
                    if inst:
                        groups.setdefault(inst.enemy_ref, []).append(iid)

                from prompts import build_standoff_match_prompt
                from llm import evaluate_trait_enhancement
                from ..messages import StandoffMatch

                remaining_hostile = list(combat_entry.enemy_instance_ids)

                for enemy_ref, iids in groups.items():
                    inst = self.world.enemy_manager.get_by_id(iids[0])
                    hint = f"你还有最后一次机会避免与{enemy_ref}的战斗——你要怎么做？"
                    all_outcomes.append(ActionOutcome(
                        intent=ActionIntent(action="standoff"),
                        success=True,
                        message=hint,
                        entity_id="STANDOFF",
                        entity_type="standoff",
                    ))
                    # Standoff needs player input — return early, game loop handles interaction
                    # For now, store state and let game loop re-enter
                    self._standoff_pending = {
                        "enemy_ref": enemy_ref,
                        "instance_ids": iids,
                        "remaining_hostile": remaining_hostile,
                    }
                    # Mark these as resolved for now
                    for iid in iids:
                        if iid in remaining_hostile:
                            remaining_hostile.remove(iid)

                # After standoff, build CombatInit for remaining hostile enemies
                hostile_iids = remaining_hostile
            else:
                hostile_iids = list(combat_entry.enemy_instance_ids)

            if hostile_iids:
                enemies = [self.world.enemy_manager.get_by_id(iid)
                          for iid in hostile_iids
                          if self.world.enemy_manager.get_by_id(iid)]
                self.world.enemy_manager.enter_combat(hostile_iids)
                combat_init = CombatInit(
                    enemies=enemies,
                    player=self.world.player,
                    scene=self.world.current_location,
                    initiative_context=combat_entry.reasoning,
                )
        else:
            combat_init = None
```

Hmm, this is getting complex. The standoff phase requires player interaction mid-turn, which doesn't fit the current `process_turn` structure well. Let me redesign this part.

Actually, let me reconsider. The standoff phase requires player input. In the current game loop, `run_turn()` takes one user input and processes it. A standoff is essentially a mini-turn within a turn. The cleanest approach:

1. Combat entry detection runs (parallel with enrich)
2. If `enter_combat=true` and avoidable enemies exist, `process_turn` returns a special `standoff_prompt` flag
3. Game loop detects `standoff_prompt` and asks player for their avoidance action
4. Game loop calls Keeper's `resolve_standoff()` method with the player's input
5. `resolve_standoff()` does semantic match + D100 check + trait enhancement, returns result
6. If standoff fails → combat begins; if succeeds → enemy → neutral, continue

This separates concerns better and uses the existing game loop's input/output cycle.

Let me rewrite Task 8.

- [ ] **Step 1: Add standoff_prompt flag in process_turn return**

After collecting combat entry result, if `enter_combat=true` with avoidable enemies:

```python
        # Step 3.6: Standoff or combat init
        combat_init = None
        standoff_prompt = None
        if combat_entry and combat_entry.enter_combat:
            # Split by avoidable
            avoidable_by_ref: dict[str, list[str]] = {}
            hostile_iids: list[str] = []
            for iid in combat_entry.enemy_instance_ids:
                inst = self.world.enemy_manager.get_by_id(iid)
                if inst and "avoidable" in inst.flags:
                    avoidable_by_ref.setdefault(inst.enemy_ref, []).append(iid)
                elif inst:
                    hostile_iids.append(iid)

            if avoidable_by_ref:
                standoff_prompt = {
                    "groups": {ref: iids for ref, iids in avoidable_by_ref.items()},
                    "current_group": next(iter(avoidable_by_ref)),
                    "hostile_iids": hostile_iids,
                    "all_enemy_iids": combat_entry.enemy_instance_ids,
                    "reasoning": combat_entry.reasoning,
                }
                first_ref = standoff_prompt["current_group"]
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="standoff"),
                    success=True,
                    message=f"你还有最后一次机会避免与{first_ref}的战斗——你要怎么做？",
                    entity_id="STANDOFF",
                    entity_type="standoff",
                ))
            elif hostile_iids:
                enemies = [self.world.enemy_manager.get_by_id(iid)
                          for iid in hostile_iids
                          if self.world.enemy_manager.get_by_id(iid)]
                self.world.enemy_manager.enter_combat(hostile_iids)
                combat_init = CombatInit(
                    enemies=enemies,
                    player=self.world.player,
                    scene=self.world.current_location,
                    initiative_context=combat_entry.reasoning,
                )
```

And update the return dict:
```python
        return {
            "brief": brief,
            "ending_name": ending_name,
            "ending_narrative": ending_narrative,
            "combat_init": combat_init,          # NEW
            "standoff_prompt": standoff_prompt,  # NEW
        }
```

- [ ] **Step 2: Add resolve_standoff method to Keeper**

```python
    def resolve_standoff(self, standoff_state: dict, player_input: str) -> dict:
        """Resolve a standoff: semantic match → D100 → trait enhancement → result."""
        from prompts import build_standoff_match_prompt
        from llm import evaluate_trait_enhancement
        from ..messages import StandoffMatch

        enemy_ref = standoff_state["current_group"]
        instance_ids = standoff_state["groups"][enemy_ref]

        # Step 1: Semantic match (LLM, flash)
        match_prompt = build_standoff_match_prompt(player_input)
        try:
            raw = call_deepseek(match_prompt, json_mode=True, model="deepseek-v4-flash",
                               system="你是 COC 7th KP 助理，将玩家输入匹配到对应技能。",
                               fallback_schema={"matched": False, "skill_name": "", "reason": ""})
            match_data = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            match_data = {"matched": False, "skill_name": "", "reason": ""}

        if not match_data.get("matched"):
            # Match failed → combat
            for iid in instance_ids:
                inst = self.world.enemy_manager.get_by_id(iid)
                if inst:
                    inst.status = "hostile"
            return {"standoff_resolved": True, "avoided": False,
                    "message": f"你的尝试无效，{enemy_ref}进入战斗！",
                    "instance_ids": instance_ids}

        # Step 2: D100 skill check
        skill_name = match_data["skill_name"]
        ok, skill_msg, tier = self.world.player.check_skill(skill_name, "regular")
        skill_detail = (
            f"[STANDOFF] {skill_name}检定 | 等级={tier} | {'成功' if ok else '失败'}\n"
            f"  {skill_msg}"
        )

        # Step 3: Trait enhancement
        inv_desc = (getattr(self.world.player, 'personal_description', '') or
                   getattr(self.world.player, 'description', ''))
        if inv_desc:
            enh = evaluate_trait_enhancement(
                inv_desc=inv_desc,
                skill_name=skill_name,
                skill_detail=skill_msg,
                current_tier=tier,
                entity_name=f"避免与{enemy_ref}战斗",
                search_context=False,
            )
            new_tier = enh.get("tier", tier)
            if new_tier != tier:
                skill_detail += f"\n  [特质修正] {tier} → {new_tier}：{enh.get('reason', '')}"
                tier = new_tier
                ok = (tier != "failure")

        # Step 4: Apply result
        if ok:
            if skill_name in ("魅惑", "说服", "话术", "恐吓"):
                for iid in instance_ids:
                    self.world.enemy_manager.set_status(iid, "neutral")
                msg = f"{skill_name}成功——{enemy_ref}被{skill_name}所动，敌意消退。"
            else:  # 潜行
                msg = f"潜行成功——你悄悄绕过了{enemy_ref}。"
            return {"standoff_resolved": True, "avoided": True,
                    "message": msg, "instance_ids": instance_ids,
                    "skill_detail": skill_detail}
        else:
            for iid in instance_ids:
                inst = self.world.enemy_manager.get_by_id(iid)
                if inst:
                    inst.status = "hostile"
            return {"standoff_resolved": True, "avoided": False,
                    "message": f"{skill_name}失败——{enemy_ref}进入战斗！",
                    "instance_ids": instance_ids,
                    "skill_detail": skill_detail}
```

- [ ] **Step 3: Verify no import errors**

Run: `python -c "from game.agents.keeper import Keeper; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add src/game/agents/keeper.py
git commit -m "feat: add standoff phase — semantic match + D100 + trait enhancement"
```

---

### Task 9: init_game EnemyLibrary + game_loop standoff handling

**Files:**
- Modify: `src/game_loop.py`

- [ ] **Step 1: Load EnemyLibrary in init_game**

Modify `init_game()`:

```python
def init_game(l2_path: str, l1_path: str, l3_path: str,
              escalation_config_path: str,
              start_node: str = "6号车厢",
              wr0_enabled: bool = False) -> dict[str, Any]:
    # ... existing code ...

    # Load enemy library
    from library import EnemyLibrary
    enemy_lib = EnemyLibrary()
    enemy_lib.load_core()

    world = ScenarioWorld(graph, start_node=start_node,
                          wr0_enabled=wr0_enabled,
                          enemy_library=enemy_lib)  # NEW
    # ... rest unchanged ...
```

- [ ] **Step 2: Delete duplicate _apply_side_effects**

Remove lines 16-36 (the local `_apply_side_effects` function). All callers should use `scenario_core.apply_side_effects` via the Keeper's `_apply_side_effects` method.

- [ ] **Step 3: Handle standoff_prompt in run_turn**

In `run_turn()`, after calling `keeper.process_turn()`, add standoff handling:

```python
    # After process_turn:
    result = keeper.process_turn(turn_input, author=author)

    standoff = result.get("standoff_prompt")
    if standoff:
        return {
            "brief": result["brief"],
            "narrative": narrate_output,
            "full": narrate_output,
            "standoff_prompt": {
                "enemy_ref": standoff["enemy_ref"],
                "message": next((o.message for o in result["brief"].action_outcomes
                               if o.entity_type == "standoff"), ""),
            },
        }
```

Then add a `continue_standoff()` helper:

```python
def continue_standoff(keeper, player_input: str) -> dict:
    """Call keeper.resolve_standoff with player's avoidance attempt."""
    s = keeper._standoff_pending
    if not s:
        return {"standoff_resolved": True, "avoided": False,
                "message": "无待处理的对峙。"}

    result = keeper.resolve_standoff(s, player_input)

    if result["standoff_resolved"]:
        if result["avoided"]:
            # Check if more avoidable groups remain
            remaining = s.get("remaining_groups", [])
            if remaining:
                # Move to next avoidable group
                next_ref = remaining[0]
                # ... setup next standoff ...
                pass
            elif s.get("hostile_iids"):
                # All avoidables handled, remaining hostiles → combat
                enemies = [keeper.world.enemy_manager.get_by_id(iid)
                          for iid in s["hostile_iids"]
                          if keeper.world.enemy_manager.get_by_id(iid)]
                keeper.world.enemy_manager.enter_combat(s["hostile_iids"])
                result["combat_init"] = CombatInit(
                    enemies=enemies,
                    player=keeper.world.player,
                    scene=keeper.world.current_location,
                    initiative_context=s.get("reasoning", ""),
                )
        else:
            # Standoff failed, all enemies → combat
            all_iids = s.get("all_enemy_iids", [])
            enemies = [keeper.world.enemy_manager.get_by_id(iid)
                      for iid in all_iids
                      if keeper.world.enemy_manager.get_by_id(iid)]
            keeper.world.enemy_manager.enter_combat(all_iids)
            result["combat_init"] = CombatInit(
                enemies=enemies,
                player=keeper.world.player,
                scene=keeper.world.current_location,
                initiative_context=s.get("reasoning", ""),
            )

    return result
```

Wait, this is getting messy. The standoff state management with multiple groups is complex. Let me simplify: store all standoff state on Keeper, and expose a simpler `continue_standoff` entry point.

Let me rewrite this section more carefully.

- [ ] **Step 3 (revised): Handle standoff in game_loop.py**

Delete the local `_apply_side_effects` function (lines 16-36).

Add `continue_standoff()` at module level:

```python
def continue_standoff(keeper, player_input: str) -> dict:
    """Process a standoff avoidance attempt. Returns updated state."""
    s = keeper._standoff_pending
    if not s:
        return {"standoff_resolved": True, "avoided": False,
                "message": "无待处理的对峙", "combat_init": None}

    result = keeper.resolve_standoff(s, player_input)
    keeper._standoff_pending = None

    combat_init = None
    if result.get("avoided"):
        # Advance to next avoidable group or handle remaining hostiles
        groups = s.get("groups", {})
        current_ref = s.get("current_group", "")
        remaining = [ref for ref in groups if ref != current_ref]
        if remaining:
            next_ref = remaining[0]
            keeper._standoff_pending = {
                **s,
                "current_group": next_ref,
            }
            result["next_standoff"] = f"你还有最后一次机会避免与{next_ref}的战斗——你要怎么做？"
        elif s.get("hostile_iids"):
            enemies = [keeper.world.enemy_manager.get_by_id(iid)
                      for iid in s["hostile_iids"]
                      if keeper.world.enemy_manager.get_by_id(iid)]
            if enemies:
                keeper.world.enemy_manager.enter_combat(s["hostile_iids"])
                combat_init = CombatInit(
                    enemies=enemies, player=keeper.world.player,
                    scene=keeper.world.current_location,
                    initiative_context=s.get("reasoning", ""),
                )
    else:
        # Standoff failed — all enemies enter combat
        all_iids = s.get("all_enemy_iids", [])
        enemies = [keeper.world.enemy_manager.get_by_id(iid)
                  for iid in all_iids
                  if keeper.world.enemy_manager.get_by_id(iid)]
        if enemies:
            keeper.world.enemy_manager.enter_combat(all_iids)
            combat_init = CombatInit(
                enemies=enemies, player=keeper.world.player,
                scene=keeper.world.current_location,
                initiative_context=s.get("reasoning", ""),
            )

    result["combat_init"] = combat_init
    return result
```

Modify `init_game` to load EnemyLibrary:

```python
    # Load enemy library
    from library import EnemyLibrary
    enemy_lib = EnemyLibrary()
    enemy_lib.load_core()

    world = ScenarioWorld(graph, start_node=start_node,
                          wr0_enabled=wr0_enabled,
                          enemy_library=enemy_lib)
```

- [ ] **Step 4: Verify import**

Run: `python -c "from game_loop import init_game; print('ok')"`
Expected: `ok` (or import error if paths wrong — need actual module paths)

- [ ] **Step 5: Commit**

```bash
git add src/game_loop.py
git commit -m "feat: load EnemyLibrary in init_game; add continue_standoff; remove dead _apply_side_effects"
```

---

### Task 10: Update game/__init__.py exports

**Files:**
- Modify: `src/game/__init__.py`

- [ ] **Step 1: Add new exports**

```python
from game.enemy_manager import EnemyInstance, EnemyManager
from game.messages import CombatEntryCheck, StandoffMatch, CombatInit
```

- [ ] **Step 2: Verify import**

Run: `python -c "from game import EnemyInstance, EnemyManager, CombatEntryCheck, StandoffMatch, CombatInit; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/game/__init__.py
git commit -m "feat: export EnemyManager, CombatEntryCheck, CombatInit from game"
```

---

### Task 11: Integration test — SpawnEnemy → combat entry detection

**Files:**
- Create: `tests/test_combat_entry.py`

- [ ] **Step 1: Write integration test**

Create `tests/test_combat_entry.py`:

```python
"""Integration tests: SpawnEnemy → EnemyManager → combat entry context."""
import pytest
from scenario_core import (
    DirectedGraph, ScenarioWorld, Entity, Edge, Node,
    apply_side_effects, parse_markup_all,
)
from library.enemies import EnemyLibrary


@pytest.fixture
def graph():
    return DirectedGraph(scenes={
        "车厢1": {"description": "测试场景",
                  "interactions": [], "auto_triggers": [], "from_here": []},
    }, events=[])


@pytest.fixture
def lib():
    l = EnemyLibrary()
    l.load_core()
    return l


@pytest.fixture
def world(graph, lib):
    w = ScenarioWorld(graph, start_node="车厢1", enemy_library=lib)
    return w


def test_spawnenemy_instantiates_enemy(world):
    """@spawn_enemy side effect creates an EnemyInstance via EnemyManager."""
    se_text = '@spawn_enemy(enemy_ref="深潜者", scene="车厢1", quantity=1)'
    effects = parse_markup_all(se_text)
    assert len(effects) == 1

    msgs = apply_side_effects(world, effects)
    assert len(msgs) == 1
    assert "生成敌人" in msgs[0]
    assert "深潜者" in msgs[0]

    assert world.enemy_manager is not None
    active = world.enemy_manager.get_active_in_scene("车厢1")
    assert len(active) == 1
    assert active[0].enemy_ref == "深潜者"
    assert "avoidable" in active[0].flags


def test_get_active_in_range_no_adjacent_aware(world):
    """Enemies without adjacent_aware only appear in their own scene."""
    world.enemy_manager.spawn("疯狂信徒", "车厢1")
    active = world.enemy_manager.get_active_in_range("车厢2", world.graph)
    assert len(active) == 0


def test_get_active_in_range_with_adjacent_aware(world):
    """adjacent_aware enemies appear in adjacent scene detection."""
    # Add a second scene connected to 车厢1
    world.graph.nodes["车厢2"] = Node(
        node_id="车厢2", description="相邻场景",
        edges=[Edge(target="车厢1", method="走过去")],
        interactions=[], auto_triggers=[],
    )
    world.graph.nodes["车厢1"].edges.append(
        Edge(target="车厢2", method="走过去")
    )
    # 大嘴吞噬者 has adjacent_aware
    world.enemy_manager.spawn("大嘴吞噬者", "车厢1")
    active = world.enemy_manager.get_active_in_range("车厢2", world.graph)
    assert len(active) == 1
    assert active[0].enemy_ref == "大嘴吞噬者"


def test_combat_context_skips_empty(world):
    ctx = world.enemy_manager.get_combat_context("车厢1")
    assert ctx is None


def test_combat_context_includes_enemy_info(world):
    world.enemy_manager.spawn("深潜者", "车厢1", quantity=2)
    ctx = world.enemy_manager.get_combat_context("车厢1")
    assert ctx is not None
    assert "深潜者" in ctx
    assert "x2" in ctx


def test_enter_combat_exit_combat_cycle(world):
    """Full combat lifecycle tracking."""
    inst = world.enemy_manager.spawn("疯狂信徒", "车厢1")
    assert inst.status == "neutral"

    world.enemy_manager.enter_combat([inst.instance_id])
    assert inst.status == "engaged"
    assert world.enemy_manager._combat_active

    world.enemy_manager.exit_combat({
        "outcome": "win",
        "defeated_instance_ids": [inst.instance_id],
    })
    assert inst.status == "dead"
    assert not world.enemy_manager._combat_active
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/test_combat_entry.py -v`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_combat_entry.py
git commit -m "test: add combat entry integration tests — SpawnEnemy through EnemyManager"
```

---

### Task 12: Run full test suite

- [ ] **Step 1: Run all tests**

Run: `pytest tests/ -v`
Expected: all existing + new tests PASS

- [ ] **Step 2: Fix any regressions**

Check for test failures in existing tests that create `ScenarioWorld(...)` without the `enemy_library` parameter — should still work (defaults to None).

- [ ] **Step 3: Commit any fixes**

```bash
git add -u
git commit -m "fix: test regressions from ScenarioWorld enemy_library param"
```

---

## Verification

After all tasks complete:

1. `python -c "from game import EnemyManager, EnemyInstance, CombatEntryCheck, CombatInit; print('All imports OK')"`
2. `python -c "from library.enemies import EnemyLibrary; lib = EnemyLibrary(); lib.load_core(); print([(e.name, e.flags) for e in lib.list_all()])"` — verify flags parsed
3. `python -c "from scenario_core import apply_side_effects, parse_markup_all; print('Markup still works')"`
4. `pytest tests/ -v` — all green
5. `python -c "from prompts import build_combat_entry_prompt, build_standoff_match_prompt; print('Prompts build OK')"`
