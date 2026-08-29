# 统一存档（B1 + F14 + E 簇占坑）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 B1 存读档三连（吞异常丢敌人 / 双读档路径引用不一致 / NPC 注入重复），落 F14 技能 checked 标记，E 簇入档最小占坑；存档格式 version 1→2，只迁一轮。

**Architecture:** 见 spec `docs/superpowers/specs/2026-08-29-unified-save-design.md`。`save_game`/`load_game`（game_loop）成为唯一入口；`Keeper.set_world` 显式重绑；`load_state` 库透传 + `world.load_warnings`；session_state 最小集入 `_meta`。

**Tech Stack:** pytest、既有 e2e 基建（`tests/e2e/helpers.py: make_world / make_scene / stub_keeper_llm`）。

**约定:**
- 基线（HEAD `1eaaf3b`）：`pytest tests/ -q` = **347 passed, 20 deselected**。已知 flaky：`test_unresolved_use_becomes_creative`、`test_combat_phase_trigger`（复跑即过，勿修）。
- 每 Task 一个 commit；同步 MAINTENANCE.md changelog 一行。
- 不提交无关脏文件（autosave、supplements、imp.py、test.py、.claude/）。
- 存档时机不变式：/save 只在输入边界；格式不含回合中间态（spec §2）。

---

## 文件结构

| 文件 | 改动 |
|---|---|
| `src/investigator/models.py` | `Skill.checked` 字段；`check_skill` 成功置位 |
| `src/investigator/serialization.py` | skills 条目 ±`checked` |
| `src/scenario_core.py` | `__init__` 存 `_npc_profiles`；`to_dict`/`from_dict` 加 `clues`/`narrative_memory`；`save_state` 加 `extra_meta`、version 2；`load_state` 库透传 + `load_warnings` + 删吞异常 |
| `src/game/agents/keeper.py` | `set_world` / `dump_session_state` / `load_session_state` |
| `src/game_loop.py` | `save_game`/`load_game` 重写为唯一入口 |
| `run_game.py` | `/save` `/load` 改走 game_loop 入口 |
| `tests/test_skill_checked.py` | 新建（F14） |
| `tests/test_save_load.py` | 新建（B1 + E 簇 + v1 兼容） |

---

### Task 1: F14 Skill.checked 标记

**Files:**
- Modify: `src/investigator/models.py:41-51`（Skill）、`:240-245`（check_skill skill 分支）
- Modify: `src/investigator/serialization.py:68-77`（to_dict）、`:140-149`（from_dict）
- Test: `tests/test_skill_checked.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_skill_checked.py`：

```python
"""F14：技能成长标记（checked）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def _inv_with_spot():
    from investigator import Investigator
    from investigator.models import Skill
    inv = Investigator(name="测试员", age=25, gender="男")
    inv.skills = [Skill(name="侦查", base_value=50)]
    return inv


class TestSkillChecked:
    def test_success_marks_checked(self, monkeypatch):
        """check_skill 成功 → skill.checked=True。"""
        inv = _inv_with_spot()
        monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 30)
        ok, msg, tier = inv.check_skill("侦查", "regular")
        assert ok
        assert inv.get_skill("侦查").checked is True

    def test_failure_does_not_mark(self, monkeypatch):
        """check_skill 失败 → checked 保持 False。"""
        inv = _inv_with_spot()
        monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 80)
        ok, msg, tier = inv.check_skill("侦查", "regular")
        assert not ok
        assert inv.get_skill("侦查").checked is False

    def test_unmastered_skill_not_marked(self, monkeypatch):
        """未掌握技能默认放行 → 无 Skill 对象可标，不报错。"""
        inv = _inv_with_spot()
        monkeypatch.setattr("investigator.models.random.randint", lambda a, b: 30)
        ok, msg, tier = inv.check_skill("考古学", "regular")
        assert ok  # 默认成功放行，不抛异常即锁定行为

    def test_serialization_roundtrip(self):
        """checked 随卡格式序列化回环；旧卡缺省 False。"""
        from investigator.serialization import to_dict, from_dict
        inv = _inv_with_spot()
        inv.get_skill("侦查").checked = True
        inv2 = from_dict(to_dict(inv))
        assert inv2.get_skill("侦查").checked is True
        # 旧卡无 checked 键 → 默认 False
        data = to_dict(inv)
        for s in data["skills"]:
            s.pop("checked", None)
        inv3 = from_dict(data)
        assert inv3.get_skill("侦查").checked is False
```

