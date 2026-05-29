# TurnMonitor + 自动存档 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现管线级状态机 TurnMonitor（追踪 process_turn 每步状态、关键段失败回退+freeze）+ 后台标志位自动存档（10分钟间隔滚动存档）+ 修复缺失的 save_game/load_game

**Architecture:** TurnMonitor 为新增模块 `src/monitor/turn_monitor.py`，持有 LLMSensor 和 ScenarioWorld 引用。Keeper 在 `__init__` 中初始化 TurnMonitor，在 `process_turn()` 中用 `execute_step()` 包装每个管线段。自动存档使用 threading.Timer daemon + 全局标志位，在 `run_turn()` 入口处检查并执行。

**Tech Stack:** Python dataclasses, threading (Timer/Thread), ThreadPoolExecutor, Operator.attrgetter (deep copy), existing LLMSensor/AgentMonitor

---

### Task 1: Config 新增配置项

**Files:**
- Modify: `src/config.py`

- [ ] **Step 1: 在 config.py 末尾的"管线参数"节后追加 TurnMonitor + 自动存档配置项**

```python
# ═══════════════════════════════════════════════════════════════
# TurnMonitor 管线状态机
# ═══════════════════════════════════════════════════════════════

TURN_STEP_MAX_RETRIES = 2
"""管线段默认最大重试次数。"""

# ═══════════════════════════════════════════════════════════════
# 自动存档
# ═══════════════════════════════════════════════════════════════

AUTOSAVE_ENABLED = True
AUTOSAVE_INTERVAL_SEC = 600       # 10 分钟
AUTOSAVE_MAX_COPIES = 5
AUTOSAVE_DIR = "data/autosave"
```

- [ ] **Step 2: Commit**

```bash
git add src/config.py
git commit -m "config: add TurnMonitor and autosave settings"
```

---

### Task 2: TurnMonitor 类 — 核心状态机

**Files:**
- Create: `src/monitor/turn_monitor.py`

- [ ] **Step 1: 创建文件，定义 StepResult dataclass**

```python
"""TurnMonitor — 管线状态机。追踪 process_turn() 每步状态，关键段失败回退+freeze。"""
from __future__ import annotations
from dataclasses import dataclass, field
import time
import operator

from monitor.sensor import LLMSensor
from config import TURN_STEP_MAX_RETRIES


@dataclass
class StepResult:
    step: str
    status: str = "pending"      # pending | running | ok | failed | skipped | retrying
    retries: int = 0
    duration_ms: float = 0.0
    error: str = ""


class TurnFrozenError(Exception):
    """关键段耗尽重试次数，回合必须冻结。"""
    pass
```

- [ ] **Step 2: 实现 TurnMonitor.__init__ 和 begin_turn()**

```python
class TurnMonitor:
    def __init__(self, sensor: LLMSensor, world, keeper=None):
        self._sensor = sensor
        self._world = world
        self._keeper = keeper   # 用于访问 narrator_l1 等
        self._steps: list[StepResult] = []
        self._last_good_state: dict | None = None
        self._freeze_message: str = ""
        self._turn_started: bool = False

    def begin_turn(self) -> None:
        from investigator.serialization import to_dict as inv_to_dict

        self._turn_started = True
        self._steps.clear()
        self._freeze_message = ""
        # 全量快照供回退：graph + world + memory + player
        self._last_good_state = {
            "graph": self._world.graph.to_dict(),
            "world": self._world.to_dict(),
            "memory": self._world.memory.to_dict(),
            "player_snapshot": inv_to_dict(self._world.player) if self._world.player else None,
            "l1_data": getattr(self._keeper, 'narrator_l1', {}).copy() if self._keeper else {},
        }
```

- [ ] **Step 3: 实现 execute_step() — 单步执行+重试+关键段回退**

