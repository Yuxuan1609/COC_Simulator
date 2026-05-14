"""L3 设计者层数据模型."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ModuleMeta:
    title: str = ""
    author: str = ""
    era: str = "1920s"
    theme: str = ""
    expected_duration: str = ""
    player_count: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, data: dict) -> "ModuleMeta":
        return cls(
            title=data.get("title", ""),
            author=data.get("author", ""),
            era=data.get("era", "1920s"),
            theme=data.get("theme", ""),
            expected_duration=data.get("expected_duration", ""),
            player_count=data.get("player_count", ""),
        )


@dataclass
class WorldRule:
    id: str
    name: str
    rule: str
    scope: List[str] = field(default_factory=list)
    is_absolute: bool = True

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "rule": self.rule,
                "scope": self.scope, "is_absolute": self.is_absolute}

    @classmethod
    def from_dict(cls, data: dict) -> "WorldRule":
        return cls(
            id=data["id"], name=data["name"], rule=data["rule"],
            scope=data.get("scope", []),
            is_absolute=data.get("is_absolute", True),
        )



@dataclass
class SceneIntent:
    purpose: str = ""
    key_threat: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        d = {"purpose": self.purpose}
        if self.key_threat:
            d["key_threat"] = self.key_threat
        if self.notes:
            d["notes"] = self.notes
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SceneIntent":
        return cls(
            purpose=data.get("purpose", ""),
            key_threat=data.get("key_threat"),
            notes=data.get("notes"),
        )


@dataclass
class EndingCondition:
    id: str
    condition: str = ""
    narrative: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "condition": self.condition, "narrative": self.narrative}

    @classmethod
    def from_dict(cls, data: dict) -> "EndingCondition":
        return cls(
            id=data["id"],
            condition=data.get("condition", ""),
            narrative=data.get("narrative", data.get("narrative_theme", "")),
        )


@dataclass
class ToneConstraints:
    genre: str = ""
    forbidden: List[str] = field(default_factory=list)
    recommended: List[str] = field(default_factory=list)
    narrative_style: str = ""

    def to_dict(self) -> dict:
        return {
            "genre": self.genre, "forbidden": self.forbidden,
            "recommended": self.recommended, "narrative_style": self.narrative_style,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ToneConstraints":
        return cls(
            genre=data.get("genre", ""),
            forbidden=data.get("forbidden", []),
            recommended=data.get("recommended", data.get("required", [])),
            narrative_style=data.get("narrative_style", ""),
        )


@dataclass
class L3Designer:
    """L3 设计者层完整数据."""
    module_meta: ModuleMeta = field(default_factory=ModuleMeta)
    world_rules: List[WorldRule] = field(default_factory=list)
    scene_intents: dict[str, SceneIntent] = field(default_factory=dict)
    ending_conditions: List[EndingCondition] = field(default_factory=list)
    tone_constraints: ToneConstraints = field(default_factory=ToneConstraints)
    driving_force: str = ""

    def to_dict(self) -> dict:
        return {
            "module_meta": self.module_meta.to_dict(),
            "world_rules": [r.to_dict() for r in self.world_rules],
            "scene_intents": {k: v.to_dict() for k, v in self.scene_intents.items()},
            "ending_conditions": [e.to_dict() for e in self.ending_conditions],
            "tone_constraints": self.tone_constraints.to_dict(),
            "driving_force": self.driving_force,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "L3Designer":
        return cls(
            module_meta=ModuleMeta.from_dict(data.get("module_meta", {})),
            world_rules=[WorldRule.from_dict(r) for r in data.get("world_rules", [])],
            scene_intents={k: SceneIntent.from_dict(v) for k, v in data.get("scene_intents", {}).items()},
            ending_conditions=[EndingCondition.from_dict(e) for e in data.get("ending_conditions", [])],
            tone_constraints=ToneConstraints.from_dict(data.get("tone_constraints", {})),
            driving_force=data.get("driving_force", ""),
        )


def load_l3(path: str) -> L3Designer:
    """从 JSON 加载 L3 数据."""
    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return L3Designer.from_dict(data)


def save_l3(l3: L3Designer, path: str) -> None:
    """保存 L3 数据到 JSON."""
    import json, os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(l3.to_dict(), f, ensure_ascii=False, indent=2)