- [ ] **Step 2: 跑测试确认红**

Run: `pytest tests/test_skill_checked.py -v`
Expected: FAIL（`Skill` 无 `checked` 属性 → AttributeError / 断言失败）

- [ ] **Step 3: 实现**

models.py `Skill`（:41）加字段：

```python
    is_occupation: bool = False
    checked: bool = False        # F14：成功使用标记（幕末成长检定用，Step3 消费）
```

models.py `check_skill` skill 分支（:240-245）改为：

```python
        skill = self.get_skill(skill_name)  # kind=="skill" 时 get_skill 已归一
        if skill is None:
            self.check_warnings.append(
                f"未掌握技能[{skill_name}]（归一={kind}:{value}），默认成功放行")
            return True, f"{skill_name}（未掌握，默认判定成功）", "regular"
        ok, msg, tier = self._roll_d100(skill_name, skill.value)
        if ok:
            skill.checked = True  # F14：COC7 成功使用才标记
        return ok, msg, tier
```

（attr/pseudo/ignore 分支不动——成长标记只适用真实技能。）

serialization.py `to_dict` skills 条目（:69-75）加 `"checked": s.checked,`；`from_dict` Skill 构造（:140-147）加 `checked=s.get("checked", False),`。

- [ ] **Step 4: 验证**

Run: `pytest tests/test_skill_checked.py -v` → 4 passed
Run: `pytest tests/ -q` → 347+4 passed, 20 deselected

- [ ] **Step 5: MAINTENANCE + Commit**

```bash
git add src/investigator/models.py src/investigator/serialization.py tests/test_skill_checked.py MAINTENANCE.md
git commit -m "feat: F14 skill checked mark on successful check_skill + serialization"
```

---

### Task 2: B1① load_state 库透传 + 删吞异常 + load_warnings

**Files:**
- Modify: `src/scenario_core.py:690-691`（存 `_npc_profiles`）、`:1178-1194`（save_state）、`:1196-1251`（load_state）
- Test: `tests/test_save_load.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_save_load.py`：

```python
"""B1：存读档统一修复（①吞异常 ②引用重绑 ③注入重复）+ E 簇占坑 + v1 兼容。"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tests', 'e2e'))


def _enemy_lib():
    from library.enemies import EnemyLibrary, LibraryEnemy
    lib = EnemyLibrary()
    lib._enemies["测试巡游者"] = LibraryEnemy.from_dict({
        "name": "测试巡游者", "type": "怪物",
        "attributes": {"CON": 30, "SIZ": 30}, "armor": "",
        "attacks": [], "special_abilities": [], "san_loss": "0",
        "description": "", "combat_behavior": "",
    })
    return lib


class TestEnemyRestoreWithLibrary:
    def test_enemies_restored_with_library(self, tmp_path):
        """带库读档：敌人实例恢复（旧行为：库为 None → 吞异常 → enemies=None）。"""
        from helpers import make_world, make_scene
        lib = _enemy_lib()
        world = make_world({"room_a": make_scene()}, "room_a", enemy_library=lib)
        world.enemies.spawn("测试巡游者", "room_a", 1)
        path = str(tmp_path / "save.json")
        world.save_state(path)

        from scenario_core import ScenarioWorld
        restored = ScenarioWorld.load_state(path, enemy_lib=lib)
        assert restored.enemies is not None, "带库读档 enemies 不得为 None"
        active = restored.enemies.get_active_in_scene("room_a")
        assert len(active) == 1, f"敌人实例应恢复，实际 {len(active)}"

    def test_missing_library_warns_not_silent(self, tmp_path):
        """无库读有敌人的档：enemies=None 但 load_warnings 非空（不静默）。"""
        from helpers import make_world, make_scene
        lib = _enemy_lib()
        world = make_world({"room_a": make_scene()}, "room_a", enemy_library=lib)
        world.enemies.spawn("测试巡游者", "room_a", 1)
        path = str(tmp_path / "save.json")
        world.save_state(path)

        from scenario_core import ScenarioWorld
        restored = ScenarioWorld.load_state(path)  # 不传库
        assert restored.enemies is None or not restored.enemies.get_active_in_scene("room_a")
        assert restored.load_warnings, "无库恢复敌人必须产生 warning（不静默）"

    def test_structural_corruption_raises(self, tmp_path):
        """结构性损坏（版本不支持）→ raise（旧世界不动）。"""
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"version": 99}), encoding="utf-8")
        from scenario_core import ScenarioWorld
        import pytest
        with pytest.raises(ValueError):
            ScenarioWorld.load_state(str(path))
```

