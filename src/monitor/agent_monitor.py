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
