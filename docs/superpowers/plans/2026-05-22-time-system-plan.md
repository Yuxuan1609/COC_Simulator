# Time System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace abstract TU with real minute-based clock, add TimeAgent/Author split for time pressure via comms packets, inject time context into prompts.

**Architecture:** `ScenarioWorld` holds `game_time` (minutes) as sole time source, auto-derives day/hour/time_of_day/time_flags. `TimeAgent` (LLM sub-agent) handles narrative time guidance. `Author` manages `time_pressure` via comms packets from Keeper. Keeper orchestrates scheduling.

**Tech Stack:** Python dataclasses, deepseek-v4-flash, COC 7th rules

---

### Task 1: time_costs.json reference library

**Files:**
- Create: `data/library/core/time_costs.json`

- [ ] **Step 1: Create time_costs.json**

```json
{
  "search": {
    "guideline": "快速扫视约1-3分钟；搜查标准房间约5-15分钟；搜索开放空间或大厅约10-30分钟；彻底翻查每个角落约15-45分钟。以房间大小和仔细程度为参考变量。",
    "override": {}
  },
  "move": {
    "guideline": "同场景内移动约1-3分钟；移动到相邻车厢/房间约2-5分钟；长距离或复杂路径约5-15分钟。以路径障碍程度为参考变量。",
    "override": {}
  },
  "dialogue": {
    "guideline": "简短对话约1-5分钟；深入交谈约5-15分钟。以话题深度和信息交换量为参考变量。",
    "override": {}
  },
  "combat_round": {
    "guideline": "每轮战斗约6-12秒。以参与者数量和动作复杂度为参考变量。",
    "override": {}
  },
  "other": {
    "guideline": "纯叙事或无明确时间消耗的行为约1-5分钟。以玩家描述的具体程度为参考变量。",
    "override": {}
  }
}
```

- [ ] **Step 2: Verify valid JSON**

Run: `python -c "import json; json.load(open('data/library/core/time_costs.json', encoding='utf-8')); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add data/library/core/time_costs.json
git commit -m "data: add time_costs.json — semi-structured time reference for entity actions"
```

---

### Task 2: ScenarioWorld clock

**Files:**
- Modify: `src/scenario_core.py`

- [ ] **Step 1: Add clock fields to ScenarioWorld.__init__**

After the `weapon_library` init block, add:

```python
        # Time system — minute clock
        self.game_time: int = 0
        self._last_comms_time: int = 0
        self.comms_interval: int = 15  # default, overridden by module_meta
        self.time_context: str = ""    # TimeAgent narrative hint for prompt injection
```

- [ ] **Step 2: Add clock properties**

```python
    @property
    def day(self) -> int:
        return self.game_time // 1440

    @property
    def hour(self) -> int:
        return (self.game_time % 1440) // 60

    @property
    def time_of_day(self) -> str:
        h = self.hour
        if h < 5:   return "夜间"
        if h < 8:   return "早晨"
        if h < 17:  return "白天"
        return "黄昏"

    def get_time_flags(self) -> dict:
        return {
            f"day:{self.day}": True,
            f"time:{self.time_of_day}": True,
        }
```

- [ ] **Step 3: Add advance_time method**

```python
    def advance_time(self, delta_minutes: int):
        """Advance the clock by N minutes."""
        self.game_time += delta_minutes
        # Auto-inject time flags into runtime_state
        for flag, value in self.get_time_flags().items():
            state = self.get_runtime_state(flag)
            state.completed = value
```

- [ ] **Step 4: Verify**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -c "
from scenario_core import DirectedGraph, ScenarioWorld
w = ScenarioWorld(DirectedGraph(scenes={}, events=[]), 'test')
print(f'day={w.day}, hour={w.hour}, tod={w.time_of_day}')
assert w.day == 0 and w.hour == 0
w.advance_time(300)
print(f'after 300min: day={w.day}, hour={w.hour}, tod={w.time_of_day}')
assert w.day == 0 and w.hour == 5 and w.time_of_day == '早晨'
w.advance_time(1440)
print(f'after +1440min: day={w.day}, tod={w.time_of_day}')
assert w.day == 1
print('ok')
"
```
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add src/scenario_core.py
git commit -m "feat: add ScenarioWorld minute clock — game_time, day/hour/time_of_day, advance_time, time_flags"
```