- [ ] **Step 2: 跑测试确认红**

Run: `pytest tests/test_save_load.py -v`
Expected: 前两条 FAIL（`load_state()` 不识别 `enemy_lib` 参数 → TypeError），第三条 PASS（现版本检查已 raise）

- [ ] **Step 3: 实现 load_state 库透传 + load_warnings**

`ScenarioWorld.__init__`（:690-691 后）加：

```python
        self._npc_profiles = npc_profiles or {}   # 存副本供读档恢复 NPC 绑定实体
        self.load_warnings: list[str] = []        # B1①：读档 warning 收集（不静默）
```

`load_state` 签名与敌人/boss/npc 恢复段（:1196-1251）改为：

```python
    @classmethod
    def load_state(cls, path: str, enemy_lib=None, boss_lib=None,
                   npc_profiles: dict | None = None) -> "ScenarioWorld":
        """从存档恢复。库由调用方（当前会话）透传——库是模组资产，不入档。
        结构性损坏 raise；单条引用失败/库缺失 → 跳过 + load_warnings。"""
        import logging
        log = logging.getLogger("scenario_core.load")
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if data.get("version") not in (1, 2):
            raise ValueError(f"不支持的存档版本: {data.get('version')}")
        graph = DirectedGraph.from_dict(data["graph"])  # 缺键自然 raise（结构性）
        world_data = data["world"]
        world_data["memory"] = data.get("memory", {})
        world = cls.from_dict(world_data, graph)
        world.load_warnings = []
        if npc_profiles is not None:
            world._npc_profiles = npc_profiles

        def _warn(msg):
            log.warning(msg)
            world.load_warnings.append(msg)

        enemies_data = world_data.get("enemies")
        if enemies_data:
            if enemy_lib is None:
                _warn("存档含敌人数据但当前会话无敌人库，敌人状态未恢复")
            else:
                from game.enemy_manager import EnemyManager
                try:
                    world.enemies = EnemyManager.from_dict(enemies_data, enemy_lib)
                except Exception as e:
                    _warn(f"敌人状态恢复失败（{e}），敌人状态未恢复")
        npcs_data = world_data.get("npcs")
        if npcs_data:
            from game.npc_manager import NPCManager
            try:
                world.npcs = NPCManager()
                world.npcs.from_dict(npcs_data, world._npc_profiles)
            except Exception as e:
                _warn(f"NPC 状态恢复失败（{e}）")
        bosses_data = world_data.get("bosses")
        if bosses_data:
            if boss_lib is None:
                _warn("存档含 Boss 数据但当前会话无 Boss 库，Boss 状态未恢复")
            else:
                from game.boss_manager import BossManager
                try:
                    world.bosses = BossManager.from_dict(bosses_data, boss_lib)
                except Exception as e:
                    _warn(f"Boss 状态恢复失败（{e}）")
        # scene_weapons / player_snapshot 恢复段保持原样（原 1240-1250）
        ...
        return world
```

注意：`from_dict` 内部已恢复 clock（:1171-1175），load_state 里原 :1208-1211 的重复 clock 恢复段可删（行为等价，顺手去重）；scene_weapons 与 player_snapshot 段原样保留。