```python
    def execute_step(self, step: str, fn, *,
                     is_critical: bool = False,
                     max_retries: int = TURN_STEP_MAX_RETRIES) -> StepResult:
        if not self._turn_started:
            self.begin_turn()

        sr = StepResult(step=step, status="running")
        t0 = time.time()
        last_error = ""

        for attempt in range(max_retries + 1):
            try:
                result = fn()
                sr.duration_ms = (time.time() - t0) * 1000
                sr.status = "ok"
                sr.retries = attempt
                self._steps.append(sr)
                return result
            except Exception as e:
                last_error = str(e)
                if attempt < max_retries:
                    sr.status = "retrying"
                    sr.retries = attempt + 1
                    continue

        # 重试耗尽
        sr.status = "failed"
        sr.retries = max_retries
        sr.duration_ms = (time.time() - t0) * 1000
        sr.error = last_error
        self._steps.append(sr)

        if is_critical:
            self._restore_world()
            from pathlib import Path
            import os
            save_dir = Path("data/autosave")
            os.makedirs(save_dir, exist_ok=True)
            self._world.save_state(str(save_dir / "recovery.json"))
            self._freeze_message = (
                f"系统异常（{step} 段失败），游戏已暂停。\n"
                "上一回合的状态已自动保存到 recovery 存档。\n"
                "请使用 /load recovery 恢复，或等待片刻后 /reset 重试。"
            )
            raise TurnFrozenError(self._freeze_message)
        else:
            return result if 'result' in dir() else None
```

- [ ] **Step 4: 实现 execute_parallel() — 并行段（enrich∥TA）包装**

```python
    def execute_parallel(self, steps: list[tuple[str, callable, bool, int]]) -> dict[str, any]:
        """执行多个并行步骤。
        steps: list of (step_name, fn, is_critical, max_retries)
        返回: {step_name: result}

        一个步骤失败不阻止其他步骤执行。所有步骤完成后：
        - 如果任一关键段失败，raise TurnFrozenError
        """
        from concurrent.futures import ThreadPoolExecutor

        results = {}
        errors: dict[str, Exception] = {}
        names = [s[0] for s in steps]

        def _run_one(name, fn, is_crit, retries):
            try:
                return (name, self.execute_step(name, fn, is_critical=is_crit, max_retries=retries), None)
            except TurnFrozenError as e:
                return (name, None, e)
            except Exception as e:
                return (name, None, e)

        with ThreadPoolExecutor(max_workers=len(steps)) as ex:
            futures = [ex.submit(_run_one, s[0], s[1], s[2], s[3]) for s in steps]
            for f in futures:
                name, result, err = f.result()
                results[name] = result
                if err:
                    errors[name] = err

        # 如果任一关键段产生 TurnFrozenError，传播
        for name, err in errors.items():
            if isinstance(err, TurnFrozenError):
                raise err

        return results
```

- [ ] **Step 5: 实现 snapshot() — 合并管线状态+LLM指标**

```python
    def snapshot(self) -> dict:
        import time as _time
        all_records = self._sensor.history if self._sensor else []
        agents = ["Keeper", "Narrator", "Author", "TimeAgent", "IntentDetector"]
        agent_stats = {}
        for name in agents:
            stats = self._sensor.get_stats(name) if self._sensor else None
            if stats:
                agent_stats[name] = {
                    "calls": stats.total_calls,
                    "failures": stats.total_failures,
                    "slow_calls": stats.total_slow_calls,
                    "avg_ms": round(stats.avg_duration_ms, 1),
                    "failure_rate": round(stats.failure_rate, 3),
                    "slow_rate": round(stats.slow_rate, 3),
                }
        return {
            "llm": {
                "total_calls": len(all_records),
                "total_failures": sum(1 for r in all_records if not r.ok) if all_records else 0,
                "total_slow": sum(1 for r in all_records if r.duration_ms > (self._sensor._slow_threshold_ms if self._sensor else 8000)) if all_records else 0,
                "agents": agent_stats,
            },
            "turn": {
                "frozen": bool(self._freeze_message),
                "freeze_message": self._freeze_message,
                "steps": [
                    {"step": s.step, "status": s.status, "retries": s.retries,
                     "duration_ms": round(s.duration_ms, 1), "error": s.error}
                    for s in self._steps
                ],
            },
        }
```

- [ ] **Step 6: 实现 _restore_world() — 从快照恢复 world**

