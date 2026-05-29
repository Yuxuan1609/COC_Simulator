"""TurnMonitor — 管线状态机。追踪 process_turn() 每步状态，关键段失败回退+freeze。"""
from __future__ import annotations
from dataclasses import dataclass
import time
from concurrent.futures import ThreadPoolExecutor

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


class TurnMonitor:
    def __init__(self, sensor, world, keeper=None):
        self._sensor = sensor
        self._world = world
        self._keeper = keeper
        self._steps: list[StepResult] = []
        self._last_good_state: dict | None = None
        self._freeze_message: str = ""
        self._turn_started: bool = False

    def begin_turn(self) -> None:
        from investigator.serialization import to_dict as inv_to_dict

        self._turn_started = True
        self._steps.clear()
        self._freeze_message = ""
        self._last_good_state = {
            "graph": self._world.graph.to_dict(),
            "world": self._world.to_dict(),
            "memory": self._world.memory.to_dict(),
            "player_snapshot": inv_to_dict(self._world.player) if self._world.player else None,
            "l1_data": dict(getattr(self._keeper, 'narrator_l1', {})) if self._keeper else {},
        }

    def execute_step(self, step: str, fn, *,
                     is_critical: bool = False,
                     max_retries: int = TURN_STEP_MAX_RETRIES):

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
            except TurnFrozenError:
                raise
            except Exception as e:
                last_error = str(e)
                if attempt < max_retries:
                    sr.status = "retrying"
                    sr.retries = attempt + 1
                    continue

        sr.status = "failed"
        sr.retries = max_retries
        sr.duration_ms = (time.time() - t0) * 1000
        sr.error = last_error
        self._steps.append(sr)

        if is_critical:
            self._restore_world()
            from pathlib import Path
            import os as _os
            save_dir = Path("data/autosave")
            _os.makedirs(save_dir, exist_ok=True)
            self._world.save_state(str(save_dir / "recovery.json"))
            self._freeze_message = (
                f"系统异常（{step} 段失败），游戏已暂停。\n"
                "上一回合的状态已自动保存到 recovery 存档。\n"
                "请使用 /load recovery 恢复，或等待片刻后 /reset 重试。"
            )
            raise TurnFrozenError(self._freeze_message)
        else:
            return None

    def execute_parallel(self, steps: list) -> dict:
        results: dict[str, any] = {}
        errors: dict[str, Exception] = {}

        def _run_one(name, fn, is_crit, retries):
            try:
                r = self.execute_step(name, fn, is_critical=is_crit, max_retries=retries)
                return (name, r, None)
            except TurnFrozenError as e:
                return (name, None, e)
            except Exception as e:
                return (name, None, e)

        with ThreadPoolExecutor(max_workers=len(steps)) as ex:
            futures = [ex.submit(_run_one, *s) for s in steps]
            for f in futures:
                name, result, err = f.result()
                results[name] = result
                if err:
                    errors[name] = err

        for name, err in errors.items():
            if isinstance(err, TurnFrozenError):
                raise err

        return results

    def snapshot(self) -> dict:
        all_records = self._sensor.history if self._sensor else []
        agents = ["Keeper", "Narrator", "Author", "TimeAgent", "IntentDetector"]
        agent_stats = {}
        slow_threshold = getattr(self._sensor, '_slow_threshold_ms', 8000) if self._sensor else 8000
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
                "total_slow": sum(1 for r in all_records if r.duration_ms > slow_threshold) if all_records else 0,
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

    def _restore_world(self) -> None:
        if not self._last_good_state:
            return
        state = self._last_good_state

        from scenario_core import DirectedGraph
        graph = DirectedGraph.from_dict(state["graph"])
        world_data = state["world"]
        world_data["memory"] = state.get("memory", {})
        restored = self._world.__class__.from_dict(world_data, graph)

        clock_data = world_data.get("clock")
        if clock_data:
            from game.clock import GameClock
            restored.clock = GameClock.from_dict(clock_data)

        enemies_data = world_data.get("enemies")
        if enemies_data and hasattr(restored, 'enemies') and restored.enemies:
            try:
                from game.enemy_manager import EnemyManager
                restored.enemies = EnemyManager.from_dict(enemies_data, restored.enemies.library)
            except Exception:
                pass

        npcs_data = world_data.get("npcs")
        if npcs_data:
            try:
                from game.npc_manager import NPCManager
                restored.npcs = NPCManager()
                restored.npcs.from_dict(npcs_data, getattr(restored, '_npc_profiles', {}))
            except Exception:
                pass

        bosses_data = world_data.get("bosses")
        if bosses_data and hasattr(restored, 'bosses') and restored.bosses:
            try:
                from game.boss_manager import BossManager
                restored.bosses = BossManager.from_dict(bosses_data, restored.bosses.library)
            except Exception:
                pass

        scene_weapons_data = world_data.get("scene_weapons", {})
        from game.side_effects import SceneWeapon
        for sc, weps in scene_weapons_data.items():
            restored.scene_weapons[sc] = [
                SceneWeapon(weapon_ref=w["weapon_ref"], scene=sc, quantity=w.get("quantity", 1))
                for w in weps
            ]

        ps = state.get("player_snapshot")
        if ps is not None:
            from investigator.serialization import from_dict as inv_from_dict
            restored.player = inv_from_dict(ps)

        l1_data = state.get("l1_data", {})
        if l1_data and self._keeper:
            self._keeper.narrator_l1 = l1_data

        for attr in list(self._world.__dict__.keys()):
            if hasattr(restored, attr):
                setattr(self._world, attr, getattr(restored, attr))