- [ ] **Step 4: 验证**

Run: `pytest tests/test_save_load.py -v` → 3 passed
Run: `pytest tests/ -q` → 351+3 passed, 20 deselected

- [ ] **Step 5: MAINTENANCE + Commit**

```bash
git add src/scenario_core.py tests/test_save_load.py MAINTENANCE.md
git commit -m "fix: B1-1 load_state library threading + loud warnings, no more silent swallow"
```

---

### Task 3: B1② set_world 重绑 + save/load 唯一入口

**Files:**
- Modify: `src/game/agents/keeper.py`（`__init__` 后加 `set_world`）
- Modify: `src/game_loop.py:638-667`（save_game/load_game 重写）
- Modify: `run_game.py:137-155`（/save /load 改道）
- Modify: `src/scenario_core.py` save_state 加 `extra_meta` + version 2
- Test: `tests/test_save_load.py`（追加）

- [ ] **Step 1: 写失败测试**

`tests/test_save_load.py` 追加：

```python
class TestLoadRebindsReferences:
    def _keeper_game(self, monkeypatch):
        from helpers import make_world, make_scene, stub_keeper_llm, StubNarrator
        from game.agents.keeper import Keeper
        world = make_world({"room_a": make_scene()}, "room_a")
        from investigator import Investigator
        world.set_player(Investigator(name="测试员", age=25, gender="男"))
        keeper = Keeper(world)
        return {"keeper": keeper, "narrator": StubNarrator(), "author": None}

    def test_load_rebinds_judge_curator_monitor(self, tmp_path, monkeypatch):
        """load_game 后 judge/curator/turn_monitor 持新 world（旧 CLI 路径丢引用）。"""
        from game_loop import save_game, load_game
        game = self._keeper_game(monkeypatch)
        path = str(tmp_path / "save.json")
        save_game(game, path)
        old_world = game["keeper"].world

        load_game(game, path)
        keeper = game["keeper"]
        assert keeper.world is not old_world
        assert keeper.judge.world is keeper.world
        assert keeper.curator.world is keeper.world
        assert keeper.turn_monitor._world is keeper.world

    def test_meta_turn_number_restored(self, tmp_path, monkeypatch):
        """_meta.turn_number 随 load_game 恢复。"""
        from game_loop import save_game, load_game
        game = self._keeper_game(monkeypatch)
        game["keeper"].turn_number = 7
        path = str(tmp_path / "save.json")
        save_game(game, path)
        game["keeper"].turn_number = 0

        load_game(game, path)
        assert game["keeper"].turn_number == 7
```

- [ ] **Step 2: 跑测试确认红**

Run: `pytest tests/test_save_load.py -v`
Expected: FAIL（`save_game`/`load_game` 为旧实现；`keeper.set_world` 不存在 → AttributeError 或断言失败）

- [ ] **Step 3: 实现**

keeper.py `__init__` 之后加：

```python
    def set_world(self, new_world: ScenarioWorld) -> None:
        """B1②：读档重绑——所有持 world 引用的内部组件统一切换。"""
        self.world = new_world
        self.judge.world = new_world
        self.curator.world = new_world
        self.turn_monitor._world = new_world
```

scenario_core.py `save_state`（:1178）改签名与写法：

```python
    def save_state(self, path: str, extra_meta: dict | None = None):
        """全量快照存档（图 + 世界 + 记忆 + 调查员快照）。version 2。"""
        from investigator.serialization import to_dict as inv_to_dict
        from datetime import datetime
        import os

        data = {
            "version": 2,
            "timestamp": datetime.now().isoformat(),
            "graph": self.graph.to_dict(),
            "world": self.to_dict(),
            "memory": self.memory.to_dict(),
            "player_snapshot": inv_to_dict(self.player) if self.player else None,
            "_meta": extra_meta or {},
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
```

game_loop.py `save_game`/`load_game`（:638-667）重写：