```python
    def _restore_world(self) -> None:
        if not self._last_good_state:
            return
        state = self._last_good_state

        from scenario_core import DirectedGraph
        graph = DirectedGraph.from_dict(state["graph"])
        world_data = state["world"]
        world_data["memory"] = state.get("memory", {})
        restored = self._world.__class__.from_dict(world_data, graph)

        # 恢复 clock
        clock_data = world_data.get("clock")
        if clock_data:
            from game.clock import GameClock
            restored.clock = GameClock.from_dict(clock_data)

        # 恢复 enemies
        enemies_data = world_data.get("enemies")
        if enemies_data and hasattr(restored, 'enemies') and restored.enemies:
            try:
                from game.enemy_manager import EnemyManager
                restored.enemies = EnemyManager.from_dict(enemies_data, restored.enemies.library)
            except Exception:
                pass

        # 恢复 npcs
        npcs_data = world_data.get("npcs")
        if npcs_data:
            try:
                from game.npc_manager import NPCManager
                restored.npcs = NPCManager()
                restored.npcs.from_dict(npcs_data, getattr(restored, '_npc_profiles', {}))
            except Exception:
                pass

        # 恢复 bosses
        bosses_data = world_data.get("bosses")
        if bosses_data and hasattr(restored, 'bosses') and restored.bosses:
            try:
                from game.boss_manager import BossManager
                restored.bosses = BossManager.from_dict(bosses_data, restored.bosses.library)
            except Exception:
                pass

        # 恢复 scene_weapons
        scene_weapons_data = world_data.get("scene_weapons", {})
        from game.side_effects import SceneWeapon
        for sc, weps in scene_weapons_data.items():
            restored.scene_weapons[sc] = [
                SceneWeapon(weapon_ref=w["weapon_ref"], scene=sc, quantity=w.get("quantity", 1))
                for w in weps
            ]

        # 恢复 player
        ps = state.get("player_snapshot")
        if ps is not None:
            from investigator.serialization import from_dict as inv_from_dict
            restored.player = inv_from_dict(ps)

        # 恢复 L1 数据到 keeper
        l1_data = state.get("l1_data", {})
        if l1_data and self._keeper:
            self._keeper.narrator_l1 = l1_data

        # 替换 world 引用（修改原 world 对象的所有属性）
        for attr in list(self._world.__dict__.keys()):
            if hasattr(restored, attr):
                setattr(self._world, attr, getattr(restored, attr))
```

- [ ] **Step 7: Commit**

```bash
git add src/monitor/turn_monitor.py
git commit -m "feat: add TurnMonitor pipeline state machine"
```

---

### Task 3: PipelineHealth 标记 deprecated + /health 命令更新

**Files:**
- Modify: `src/monitor/health.py`
- Modify: `src/game_loop.py:94-108`

- [ ] **Step 1: health.py 改为委托到 TurnMonitor（保持向后兼容）**

```python
"""PipelineHealth — deprecated, logic merged into TurnMonitor.snapshot()."""
from __future__ import annotations
import warnings
from monitor.sensor import LLMSensor


class PipelineHealth:
    def __init__(self, sensor: LLMSensor):
        warnings.warn("PipelineHealth is deprecated. Use TurnMonitor.snapshot() instead.",
                      DeprecationWarning, stacklevel=2)
        self._sensor = sensor

    def snapshot(self) -> dict:
        """返回纯 LLM 指标子集。TurnMonitor 已合并完整功能。"""
        all_records = self._sensor.history
        agents = ["Keeper", "Narrator", "Author", "TimeAgent", "IntentDetector"]
        agent_stats = {}
        for name in agents:
            stats = self._sensor.get_stats(name)
            agent_stats[name] = {
                "calls": stats.total_calls,
                "failures": stats.total_failures,
                "slow_calls": stats.total_slow_calls,
                "avg_ms": round(stats.avg_duration_ms, 1),
                "failure_rate": round(stats.failure_rate, 3),
                "slow_rate": round(stats.slow_rate, 3),
            }
        return {
            "uptime_seconds": 0,
            "total_calls": len(all_records),
            "total_failures": sum(1 for r in all_records if not r.ok),
            "total_slow": sum(1 for r in all_records
                             if r.duration_ms > self._sensor._slow_threshold_ms),
            "agents": agent_stats,
        }
```

- [ ] **Step 2: game_loop.py /health 命令改为优先读 TurnMonitor**