---

### Task 3: TimeCommsPacket dataclass

**Files:**
- Modify: `src/game/messages.py`

- [ ] **Step 1: Add TimeCommsPacket**

```python
@dataclass
class TimeCommsPacket:
    """Keeper -> Author: time pressure communication packet."""
    game_time: int = 0
    day: int = 0
    time_of_day: str = ""
    current_scene: str = ""
    player_actions: str = ""   # recent actions summary (≤200 chars)
    world_state: str = ""      # world state overview (≤200 chars)
```

Total packet ≤500 chars.

- [ ] **Step 2: Verify import**

Run: `cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -c "from game.messages import TimeCommsPacket; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/game/messages.py
git commit -m "feat: add TimeCommsPacket dataclass — Keeper->Author time pressure communication"
```

---

### Task 4: TimeAgent class

**Files:**
- Create: `src/game/agents/time_agent.py`
- Test: `tests/test_time_agent.py`

- [ ] **Step 1: Create TimeAgent**

```python
"""TimeAgent — LLM sub-agent for time narrative guidance."""
from __future__ import annotations
import json
from llm import call_deepseek


class TimeAgent:
    """LLM sub-agent: narrative time guidance. Not a counter."""

    def build_prompt(
        self,
        game_time: int,
        day: int,
        time_of_day: str,
        hour: int,
        recent_actions: str,
        current_scene: str,
        scene_description: str,
        time_costs_guideline: str,
    ) -> str:
        return f"""你是 TRPG 时间叙事引导者。基于当前游戏状态，评估时间推进的节奏和叙事影响。

当前时间：累计{game_time}分钟 (第{day}天 {time_of_day} {hour}时)
玩家最近行动：{recent_actions}
当前场景：{current_scene}
场景描述：{scene_description}
时间消耗参考：{time_costs_guideline}

评估要点：
- 玩家刚刚的动作消耗了多少时间？节奏需要加速还是减速？
- 时间变化是否影响场景氛围或实体可见性？
- 是否有需要 day/time_of_day 变更的重大时间跳跃？

返回 JSON：
{{"time_delta": 0, "narrative_hint": "时间相关的叙事提示（可为空）", "signal_hint": ""}}

time_delta 是额外推进的分钟数（如"睡觉"跳8小时），默认 0。narrative_hint 具体而非泛泛。signal_hint 仅在时间压力相关信号出现时填写。"""

    def assess(self, **kwargs) -> dict:
        prompt = self.build_prompt(**kwargs)
        try:
            response = call_deepseek(
                prompt,
                json_mode=True,
                model="deepseek-v4-flash",
                system="你是 COC 7th KP 时间叙事引导者。",
                max_tokens=300,
                fallback_schema={"time_delta": 0, "narrative_hint": "", "signal_hint": ""},
            )
            return json.loads(response) if isinstance(response, str) else response
        except Exception:
            return {"time_delta": 0, "narrative_hint": "", "signal_hint": ""}
```

- [ ] **Step 2: Verify import**

Run: `cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -c "from game.agents.time_agent import TimeAgent; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/game/agents/time_agent.py
git commit -m "feat: add TimeAgent class — LLM sub-agent for narrative time guidance"
```

---

### Task 5: Author time_pressure + assess_time_pressure

**Files:**
- Modify: `src/game/agents/author.py`

- [ ] **Step 1: Add time_pressure to Author**

In `Author.__init__`, add after existing initialization:

```python
        self.time_pressure = self.l3_data.get("time_pressure")
        self._next_comms_trigger: int = 0
```

- [ ] **Step 2: Add assess_time_pressure method**