```python
def save_game(game: dict, path: str) -> None:
    """唯一保存入口（B1②）：一次性写出版本 2 存档 + _meta。"""
    keeper = game["keeper"]
    keeper.world.save_state(path, extra_meta={
        "turn_number": keeper.turn_number,
        "session_state": keeper.dump_session_state(),
    })


def load_game(game: dict, path: str) -> None:
    """唯一读档入口（B1②）：load_state(库透传) → set_world 重绑 → _meta 恢复。"""
    import json as _json
    keeper = game["keeper"]
    cur = keeper.world
    restored = ScenarioWorld.load_state(
        path,
        enemy_lib=cur.enemies.library if cur.enemies else None,
        boss_lib=cur.bosses.library if cur.bosses else None,
        npc_profiles=getattr(cur, "_npc_profiles", {}),
    )
    keeper.set_world(restored)
    with open(path, "r", encoding="utf-8") as f:
        meta = _json.load(f).get("_meta", {})
    keeper.turn_number = meta.get("turn_number", 0)
    keeper.load_session_state(meta.get("session_state", {}))
    for w in restored.load_warnings:
        print(f"[warn] {w}")
```

（`ScenarioWorld` 在 game_loop.py 顶部若无 import 则加 `from scenario_core import ScenarioWorld`——检查现有 import 段。）

run_game.py `/save`（:137-142）改：

```python
        elif cmd.startswith("/save"):
            slot = cmd.split(maxsplit=1)[1] if len(cmd.split()) > 1 else "quick"
            path = f"data/saves/{slot}.json"
            from game_loop import save_game
            save_game(game, path)
            print(f"[info] 存档已保存至 {path}")
            continue
```

`/load`（:143-155）改：

```python
        elif cmd.startswith("/load"):
            slot = cmd.split(maxsplit=1)[1] if len(cmd.split()) > 1 else "quick"
            path = f"data/saves/{slot}.json"
            if _os.path.exists(path):
                from game_loop import load_game
                load_game(game, path)
                world = game["keeper"].world
                print(f"[info] 已从 {path} 读档")
                print(_scene_text(world))
            else:
                print(f"[warn] 存档 {path} 不存在")
            continue
```

注意：run_game.py 主循环后续用 `world` 局部变量——确认循环内每轮是否重读 `keeper.world`；若是 `world = keeper.world` 在循环外只取一次，需把 /load 后的 `world = game["keeper"].world` 重赋值加上（上面已含）。

- [ ] **Step 4: 验证**

Run: `pytest tests/test_save_load.py -v` → 5 passed
Run: `pytest tests/ -q` → 全绿
Run: `pytest tests/test_turn_monitor.py -v` → 全绿（autosave 用 save_state 的 mock，签名兼容确认）

- [ ] **Step 5: MAINTENANCE + Commit**

```bash
git add src/game/agents/keeper.py src/game_loop.py run_game.py src/scenario_core.py tests/test_save_load.py MAINTENANCE.md
git commit -m "fix: B1-2 unified save/load entry + keeper.set_world rebinding"
```

---

### Task 4: B1③ session_state 入档 + 注入不重复

**Files:**
- Modify: `src/game/agents/keeper.py`（dump/load_session_state）
- Test: `tests/test_save_load.py`（追加）

- [ ] **Step 1: 写失败测试**

`tests/test_save_load.py` 追加：

