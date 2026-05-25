# PipelineMonitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a two-layer LLM pipeline monitoring system — LLMSensor for transparent call recording, AgentMonitor per-agent with config-driven degradation policies, and PipelineHealth for global observability.

**Architecture:** `src/monitor/` package (sensor, agent_monitor, health, policies) + 15-line sensor embed in `call_deepseek()` + centralized `DEGRADE_POLICY` in `config.py`. Agents swap `call_deepseek(...)` → `self.monitor.call(...)`.

**Tech Stack:** Python dataclasses, Protocol for DegradationPolicy, time/perf_counter for timing, existing `call_deepseek` entry point.

---

### Task 1: config.py — centralized monitor + degradation policy config

**Files:** Modify `src/config.py:38-47`

- [ ] **Step 1: Replace existing U5 placeholder config with full config**

Replace lines 38-47 (the `# 管线监控 （U5 — 待实施）` block) with:

```python
# ═══════════════════════════════════════════════════════════════
# 管线监控（U5）
# ═══════════════════════════════════════════════════════════════

MONITOR_ENABLED = True
"""监控总开关。False 时 LLMSensor 零开销跳过所有记录。"""

MONITOR_HISTORY_SIZE = 200
"""LLMSensor 环形缓冲最大记录数。"""

# ── 降级阈值 ──

LLM_SLOW_THRESHOLD_MS = 8000
"""LLM 调用慢阈值（毫秒）。超过此阈值的调用记录 slow。"""

LLM_TIMEOUT_MS = 45000
"""LLM 调用超时阈值（毫秒）。超时后触发 on_timeout 降级。"""

LLM_MAX_CONSECUTIVE_FAILURES = 3
"""连续失败次数阈值。达到后触发 on_consecutive_failures 降级。"""

LLM_DEGRADE_RECOVERY_COUNT = 5
"""降级后恢复所需连续成功次数。"""

LLM_SLOW_RATE_THRESHOLD = 0.5
"""近 10 次慢调用比例阈值。超过后预防性降级。"""

# ── 降级策略集中化配置 ──

DEGRADE_POLICY: dict[str, dict] = {
    "keeper": {
        "fallback_model": "deepseek-v4-flash",
        "skip_enrich": True,
        "skip_combat_entry": True,
        "skip_intent_detect": True,
    },
    "narrator": {
        "fallback_model": "deepseek-v4-flash",
        "thinking": False,
        "reasoning_effort": "low",
    },
    "author": {
        "fallback_model": "deepseek-v4-flash",
        "reject_all_structural": True,
    },
    "time_agent": {
        "skip": True,
    },
    "intent_detector": {
        "default_result": True,
    },
}
"""每个 Agent 的降级行为参数。DegradationPolicy 实现类在 init 时读取。"""
```

- [ ] **Step 2: Commit**

```bash
git add src/config.py
git commit -m "feat: add PipelineMonitor centralized config — thresholds + DEGRADE_POLICY"
```

---

### Task 2: LLMCallRecord + LLMSensor

**Files:**
- Create: `src/monitor/__init__.py`
- Create: `src/monitor/sensor.py`

- [ ] **Step 1: Create package init**

```python
# src/monitor/__init__.py
"""PipelineMonitor — LLM 调用监控 + Agent 降级 + 全局健康检查."""

from monitor.sensor import LLMSensor, LLMCallRecord, AgentStats
from monitor.agent_monitor import AgentMonitor, DegradationPolicy
from monitor.health import PipelineHealth
from monitor.policies import (
    KeeperPolicy, NarratorPolicy, AuthorPolicy,
    TimeAgentPolicy, IntentDetectorPolicy,
)
```

- [ ] **Step 2: Write sensor.py**