```python
    def assess_time_pressure(self, comms_packet) -> dict:
        """Receive comms packet from Keeper, judge if time pressure needs action.
        Returns {"should_press": bool, "urgency_update": int|None}."""

        tp = self.time_pressure
        if not tp:
            return {"should_press": False, "urgency_update": None}

        from prompts import build_time_pressure_assess_prompt
        from llm import call_deepseek
        import json as _json

        prompt = build_time_pressure_assess_prompt(
            guide=tp.get("guide", ""),
            urgency=tp.get("urgency", 0),
            urgency_max=tp.get("urgency_max", 10),
            key_signals=tp.get("key_signals", []),
            game_time=comms_packet.game_time,
            day=comms_packet.day,
            time_of_day=comms_packet.time_of_day,
            current_scene=comms_packet.current_scene,
            player_actions=comms_packet.player_actions,
            world_state=comms_packet.world_state,
        )
        try:
            response = call_deepseek(
                prompt, json_mode=True, model="deepseek-v4-flash",
                system="你是 COC 7th 模组的时间压力管理者。",
                fallback_schema={"should_press": False, "urgency_update": None, "reason": ""},
            )
            result = _json.loads(response) if isinstance(response, str) else response
            if result.get("urgency_update") is not None:
                tp["urgency"] = min(result["urgency_update"], tp.get("urgency_max", 10))
            return result
        except Exception:
            return {"should_press": False, "urgency_update": None}
```

- [ ] **Step 3: Add build_time_pressure_assess_prompt to prompts.py**

In `src/prompts.py`, add:

```python
def build_time_pressure_assess_prompt(
    guide: str,
    urgency: int,
    urgency_max: int,
    key_signals: list,
    game_time: int,
    day: int,
    time_of_day: str,
    current_scene: str,
    player_actions: str,
    world_state: str,
) -> str:
    signals = "\n".join(f"- {s}" for s in key_signals)
    return f"""你是 COC 7th 模组的时间压力管理者。根据模组预设的时间压力指南和当前游戏状态，判断是否需要介入催促玩家。

【时间压力指南】
{guide}

当前 urgency：{urgency}/{urgency_max}

可选信号：
{signals}

【当前状态】
累计时间：{game_time}分钟 (第{day}天 {time_of_day})
当前场景：{current_scene}
玩家最近行动：{player_actions}
世界状态：{world_state}

判断是否需要介入。返回 JSON：
{{"should_press": true/false, "urgency_update": 新的urgency值(0-{urgency_max})或null, "reason": "简要理由", "signal": "选用的信号文本（should_press=true时填写）"}}

规则：
- 玩家推进正常、无异常停留 → should_press=false
- 玩家反复搜索同一区域、长时间无进展、或 guide 中明确的时间节点被跨越 → should_press=true
- urgency_update 根据 guide 中的描述弹性调整，不机械"""
```

- [ ] **Step 4: Verify import**

Run: `cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -c "from game.agents.author import Author; print('ok')"`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add src/game/agents/author.py src/prompts.py
git commit -m "feat: add Author time_pressure management + assess_time_pressure + prompt"
```

---

### Task 6: Keeper integration

**Files:**
- Modify: `src/game/agents/keeper.py`

- [ ] **Step 1: Add time advancement after entity execution**

After `self._apply_side_effects(outcome.side_effects)` (line 102), add time advancement. Before the `judged_entities.append` block:

In the `entry_type in ("auto_trigger", "interaction", "event")` branch, after `outcome = self.judge._execute_entity(...)`:

```python
                # Time advancement
                if outcome.success:
                    time_delta = self._resolve_time_delta(entity, raw)
                    self.world.advance_time(time_delta)