```python
    if cmd == "/health":
        if game and hasattr(game["keeper"], 'turn_monitor') and game["keeper"].turn_monitor:
            snap = game["keeper"].turn_monitor.snapshot()
            llm = snap["llm"]
            turn = snap["turn"]
            lines = ["Pipeline Health:"]
            lines.append(f"  Total calls: {llm['total_calls']} / Failures: {llm['total_failures']} / Slow: {llm['total_slow']}")
            for agent, stats in llm.get("agents", {}).items():
                lines.append(f"  {agent}: {stats['calls']} calls, {stats['failures']} fail, "
                           f"{stats['avg_ms']}ms avg, {stats['slow_rate']:.0%} slow")
            if turn["steps"]:
                lines.append("Turn Steps:")
                for s in turn["steps"]:
                    status_icon = {"ok": "O", "failed": "X", "skipped": "-"}.get(s["status"], "?")
                    lines.append(f"  [{status_icon}] {s['step']} {s['duration_ms']:.0f}ms"
                               + (f" (retry x{s['retries']})" if s['retries'] else ""))
            lines.append(f"Turn Start Status: {'FROZEN' if turn['frozen'] else 'OK'}")
            return {"brief": "\n".join(lines), "narrative": "\n".join(lines), "full": "\n".join(lines)}
        # fallback to old PipelineHealth
        from monitor.health import PipelineHealth
        from llm import get_sensor
        sensor = get_sensor()
        if sensor:
            health = PipelineHealth(sensor)
            snap = health.snapshot()
            lines = ["Pipeline Health (legacy):"]
            lines.append(f"  Uptime: {snap['uptime_seconds']}s")
            lines.append(f"  Total calls: {snap['total_calls']} / Failures: {snap['total_failures']} / Slow: {snap['total_slow']}")
            for agent, stats in snap.get("agents", {}).items():
                lines.append(f"  {agent}: {stats['calls']} calls, {stats['failures']} fail, "
                           f"{stats['avg_ms']}ms avg, {stats['slow_rate']:.0%} slow")
            return {"brief": "\n".join(lines), "narrative": "\n".join(lines), "full": "\n".join(lines)}
        return {"brief": "Monitor not initialized.", "narrative": "监控未初始化", "full": "监控未初始化"}
```

- [ ] **Step 3: Commit**

```bash
git add src/monitor/health.py src/game_loop.py
git commit -m "refactor: deprecate PipelineHealth, /health reads TurnMonitor"
```

---

### Task 4: Keeper 集成 TurnMonitor

**Files:**
- Modify: `src/game/agents/keeper.py:43-71` (__init__ 新增 turn_monitor)
- Modify: `src/game/agents/keeper.py:73-795` (process_turn 各步接入)

- [ ] **Step 1: Keeper.__init__ 新增 turn_monitor 初始化**

在 `self._pending_move = None` 之后追加：

```python
        from monitor.turn_monitor import TurnMonitor
        self.turn_monitor = TurnMonitor(self._sensor, self.world, keeper=self)
```

- [ ] **Step 2: process_turn() 开头添加 begin_turn 和 TurnFrozenError catch**

在 `self._pending_move = None` 之后（L122），所有步骤之前：

```python
        try:
            self.turn_monitor.begin_turn()
        except Exception:
            pass  # begin_turn should never fail, but guard

        # 后续所有步骤用 try/except TurnFrozenError 包裹顶层处理
```

在 `process_turn()` 整个函数体外层包裹 try/except。实际做法是在函数末尾 return 之前，将所有步骤逻辑放入 try 块。由于函数体已有一个大的 if/else 分支序列，最简单的方式是用一个顶层 try/except TurnFrozenError 包裹从 Step 0 到 return 的全部逻辑，在 except 块中返回 frozen 响应。

在 `process_turn()` 方法签名之后、`raw = turn_input.raw_text` 之前插入 try：

```python
    def process_turn(self, turn_input: TurnInput, author: Any = None, _depth: int = 0) -> dict:
        """Execute full turn: parse -> judge -> enrich -> curate."""
        try:
            # ... 所有现有逻辑（从 raw = turn_input.raw_text 到最后的 return）
        except TurnFrozenError as e:
            return {
                "brief": "",
                "narrative": "",
                "narrative_html": "",
                "combat": None,
                "skill_results": [],
                "game_frozen": True,
                "frozen_message": str(e),
                "game_over": False,
                "ending": None,
                "timestamp": "",
                "player_snapshot": None,
            }
```

注意：需在文件顶部 import TurnFrozenError：

```python
from monitor.turn_monitor import TurnFrozenError
```

- [ ] **Step 3: 用 execute_step 包装 parse 步骤**

将 `_parse()` 调用（L140）改为：

```python
        parse_result = self.turn_monitor.execute_step(
            "parse",
            lambda: self._parse(raw),
            is_critical=True,
        )
```