```python
# src/monitor/sensor.py
"""LLMSensor — 嵌入 call_deepseek 的零侵入埋点层."""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import deque
import time


@dataclass
class LLMCallRecord:
    timestamp: float
    label: str
    model: str
    json_mode: bool
    duration_ms: float
    http_status: int
    ok: bool
    json_valid: bool | None
    response_len: int
    tokens_used: int | None = None


@dataclass
class AgentStats:
    agent_name: str = ""
    total_calls: int = 0
    total_failures: int = 0
    total_slow_calls: int = 0
    avg_duration_ms: float = 0.0
    failure_rate: float = 0.0        # 最近 20 次
    slow_rate: float = 0.0           # 最近 20 次

    def update(self, records: list[LLMCallRecord], slow_threshold_ms: int):
        recent = records[-20:]
        self.total_calls = len(records)
        self.total_failures = sum(1 for r in records if not r.ok)
        self.total_slow_calls = sum(1 for r in records if r.duration_ms > slow_threshold_ms)
        self.avg_duration_ms = (sum(r.duration_ms for r in records) / len(records)
                                if records else 0.0)
        if recent:
            self.failure_rate = sum(1 for r in recent if not r.ok) / len(recent)
            self.slow_rate = sum(1 for r in recent if r.duration_ms > slow_threshold_ms) / len(recent)


class LLMSensor:
    def __init__(self, enabled: bool = True, history_size: int = 200,
                 slow_threshold_ms: int = 8000):
        self.enabled = enabled
        self._history: deque[LLMCallRecord] = deque(maxlen=history_size)
        self._slow_threshold_ms = slow_threshold_ms

    def record(self, *, label: str = "", model: str = "",
               json_mode: bool = True, duration_ms: float = 0.0,
               http_status: int = 0, ok: bool = True,
               json_valid: bool | None = None,
               response_len: int = 0, tokens_used: int | None = None):
        if not self.enabled:
            return
        self._history.append(LLMCallRecord(
            timestamp=time.time(), label=label, model=model,
            json_mode=json_mode, duration_ms=duration_ms,
            http_status=http_status, ok=ok, json_valid=json_valid,
            response_len=response_len, tokens_used=tokens_used,
        ))

    def get_records(self, label_prefix: str = "") -> list[LLMCallRecord]:
        if label_prefix:
            return [r for r in self._history if r.label.startswith(label_prefix)]
        return list(self._history)

    def get_stats(self, label_prefix: str) -> AgentStats:
        records = self.get_records(label_prefix)
        stats = AgentStats(agent_name=label_prefix)
        stats.update(records, self._slow_threshold_ms)
        return stats

    @property
    def history(self) -> list[LLMCallRecord]:
        return list(self._history)

    @property
    def consecutive_failures(self) -> int:
        count = 0
        for r in reversed(self._history):
            if not r.ok:
                count += 1
            else:
                break
        return count

    @property
    def recent_slow_rate(self) -> float:
        recent = list(self._history)[-10:]
        if not recent:
            return 0.0
        return sum(1 for r in recent if r.duration_ms > self._slow_threshold_ms) / len(recent)
```

- [ ] **Step 3: Commit**

```bash
git add src/monitor/__init__.py src/monitor/sensor.py
git commit -m "feat: add LLMCallRecord + LLMSensor — transparent call recording layer"
```

---

### Task 3: DegradationPolicy + AgentMonitor

**Files:**
- Create: `src/monitor/agent_monitor.py`
- Create: `src/monitor/policies.py`

- [ ] **Step 1: Write agent_monitor.py**

