from __future__ import annotations
from game.messages import CombatInit
from library.bosses import BossLibrary


class BossManager:
    def __init__(self, boss_library: BossLibrary, boss_encounters: list[dict]):
        self._library = boss_library
        self._encounters = boss_encounters
        self._active_boss_id: str | None = None

    def check_by_engage_type(self, engage_type: str, *, scene: str | None = None) -> list[dict]:
        results = []
        for enc in self._encounters:
            if enc.get("engage_type") != engage_type:
                continue
            if engage_type in ("at", "interaction") and scene is not None:
                if enc.get("scene") != scene:
                    continue
            results.append(enc)
        return results

    def build_combat_init(self, boss_entity: dict, player, scene: str) -> CombatInit:
        from game.enemy_manager import EnemyInstance
        import uuid

        boss_ref = boss_entity["boss_ref"]
        lib_boss = self._library.get(boss_ref)
        if not lib_boss:
            raise KeyError(f"Boss '{boss_ref}' not found in boss library")

        attrs = lib_boss.attributes
        base_hp = (attrs.get("CON", 100) + attrs.get("SIZ", 100)) // 10

        enemy = EnemyInstance(
            instance_id=f"{boss_ref}_{uuid.uuid4().hex[:8]}",
            enemy_ref=boss_ref,
            scene=scene,
            quantity=1,
            status="hostile",
            flags=list(lib_boss.flags),
            combat_behavior=lib_boss.boss_mechanics,
            description=lib_boss.description,
            attributes=dict(attrs),
            armor=lib_boss.armor,
            attacks=list(lib_boss.attacks),
            special_abilities=list(lib_boss.special_abilities),
            san_loss=lib_boss.san_loss,
            hp=base_hp,
            boss_mechanics=lib_boss.boss_mechanics,
        )

        return CombatInit(
            enemies=[enemy],
            player=player,
            scene=scene,
            initiative_context=boss_entity.get("description", ""),
        )

    @property
    def active_boss_id(self) -> str | None:
        return self._active_boss_id

    @active_boss_id.setter
    def active_boss_id(self, value: str | None):
        self._active_boss_id = value

    def set_active(self, boss_id: str | None):
        self.active_boss_id = boss_id

    def resolve_outcome(self, combat_result):
        if not self._active_boss_id:
            return None
        return combat_result.outcome

    def to_dict(self) -> dict:
        return {
            "active_boss_id": self._active_boss_id,
            "encounters": self._encounters,
        }

    @classmethod
    def from_dict(cls, data: dict, boss_library: BossLibrary) -> "BossManager":
        mgr = cls(boss_library, data.get("encounters", []))
        mgr._active_boss_id = data.get("active_boss_id")
        return mgr
