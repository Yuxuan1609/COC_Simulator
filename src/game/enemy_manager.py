"""EnemyInstance + EnemyManager — runtime enemy tracking."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import uuid

from library.enemies import EnemyLibrary


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class EnemyInstance:
    instance_id: str
    enemy_ref: str
    scene: str
    quantity: int = 1
    status: str = "neutral"
    flags: list[str] = field(default_factory=list)
    combat_behavior: str = ""
    description: str = ""


class EnemyManager:
    def __init__(self, enemy_library: EnemyLibrary):
        self._library = enemy_library
        self._instances: dict[str, EnemyInstance] = {}
        self._combat_active: bool = False
        self._combat_enemies: list[str] = []

    def spawn(self, enemy_ref: str, scene: str, quantity: int = 1) -> EnemyInstance:
        lib_enemy = self._library.get(enemy_ref)
        if not lib_enemy:
            raise KeyError(f"Enemy '{enemy_ref}' not found in library")
        instance_id = f"{enemy_ref}_{_short_id()}"
        inst = EnemyInstance(
            instance_id=instance_id,
            enemy_ref=enemy_ref,
            scene=scene,
            quantity=quantity,
            flags=list(lib_enemy.flags),
            combat_behavior=lib_enemy.combat_behavior,
            description=lib_enemy.description,
        )
        self._instances[instance_id] = inst
        return inst

    def remove(self, instance_id: str):
        self._instances.pop(instance_id, None)
        if instance_id in self._combat_enemies:
            self._combat_enemies.remove(instance_id)

    def get_active_in_scene(self, scene: str) -> list[EnemyInstance]:
        return [
            i for i in self._instances.values()
            if i.scene == scene and i.status != "dead"
        ]

    def get_active_in_range(self, scene: str, graph) -> list[EnemyInstance]:
        candidates = self.get_active_in_scene(scene)
        for inst in self._instances.values():
            if "adjacent_aware" not in inst.flags:
                continue
            if inst.status == "dead":
                continue
            if inst in candidates:
                continue  # already included
            # Check if queried scene is the enemy's scene
            if inst.scene == scene:
                candidates.append(inst)
                continue
            # Check if queried scene is adjacent to the enemy's scene
            node = graph.nodes.get(inst.scene)
            if node:
                for edge in node.edges:
                    if edge.target == scene:
                        candidates.append(inst)
                        break
        return candidates

    def group_by_ref(self, scene: str) -> dict[str, list[EnemyInstance]]:
        groups: dict[str, list[EnemyInstance]] = {}
        for inst in self.get_active_in_scene(scene):
            groups.setdefault(inst.enemy_ref, []).append(inst)
        return groups

    def set_status(self, instance_id: str, status: str):
        if instance_id in self._instances:
            self._instances[instance_id].status = status

    def mark_dead(self, instance_id: str):
        self.set_status(instance_id, "dead")

    def get_by_id(self, instance_id: str) -> Optional[EnemyInstance]:
        return self._instances.get(instance_id)

    def enter_combat(self, instance_ids: list[str]):
        for iid in instance_ids:
            if iid in self._instances:
                self._instances[iid].status = "engaged"
        self._combat_enemies = list(instance_ids)
        self._combat_active = True

    def exit_combat(self, result: dict):
        defeated = set(result.get("defeated_instance_ids", []))
        for iid in self._combat_enemies:
            inst = self._instances.get(iid)
            if not inst:
                continue
            if iid in defeated:
                inst.status = "dead"
            elif inst.status == "engaged":
                inst.status = "hostile"
        self._combat_enemies.clear()
        self._combat_active = False

    def get_combat_context(self, scene: str, graph=None) -> Optional[str]:
        candidates = self.get_active_in_range(scene, graph) if graph \
                     else self.get_active_in_scene(scene)
        if not candidates:
            return None
        lines = []
        for inst in candidates:
            flags_str = " ".join(f"[{f}]" for f in inst.flags) if inst.flags else ""
            lines.append(
                f"- [{inst.enemy_ref}] x{inst.quantity} | {inst.status}"
                + (f" | {flags_str}" if flags_str else "")
                + f"\n  习性：{inst.combat_behavior}"
                + (f"\n  描述：{inst.description}" if inst.description else "")
            )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "instances": {
                iid: {
                    "instance_id": inst.instance_id,
                    "enemy_ref": inst.enemy_ref,
                    "scene": inst.scene,
                    "quantity": inst.quantity,
                    "status": inst.status,
                }
                for iid, inst in self._instances.items()
            },
            "combat_active": self._combat_active,
            "combat_enemies": self._combat_enemies,
        }

    @classmethod
    def from_dict(cls, data: dict, library: EnemyLibrary) -> "EnemyManager":
        mgr = cls(library)
        for iid, idata in data.get("instances", {}).items():
            lib_enemy = library.get(idata["enemy_ref"])
            flags = list(lib_enemy.flags) if lib_enemy else []
            behavior = lib_enemy.combat_behavior if lib_enemy else ""
            desc = lib_enemy.description if lib_enemy else ""
            mgr._instances[iid] = EnemyInstance(
                instance_id=idata["instance_id"],
                enemy_ref=idata["enemy_ref"],
                scene=idata["scene"],
                quantity=idata.get("quantity", 1),
                status=idata.get("status", "neutral"),
                flags=flags,
                combat_behavior=behavior,
                description=desc,
            )
        mgr._combat_active = data.get("combat_active", False)
        mgr._combat_enemies = data.get("combat_enemies", [])
        return mgr

    def __repr__(self):
        return f"EnemyManager({len(self._instances)} instances, combat={'on' if self._combat_active else 'off'})"
