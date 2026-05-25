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
