# Game Loop Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Keeper duplicate state (Phase 1) and build unified world snapshot consumed by all prompt builders (Phase 2).

**Architecture:** Phase 1 makes `ScenarioWorld` the single source of truth for all subsystems, eliminating duplicate BossManager/NPCManager instances. Phase 2 adds `build_snapshot()` methods and refactors 7 fragmented context helpers into one consistent data source.

**Tech Stack:** Python, no new dependencies

---

### Task 1: Add `npc_profiles` param to ScenarioWorld.__init__

**Files:**
- Modify: `src/scenario_core.py:621-644`

- [ ] **Step 1: Add `npc_profiles` param and initialize NPCManager from it**

Change lines 621-644:

```python
def __init__(self, graph: DirectedGraph, start_node: str,
             background_story: str = "",
             wr0_enabled: bool = False,
             enemy_library: Any = None,
             weapon_library: Any = None,
             boss_library: Any = None,
             boss_encounters: list | None = None,
             npc_profiles: dict | None = None):
    from game.clock import GameClock
    from game.enemy_manager import EnemyManager
    from game.npc_manager import NPCManager
    from game.boss_manager import BossManager

    self.graph = graph
    self.current_location = start_node
    self.player: 'InvestigatorType | None' = None
    self.background_story = background_story
    self.wr0_enabled = wr0_enabled

    # 子系统
    self.clock = GameClock()
    self.memory = MemoryManager()
    self.enemies = EnemyManager(enemy_library) if enemy_library else None
    self.npcs = NPCManager()
    if npc_profiles:
        self.npcs.init_from_profiles(npc_profiles)
    self.bosses = BossManager(boss_library, boss_encounters or []) if boss_library else None

    # 本体状态
    self.scene_weapons: dict[str, list[SceneWeapon]] = {}
    self.weapon_library = weapon_library

    self.triggered_events: Dict[str, bool] = {
        eid: False for eid in graph.get_all_event_ids()
    }
    self.completed_interactions: Dict[str, Set[str]] = {}

    self.runtime_state: Dict[str, NodeRuntimeState] = {}
    self.dependency_graph: Dict[str, Any] = {}
```

- [ ] **Step 2: Commit**

```bash
git add src/scenario_core.py
git commit -m "feat: add npc_profiles param to ScenarioWorld.__init__"
```

---

### Task 2: Fix `apply_side_effects` backward-compat pattern

**Files:**
- Modify: `src/scenario_core.py:1121-1134`

- [ ] **Step 1: Replace `hasattr(world, 'npc_manager')` with `world.npcs`**

Read lines 1121-1134, replace:

```python
        elif isinstance(effect, NPCStateChange):
            # Route through NPCManager — unified NPC state tracking
            if hasattr(world, 'npc_manager') and world.npc_manager:
                world.npc_manager.set_state(effect.npc_name, effect.new_state)
            else:
                world.set_npc_state(effect.npc_name, effect.new_state)
            msgs.append(f"[NPC状态] {effect.npc_name} -> {effect.new_state}")
        elif isinstance(effect, NPCFollow):
            if hasattr(world, 'npc_manager') and world.npc_manager:
                world.npc_manager.set_following(effect.npc_name, effect.follow)
                status = "开始跟随" if effect.follow else "停止跟随"
                msgs.append(f"[NPC跟随] {effect.npc_name} {status}")
            else:
                msgs.append(f"[NPC跟随] {effect.npc_name} follow={effect.follow}")
```

With:

```python
        elif isinstance(effect, NPCStateChange):
            world.npcs.set_state(effect.npc_name, effect.new_state)
            msgs.append(f"[NPC状态] {effect.npc_name} -> {effect.new_state}")
        elif isinstance(effect, NPCFollow):
            world.npcs.set_following(effect.npc_name, effect.follow)
            status = "开始跟随" if effect.follow else "停止跟随"
            msgs.append(f"[NPC跟随] {effect.npc_name} {status}")
```

- [ ] **Step 2: Commit**

```bash
git add src/scenario_core.py
git commit -m "fix: remove hasattr(npc_manager) backward-compat in apply_side_effects"
```

---

### Task 3: Update `init_game` — pass subsystems to World, drop dict keys

**Files:**
- Modify: `src/game_loop.py:92-217, 262-269`

- [ ] **Step 1: Pass boss_library, boss_encounters, npc_profiles to ScenarioWorld**

Read lines 147-196. Change lines 147-178 from:

```python
    # Load enemy library
    from library import EnemyLibrary
    enemy_lib = EnemyLibrary()
    enemy_lib.load_core()

    # Load weapon library
    from library.weapons import WeaponLibrary
    weapon_lib = WeaponLibrary()
    weapon_lib.load_core()

    # Load boss library
    from library.bosses import BossLibrary
    boss_library = BossLibrary("data/library/core/bosses.json")
    boss_encounters = l2.get("boss_encounters", [])
    boss_manager = BossManager(boss_library, boss_encounters)

    # Init NPC manager
    npc_manager = NPCManager()
    npc_profiles = l2.get("npc_profiles", {})
    # Extract initial NPC scenes from L2 scene data
    for scene_name, scene_data in l2_scenes.items():
        for npc_data in scene_data.get("npcs", []):
            name = npc_data.get("name", "")
            if name in npc_profiles:
                if "scene" not in npc_profiles[name] or not npc_profiles[name]["scene"]:
                    npc_profiles[name] = {**npc_profiles[name], "scene": scene_name}
    npc_manager.init_from_profiles(npc_profiles)

    world = ScenarioWorld(graph, start_node=start_node,
                          wr0_enabled=wr0_enabled,
                          enemy_library=enemy_lib,
                          weapon_library=weapon_lib)
```

To:

```python
    # Load enemy library
    from library import EnemyLibrary
    enemy_lib = EnemyLibrary()
    enemy_lib.load_core()

    # Load weapon library
    from library.weapons import WeaponLibrary
    weapon_lib = WeaponLibrary()
    weapon_lib.load_core()

    # Load boss library
    from library.bosses import BossLibrary
    boss_library = BossLibrary("data/library/core/bosses.json")
    boss_encounters = l2.get("boss_encounters", [])

    # Prepare NPC profiles
    npc_profiles = l2.get("npc_profiles", {})
    for scene_name, scene_data in l2_scenes.items():
        for npc_data in scene_data.get("npcs", []):
            name = npc_data.get("name", "")
            if name in npc_profiles:
                if "scene" not in npc_profiles[name] or not npc_profiles[name]["scene"]:
                    npc_profiles[name] = {**npc_profiles[name], "scene": scene_name}

    world = ScenarioWorld(graph, start_node=start_node,
                          wr0_enabled=wr0_enabled,
                          enemy_library=enemy_lib,
                          weapon_library=weapon_lib,
                          boss_library=boss_library,
                          boss_encounters=boss_encounters,
                          npc_profiles=npc_profiles)
```

- [ ] **Step 2: Remove boss_manager/npc_manager from Keeper constructor and game dict**

Change lines 198-217 from:

```python
    # Init agents
    narrator = Narrator(l1)
    keeper = Keeper(
        world,
        dependency_graph=l2.get("dependency_graph"),
        phase1=l2.get("_phase1"),
        npc_profiles=l2.get("npc_profiles"),
        boss_manager=boss_manager,
        npc_manager=npc_manager,
    )
    author = Author(l3)
    keeper.narrator_l1 = l1  # Keeper holds reference for supplement merging

    return {
        "keeper": keeper,
        "narrator": narrator,
        "author": author,
        "boss_manager": boss_manager,
        "npc_manager": npc_manager,
    }
```

To:

```python
    # Init agents
    narrator = Narrator(l1)
    keeper = Keeper(
        world,
        phase1=l2.get("_phase1"),
    )
    author = Author(l3)
    keeper.narrator_l1 = l1

    return {
        "keeper": keeper,
        "narrator": narrator,
        "author": author,
    }
```

- [ ] **Step 3: Fix run_turn boss reference (line 263-267)**

Change:

```python
            # Boss post-combat resolution
            if 'boss_manager' in game:
                boss_mgr = game['boss_manager']
                if boss_mgr.active_boss_id:
                    boss_mgr.resolve_outcome(combat_result)
                    boss_mgr.set_active(None)
```

To:

```python
            # Boss post-combat resolution
            if world.bosses and world.bosses.active_boss_id:
                world.bosses.resolve_outcome(combat_result)
                world.bosses.set_active(None)
```

- [ ] **Step 4: Commit**

```bash
git add src/game_loop.py
git commit -m "refactor: pass subsystems to World, remove from init_game dict"
```

---

### Task 4: Clean up Keeper duplicate params

**Files:**
- Modify: `src/game/agents/keeper.py:35-55, 76-81, 245-250, 358-360, 388, 479-484, 697`

- [ ] **Step 1: Update `__init__` — remove duplicate params**

Change lines 35-55 from:

```python
    def __init__(
        self,
        world: ScenarioWorld,
        dependency_graph: dict | None = None,
        phase1: dict | None = None,
        npc_profiles: dict[str, Any] | None = None,
        boss_manager: Any = None,
        npc_manager: Any = None,
        time_costs: dict | None = None,
        comms_interval: int = 15,
    ):
        self.world = world
        # dependency_graph is now owned by world; keep reference here for backward compat
        self.dependency_graph = dependency_graph or {}
        self.phase1 = phase1 or {}
        self.npc_profiles = npc_profiles or {}
        self.boss_manager = boss_manager
        self.npc_manager = npc_manager
        self.time_costs = time_costs or {}
        self.comms_interval = comms_interval
        self._last_comms_time = 0
```

To:

```python
    def __init__(
        self,
        world: ScenarioWorld,
        phase1: dict | None = None,
    ):
        self.world = world
        self.phase1 = phase1 or {}
        self._last_comms_time = 0
```