```python
# src/monitor/agent_monitor.py
"""AgentMonitor — per-agent monitoring with degradation policy."""
from __future__ import annotations
from typing import Protocol, Any
import time

from monitor.sensor import LLMSensor, AgentStats
from config import (
    LLM_TIMEOUT_MS, LLM_MAX_CONSECUTIVE_FAILURES,
    LLM_SLOW_RATE_THRESHOLD, LLM_DEGRADE_RECOVERY_COUNT,
)


class DegradationPolicy(Protocol):
    """每个 Agent 自定义降级行为，参数从 config.py:DEGRADE_POLICY 读取."""
    def on_timeout(self, label: str) -> dict | None: ...
    def on_consecutive_failures(self, count: int) -> str | None: ...
    def on_degrade(self) -> dict: ...


class AgentMonitor:
    def __init__(self, agent_name: str, sensor: LLMSensor,
                 policy: DegradationPolicy):
        self.agent_name = agent_name
        self._sensor = sensor
        self._policy = policy
        self._degraded = False
        self._recovery_count = 0

    def call(self, llm_fn, prompt: str, **kwargs) -> Any:
        """包装 LLM 调用，自动记录 + 降级决策。
        
        llm_fn: 实际 LLM 调用函数 (通常是 call_deepseek)
        """
        if self._degraded:
            degrade_cfg = self._policy.on_degrade()
            if degrade_cfg.get("skip"):
                return {} if kwargs.get("json_mode", True) else ""
            fallback = degrade_cfg.get("fallback_model", "")
            if fallback:
                kwargs["model"] = fallback
            if "thinking" in degrade_cfg:
                kwargs["thinking"] = degrade_cfg["thinking"]
            if "reasoning_effort" in degrade_cfg:
                kwargs["reasoning_effort"] = degrade_cfg["reasoning_effort"]

        t0 = time.time()
        try:
            result = llm_fn(prompt, **kwargs)
            duration = (time.time() - t0) * 1000
            ok = True
        except Exception:
            duration = (time.time() - t0) * 1000
            ok = False
            self._sensor.record(label=kwargs.get("_label", self.agent_name),
                               duration_ms=duration, ok=False)
            self._maybe_trigger()
            raise

        self._sensor.record(label=kwargs.get("_label", self.agent_name),
                           duration_ms=duration, ok=ok)

        if not ok:
            self._maybe_trigger()
        elif self._degraded:
            self._recovery_count += 1
            if self._recovery_count >= LLM_DEGRADE_RECOVERY_COUNT:
                self._degraded = False
                self._recovery_count = 0

        return result

    def _maybe_trigger(self):
        cf = self._sensor.consecutive_failures
        if cf >= LLM_MAX_CONSECUTIVE_FAILURES:
            self._degraded = True
            return
        if self._sensor.recent_slow_rate >= LLM_SLOW_RATE_THRESHOLD:
            self._degraded = True

    @property
    def degraded(self) -> bool:
        return self._degraded

    @property
    def stats(self) -> AgentStats:
        return self._sensor.get_stats(self.agent_name)
```

- [ ] **Step 2: Write policies.py**

```python
# src/monitor/policies.py
"""Per-agent DegradationPolicy implementations — reads from config.py:DEGRADE_POLICY."""
from config import DEGRADE_POLICY


class _BasePolicy:
    def __init__(self, agent_key: str):
        self._cfg = DEGRADE_POLICY.get(agent_key, {})

    def on_timeout(self, label: str) -> dict | None:
        fb = self._cfg.get("fallback_model", "")
        return {"model": fb} if fb else None

    def on_consecutive_failures(self, count: int) -> str | None:
        return self._cfg.get("fallback_model")

    def on_degrade(self) -> dict:
        return dict(self._cfg)


class KeeperPolicy(_BasePolicy):
    def __init__(self):
        super().__init__("keeper")


class NarratorPolicy(_BasePolicy):
    def __init__(self):
        super().__init__("narrator")


class AuthorPolicy(_BasePolicy):
    def __init__(self):
        super().__init__("author")


class TimeAgentPolicy(_BasePolicy):
    def __init__(self):
        super().__init__("time_agent")


class IntentDetectorPolicy(_BasePolicy):
    def __init__(self):
        super().__init__("intent_detector")
```

- [ ] **Step 3: Commit**

```bash
git add src/monitor/agent_monitor.py src/monitor/policies.py
git commit -m "feat: add AgentMonitor + DegradationPolicy config-driven architecture"
```

---

### Task 4: PipelineHealth — global aggregation

**Files:**
- Create: `src/monitor/health.py`

- [ ] **Step 1: Write health.py**

```python
# src/monitor/health.py
"""PipelineHealth — 跨 Agent 只读聚合，不参与降级决策."""
from __future__ import annotations
import time
from monitor.sensor import LLMSensor


class PipelineHealth:
    def __init__(self, sensor: LLMSensor):
        self._sensor = sensor
        self._start_time = time.time()

    def snapshot(self) -> dict:
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
        all_records = self._sensor.history
        return {
            "uptime_seconds": round(time.time() - self._start_time, 1),
            "total_calls": len(all_records),
            "total_failures": sum(1 for r in all_records if not r.ok),
            "total_slow": sum(1 for r in all_records
                             if r.duration_ms > self._sensor._slow_threshold_ms),
            "agents": agent_stats,
        }
```