```

Also for move and search — add time advancement after their respective `result = self.world.move(target)` and successful search.

- [ ] **Step 2: Add _resolve_time_delta helper**

```python
    def _resolve_time_delta(self, entity, user_input: str) -> int:
        """Resolve time delta based on entity extra.time_range and user input."""
        # Use entity override if present
        if entity.extra and entity.extra.get("time_range"):
            tr = entity.extra["time_range"]
            # Take midpoint unless user description suggests otherwise
            return (tr.get("min", 3) + tr.get("max", 10)) // 2

        # Use time_costs guideline for the entity type
        category = self._infer_time_category(entity)
        defaults = {"search": 10, "move": 3, "dialogue": 5, "combat_round": 0.1, "other": 3}
        return defaults.get(category, 5)

    def _infer_time_category(self, entity) -> str:
        if entity.entity_type in ("auto_trigger", "event"):
            return "other"
        if entity.type in ("侦查", "聆听", "图书馆使用", "搜索"):
            return "search"
        return "other"
```

- [ ] **Step 3: Add TimeAgent trigger after enrich**

After the enrich block and combat entry detection, add TimeAgent trigger:

```python
        # TimeAgent trigger
        time_agent_narrative = ""
        if self._should_trigger_time_agent():
            from game.agents.time_agent import TimeAgent
            ta = TimeAgent()
            recent = self.world.memory.raw_history[-3:] if self.world.memory.raw_history else []
            recent_summary = "; ".join(
                r.get("user_input", "")[:80] for r in recent
            )
            result = ta.assess(
                game_time=self.world.game_time,
                day=self.world.day,
                time_of_day=self.world.time_of_day,
                hour=self.world.hour,
                recent_actions=recent_summary,
                current_scene=self.world.current_location,
                scene_description=self.world.get_current_description(),
                time_costs_guideline=self._load_time_costs_text(),
            )
            if result.get("time_delta", 0) > 0:
                self.world.advance_time(result["time_delta"])
            time_agent_narrative = (result.get("narrative_hint", "") or "") + \
                                    (f" {result.get('signal_hint', '')}" if result.get("signal_hint") else "")
            if time_agent_narrative.strip():
                self.world.time_context = time_agent_narrative

    def _should_trigger_time_agent(self) -> bool:
        if not hasattr(self, '_last_time_agent_call'):
            self._last_time_agent_call = -1
        if self._last_time_agent_call < 0:
            self._last_time_agent_call = self.world.game_time
            return True
        # Trigger if >30min since last call
        if self.world.game_time - self._last_time_agent_call >= 30:
            self._last_time_agent_call = self.world.game_time
            return True
        return False
```

- [ ] **Step 4: Add comms packet dispatch**

After TimeAgent, add comms dispatch:

```python
        # TimePressure comms — at most 1 per turn, interval-based
        tp = author.time_pressure if author else None
        if tp and self.world.game_time - self.world._last_comms_time >= self.world.comms_interval:
            self.world._last_comms_time = self.world.game_time
            recent = self.world.memory.raw_history[-5:] if self.world.memory.raw_history else []
            packet = TimeCommsPacket(
                game_time=self.world.game_time,
                day=self.world.day,
                time_of_day=self.world.time_of_day,
                current_scene=self.world.current_location,
                player_actions="; ".join(r.get("user_input", "")[:60] for r in recent[-3:]),
                world_state=f"场景:{self.world.current_location}, NPC:{list(self.world.npc_states.keys())[:3]}",
            )
            tp_result = author.assess_time_pressure(packet)
            if tp_result.get("should_press") and tp_result.get("signal"):
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="time_pressure"),
                    success=True,
                    message=f"【时间压力】{tp_result.get('signal', '')}",
                    entity_id="TIME_PRESS",
                    entity_type="time_pressure",
                ))
```

- [ ] **Step 5: Verify import**

Run: `cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -c "from game.agents.keeper import Keeper; print('ok')"`
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add src/game/agents/keeper.py
git commit -m "feat: Keeper time integration — advance_time + TimeAgent trigger + comms dispatch"
```

---

### Task 7: Prompt time context injection

**Files:**
- Modify: `src/prompts.py`

- [ ] **Step 1: Add time context to enrich and narrator prompts**