- [ ] **Step 2: Route `self.npc_manager` → `self.world.npcs`**

Line 76-81 — change:

```python
        if self.npc_manager:
            npcs_present = self.npc_manager.get_in_scene(self.world.current_location)
            for npc in npcs_present:
                if npc.name in raw:
                    response = self.npc_manager.talk_to(npc.name, raw, lambda prompt, **kw: call_deepseek(prompt, **kw))
```

To:

```python
        if self.world.npcs:
            npcs_present = self.world.npcs.get_in_scene(self.world.current_location)
            for npc in npcs_present:
                if npc.name in raw:
                    response = self.world.npcs.talk_to(npc.name, raw, lambda prompt, **kw: call_deepseek(prompt, **kw))
```

- [ ] **Step 3: Route `self.boss_manager` → `self.world.bosses`**

Lines 245-250 and 479-484 — change all four occurrences of `self.boss_manager` to `self.world.bosses`.

Line 245: `if self.boss_manager:` → `if self.world.bosses:`
Line 246: `self.boss_manager.check_by_engage_type(` → `self.world.bosses.check_by_engage_type(`
Line 249: `self.boss_manager.build_combat_init(` → `self.world.bosses.build_combat_init(`
Line 250: `self.boss_manager.set_active(` → `self.world.bosses.set_active(`
Line 479: `if self.boss_manager:` → `if self.world.bosses:`
Line 480: `self.boss_manager.check_by_engage_type(` → `self.world.bosses.check_by_engage_type(`
Line 483: `self.boss_manager.build_combat_init(` → `self.world.bosses.build_combat_init(`
Line 484: `self.boss_manager.set_active(` → `self.world.bosses.set_active(`

- [ ] **Step 4: Route `self.time_costs` → `self.world.time_costs`**

Lines 358-360 and 697 — change:

Line 358: `if self.time_costs:` → `if self.world.time_costs:`
Line 360: `tc_guideline = _json.dumps(self.time_costs, ensure_ascii=False)` → `tc_guideline = _json.dumps(self.world.time_costs, ensure_ascii=False)`
Line 697: `defaults = self.time_costs or {` → `defaults = self.world.time_costs or {`

- [ ] **Step 5: Route `self.comms_interval` → `self.world.comms_interval`**

Line 388 — change:

```python
        if tp and self.world.clock.game_time - self._last_comms_time >= self.comms_interval:
```

To:

```python
        if tp and self.world.clock.game_time - self._last_comms_time >= self.world.comms_interval:
```

- [ ] **Step 6: Route `self.dependency_graph` → `self.world.dependency_graph`**

The only usage was the `__init__` assignment — already removed. No further changes needed.

- [ ] **Step 7: Commit**

```bash
git add src/game/agents/keeper.py
git commit -m "refactor: remove Keeper duplicate state, route through world"
```

---

### Task 5: Verify Phase 1 — run test suite

**Files:**
- None (verification only)

- [ ] **Step 1: Run unit tests for affected modules**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -m pytest tests/test_enemy_manager.py tests/test_npc_manager.py tests/test_boss_manager.py tests/test_boss_library.py tests/test_combat.py -v --tb=short
```
Expected: all pass

- [ ] **Step 2: Run game loop harness**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python tests/game_loop_harness.py
```
Expected: completes without AttributeError (no `self.boss_manager`/`self.npc_manager` references remaining)

- [ ] **Step 3: Commit if any harness fixes needed**

Only if the harness had direct references to removed fields.

---

### Task 6: Add snapshot helpers to NPCManager, EnemyManager, BossManager

**Files:**
- Modify: `src/game/npc_manager.py:52-53` (after `get_in_scene`)
- Modify: `src/game/enemy_manager.py:71-75` (after `get_active_in_scene`)
- Modify: `src/game/boss_manager.py:60-74` (after `set_active`)

- [ ] **Step 1: Add `get_in_scene_snapshot()` to NPCManager**

After line 53 (`get_in_scene`), insert:

```python
    def get_in_scene_snapshot(self, scene: str) -> list[dict]:
        """Lightweight dict list for world snapshot — no dataclass internals exposed."""
        return [
            {"name": n.name, "state": n.state, "attitude": n.attitude, "following": n.following}
            for n in self._npcs.values() if n.scene == scene
        ]
```

- [ ] **Step 2: Add `get_active_in_scene_snapshot()` to EnemyManager**

After line 75 (`get_active_in_scene`), insert:

```python
    def get_active_in_scene_snapshot(self, scene: str) -> list[dict]:
        """Lightweight dict list for world snapshot."""
        return [
            {
                "enemy_ref": i.enemy_ref,
                "status": i.status,
                "flags": i.flags,
                "quantity": i.quantity,
            }
            for i in self._instances.values()
            if i.scene == scene and i.status != "dead"
        ]
```

- [ ] **Step 3: Add `active_snapshot()` to BossManager**