同时移除 `_parse()` 内部已有的 try/except（L1057-1059），因为 TurnMonitor 已处理重试。但保留原来返回 fallback 的逻辑——改为在 `_parse()` 自身抛异常，让 TurnMonitor 处理。

**不修改 `_parse()` 内部**。`_parse()` 已有自己的 try/except 返回 fallback（L1057-1059），这意味着 `_parse()` 本身不会抛异常。要让 TurnMonitor 的重试生效，需让 `_parse()` 内部的 `except Exception` 在重试耗尽时 re-raise。简单方案：不在 `_parse()` 内部做重试，让 TurnMonitor 统一管理。

将 `_parse()` 的 L1057-1059 改为：

```python
        except Exception as e:
            raise  # let TurnMonitor handle retries
```

- [ ] **Step 4: 用 execute_parallel 包装 enrich∥time_agent 并行段**

将 L563-601 的并行 enrich 段改为：

```python
        parallel_results = self.turn_monitor.execute_parallel([
            ("enrich", lambda: self._enrich(enrich_input.entities, raw) if enrich_input.entities else {"results": {}, "reasoning": "", "emphasis_hint": ""},
             False, 2),
            ("time_agent", lambda: self._run_time_agent(enrich_input.actions, raw) if enrich_input.actions else {"time_delta": 0, "narrative_hint": ""},
             False, 2),
        ])
        enrichment = parallel_results.get("enrich")
        ta_result = parallel_results.get("time_agent")
```

然后移除原有的 ThreadPoolExecutor 创建 / enrich_future / ta_future / executor.shutdown 代码（L568-601）。将结果收集逻辑简化为直接使用 `enrichment` 和 `ta_result`。

- [ ] **Step 5: 用 execute_step 包装 intent_detect 收集**

将 L673-680 的 detect_future 收集改为：

```python
        if detect_future:
            try:
                intent_result = self.turn_monitor.execute_step(
                    "intent_detect",
                    lambda: detect_future.result(),
                    is_critical=False,
                )
            except TurnFrozenError:
                pass  # non-critical — handled by execute_step internally (won't raise)
            except Exception:
                intent_result = None
                self._warnings.append("意图检测失败，流程无中断。")
            finally:
                if executor:
                    executor.shutdown(wait=False)
```

- [ ] **Step 6: 用 execute_step 包装 curate**

将 L766-767 的 curate 调用改为：

```python
        brief = self.turn_monitor.execute_step(
            "curate",
            lambda: self.curator.assemble(all_outcomes, ambient, emphasis),
            is_critical=True,
        )
```

- [ ] **Step 7: 在 game_loop.py 的 run_turn() 中处理 game_frozen 信号**

在 `run_turn()` 中，`result = keeper.process_turn(...)` 之后添加 frozen 检查，透传 frozen 信号：

```python
    # 在 result = keeper.process_turn(turn_input, author=author) 之后
    if result.get("game_frozen"):
        return result  # 直接透传 frozen，不执行后续 narrator/combat 逻辑
```

- [ ] **Step 8: Commit**

```bash
git add src/game/agents/keeper.py src/game_loop.py
git commit -m "feat: integrate TurnMonitor into Keeper.process_turn()"
```

---

### Task 5: 实现 save_game / load_game + 自动存档

**Files:**
- Modify: `src/game_loop.py`

- [ ] **Step 1: 在 game_loop.py 实现 save_game() 和 load_game()**

在 `init_game()` 之后插入：

```python
# ── Save / Load ──

def save_game(game: dict, path: str) -> None:
    """存档：全量快照 world + graph + keeper turn_number。"""
    import os
    world = game["keeper"].world
    keeper = game["keeper"]
    author = game.get("author")
    narrator = game.get("narrator")

    world.save_state(path)
    # 补充元信息
    with open(path, "r", encoding="utf-8") as f:
        import json as _json
        data = _json.load(f)
    data["_meta"] = {
        "turn_number": keeper.turn_number,
        "l3_checksum": str(hash(str(author.l3_data))) if author and hasattr(author, 'l3_data') else "",
    }
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(data, f, ensure_ascii=False, indent=2)


def load_game(game: dict, path: str) -> None:
    """读档：恢复 world + 重建 Keeper/Narrator 引用。"""
    from investigator.serialization import to_dict as inv_to_dict
    import json as _json, os

    world = game["keeper"].world
    author = game.get("author")
    narrator = game.get("narrator")

    restored = world.__class__.load_state(path)

    with open(path, "r", encoding="utf-8") as f:
        data = _json.load(f)
    meta = data.get("_meta", {})

    # 替换 world 对象内容
    for attr in list(world.__dict__.keys()):
        if hasattr(restored, attr):
            setattr(world, attr, getattr(restored, attr))

    game["keeper"].turn_number = meta.get("turn_number", 0)

    # 重建 narrator 引用 l1_data
    if narrator and hasattr(narrator, 'l1_data'):
        # l1_data 不变（从 init_game 加载）
        pass
```