- [ ] **Step 2: Commit**

```bash
git add src/monitor/health.py
git commit -m "feat: add PipelineHealth global aggregation + snapshot"
```

---

### Task 5: Embed LLMSensor in call_deepseek — 15-line change

**Files:** Modify `src/llm.py`

- [ ] **Step 1: Add global sensor + import**

After the existing `_log_dir` / `_current_log_label` section (around line 40-48), add:

```python
# ── PipelineMonitor 传感器 ──

_sensor: "LLMSensor | None" = None

def _init_sensor():
    """延迟初始化传感器（避免 config import 循环）."""
    global _sensor
    if _sensor is None:
        from config import MONITOR_ENABLED, MONITOR_HISTORY_SIZE, LLM_SLOW_THRESHOLD_MS
        from monitor.sensor import LLMSensor
        _sensor = LLMSensor(
            enabled=MONITOR_ENABLED,
            history_size=MONITOR_HISTORY_SIZE,
            slow_threshold_ms=LLM_SLOW_THRESHOLD_MS,
        )
    return _sensor
```

- [ ] **Step 2: Add sensor record at call_deepseek start/end**

In `call_deepseek()`, after line ~130 (right before the actual API call logic), add timing and record to success path:

```python
    import time as _time
    _t0 = _time.time()
    _s = _init_sensor()
```

After the successful response (before return), add:

```python
    _duration = (_time.time() - _t0) * 1000
    if _s.enabled:
        _s.record(
            label=_current_log_label or "llm",
            model=_model,
            json_mode=json_mode,
            duration_ms=_duration,
            http_status=200,
            ok=True,
            json_valid=_json_ok_if_applicable,
            response_len=len(_raw_response_text),
        )
```

In the except/error path, add:

```python
    _duration = (_time.time() - _t0) * 1000
    if _s.enabled:
        _s.record(
            label=_current_log_label or "llm",
            model=_model,
            json_mode=json_mode,
            duration_ms=_duration,
            http_status=getattr(e, 'status_code', 0),
            ok=False,
            json_valid=False,
            response_len=0,
        )
    raise
```

**Note:** The exact placement depends on the current code structure of `call_deepseek()`. Read the function body carefully before inserting.

- [ ] **Step 3: Expose sensor for global access**

Add at end of `llm.py`:

```python
def get_sensor() -> "LLMSensor | None":
    return _sensor
```

- [ ] **Step 4: Commit**

```bash
git add src/llm.py
git commit -m "feat: embed LLMSensor in call_deepseek — timing + record on every LLM call"
```

---

### Task 6: Wire AgentMonitor into Keeper

**Files:** Modify `src/game/agents/keeper.py`

- [ ] **Step 1: Add monitor init in Keeper.__init__**

```python
# In Keeper.__init__, after self._warnings = []:
        from monitor.sensor import LLMSensor
        from monitor.agent_monitor import AgentMonitor
        from monitor.policies import KeeperPolicy
        self._sensor = _get_or_init_sensor()
        self.monitor = AgentMonitor("Keeper", self._sensor, KeeperPolicy())
```

- [ ] **Step 2: Swap LLM calls in Keeper**

Replace direct `call_deepseek(...)` calls in `_parse()` and `_enrich()` with:

```python
# Before: call_deepseek(prompt, json_mode=True, ...)
# After:  self.monitor.call(lambda p, **kw: call_deepseek(p, **kw), prompt, json_mode=True, ...)
```

For the NPC intent detect call:

```python
# Before: call_deepseek(intent_prompt, json_mode=True, model=LLM_FLASH_MODEL, ...)
# After:  self.monitor.call(lambda p, **kw: call_deepseek(p, **kw),
#                          intent_prompt, json_mode=True, model=LLM_FLASH_MODEL,
#                          _label="Keeper IntentDetect", ...)
```