After line 74 (`resolve_outcome`), insert:

```python
    def active_snapshot(self) -> dict | None:
        """Return active boss info for world snapshot, or None."""
        if not self._active_boss_id:
            return None
        for enc in self._encounters:
            if enc.get("id") == self._active_boss_id:
                lib_boss = self._library.get(enc.get("boss_ref", ""))
                return {
                    "entity_id": self._active_boss_id,
                    "boss_ref": enc.get("boss_ref", ""),
                    "engage_type": enc.get("engage_type", ""),
                    "mechanics": lib_boss.boss_mechanics if lib_boss else "",
                }
        return None
```

- [ ] **Step 4: Commit**

```bash
git add src/game/npc_manager.py src/game/enemy_manager.py src/game/boss_manager.py
git commit -m "feat: add snapshot helpers to NPCManager, EnemyManager, BossManager"
```

---

### Task 7: Add `build_snapshot()` to Investigator

**Files:**
- Modify: `src/investigator/models.py` (after line 262, end of `check_skills`)

- [ ] **Step 1: Add `build_snapshot()` method**

After line 262 (end of `check_skills`), insert:

```python
    def build_snapshot(self) -> dict:
        """Return a lightweight dict of player state for prompt contexts."""
        return {
            "name": self.name,
            "hp": self.derived.HP,
            "san": self.derived.SAN,
            "mp": self.derived.MP,
            "weapons": [w.name for w in self.weapons],
            "inventory": self.item_manager.describe(),
            "skills_summary": ", ".join(
                f"{s.name}={s.value}" for s in self.skills[:10]
            ),
            "description": self.personal_description or "",
        }
```

- [ ] **Step 2: Commit**

```bash
git add src/investigator/models.py
git commit -m "feat: add Investigator.build_snapshot()"
```

---

### Task 8: Add `build_snapshot()` to ScenarioWorld

**Files:**
- Modify: `src/scenario_core.py` (after `get_active_event_effects`, ~line 920)

- [ ] **Step 1: Add `build_snapshot()` method**

After `get_active_event_effects()` (after line 920), insert:

```python
    def build_snapshot(self) -> dict:
        """Pure data assembly — single source of truth for all prompt builders."""
        return {
            "location": self.current_location,
            "description": self.get_current_description(),
            "exits": [
                {"target": e.target, "method": e.method}
                for e in self.get_possible_exits()
            ],
            "time": self.clock.to_dict(),
            "player": self.player.build_snapshot() if self.player else {},
            "npcs_in_scene": self.npcs.get_in_scene_snapshot(self.current_location),
            "enemies_in_scene": (
                self.enemies.get_active_in_scene_snapshot(self.current_location)
                if self.enemies else []
            ),
            "boss_active": self.bosses.active_snapshot() if self.bosses else None,
            "scene_weapons": [
                {"weapon_ref": sw.weapon_ref, "quantity": sw.quantity}
                for sw in self.scene_weapons.get(self.current_location, [])
            ],
            "runtime": {
                "completed": [
                    eid for eid, s in self.runtime_state.items() if s.completed
                ],
                "triggered_events": [
                    eid for eid, t in self.triggered_events.items() if t
                ],
            },
        }
```

- [ ] **Step 2: Commit**

```bash
git add src/scenario_core.py
git commit -m "feat: add ScenarioWorld.build_snapshot()"
```

---

### Task 9: Replace Keeper fragmented snapshot builders

**Files:**
- Modify: `src/game/agents/keeper.py:680-730`

- [ ] **Step 1: Replace `_build_world_snapshot()`**

Lines 680-689 — change from:

```python
    def _build_world_snapshot(self) -> dict:
        """Lightweight snapshot for IntentDetector."""
        l1 = getattr(self, "narrator_l1", {}) or {}
        l1_scene = l1.get(self.world.current_location, {})
        scene_desc = l1_scene.get("description", "") if isinstance(l1_scene, dict) else ""
        return {
            "location": self.world.current_location,
            "scene_description": scene_desc,
            "npc_states": {name: npc.state for name, npc in self.world.npcs._npcs.items()},
        }
```

To:

```python
    def _build_world_snapshot(self) -> dict:
        """Lightweight snapshot for IntentDetector. Delegates to World."""
        snap = self.world.build_snapshot()
        l1 = getattr(self, "narrator_l1", {}) or {}
        l1_scene = l1.get(self.world.current_location, {})
        scene_desc = l1_scene.get("description", "") if isinstance(l1_scene, dict) else ""
        return {
            "location": snap["location"],
            "scene_description": scene_desc or snap["description"],
            "npc_states": {n["name"]: n["state"] for n in snap["npcs_in_scene"]},
        }
```

- [ ] **Step 2: Replace `_build_scene_context_for_author()`**

Lines 716-730 — change from:

```python
    def _build_scene_context_for_author(self) -> dict:
        """Build scene_context for AuthorRequest."""
        node = self.world._current_node()
        return {
            "location": self.world.current_location,
            "description": node.description if node else "",
            "available_scenes": list(self.world.graph.nodes.keys()),
            "npc_states": {name: npc.state for name, npc in self.world.npcs._npcs.items()},
            "runtime_summary": {
                eid: s.result_tier
                for eid, s in self.world.runtime_state.items()
                if s.completed
            },
            "wr0_enabled": self.world.wr0_enabled,
        }
```

To:

```python
    def _build_scene_context_for_author(self) -> dict:
        """Build scene_context for AuthorRequest. Delegates to World snapshot."""
        snap = self.world.build_snapshot()
        return {
            "location": snap["location"],
            "description": snap["description"],
            "available_scenes": list(self.world.graph.nodes.keys()),
            "npc_states": {n["name"]: n["state"] for n in snap["npcs_in_scene"]},
            "runtime_summary": {
                eid: s.result_tier
                for eid, s in self.world.runtime_state.items()
                if s.completed
            },
            "wr0_enabled": self.world.wr0_enabled,
        }
```

- [ ] **Step 3: Commit**

```bash
git add src/game/agents/keeper.py
git commit -m "refactor: replace Keeper fragmented snapshot builders with world.build_snapshot()"
```

---

### Task 10: Refactor prompt builders to use unified snapshot

**Files:**
- Modify: `src/prompts.py:93-144` (helper functions), `src/prompts.py:387-514` (parse + enrich builders)

- [ ] **Step 1: Replace `_build_scene_context()` to consume snapshot**

Lines 93-108 — change signature and implementation:

```python
def _build_scene_context(snap: dict) -> str:
    """Get current scene position, description, and exits from snapshot."""
    exit_list = "\n".join([
        f"  → {e['target']}：{e['method']}" for e in snap.get("exits", [])
    ]) or "（无）"

    return f"""【当前位置】{snap['location']}
【场景描述】{snap['description']}

【可移动方向】
{exit_list}"""
```

- [ ] **Step 2: Replace `_build_world_state()` to consume snapshot**

Lines 138-144 — change:

```python
def _build_world_state(snap: dict) -> str:
    """从 snapshot 获取当前状态摘要"""
    runtime = snap.get("runtime", {})
    triggered = runtime.get("triggered_events", [])
    completed = runtime.get("completed", [])
    flags_str = ", ".join(completed) or "（无）"
    return f"""已触发事件：{triggered or '（无）'}
世界标记：{flags_str}"""
```

- [ ] **Step 3: Replace `_build_investigator_info()` to consume snapshot**

Lines 117-134 — change signature and implementation:

```python
def _build_investigator_info(snap: dict) -> str:
    """构建调查员基本信息（从 snapshot player 字段）"""
    p = snap.get("player", {})
    if not p or not p.get("name"):
        return ""
    parts = [f"  姓名：{p['name']}"]
    if p.get("description"):
        parts.append(f"  描述：{p['description']}")
    return "【调查员】\n" + "\n".join(parts) + "\n"


def _build_player_state(snap: dict) -> str:
    """构建调查员状态块（HP/SAN/武器/物品）"""
    p = snap.get("player", {})
    if not p:
        return ""
    lines = ["【调查员状态】"]
    lines.append(f"  HP={p.get('hp', '?')} SAN={p.get('san', '?')} MP={p.get('mp', '?')}")
    if p.get("weapons"):
        lines.append(f"  武器：{', '.join(p['weapons'])}")
    inv = p.get("inventory", "")
    if inv and inv != "（未持有物品）":
        lines.append(f"  物品：{inv}")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Add `_build_scene_state()` helper for NPCs/enemies/weapons**

After `_build_player_state`, insert:

```python
def _build_scene_state(snap: dict) -> str:
    """构建场景现状（NPC/敌人/武器）"""
    parts = []
    npcs = snap.get("npcs_in_scene", [])
    if npcs:
        parts.append(f"  NPC：{', '.join(n['name'] for n in npcs)}")
    enemies = snap.get("enemies_in_scene", [])
    if enemies:
        parts.append(f"  敌人：{', '.join(e['enemy_ref'] for e in enemies)}")
    weps = snap.get("scene_weapons", [])
    if weps:
        parts.append(f"  场景武器：{', '.join(w['weapon_ref'] for w in weps)}")
    if not parts:
        return ""
    return "【场景现状】\n" + "\n".join(parts) + "\n"
```

- [ ] **Step 5: Add `_build_time_block()` helper**

After `_build_scene_state`, insert:

```python
def _build_time_block(snap: dict) -> str:
    """构建时间上下文块"""
    t = snap.get("time", {})
    if not t:
        return ""
    lines = [f"【时间】第{t.get('day', 0)}天 {t.get('time_of_day', '')}（累计{t.get('game_time', 0)}分钟）"]
    ctx = t.get("time_context", "")
    if ctx:
        lines.append(ctx)
    return "\n".join(lines) + "\n"
