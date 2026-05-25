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
    failure_rate: float = 0.0
    slow_rate: float = 0.0

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