- [ ] **Step 2: 实现 autosave 标志位和后台线程**

在 `game_loop.py` 中继续插入：

```python
# ── Autosave ──

import threading
from config import AUTOSAVE_ENABLED, AUTOSAVE_INTERVAL_SEC, AUTOSAVE_MAX_COPIES, AUTOSAVE_DIR

_autosave_flag: bool = False
_autosave_timer: threading.Timer | None = None
_autosave_counter: int = 0
_autosave_game_ref: dict | None = None  # weak ref to game instance


def _autosave_callback():
    """Timer callback: set flag and reschedule."""
    global _autosave_flag, _autosave_timer
    _autosave_flag = True
    if AUTOSAVE_ENABLED:
        _autosave_timer = threading.Timer(AUTOSAVE_INTERVAL_SEC, _autosave_callback)
        _autosave_timer.daemon = True
        _autosave_timer.start()


def start_autosave(game: dict) -> None:
    """启动自动存档后台定时器。"""
    global _autosave_game_ref, _autosave_timer
    _autosave_game_ref = game
    if not AUTOSAVE_ENABLED:
        return
    if _autosave_timer:
        _autosave_timer.cancel()
    _autosave_timer = threading.Timer(AUTOSAVE_INTERVAL_SEC, _autosave_callback)
    _autosave_timer.daemon = True
    _autosave_timer.start()


def _check_autosave(game: dict) -> None:
    """如果 autosave flag 为 True，执行滚动存档并清除 flag。"""
    global _autosave_flag, _autosave_counter
    if not _autosave_flag:
        return
    _autosave_flag = False
    import os
    save_dir = os.path.join(AUTOSAVE_DIR)
    os.makedirs(save_dir, exist_ok=True)

    _autosave_counter = (_autosave_counter % AUTOSAVE_MAX_COPIES) + 1
    path = os.path.join(save_dir, f"autosave_{_autosave_counter}.json")
    try:
        save_game(game, path)
    except Exception:
        pass  # autosave is best-effort
```

- [ ] **Step 3: 在 run_turn() 开头添加 autosave flag 检查**

在 `run_turn()` 的开头（`keeper = game["keeper"]` 之后）插入：

```python
    from game_loop import _check_autosave as _auto
    _auto(game)
```

- [ ] **Step 4: Commit**

```bash
git add src/game_loop.py
git commit -m "feat: implement save_game/load_game and autosave timer"
```

---

### Task 6: 前端路由修复 — /save /load 实际可用 + freeze 响应 + autosave 启动

**Files:**
- Modify: `frontend/routers/game.py`

- [ ] **Step 1: 修复 /save /load 命令的 import**

`_handle_slash_command()` 中的 `/save` 和 `/load` 分支（L208-227 和 L590-607）引用 `from game_loop import save_game, load_game`。这两个函数现在真实存在了，无需修改 import 语句本身。但需确保两处引用一致。

在 `_handle_slash_command()` 的 `/save` 和 `/load` 中，两处都已有 `from game_loop import save_game` / `from game_loop import load_game`，现在函数已实现，直接可用。无需修改。

- [ ] **Step 2: process_turn() 检查 autosave flag**

在 `process_turn()` 的 `stripped = user_input.strip()` 之后、slash command 路由之前插入：

```python
    from game_loop import _check_autosave as _auto, _autosave_game_ref
    g = get_game()
    if g:
        _auto(g)
```

注意：需要同时声明 `_autosave_game_ref` 为 global（或通过函数访问）。

更好的做法：在 `frontend/routers/game.py` 中直接调用：

```python
    import game_loop
    g = get_game()
    if g:
        game_loop._check_autosave(g)
```

- [ ] **Step 3: 处理 game_frozen 响应**

在 `process_turn()` 的 `turn` 结果获取后（L291 之后），添加 frozen 检查：