```

- [ ] **Step 6: Update `build_keeper_parse_prompt()` to use snapshot**

Lines 387-461 — change the function body to use snapshot:

```python
def build_keeper_parse_prompt(world, user_input: str) -> str:
    """Keeper step 1: match player input against ALL entities, evaluate NL requirements."""
    snap = world.build_snapshot()
    scene_ctx = _build_scene_context(snap)
    state = _build_world_state(snap)
    context = world.memory.get_context()
    inv_info = _build_investigator_info(snap)
    player_state = _build_player_state(snap)
    scene_state = _build_scene_state(snap)
    time_block = _build_time_block(snap)

    trig_scene, nontrig_scene, trig_events, nontrig_events = _build_entity_lines(world)

    # Scene entities section
    scene_entity_parts = []
    if trig_scene:
        scene_entity_parts.append("【可触发 — AUTO_TRIGGER / INTERACT】\n" + "\n".join(trig_scene))
    if _SHOW_NON_TRIGGERABLE and nontrig_scene:
        scene_entity_parts.append("【暂不可触发 — AUTO_TRIGGER / INTERACT】\n" + "\n".join(nontrig_scene))
    scene_entity_text = "\n\n".join(scene_entity_parts) if scene_entity_parts else "（无）"

    event_parts = []
    if trig_events:
        event_parts.append("【可触发 — EVENT】\n" + "\n".join(trig_events))
    if _SHOW_NON_TRIGGERABLE and nontrig_events:
        event_parts.append("【暂不可触发 — EVENT】\n" + "\n".join(nontrig_events))
    event_text = "\n\n".join(event_parts) if event_parts else "（无）"

    prompt = f"""
你的任务是为玩家的输入匹配结构化的内容

【玩家历史行动】
{context or '（游戏刚开始）'}

【世界状态】
{state}

{inv_info}
{player_state}
{scene_state}
{scene_ctx}
{time_block}
【场景实体】
{scene_entity_text}

【全局事件】
{event_text}

【玩家输入】
{user_input}

实体分为三类：INTERACT（场景交互）、AUTO_TRIGGER（自动触发）、EVENT（全局事件）。
硬性条件（flag/依赖关系）已由系统判定完成。你只需：
1. 判断玩家意图匹配了哪些可触发实体或者其他行为包括(move/search/other)。如有「条件=」字段（软性条件/自然语言描述），评估是否满足，不满足的排除。

返回 JSON：
{{
  "actions": [
    {{"type": "auto_trigger", "id": "AT1"}},
    {{"type": "interaction", "id": "I3"}},
    {{"type": "event", "id": "E22"}},
    {{"type": "move", "target": "7号车厢"}},
    {{"type": "search"}},
    {{"type": "other", "text": "唱了一首歌"}}
  ]
}}

规则：
- 玩家输入有明确对应的entity优先返回entity结果，之后再考虑search/move/other
- 对当前场景整体没有明确指定对象的搜索、探查、感知行为属于search不触发entity
- 一般来讲玩家一个动作（注意不是一轮输入）只匹配一个结果，但也允许同时匹配多个结果的特殊情况，你可以基于具体文字发挥
- move指移动到别的场景，other泛指所有其他行为
- auto_trigger 必须排在列表最前面
- id 必须从上述实体列表中精确复制
- move：target 填可移动方向中列出的目标
- other：text 用自然语言简述玩家意图
- 只考虑可触发的entity
- 如有「条件=」字段，评估是否满足，不满足的排除（硬性条件系统已处理）
- 直接输出 JSON，不要额外文字
"""
    _show_prompt("Keeper Parse", prompt)
    return prompt
```

- [ ] **Step 7: Update `build_keeper_enrich_prompt()` to use snapshot**

Lines 466-514 — change the function body to include time and scene state:

```python
def build_keeper_enrich_prompt(world, judged_entities, user_input) -> str:
    """Keeper step 3: describe and enrich entity results. No trigger evaluation."""
    snap = world.build_snapshot()
    state = _build_world_state(snap)
    scene_state = _build_scene_state(snap)
    time_block = _build_time_block(snap)

    entities_text = ""
    for e in judged_entities:
        entities_text += (
            f"  [{e['entity_type']}] id={e['id']} name=\"{e['name']}\" "
            f"result=\"{e['result']}\" success={e['success']}"
        )
        if e.get('skill_tier'):
            entities_text += f" skill_tier={e['skill_tier']}"
        entities_text += "\n"

    prompt = f"""
你的任务是整合不同的文本并以半结构化的json格式输出他们
【世界状态】
{state}

【当前场景】{snap['location']}
{snap['description']}

{scene_state}
{time_block}
【玩家输入】{user_input}

【本轮已触发实体】
{entities_text or '（无）'}

请为以上已触发实体做叙事整合：
1. 将所有实体（auto_trigger / interaction / event）的结果合并润色，统一为流畅连贯的叙事
2. 根据 success 调整叙事：
   - success=true → 结果被清晰、明确地描述并整合进叙事，玩家能确切感知到发生了什么
   - success=false → 侦察感知类任务描述为：结果晦涩、模糊、没有实际影响，仿佛是错觉或微不足道的细节，玩家难以确定是否真的发生了什么。可以明确得到反馈的任务描述为行动失败。
3. 提供 reasoning：简短说明本轮整合的逻辑（为什么这样合并/改写）

返回 JSON：
{{
  "results": "本轮所有实体结果合并润色后的连贯叙事",
  "reasoning": "简短说明整合逻辑",
  "emphasis_hint": "叙事强调方向"
}}

直接输出 JSON。
"""
    _show_prompt("Keeper Enrich", prompt)
    return prompt