```python
class TestNpcInjectionNoDuplicate:
    def test_injection_ids_survive_load(self, tmp_path, monkeypatch):
        """B1③：_npc_injected_at_ids 入档，读档后不重复注入。"""
        from helpers import make_world, make_scene
        from game_loop import save_game, load_game
        from game.agents.keeper import Keeper
        from helpers import StubNarrator

        profile = {"name": "列车员", "scene": "room_a", "can_interact": True,
                   "bound_auto_triggers": [{
                       "id": "AT_NPC1", "entity_type": "auto_trigger",
                       "name": "列车员的提醒", "type": "无", "requirement": "",
                       "trigger": "玩家进入车厢时", "result": "列车员低声提醒你。",
                       "difficulty": "None"}]}
        world = make_world({"room_a": make_scene()}, "room_a",
                           npc_profiles={"列车员": profile})
        keeper = Keeper(world)
        game = {"keeper": keeper, "narrator": StubNarrator(), "author": None}
        keeper._inject_npc_at()
        node = world.graph.nodes["room_a"]
        assert sum(1 for e in node.auto_triggers if e.id == "AT_NPC1") == 1

        path = str(tmp_path / "save.json")
        save_game(game, path)
        load_game(game, path)

        keeper._inject_npc_at()
        node2 = keeper.world.graph.nodes["room_a"]
        ids = [e.id for e in node2.auto_triggers if e.id == "AT_NPC1"]
        assert len(ids) == 1, f"读档后 AT_NPC1 不得重复注入，实际 {len(ids)} 个"

    def test_session_state_roundtrip_minimal(self, tmp_path, monkeypatch):
        """session_state 最小集回环：注入集合/最近意图/上次通信时间。"""
        from helpers import make_world, make_scene, StubNarrator
        from game_loop import save_game, load_game
        from game.agents.keeper import Keeper
        world = make_world({"room_a": make_scene()}, "room_a")
        keeper = Keeper(world)
        keeper._npc_injected_at_ids.add("AT_X")
        keeper._recent_intents.append("练拳")
        keeper._last_comms_time = 42
        game = {"keeper": keeper, "narrator": StubNarrator(), "author": None}

        path = str(tmp_path / "save.json")
        save_game(game, path)
        keeper._npc_injected_at_ids.clear()
        keeper._recent_intents.clear()
        keeper._last_comms_time = 0
        load_game(game, path)

        assert keeper._npc_injected_at_ids == {"AT_X"}
        assert keeper._recent_intents == ["练拳"]
        assert keeper._last_comms_time == 42
```

- [ ] **Step 2: 跑测试确认红**

Run: `pytest tests/test_save_load.py -v`
Expected: FAIL（`dump_session_state`/`load_session_state` 不存在）

- [ ] **Step 3: 实现**

keeper.py `set_world` 之后加：

```python
    # ── session_state 入档（B1③；最小集，spec §1）──

    def dump_session_state(self) -> dict:
        return {
            "npc_injected_at_ids": sorted(self._npc_injected_at_ids),
            "recent_intents": list(self._recent_intents),
            "last_comms_time": self._last_comms_time,
        }

    def load_session_state(self, data: dict) -> None:
        self._npc_injected_at_ids = set(data.get("npc_injected_at_ids", []))
        self._recent_intents = list(data.get("recent_intents", []))
        self._last_comms_time = data.get("last_comms_time", 0)
```

- [ ] **Step 4: 验证**

Run: `pytest tests/test_save_load.py -v` → 7 passed
Run: `pytest tests/ -q` → 全绿

- [ ] **Step 5: MAINTENANCE + Commit**

```bash
git add src/game/agents/keeper.py tests/test_save_load.py MAINTENANCE.md
git commit -m "fix: B1-3 session_state persisted (npc_injected_at_ids/throttles), no re-injection on load"
```

---

### Task 5: E 簇占坑 + v1 兼容

**Files:**
- Modify: `src/scenario_core.py:1118-1142`（to_dict）、`:1145-1176`（from_dict）
- Test: `tests/test_save_load.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
class TestFormatV2:
    def test_placeholder_containers_present(self, tmp_path):
        """E 簇占坑：存档含 clues/narrative_memory 空容器，回环保持。"""
        from helpers import make_world, make_scene
        world = make_world({"room_a": make_scene()}, "room_a")
        path = str(tmp_path / "save.json")
        world.save_state(path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["version"] == 2
        assert data["world"]["clues"] == []
        assert data["world"]["narrative_memory"] == []

        from scenario_core import ScenarioWorld
        restored = ScenarioWorld.load_state(path)
        assert restored.clues == []
        assert restored.narrative_memory == []

    def test_v1_save_loads_with_defaults(self, tmp_path):
        """v1 旧档可读：缺 session_state/clues/checked 一律默认值。"""
        from helpers import make_world, make_scene
        world = make_world({"room_a": make_scene()}, "room_a")
        path = tmp_path / "save.json"
        world.save_state(str(path))
        data = json.loads(path.read_text(encoding="utf-8"))
        data["version"] = 1                      # 模拟旧档
        data.pop("_meta", None)
        data["world"].pop("clues", None)
        data["world"].pop("narrative_memory", None)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        from scenario_core import ScenarioWorld
        restored = ScenarioWorld.load_state(str(path))
        assert restored.clues == []
        assert restored.narrative_memory == []
        assert restored.current_location == "room_a"
```