In `build_keeper_enrich_prompt`, add after the scene context:

```python
    # Time context
    if world.time_context:
        time_block = f"\n【时间感知】当前时间：第{world.day}天 {world.time_of_day}（累计{world.game_time}分钟）\n{world.time_context}\n"
    else:
        time_block = ""
```

Inject `time_block` at the end of each prompt. Do the same for `build_narrator_prompt`.

- [ ] **Step 2: Verify**

Run: `cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -c "from prompts import build_keeper_enrich_prompt; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add src/prompts.py
git commit -m "feat: inject time context (day/time_of_day/narrative_hint) into enrich and narrator prompts"
```

---

### Task 8: Pipeline — Phase 2 time_of_day standardization + Step 1a/1b estimated_duration

**Files:**
- Modify: `src/module_designer/layered_parser.py`

- [ ] **Step 1: Add 标准时段名称 to Phase 2 prompt**

In `build_step4_prompt`, after the `## 标准场景名称列表` block, add:

```python
    time_periods = "凌晨、早晨、白天、黄昏、夜间"
    # ...
    return f"""...
## 标准场景名称列表（@标记中的 scene 必须使用下表中的名称）
{scene_names}

## 标准时段名称（time_of_day 必须使用下表中的名称）
{time_periods}

## 标准技能列表...
"""
```

- [ ] **Step 2: Add estimated_duration to Step 1a/1b output**

In the parse prompt for Step 1a, add a requirement to estimate total module duration:

```
14. 估算模组剧情的预计总耗时（分钟），考虑所有可能的探索路径和对话。写入 module_meta.estimated_duration。
15. 推荐通信间隔（分钟）写入 module_meta.comms_interval（短模组≤2h: 6-8min, 中型2-6h: 10-15min, 长型6-24h: 15-20min, 超长≥24h: 60-120min）。
```

- [ ] **Step 3: Verify existing pipeline tests**

Run: `cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -m pytest tests/test_module_designer.py -v --tb=short -k "prompt" 2>&1 | tail -10`

- [ ] **Step 4: Commit**

```bash
git add src/module_designer/layered_parser.py
git commit -m "feat: pipeline Phase 2 add time_of_day standard names; Step 1a/1b add estimated_duration + comms_interval"
```

---

### Task 9: L3 time_pressure schema

**Files:**
- Modify: `src/module_designer/l3_designer.py`
- Modify: `src/module_designer/layered_schema.py`

- [ ] **Step 1: Add time_pressure to L3Designer**

In `l3_designer.py`, add:

```python
@dataclass
class TimePressureConfig:
    name: str = ""
    guide: str = ""
    urgency: int = 0
    urgency_max: int = 10
    key_signals: list = field(default_factory=list)

    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, data: dict) -> "TimePressureConfig": ...
```

Add `time_pressure: TimePressureConfig | None = None` to the main L3 dataclass.

- [ ] **Step 2: Update Schema**

In `layered_schema.py`, add time_pressure to the L3 validation schema.

- [ ] **Step 3: Verify**

Run: `cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -c "from module_designer.l3_designer import TimePressureConfig; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add src/module_designer/l3_designer.py src/module_designer/layered_schema.py
git commit -m "feat: add TimePressureConfig to L3 schema — guide, urgency, key_signals"
```

---

### Task 10: Game loop time_costs loading

**Files:**
- Modify: `src/game_loop.py`

- [ ] **Step 1: Load time_costs in init_game**

After WeaponLibrary loading, add:

```python
    # Load time costs
    import json, os
    time_costs_path = os.path.join("data", "library", "core", "time_costs.json")
    time_costs = {}
    if os.path.exists(time_costs_path):
        with open(time_costs_path, "r", encoding="utf-8") as f:
            time_costs = json.load(f)
    world.time_costs = time_costs
```

- [ ] **Step 2: Load comms_interval from module_meta**