```

- [ ] **Step 8: Update `build_narrator_prompt()` to accept snapshot**

Lines 519-577 — add `snap` param and use it:

```python
def build_narrator_prompt(brief, l1_scene=None, snap: dict | None = None, user_input: str = "") -> str:
    """Narrator: converts NarratorBrief + L1 context into immersive narrative."""
    entity_outcomes = ""
    flavor_outcomes = ""
    for o in brief.action_outcomes:
        if o.intent.action == "other" and o.entity_type != "auto_trigger":
            flavor_outcomes += f"  · {o.message}\n"
        elif o.entity_type != "auto_trigger":
            entity_outcomes += f"  {'✓' if o.success else '✗'} {o.message}\n"

    ambient_text = "\n".join(f"  · {a}" for a in brief.ambient_changes) or "（无）"

    l1_ctx = _build_l1l3_context(l1_scene=l1_scene,
                                  scene_name=brief.scene_snapshot.location)

    inv_info = ""
    if snap:
        inv_info = _build_investigator_info(snap)

    prompt = f"""{l1_ctx}

{inv_info}
【玩家输入】{user_input or '（无）'}

【当前场景】{brief.scene_snapshot.location}
{brief.scene_snapshot.description}

【可通行方向】{', '.join(f"{e['target']}({e['method']})" for e in brief.scene_snapshot.exits)}

【实体行动结果】
{entity_outcomes or '（无）'}
{'' if not flavor_outcomes else f'【即兴行为】\n{flavor_outcomes}'}
【环境变化】
{ambient_text}

【叙事强调】{brief.suggested_emphasis}

请以TRPG主持人身份生成沉浸式叙事。

返回 JSON：
{{
  "brief": "简洁、清晰、客观的概括——本轮发生了什么。仅陈述事实，不含情绪色彩。",
  "narrative": "基于结果进行文学性展开，融入场景氛围，让玩家身临其境。中文不超过100字。",
  "scene_update": ""
}}

规则：
- **你的任务是讲述，唯一的讲述根据是结合【实体行动结果】和【场景感知信息】回复用户的输入，严禁出现任何其他实质性内容**
- brief 与 narrative 必须严格呼应，brief "简洁、清晰、客观的概述事实，narrative 基于结果进行文学性展开
- scene_update：判断本轮行动是否导致场景可见变化（物品移动、门打开、血迹、光源、NPC出现/消失等）。有变化则输出更新后的完整场景描述；无变化则为空字符串 ""
- 仅当本轮行动确实改变了场景时才填写 scene_update
- 「即兴行为」不导致场景变化，不填写 scene_update
- 不要给出前文没有的实质性信息
- **禁止在【实体行动结果】未提及获得/找到/发现物品时，在叙事中描述玩家获得/找到/发现了物品。物品的获取必须严格依据实体行动结果中记录的内容**
- 以上下文语境和场景氛围为准
- 叙事强调指明了本轮的叙事方向，是叙事的核心重点
- 【场景感知信息】虽非本轮事件的直接结果，但构成当前场景的完整感知背景，必须一并融入叙事，不可只聚焦行动结果而忽略场景氛围
- 「即兴行为」仅为叙述性描写，不对世界产生任何实际影响——场景状态、物品位置、
  NPC状态等均不因其改变。描述时作为短暂的、无后果的角色动作自然融入叙事，
  一带而过即可，不做展开
直接输出 JSON。
"""
    _show_prompt("Narrator", prompt)
    return prompt
```

- [ ] **Step 9: Update `game_loop.py` narrator call to pass snapshot**

In `src/game_loop.py`, the `run_turn` function around line 284-286 — change:

```python
        narrative_brief, narrative, scene_update = narrator.narrate(
            brief, inv_info=_build_investigator_info(world), user_input=user_input)
```

To:

```python
        snap = world.build_snapshot()
        narrative_brief, narrative, scene_update = narrator.narrate(
            brief, snap=snap, user_input=user_input)
