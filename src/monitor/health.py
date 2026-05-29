"""PipelineHealth — deprecated, logic merged into TurnMonitor.snapshot()."""
from __future__ import annotations
import warnings
import time
from monitor.sensor import LLMSensor


class PipelineHealth:
    def __init__(self, sensor: LLMSensor):
        warnings.warn("PipelineHealth is deprecated. Use TurnMonitor.snapshot() instead.",
                      DeprecationWarning, stacklevel=2)
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
