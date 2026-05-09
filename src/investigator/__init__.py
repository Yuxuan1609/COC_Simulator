# src/investigator/__init__.py
"""COC 7th 调查员车卡系统 —— 数据模型、规则引擎、序列化"""

from investigator.models import (
    Stats,
    DerivedStats,
    Skill,
    Occupation,
    Weapon,
    Investigator,
)

__all__ = [
    "Stats",
    "DerivedStats",
    "Skill",
    "Occupation",
    "Weapon",
    "Investigator",
]

# Serialization — will be available after Task 4
try:
    from investigator.serialization import (
        to_json,
        from_json,
        to_dict,
        from_dict,
    )
    __all__.extend(["to_json", "from_json", "to_dict", "from_dict"])
except ImportError:
    pass