```python
    if turn and turn.get("game_frozen"):
        return {
            "brief": "",
            "narrative": "",
            "narrative_html": (
                f'<div class="msg-frozen px-4 py-3 text-red-400 border-2 border-red-600 '
                f'bg-[#1a0a0a] rounded">{turn.get("frozen_message", "系统异常")}</div>'
            ),
            "combat": None,
            "skill_results": [],
            "game_frozen": True,
            "frozen_message": turn.get("frozen_message", ""),
            "game_over": False,
            "ending": None,
            "timestamp": "",
            "player_snapshot": None,
        }
```

- [ ] **Step 4: init_game_api 中启动 autosave**

在 `init_game_api()` 的 `_game_instance = g` 之后（L737）追加：

```python
    from game_loop import start_autosave
    start_autosave(g)
```

- [ ] **Step 5: Commit**

```bash
git add frontend/routers/game.py
git commit -m "fix: wire /save/load to real functions, add autosave startup and freeze handling"
```

---

### Task 7: 前端 freeze 覆盖层

**Files:**
- Modify: `frontend/templates/game.html`

- [ ] **Step 1: 读取 game.html 中 sendTurn() 附近的 JS 代码位置**

（执行时由 agent 读取确认）

- [ ] **Step 2: 在 sendTurn() 的 fetch 响应处理中添加 frozen 检测**

在 `.then(data => { ... })` 回调开头插入：

```javascript
if (data.game_frozen) {
    // 显示冻结覆盖层
    const overlay = document.getElementById('freeze-overlay');
    const msg = document.getElementById('freeze-message');
    if (overlay && msg) {
        msg.textContent = data.frozen_message || '系统异常，游戏已暂停。';
        overlay.classList.remove('hidden');
    }
    // 禁用输入框
    const input = document.getElementById('player-input');
    if (input) input.disabled = true;
    const sendBtn = document.getElementById('send-btn');
    if (sendBtn) sendBtn.disabled = true;
    return;
}
```

- [ ] **Step 3: 在 game.html 底部（`<div id="chatMessages">` 之后）添加 freeze 覆盖层 DOM**

```html
<div id="freeze-overlay" class="hidden fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
    <div class="bg-[#1a1410] border-2 border-red-600 rounded-lg p-6 max-w-lg mx-4 text-center">
        <div class="text-red-400 text-lg font-bold mb-3">&#9888; 游戏已暂停</div>
        <div id="freeze-message" class="text-gray-400 text-sm leading-relaxed"></div>
        <div class="mt-4 flex gap-3 justify-center">
            <button onclick="location.href='/'" class="px-4 py-1.5 text-xs border border-gray-600 rounded text-gray-400 hover:bg-gray-800">
                返回启动页
            </button>
        </div>
    </div>
</div>
```

- [ ] **Step 4: Commit**

```bash
git add frontend/templates/game.html
git commit -m "feat: add freeze overlay for game_frozen state"
```

---

### Task 8: 测试 — TurnMonitor 单元测试

**Files:**
- Create: `tests/test_turn_monitor.py`

- [ ] **Step 1: 创建测试文件**