```

- [ ] **Step 10: Update Narrator.narrate() signature if needed**

Read `src/game/agents/narrator.py` — check if `narrate()` accepts `snap` param. If it currently takes `inv_info` and passes it to `build_narrator_prompt`, change it to accept and forward `snap`.

Check the Narrator class:

```bash
grep -n "def narrate" src/game/agents/narrator.py
```

Expected change: replace `inv_info` param with `snap` param, forward `snap=snap` to `build_narrator_prompt`.

- [ ] **Step 11: Commit**

```bash
git add src/prompts.py src/game_loop.py src/game/agents/narrator.py
git commit -m "refactor: prompt builders consume unified world snapshot"
```

---

### Task 11: Verify Phase 2 — run full test suite

**Files:**
- None (verification only)

- [ ] **Step 1: Run full unit test suite**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -m pytest tests/ -v --tb=short -x
```
Expected: all deterministic tests pass

- [ ] **Step 2: Run game loop harness**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python tests/game_loop_harness.py
```
Expected: completes successfully, prompt logs show new `【调查员状态】` and `【场景现状】` blocks

- [ ] **Step 3: Verify snapshot in prompt logs**

Check the latest prompt log in `logs/prompt_log_*/` — confirm the `Keeper Parse` prompt includes:
- `【调查员状态】` with HP/SAN/MP/weapons
- `【场景现状】` with NPCs/enemies
- `【时间】` block

- [ ] **Step 4: Commit any final fixes**

```bash
git add -A
git commit -m "chore: final fixes from verification"
```

---

### Task 12: Clean up Investigator item management

**Files:**
- Modify: `src/investigator/models.py:148-178, 354-360`

- [ ] **Step 1: Remove `self.equipment` field, keep kwarg no-op**

Lines 148-178 — change `__init__`:

```python
def __init__(
    self,
    name: str = "Unknown",
    age: int = 20,
    gender: str = "",
    occupation: Optional[Occupation] = None,
    stats: Optional[Stats] = None,
    derived: Optional[DerivedStats] = None,
    skills: Optional[List[Skill]] = None,
    weapons: Optional[List[Weapon]] = None,
    equipment: Optional[List[str]] = None,   # deprecated, kept for serialization compat
    backstory: str = "",
    appearance: str = "",
    personal_description: str = "",
):
    self.name = name
    self.age = age
    self.gender = gender
    self.occupation = occupation

    self.stats = stats or Stats()
    self.derived = derived or DerivedStats()

    self.skills: List[Skill] = skills or []
    self.weapons: List[Weapon] = weapons or []
    self.item_manager: ItemManager = ItemManager()

    self.backstory = backstory
    self.appearance = appearance
    self.personal_description = personal_description
```

Key change: remove `self.equipment: List[str] = equipment or []`, keep `equipment` in signature as ignored kwarg.

- [ ] **Step 2: Remove dead `add_item()` / `remove_item()` methods**

Lines 354-360 — delete these methods entirely:

```python
    def add_item(self, item: str):
        if item not in self.equipment:
            self.equipment.append(item)

    def remove_item(self, item: str):
        if item in self.equipment:
            self.equipment.remove(item)
```

- [ ] **Step 3: Add `has_item()` / `list_items()` convenience wrappers**

After line 262 (end of `check_skills`), add:

```python
    # ── 物品便捷查询 ──

    def has_item(self, name: str) -> bool:
        """Check if investigator holds a specific item."""
        return self.item_manager.has(name)

    def list_items(self) -> str:
        """Describe all held items (formatted string)."""
        return self.item_manager.describe()
```

- [ ] **Step 4: Commit**

```bash
git add src/investigator/models.py
git commit -m "refactor: remove dead equipment field, add has_item/list_items wrappers"
```

---

### Task 13: Update README — known serialization gaps

**Files:**
- Modify: `README.md` — add item to 已知缺口 table

- [ ] **Step 1: Add serialization gaps to 已知缺口 table**

Find the table at `## 已知缺口` (around line 209). Add two rows:

```markdown
| G9 | `item_manager` 未序列化 | ⚠ KNOWN — `to_dict`/`from_dict` 不包含 ItemManager。游戏过程中通过 `@item_gain` 获得的物品在存档/读档后丢失。`equipment` 字段仅为向后兼容保留的空壳 |
| G10 | 子系统 (clock/enemies/npcs/bosses) 未序列化 | ⚠ KNOWN — `to_dict`/`from_dict` 不包含 GameClock、EnemyManager、NPCManager、BossManager。存档/读档后游戏时间、敌人位置、NPC 态度、Boss 状态丢失 |
```

- [ ] **Step 2: Update O7 in 待优化 — note outstanding serialization work**

O7 line 232 currently says "✅ FIXED". Append a note:

```markdown
| O7 | 世界状态类 & 调查员类 | ⚠ 架构已重构，序列化待修复 — ScenarioWorld 重构为 Facade + GameClock + EnemyManager/NPCManager/BossManager 组合模式；@markup 解析迁至 `game/side_effects.py`；Keeper 接管 time_costs/comms_interval/apply_side_effects。详见 `docs/superpowers/specs/2026-05-22-world-refactor-design.md`。**子系统序列化 (G9/G10) 待后续修复** |
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add serialization gaps G9/G10 to README"
```