For combat_entry and standoff LLM calls: same pattern.

When `self.monitor.degraded` and `DEGRADE_POLICY["keeper"]["skip_enrich"]` is True, skip the enrich LLM call entirely and pass judged_entities directly to curator.

- [ ] **Step 3: Commit**

```bash
git add src/game/agents/keeper.py
git commit -m "feat: wire AgentMonitor into Keeper — all LLM calls through monitor"
```

---

### Task 7: Wire AgentMonitor into Narrator + Author + TimeAgent + IntentDetector

**Files:** Modify:
- `src/game/agents/narrator.py`
- `src/game/agents/author.py`
- `src/game/agents/time_agent.py`
- `src/game/intent_detector.py`

- [ ] **Step 1: Narrator**

```python
# In Narrator.__init__:
        self.monitor = AgentMonitor("Narrator", _get_or_init_sensor(), NarratorPolicy())

# In narrate(): swap call_deepseek → self.monitor.call(lambda p, **kw: call_deepseek(p, **kw), ...)
```

- [ ] **Step 2: Author**

```python
# In Author.__init__:
        self.monitor = AgentMonitor("Author", _get_or_init_sensor(), AuthorPolicy())

# In handle_request(): swap call_deepseek → self.monitor.call(...)
# When degraded: check reject_all_structural → return early with rejection
```

- [ ] **Step 3: TimeAgent**

```python
# In TimeAgent.__init__:
        self.monitor = AgentMonitor("TimeAgent", _get_or_init_sensor(), TimeAgentPolicy())

# In assess(): when degraded → return {"total_extra_minutes": 0} (skip)
```

- [ ] **Step 4: IntentDetector**

```python
# In IntentDetector.__init__:
        self.monitor = AgentMonitor("IntentDetector", _get_or_init_sensor(), IntentDetectorPolicy())

# In detect(): when degraded → return IntentResult(needs_author=True, ...)
```

- [ ] **Step 5: Commit**

```bash
git add src/game/agents/narrator.py src/game/agents/author.py src/game/agents/time_agent.py src/game/intent_detector.py
git commit -m "feat: wire AgentMonitor into Narrator, Author, TimeAgent, IntentDetector"
```

---

### Task 8: PipelineHealth integration + CLI /health

**Files:** Modify `src/game_loop.py`

- [ ] **Step 1: Add /health command handler**

In `_handle_spawn_command()`, add before the `return None` at end:

```python
    if cmd == "/health":
        from monitor.health import PipelineHealth
        from llm import get_sensor
        sensor = get_sensor()
        if sensor:
            health = PipelineHealth(sensor)
            snap = health.snapshot()
            lines = ["Pipeline Health:"]
            lines.append(f"  Uptime: {snap['uptime_seconds']}s")
            lines.append(f"  Total calls: {snap['total_calls']} / Failures: {snap['total_failures']} / Slow: {snap['total_slow']}")
            for agent, stats in snap.get("agents", {}).items():
                lines.append(f"  {agent}: {stats['calls']} calls, {stats['failures']} fail, "
                           f"{stats['avg_ms']}ms avg, {stats['slow_rate']:.0%} slow")
            return {"brief": "\n".join(lines), "narrative": "\n".join(lines), "full": "\n".join(lines)}
        return {"brief": "Monitor not initialized.", "narrative": "监控未初始化", "full": "监控未初始化"}
```

- [ ] **Step 2: Commit**

```bash
git add src/game_loop.py
git commit -m "feat: add /health CLI command + PipelineHealth integration"
```

---

### Task 9: Tests — LLMSensor + AgentMonitor

**Files:** Create `tests/test_monitor.py`

- [ ] **Step 1: Write tests**