- [ ] **Step 2: 跑测试确认红**

Run: `pytest tests/test_save_load.py::TestFormatV2 -v`
Expected: FAIL（`to_dict` 无 clues 键 / `restored.clues` AttributeError）

- [ ] **Step 3: 实现**

`to_dict`（:1118-1142）return dict 加两键：

```python
            "san_seen_sources": sorted(self.san_seen_sources),
            "clues": list(getattr(self, "clues", [])),              # F22 占坑
            "narrative_memory": list(getattr(self, "narrative_memory", [])),  # F25 占坑
```

`from_dict`（:1170 附近）加：

```python
        world.san_seen_sources = set(data.get("san_seen_sources", []))
        world.clues = list(data.get("clues", []))                  # F22 占坑
        world.narrative_memory = list(data.get("narrative_memory", []))  # F25 占坑
```

`__init__`（:700 附近）加 `self.clues: list = []` 与 `self.narrative_memory: list = []`。

- [ ] **Step 4: 验证**

Run: `pytest tests/test_save_load.py -v` → 9 passed
Run: `pytest tests/ -q` → 全绿

- [ ] **Step 5: MAINTENANCE + Commit**

```bash
git add src/scenario_core.py tests/test_save_load.py MAINTENANCE.md
git commit -m "feat: save format v2 — clues/narrative_memory placeholders + additive-default v1 compat"
```

---

### Task 6: 收口（ISSUES / MAINTENANCE / 全量回归）

- [ ] **Step 1: docs/ISSUES.md**

- B1 从 §1 🔴 表移入 §5 已收口（一行：三连修法 + commit 号）
- F14 行更新标注：「checked 标记已落（Task1 commit）；幕末成长检定循环仍 Step3/U4」
- ISSUES 行号引用有漂移则顺手修

- [ ] **Step 2: MAINTENANCE.md 刷新**

受影响函数行号：`save_state`/`load_state`/`to_dict`/`from_dict`（scenario_core）、`set_world`/`dump_session_state`/`load_session_state`（keeper）、`save_game`/`load_game`（game_loop）、`check_skill`/`Skill`（models）、serialization 两函数。

- [ ] **Step 3: 全量回归**

Run: `pytest tests/ -q`
Expected: 360 passed（347+4+3+2+2+2）, 20 deselected（flaky 复跑即过）

- [ ] **Step 4: Commit**

```bash
git add docs/ISSUES.md MAINTENANCE.md
git commit -m "docs: close unified save batch (B1 triple fix + F14 mark + format v2)"
```

---

## Self-Review 记录

- Spec 覆盖：§2 格式 v2（Task3 save_state + Task5 占坑）§3 B1①（Task2）B1②（Task3）B1③（Task4）/save 统一（Task3）§4 F14（Task1）§5 E 簇（Task5）§6 验收测试（各 Task Step1）§7 非目标（未列入任何 Task）——全覆盖
- 依赖顺序：Task2（_npc_profiles 存储）→ Task4（注入测试依赖 profiles 透传）；Task3（save_state extra_meta）→ Task4（session_state 写入）
- 类型一致：`dump_session_state` 键名（npc_injected_at_ids/recent_intents/last_comms_time）在 Task3 调用与 Task4 定义一致；`load_warnings` 在 Task2 定义、Task3 消费
- 占位扫描：无 TBD；Task2 Step3 的 `...` 处已注明保留原段内容
- 风险：`run_game.py` 主循环 `world` 局部变量重赋值已在 Task3 Step3 显式提醒；`test_turn_monitor.py` 对 save_state 的 MagicMock 不受签名变更影响（mock 不在意参数），Task3 Step4 已列验证