```python
"""TurnMonitor 单元测试 — 无需 LLM 调用。"""
import pytest
from unittest.mock import MagicMock, patch
from monitor.turn_monitor import TurnMonitor, StepResult, TurnFrozenError


class TestStepResult:
    def test_step_result_defaults(self):
        sr = StepResult(step="test")
        assert sr.step == "test"
        assert sr.status == "pending"
        assert sr.retries == 0
        assert sr.duration_ms == 0.0
        assert sr.error == ""


class TestTurnMonitorExecuteStep:
    def test_successful_step(self):
        sensor = MagicMock()
        world = MagicMock()
        world.to_dict.return_value = {"current_location": "test"}
        tm = TurnMonitor(sensor, world)

        result = tm.execute_step("parse", lambda: "parsed_result")

        assert result == "parsed_result"
        assert len(tm._steps) == 1
        assert tm._steps[0].step == "parse"
        assert tm._steps[0].status == "ok"

    def test_retry_then_success(self):
        sensor = MagicMock()
        world = MagicMock()
        world.to_dict.return_value = {"current_location": "test"}
        tm = TurnMonitor(sensor, world)

        call_count = [0]

        def flaky_fn():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("transient error")
            return "finally ok"

        result = tm.execute_step("parse", flaky_fn, max_retries=2)

        assert result == "finally ok"
        assert tm._steps[0].retries == 2

    def test_critical_step_exhausts_retries_raises_frozen(self):
        sensor = MagicMock()
        world = MagicMock()
        world.to_dict.return_value = {"current_location": "test"}
        world.save_state = MagicMock()

        def always_fail():
            raise RuntimeError("permanent error")

        tm = TurnMonitor(sensor, world)
        tm.begin_turn()

        with pytest.raises(TurnFrozenError):
            tm.execute_step("parse", always_fail, is_critical=True, max_retries=2)

        assert tm._steps[0].status == "failed"
        assert tm._steps[0].retries == 2
        world.save_state.assert_called_once()

    def test_non_critical_step_returns_none_on_failure(self):
        sensor = MagicMock()
        world = MagicMock()
        tm = TurnMonitor(sensor, world)

        def always_fail():
            raise RuntimeError("non-critical error")

        result = tm.execute_step("enrich", always_fail, is_critical=False, max_retries=2)

        assert result is None
        assert tm._steps[0].status == "failed"


class TestTurnMonitorSnapshot:
    def test_snapshot_structure(self):
        sensor = MagicMock()
        sensor.history = []
        sensor.get_stats.return_value = MagicMock(
            total_calls=10, total_failures=1, total_slow_calls=2,
            avg_duration_ms=1500.0, failure_rate=0.1, slow_rate=0.2,
        )
        sensor._slow_threshold_ms = 8000
        world = MagicMock()
        tm = TurnMonitor(sensor, world)

        snap = tm.snapshot()

        assert "llm" in snap
        assert "turn" in snap
        assert "steps" in snap["turn"]
        assert not snap["turn"]["frozen"]

    def test_snapshot_after_freeze(self):
        sensor = MagicMock()
        sensor.history = []
        sensor.get_stats.return_value = MagicMock(
            total_calls=0, total_failures=0, total_slow_calls=0,
            avg_duration_ms=0.0, failure_rate=0.0, slow_rate=0.0,
        )
        sensor._slow_threshold_ms = 8000
        world = MagicMock()
        world.to_dict.return_value = {}
        world.save_state = MagicMock()
        world.graph = MagicMock()
        world.graph.to_dict.return_value = {"nodes": {}}
        world.memory = MagicMock()
        world.memory.to_dict.return_value = {}
        world.player = None

        tm = TurnMonitor(sensor, world)
        tm.begin_turn()

        def fail():
            raise RuntimeError("bang")

        try:
            tm.execute_step("parse", fail, is_critical=True, max_retries=0)
        except TurnFrozenError:
            pass

        snap = tm.snapshot()
        assert snap["turn"]["frozen"] is True
        assert len(snap["turn"]["freeze_message"]) > 0
```

- [ ] **Step 2: 运行测试，确认全部通过**

```bash
python -m pytest tests/test_turn_monitor.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_turn_monitor.py
git commit -m "test: add TurnMonitor unit tests"
```

---

### Task 9: 端到端验证

- [ ] **Step 1: 运行 mock harness 确保无回归**

```bash
python tests/test_harness_parallel.py --mock --cases search,at_test,npc_test,weapons
```

- [ ] **Step 2: 验证 /health 命令输出**

手动或通过 llm_player 确认 `/health` 命令返回 TurnMonitor snapshot 格式。

---

## 自审清单

1. **Spec 覆盖**
   - TurnMonitor 类 + StepResult: Task 2 ✓
   - 关键段/非关键段分类: Task 2 (execute_step is_critical 参数) ✓
   - 并行段包装 (enrich∥TA): Task 2 (execute_parallel) + Task 4 Step 4 ✓
   - Freeze 回退+存档: Task 2 (_restore_world) ✓
   - PipelineHealth 合并: Task 3 ✓
   - /health 命令更新: Task 3 Step 2 ✓
   - 自动存档标志位: Task 5 Step 2-3 ✓
   - 存档文件滚动: Task 5 Step 2 (_check_autosave) ✓
   - save_game/load_game 修复: Task 5 Step 1 ✓
   - 前端 freeze 覆盖层: Task 7 ✓
   - 配置项: Task 1 ✓

2. **无占位符**: 每步都有实际代码 ✓

3. **类型一致性**: StepResult / TurnMonitor / TurnFrozenError 在 Task 2 定义，Task 4/5/6/7 引用一致 ✓