```python
"""PipelineMonitor tests — LLMSensor + AgentMonitor + PipelineHealth."""
from monitor.sensor import LLMSensor, LLMCallRecord, AgentStats


def test_sensor_record_and_retrieval():
    s = LLMSensor(enabled=True, history_size=5, slow_threshold_ms=1000)
    s.record(label="Keeper Parse", model="deepseek-v4-pro", duration_ms=500, ok=True,
             json_mode=True, json_valid=True, response_len=100, http_status=200)
    s.record(label="Keeper Enrich", model="deepseek-v4-pro", duration_ms=3000, ok=True,
             json_mode=True, json_valid=True, response_len=200, http_status=200)
    s.record(label="Narrator", model="deepseek-v4-pro", duration_ms=200, ok=False,
             json_mode=True, json_valid=False, response_len=0, http_status=500)

    assert len(s.history) == 3
    assert len(s.get_records("Keeper")) == 2
    assert len(s.get_records("Narrator")) == 1
    assert s.consecutive_failures == 1


def test_sensor_disabled_zero_overhead():
    s = LLMSensor(enabled=False)
    s.record(label="test", duration_ms=100)
    assert len(s.history) == 0


def test_sensor_ring_buffer():
    s = LLMSensor(enabled=True, history_size=3)
    for i in range(5):
        s.record(label=f"call_{i}", duration_ms=100, ok=True)
    assert len(s.history) == 3


def test_agent_stats():
    s = LLMSensor(enabled=True, slow_threshold_ms=1000)
    for _ in range(5):
        s.record(label="Keeper Parse", duration_ms=500, ok=True, json_mode=True,
                 json_valid=True, response_len=100, http_status=200)
    for _ in range(3):
        s.record(label="Keeper Parse", duration_ms=2000, ok=True, json_mode=True,
                 json_valid=True, response_len=100, http_status=200)
    for _ in range(2):
        s.record(label="Keeper Parse", duration_ms=100, ok=False, json_mode=True,
                 json_valid=False, response_len=0, http_status=500)

    stats = s.get_stats("Keeper")
    assert stats.total_calls == 10
    assert stats.total_failures == 2
    assert stats.total_slow_calls == 3
    assert stats.failure_rate == 0.1   # 2/20 in recent window
    assert stats.slow_rate == 0.15      # 3/20 in recent window


def test_consecutive_failures():
    s = LLMSensor(enabled=True)
    s.record(label="test", duration_ms=100, ok=True)
    s.record(label="test", duration_ms=100, ok=False)
    s.record(label="test", duration_ms=100, ok=False)
    assert s.consecutive_failures == 2
    s.record(label="test", duration_ms=100, ok=True)
    assert s.consecutive_failures == 0


def test_recent_slow_rate():
    s = LLMSensor(enabled=True, slow_threshold_ms=1000)
    for _ in range(6):
        s.record(label="test", duration_ms=500, ok=True)
    for _ in range(4):
        s.record(label="test", duration_ms=2000, ok=True)
    assert s.recent_slow_rate == 0.4


def test_degrade_policies_load_from_config():
    from monitor.policies import KeeperPolicy, NarratorPolicy, AuthorPolicy
    kp = KeeperPolicy()
    assert kp.on_degrade()["skip_enrich"] is True
    np = NarratorPolicy()
    assert np.on_degrade()["thinking"] is False
    ap = AuthorPolicy()
    assert ap.on_degrade()["reject_all_structural"] is True


def test_pipeline_health_snapshot():
    from monitor.health import PipelineHealth
    s = LLMSensor(enabled=True)
    s.record(label="Keeper Parse", duration_ms=100, ok=True, json_mode=True,
             json_valid=True, response_len=50, http_status=200, model="deepseek-v4-pro")
    s.record(label="Narrator", duration_ms=200, ok=True, json_mode=True,
             json_valid=True, response_len=80, http_status=200, model="deepseek-v4-pro")

    health = PipelineHealth(s)
    snap = health.snapshot()
    assert snap["total_calls"] == 2
    assert snap["total_failures"] == 0
    assert "Keeper" in snap["agents"]
    assert "Narrator" in snap["agents"]
```

- [ ] **Step 2: Run tests**

```bash
PYTHONPATH="src;." python -m pytest tests/test_monitor.py -v --tb=short
```

Expected: 8 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_monitor.py
git commit -m "test: add PipelineMonitor unit tests — sensor, stats, policies, health"
```