```python
    module_meta = l2.get("module_meta", {})
    if module_meta.get("comms_interval"):
        world.comms_interval = module_meta["comms_interval"]
```

- [ ] **Step 3: Verify import**

Run: `cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -c "from game_loop import init_game; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add src/game_loop.py
git commit -m "feat: load time_costs.json + comms_interval in init_game"
```

---

### Task 11: Integration test

**Files:**
- Create: `tests/test_time_system.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for time system — deterministic, no LLM dependency."""
import json
import os
import pytest
from scenario_core import DirectedGraph, ScenarioWorld


def test_clock_defaults():
    w = ScenarioWorld(DirectedGraph(scenes={}, events=[]), "test")
    assert w.game_time == 0
    assert w.day == 0
    assert w.hour == 0
    assert w.time_of_day == "夜间"


def test_advance_time_minutes():
    w = ScenarioWorld(DirectedGraph(scenes={}, events=[]), "test")
    w.advance_time(300)  # 5 hours
    assert w.game_time == 300
    assert w.day == 0
    assert w.hour == 5
    assert w.time_of_day == "早晨"


def test_advance_time_cross_day():
    w = ScenarioWorld(DirectedGraph(scenes={}, events=[]), "test")
    w.advance_time(1500)  # 25 hours
    assert w.day == 1
    assert w.time_of_day == "夜间"


def test_time_of_day_transitions():
    w = ScenarioWorld(DirectedGraph(scenes={}, events=[]), "test")
    assert w.time_of_day == "夜间"  # 0:00
    w.advance_time(300)  # 5:00
    assert w.time_of_day == "早晨"
    w.advance_time(180)  # 8:00
    assert w.time_of_day == "白天"
    w.advance_time(540)  # 17:00
    assert w.time_of_day == "黄昏"
    w.advance_time(180)  # 20:00
    assert w.time_of_day == "夜间"


def test_time_flags():
    w = ScenarioWorld(DirectedGraph(scenes={}, events=[]), "test")
    flags = w.get_time_flags()
    assert flags["day:0"] is True
    assert flags["time:夜间"] is True


def test_time_flags_in_runtime_state():
    w = ScenarioWorld(DirectedGraph(scenes={}, events=[]), "test")
    w.advance_time(480)  # 8:00, 白天
    state = w.get_runtime_state("time:白天")
    assert state.completed is True


def test_time_costs_loads():
    path = "data/library/core/time_costs.json"
    assert os.path.exists(path), f"{path} not found"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert "search" in data
    assert "move" in data
    assert "guideline" in data["search"]
```

- [ ] **Step 2: Run tests**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -m pytest tests/test_time_system.py -v --tb=short
```
Expected: all 7 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_time_system.py
git commit -m "test: add time system unit tests — clock, advance_time, time_of_day, flags, time_costs"
```

---

### Task 12: Run full test suite + fix regressions

- [ ] **Step 1: Run all tests**

```bash
cd C:/Users/micha/PyCharmMiscProject && PYTHONPATH="src;." python -m pytest tests/ -v --tb=short --ignore=tests/test_author.py 2>&1 | tail -10
```

- [ ] **Step 2: Fix any failures**

Focus on `test_integration.py` which creates `ScenarioWorld(...)` — verify the new `time_costs` attr doesn't break anything.

- [ ] **Step 3: Commit fixes**

```bash
git add -u
git commit -m "fix: test regressions from time system additions"
```

---

## Verification

After all tasks complete:
1. `PYTHONPATH="src;." python -c "from scenario_core import ScenarioWorld, DirectedGraph; w = ScenarioWorld(DirectedGraph(scenes={},events=[]), 'test'); print(w.day, w.time_of_day, w.get_time_flags())"`
2. `PYTHONPATH="src;." python -c "from game.agents.time_agent import TimeAgent; print('TimeAgent OK')"`
3. `PYTHONPATH="src;." python -c "from game.messages import TimeCommsPacket; print('Packet OK')"`
4. `pytest tests/ -v --tb=short` — all green
