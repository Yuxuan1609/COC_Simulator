# Progressive Parser Rewrite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace one-shot `parse_module()` with a 4-step progressive pipeline (name anchoring → content generation → dependency resolution → library matching) with retry/fallback on every LLM call.

**Architecture:** `layered_parser.py` holds all prompt builders + individual step parsers + fallback wrapper. `layered_pipeline.py` orchestrates the 6-serial-step flow, runs deterministic cross-validation after Step 3b, and reports results. Data models sync first (remove HiddenInfo, add AutoTrigger; sync L3 fields to new template).

**Tech Stack:** Python 3.10+, dataclasses, DeepSeek API via `llm.call_deepseek`, pytest

---

## File Structure

```
src/module_designer/
├── layered_parser.py      ← COMPLETE REWRITE: 10 prompt builders + 10 parse funcs + fallback wrapper
├── layered_pipeline.py    ← REWRITE: orchestration + deterministic cross-validate + save
├── layered_schema.py      ← MODIFY: add L2_AUTO_TRIGGER_SCHEMA, remove L2_HIDDEN_INFO_SCHEMA,
│                             sync L3 schema (narrative_theme→narrative, required→recommended,
│                             remove logic_chains, remove emotion/danger_level/key_info/exit_leads_to)
├── l2_keeper.py           ← MODIFY: remove HiddenInfo, add AutoTrigger dataclass, update SceneL2
├── l3_designer.py         ← MODIFY: sync field names (narrative_theme→narrative, required→recommended),
│                             remove LogicChain/Branch, trim SceneIntent fields
data/templates/
├── l2_template.json       ← MODIFY: remove hidden_info section, add auto_triggers section
tests/
└── test_module_designer.py ← MODIFY: add Step1-4 prompt tests, fallback tests, AutoTrigger tests
```

---

### Task 1: Sync L2 data model — remove HiddenInfo, add AutoTrigger

**Files:**
- Modify: `src/module_designer/l2_keeper.py`
- Modify: `tests/test_module_designer.py`

- [ ] **Step 1: Add AutoTrigger dataclass and update SceneL2**

Replace the `HiddenInfo` dataclass with `AutoTrigger`. In `SceneL2`, replace `hidden_info` field with `auto_triggers`.

Edit `src/module_designer/l2_keeper.py`:

```python
# Remove lines 66-91 (HiddenInfo class) and replace with:
@dataclass
class AutoTrigger:
    """自动触发事件（替代 HiddenInfo）."""
    id: str                      # AT1, AT2...
    name: str
    scene: str = ""              # 生效场景 ID (S1, S2...)
    trigger_condition: str = ""  # 自然语言触发条件
    effect_type: str = ""        # reveal_info / spawn_enemy / grant_weapon / npc_state_change
    effect_ref: str = ""         # 引用目标（enemy名/weapon名/NPC名，Step 4 填）
    reveal_narrative: str = ""   # 揭示叙事（仅 reveal_info 类型）
    extra: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {
            "id": self.id, "name": self.name, "scene": self.scene,
            "trigger_condition": self.trigger_condition,
            "effect_type": self.effect_type, "effect_ref": self.effect_ref,
            "reveal_narrative": self.reveal_narrative,
        }
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "AutoTrigger":
        return cls(
            id=data["id"], name=data["name"],
            scene=data.get("scene", ""),
            trigger_condition=data.get("trigger_condition", ""),
            effect_type=data.get("effect_type", ""),
            effect_ref=data.get("effect_ref", ""),
            reveal_narrative=data.get("reveal_narrative", ""),
            extra=data.get("extra"),
        )
```

- [ ] **Step 2: Update SceneL2 — replace `hidden_info` with `auto_triggers`**

Edit `SceneL2` in `src/module_designer/l2_keeper.py` lines 133-173:

```python
@dataclass
class SceneL2:
    """单个场景的 L2 KP 信息."""
    scene_name: str
    description: str = ""
    from_here: list = field(default_factory=list)
    to_here: list = field(default_factory=list)
    interactions: list = field(default_factory=list)   # list[dict]
    encounters: List[Encounter] = field(default_factory=list)
    scene_weapons: List[SceneWeapon] = field(default_factory=list)
    auto_triggers: List[AutoTrigger] = field(default_factory=list)
    extra: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {
            "description": self.description,
            "from_here": self.from_here,
            "to_here": self.to_here,
            "interactions": self.interactions,
            "encounters": [e.to_dict() for e in self.encounters],
            "scene_weapons": [sw.to_dict() for sw in self.scene_weapons],
            "auto_triggers": [at.to_dict() for at in self.auto_triggers],
        }
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict, scene_name: str = "") -> "SceneL2":
        return cls(
            scene_name=scene_name,
            description=data.get("description", ""),
            from_here=data.get("from_here", []),
            to_here=data.get("to_here", []),
            interactions=data.get("interactions", []),
            encounters=[Encounter.from_dict(e) for e in data.get("encounters", [])],
            scene_weapons=[SceneWeapon.from_dict(sw) for sw in data.get("scene_weapons", [])],
            auto_triggers=[AutoTrigger.from_dict(at) for at in data.get("auto_triggers", [])],
            extra=data.get("extra"),
        )
```

- [ ] **Step 3: Update test imports and roundtrip test**

Edit `tests/test_module_designer.py` — update the import line:

```python
from module_designer.l2_keeper import SceneL2, Encounter, SceneWeapon, AutoTrigger, NPCProfile
```

Replace the `test_scene_l2_roundtrip` function (lines 29-45) to use AutoTrigger instead of HiddenInfo:

```python
def test_scene_l2_roundtrip():
    scene = SceneL2(
        scene_name="6号车厢",
        description="调查员醒来的车厢",
        encounters=[Encounter(enemy_ref="Clicker", quantity=1)],
        scene_weapons=[SceneWeapon(weapon_ref="手电筒", location="座位下")],
        auto_triggers=[AutoTrigger(
            id="AT1",
            name="发现血迹",
            scene="S1",
            trigger_condition="调查员搜索地板时触发",
            effect_type="reveal_info",
            effect_ref="",
            reveal_narrative="你注意到地板缝隙中有暗红色的痕迹",
        )],
    )
    d = scene.to_dict()
    restored = SceneL2.from_dict(d, "6号车厢")
    assert restored.description == "调查员醒来的车厢"
    assert len(restored.encounters) == 1
    assert restored.encounters[0].enemy_ref == "Clicker"
    assert len(restored.auto_triggers) == 1
    assert restored.auto_triggers[0].id == "AT1"
    assert restored.auto_triggers[0].effect_type == "reveal_info"

def test_auto_trigger_roundtrip():
    at = AutoTrigger(
        id="AT1", name="Clicker 出现", scene="S2",
        trigger_condition="玩家进入7号车厢且持有钥匙",
        effect_type="spawn_enemy", effect_ref="Clicker",
        reveal_narrative="",
    )
    d = at.to_dict()
    restored = AutoTrigger.from_dict(d)
    assert restored.id == "AT1"
    assert restored.effect_type == "spawn_enemy"
    assert restored.effect_ref == "Clicker"
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_module_designer.py::test_scene_l2_roundtrip tests/test_module_designer.py::test_auto_trigger_roundtrip -v
```

Expected: 2 PASS

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: All tests pass (HiddenInfo references in other tests may need updates — fix any failures before committing).

- [ ] **Step 6: Commit**

```bash
git add src/module_designer/l2_keeper.py tests/test_module_designer.py
git commit -m "refactor(l2): replace HiddenInfo with AutoTrigger dataclass"
```

---

### Task 2: Sync L3 data model to new l3_template.json

**Files:**
- Modify: `src/module_designer/l3_designer.py`
- Modify: `tests/test_module_designer.py`

- [ ] **Step 1: Update EndingCondition — rename `narrative_theme` to `narrative`, remove `type`**

```python
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
```

- [ ] **Step 2: Update ToneConstraints — rename `required` to `recommended`**

```python
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
```

- [ ] **Step 3: Trim SceneIntent — remove `emotion`, `danger_level`, `key_info`, `exit_leads_to`**

```python
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
```

- [ ] **Step 4: Remove Branch and LogicChain classes, update L3Designer**

Remove the `Branch` dataclass (lines 52-70) and `LogicChain` dataclass (lines 73-98). Update `L3Designer`:

```python
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
```

- [ ] **Step 5: Update test imports and L3 roundtrip test**

In `tests/test_module_designer.py`, update the L3 import:

```python
from module_designer.l3_designer import (
    L3Designer, ModuleMeta, WorldRule, SceneIntent, ToneConstraints, EndingCondition,
)
```

Replace `test_l3_designer_roundtrip` (lines 62-74):

```python
def test_l3_designer_roundtrip():
    l3 = L3Designer(
        module_meta=ModuleMeta(title="常暗之厢", era="1920s"),
        world_rules=[WorldRule(id="WR1", name="无路可退", rule="后方车厢被吞噬，只能前进")],
        scene_intents={"6号车厢": SceneIntent(purpose="苏醒点")},
        tone_constraints=ToneConstraints(genre="克苏鲁恐怖", recommended=["压迫感"]),
        ending_conditions=[EndingCondition(id="END1", condition="加速逃脱", narrative="重见光明")],
        driving_force="电车正被奈亚拉托提普的化身吞噬",
    )
    d = l3.to_dict()
    restored = L3Designer.from_dict(d)
    assert restored.driving_force == "电车正被奈亚拉托提普的化身吞噬"
    assert len(restored.world_rules) == 1
    assert restored.world_rules[0].id == "WR1"
    assert restored.tone_constraints.recommended == ["压迫感"]
    assert restored.ending_conditions[0].narrative == "重见光明"
```

- [ ] **Step 6: Run tests**

```bash
python -m pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/module_designer/l3_designer.py tests/test_module_designer.py
git commit -m "refactor(l3): sync to new template — narrative_theme→narrative, required→recommended, remove logic_chains/SceneIntent extras"
```

---

### Task 3: Sync layered_schema.py and l2_template.json

**Files:**
- Modify: `src/module_designer/layered_schema.py`
- Modify: `data/templates/l2_template.json`

- [ ] **Step 1: Update L2 schema — remove HIDDEN_INFO, add AUTO_TRIGGER schema**

In `src/module_designer/layered_schema.py`, remove `L2_HIDDEN_INFO_SCHEMA` (lines 70-76) and add:

```python
L2_AUTO_TRIGGER_SCHEMA = {
    "id": {"required": True},
    "name": {"required": True},
    "scene": {"required": False},
    "trigger_condition": {"required": False},
    "effect_type": {"required": False},
    "effect_ref": {"required": False},
    "reveal_narrative": {"required": False},
    "extra": {"required": False},
}
```

Update `L2_SCENE_SCHEMA` (lines 98-107) — replace `hidden_info` with `auto_triggers`:

```python
L2_SCENE_SCHEMA = {
    "description": {"required": False},
    "from_here": {"required": False},
    "to_here": {"required": False},
    "interactions": {"required": False, "list_of": L2_INTERACTION_SCHEMA},
    "encounters": {"required": False, "list_of": L2_ENCOUNTER_SCHEMA},
    "scene_weapons": {"required": False, "list_of": L2_SCENE_WEAPON_SCHEMA},
    "auto_triggers": {"required": False, "list_of": L2_AUTO_TRIGGER_SCHEMA},
    "extra": {"required": False},
}
```

- [ ] **Step 2: Update L3 schema — sync to new template**

Replace L3 schema definitions (lines 113-181):

```python
# Remove L3_DANGER_LEVELS, L3_ENDING_TYPES, L3_LOGIC_CHAIN_SCHEMA, L3_BRANCH_SCHEMA

L3_SCENE_INTENT_SCHEMA = {
    "purpose": {"required": False},
    "key_threat": {"required": False},
    "notes": {"required": False},
}

L3_ENDING_CONDITION_SCHEMA = {
    "id": {"required": True},
    "condition": {"required": False},
    "narrative": {"required": False},
}

L3_TONE_CONSTRAINTS_SCHEMA = {
    "genre": {"required": False},
    "forbidden": {"required": False},
    "recommended": {"required": False},
    "narrative_style": {"required": False},
}

L3_TOP_SCHEMA = {
    "module_meta": {"required": False, "nested": L3_MODULE_META_SCHEMA},
    "world_rules": {"required": False, "list_of": L3_WORLD_RULE_SCHEMA},
    "scene_intents": {"required": False},
    "ending_conditions": {"required": False, "list_of": L3_ENDING_CONDITION_SCHEMA},
    "tone_constraints": {"required": False, "nested": L3_TONE_CONSTRAINTS_SCHEMA},
    "driving_force": {"required": False},
}
```

- [ ] **Step 3: Update test_validate_l2_valid and test_validate_l3_valid**

In `tests/test_module_designer.py`, update `test_validate_l2_valid` (lines 131-153) to use `auto_triggers`:

```python
def test_validate_l2_valid():
    data = {
        "scenes": {
            "6号车厢": {
                "description": "测试场景",
                "interactions": [
                    {"type": "调查", "name": "搜查桌面", "difficulty": "regular"}
                ],
                "encounters": [
                    {"enemy_ref": "Clicker", "quantity": 1}
                ],
                "auto_triggers": [
                    {"id": "AT1", "name": "测试自动触发", "effect_type": "reveal_info"}
                ],
            }
        },
        "events": [
            {"id": "E1", "name": "测试事件"}
        ],
        "npc_profiles": {
            "NPC1": {"name": "NPC1", "role": "关键人物"}
        },
    }
    report = validate_l2(data)
    assert report.is_valid
```

Update `test_validate_l3_valid` (lines 155-170):

```python
def test_validate_l3_valid():
    data = {
        "module_meta": {"title": "测试", "era": "1920s"},
        "world_rules": [
            {"id": "WR1", "name": "测试规则", "rule": "一条规则"}
        ],
        "scene_intents": {
            "6号车厢": {"purpose": "苏醒点"}
        },
        "ending_conditions": [
            {"id": "END1", "condition": "条件", "narrative": "结局"}
        ],
        "tone_constraints": {"genre": "克苏鲁恐怖", "recommended": ["压迫感"]},
        "driving_force": "测试驱动力",
    }
    report = validate_l3(data)
    assert report.is_valid
```

Remove `test_validate_l3_invalid_danger` (lines 173-180) since `danger_level` and its enum are gone.

- [ ] **Step 4: Update l2_template.json**

Write `data/templates/l2_template.json`:

```json
{
  "scenes": {
    "6号车厢": {
      "description": "场景功能性描述（KP用）",
      "from_here": [{"target": "目标场景", "method": "通行方式"}],
      "to_here": [{"source": "来源场景", "method": "通行方式"}],
      "interactions": [
        {
          "id": "I1",
          "type": "调查",
          "name": "互动名称",
          "requirement": "前置条件声明（自然语言）",
          "trigger": "触发条件",
          "result": "结果描述",
          "clue": "线索（可选）",
          "side_effects": [],
          "enemy_ref": null,
          "weapon_ref": null,
          "skill_name": "关联技能（可选）",
          "difficulty": "regular"
        }
      ],
      "encounters": [
        {
          "enemy_ref": null,
          "trigger_condition": "触发条件",
          "initial_behavior": "初始行为",
          "quantity": 1,
          "notes": "备注（可选）",
          "extra": {}
        }
      ],
      "scene_weapons": [
        {
          "weapon_ref": null,
          "location": "位置描述",
          "discovery_method": "发现方式",
          "extra": {}
        }
      ],
      "auto_triggers": [
        {
          "id": "AT1",
          "name": "自动触发名称",
          "scene": "S1",
          "trigger_condition": "触发条件（自然语言）",
          "effect_type": "reveal_info",
          "effect_ref": null,
          "reveal_narrative": "揭示时的叙事文本"
        }
      ],
      "extra": {}
    }
  },
  "events": [
    {
      "id": "E1",
      "name": "事件名称",
      "trigger": "触发描述",
      "irreversible_impact": "不可逆影响",
      "requirement": "前置条件声明（自然语言）",
      "extra": {}
    }
  ],
  "npc_profiles": {
    "NPC名称": {
      "name": "NPC名称",
      "role": "在故事中的角色",
      "motivation": "核心动机",
      "knowledge": ["NPC知道的信息"],
      "personality": "性格描述",
      "voice_notes": "说话风格（可选）",
      "notes": "KP备注（可选）",
      "extra": {}
    }
  }
}
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/module_designer/layered_schema.py data/templates/l2_template.json tests/test_module_designer.py
git commit -m "refactor(schema): sync L2 schema (auto_triggers replace hidden_info) and L3 schema (match new template)"
```

---

### Task 4: Rewrite layered_parser.py — utility functions + Step 1

**Files:**
- Modify: `src/module_designer/layered_parser.py` (complete rewrite)
- Modify: `tests/test_module_designer.py`

This task replaces the ENTIRE content of `layered_parser.py`. The rewrite is split across Tasks 4-7.

- [ ] **Step 1: Write the module header and utility functions**

Write `src/module_designer/layered_parser.py`:

```python
"""
四步渐进式解析器：从模组源文档逐步生成 L1 + L2 + L3 JSON。

流程:
  Step 1a: 结构化提取 (meta + scenes + characters)
  Step 1b: 精修模组 (condensed_text)
  Step 2a: interactions (先跑)
  Step 2b: events + auto_triggers (并行，注入 interaction IDs)
  Step 2c: L1 + L3 (并行)
  Step 3a: L2 依赖解析
  Step 3b: L1 ↔ L2 交叉核对
  Step 4:  Library 匹配 enemies/weapons

保底策略: 每步格式/内容失败 → 重调 (最多 N 次) → 仍失败则基于可解析内容写 JSON。
"""
from __future__ import annotations
import json
import os
import re
from typing import Callable, Optional

# ═══════════════════════════════════════════════════════════════
#  Utility
# ═══════════════════════════════════════════════════════════════

def _load_template(name: str) -> str:
    """加载模板文件并格式化为示例 JSON 字符串."""
    template_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "templates")
    path = os.path.join(template_dir, name)
    with open(path, "r", encoding="utf-8") as f:
        template = json.load(f)
    return json.dumps(template, ensure_ascii=False, indent=2)


def _clean_json(raw: str) -> str:
    """清理 LLM 返回的 JSON 字符串（去除 markdown 包裹等）."""
    raw = raw.strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    return raw.strip()


def _safe_parse_json(raw: str) -> dict:
    """安全解析 JSON，失败返回空 dict."""
    try:
        return json.loads(_clean_json(raw))
    except json.JSONDecodeError:
        return {}


def _is_valid_json_output(data: dict, required_keys: list[str]) -> bool:
    """检查 JSON 输出是否格式合法且含必需的非空字段."""
    if not isinstance(data, dict):
        return False
    for key in required_keys:
        val = data.get(key)
        if val is None or (isinstance(val, (str, list, dict)) and len(val) == 0):
            return False
    return True


# ═══════════════════════════════════════════════════════════════
#  Fallback wrapper
# ═══════════════════════════════════════════════════════════════

def _with_fallback(
    parse_fn: Callable[[], dict],
    required_keys: list[str],
    fallback_data: dict,
    max_retries: int = 3,
    verbose: bool = True,
    step_name: str = "",
) -> dict:
    """
    包装一次 LLM 调用，含重试 + 保底策略。

    1. 调用 parse_fn()
    2. 检查 _is_valid_json_output → 通过返回
    3. 失败则重试 parse_fn() 最多 max_retries 次
    4. 全部失败 → 用 fallback_data + 标记 _fallback: True
    """
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            result = parse_fn()
            if _is_valid_json_output(result, required_keys):
                return result
            last_error = f"内容校验失败（缺失必需字段 {required_keys}）"
        except Exception as e:
            last_error = str(e)
        if verbose:
            print(f"  [{step_name}] 第 {attempt}/{max_retries} 次尝试失败: {last_error}")

    # 保底
    if verbose:
        print(f"  [{step_name}] 重调用尽，使用保底输出")
    fallback_data["_fallback"] = True
    fallback_data["_fallback_reason"] = last_error
    return fallback_data


# ═══════════════════════════════════════════════════════════════
#  Step 1a: 结构化提取
# ═══════════════════════════════════════════════════════════════

STEP1A_SYSTEM = """你是一个 TRPG 模组结构化解析助手。
你的任务是：从模组文档中提取模组的元信息、场景列表和人物列表，使用固定的 ID 体系。

重要原则：
- 场景 ID 使用 S1, S2, S3... 格式
- 人物 ID 使用 NPC_1, NPC_2... 格式
- 场景名和人物名使用原文中的中文名称
- 仅输出 JSON，不要任何解释性文字"""


def build_step1a_prompt(content: str) -> str:
    return f"""从以下模组文档中提取结构化信息。

输出格式:
{{
  "module_meta": {{"title": "模组标题", "era": "年代（如1920s）", "theme": "核心主题"}},
  "scenes": [
    {{"name": "场景中文名", "id": "S1"}},
    {{"name": "场景中文名", "id": "S2"}}
  ],
  "characters": [
    {{"name": "角色中文名", "id": "NPC_1"}},
    {{"name": "角色中文名", "id": "NPC_2"}}
  ]
}}

要求：
1. scenes 按玩家可能到达的顺序排列
2. characters 列出所有有名字或有重要作用的角色
3. 仅输出 JSON

模组文档：
\"\"\"
{content}
\"\"\""""


def parse_step1a(content: str, llm_call) -> dict:
    """从模组文档提取结构化元信息."""
    prompt = build_step1a_prompt(content)
    return llm_call(prompt, system=STEP1A_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 1b: 精修模组
# ═══════════════════════════════════════════════════════════════

STEP1B_SYSTEM = """你是一个 TRPG 模组编辑助手。
你的任务是：将模组文档整理为完整、流畅的半结构化叙事文本。

重要原则：
- 输出是一篇可直接阅读的完整模组文本，不是摘要或碎片列表
- 保留所有关键叙事细节，不压缩信息量
- 去除原作者备注、创作说明等非模组本体内容
- 原文模糊、不连贯或不合理处 → 基于上下文扩写和衔接
- 使用固定的 markdown 章节标题组织内容"""


def build_step1b_prompt(content: str) -> str:
    return f"""将以下模组文档整理为完整流畅的半结构化叙事文本。

输出格式（固定章节标题，每节内为完整叙事文本）:

## module_overview
[模组全局概述：核心设定、时代背景、整体叙事走向]

## scenes
[每个场景的完整叙事信息，以场景名和 ID 开头]
例如: S1: 6号车厢 — [场景的完整叙事描述，包含氛围、关键物品位置、可感知细节]

## npcs
[每个 NPC 的完整信息，以 NPC 名和 ID 开头]
例如: NPC_1: 京山人吉 — [角色的完整描述，包含外貌、身份、行为模式]

## clues_and_items
[所有关键线索和物品的完整描述，包含位置、获取方式、关联信息]

## events_summary
[所有重要事件的时间线和触发条件描述]

要求：
1. 以完整叙事行文呈现，确保阅读流畅
2. 不压缩信息量，不简化关键细节
3. 去除原作者备注等非模组内容，但原文信息不能丢失
4. 原文模糊处可基于上下文合理扩写
5. 整个 condensed_text 应该可以作为后续 LLM 提取信息的唯一来源
6. 仅输出以上 markdown 格式文本，不要 JSON 包裹

模组文档：
\"\"\"
{content}
\"\"\""""


def parse_step1b(content: str, llm_call) -> dict:
    """从模组文档生成精修模组文本."""
    prompt = build_step1b_prompt(content)
    raw = llm_call(prompt, system=STEP1B_SYSTEM)
    # Step 1b 返回的是 markdown 字符串（非 JSON），包裹为 dict
    if isinstance(raw, str):
        return {"condensed_text": raw}
    if isinstance(raw, dict):
        return raw
    return {"condensed_text": str(raw)}
```

- [ ] **Step 2: Update tests — add Step 1 prompt tests**

In `tests/test_module_designer.py`, update the parser import:

```python
from module_designer.layered_parser import (
    build_step1a_prompt, build_step1b_prompt,
)
```

Replace the old prompt test functions (lines 201-223) with:

```python
def test_build_step1a_prompt_structure():
    prompt = build_step1a_prompt("测试模组内容\n包含6号车厢和7号车厢")
    assert "测试模组内容" in prompt
    assert '"id": "S1"' in prompt or "S1" in prompt
    assert '"name":' in prompt
    assert "scenes" in prompt
    assert "characters" in prompt
    assert "module_meta" in prompt


def test_build_step1b_prompt_structure():
    prompt = build_step1b_prompt("测试模组内容")
    assert "测试模组内容" in prompt
    assert "## module_overview" in prompt
    assert "## scenes" in prompt
    assert "## npcs" in prompt
    assert "## clues_and_items" in prompt
    assert "## events_summary" in prompt
    assert "condensed_text" in prompt or "叙事文本" in prompt or "叙事" in prompt
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_module_designer.py::test_build_step1a_prompt_structure tests/test_module_designer.py::test_build_step1b_prompt_structure -v
```

Expected: 2 PASS

- [ ] **Step 4: Commit**

```bash
git add src/module_designer/layered_parser.py tests/test_module_designer.py
git commit -m "feat(parser): add Step 1a/1b — structured extraction + condensed module text"
```

---

### Task 5: Add Step 2 prompt builders + parsers to layered_parser.py

**Files:**
- Modify: `src/module_designer/layered_parser.py`
- Modify: `tests/test_module_designer.py`

- [ ] **Step 1: Append Step 2a (interactions) to layered_parser.py**

```python
# ═══════════════════════════════════════════════════════════════
#  Step 2a: Interactions
# ═══════════════════════════════════════════════════════════════

STEP2A_SYSTEM = """你是一个 TRPG 模组解析助手，专门提取场景中的可执行互动。
你的任务是：从精修模组文本中提取每个场景的全部互动选项。

重要原则：
- enemy_ref 和 weapon_ref 留空（填 null），等待后续步骤匹配
- flag 的命名在此固化（如 flag:found_key），后续步骤将使用同一名称
- requirement 使用自然语言声明（如 "需要先找到钥匙"），不引用其他 ID
- 每个互动必须有唯一 id (I1, I2, I3...)
- 仅输出 JSON，不要任何解释性文字"""


def build_step2a_prompt(condensed_text: str, scenes: list[dict]) -> str:
    scene_list = "\n".join(
        f"- {s['id']}: {s['name']}" for s in scenes
    )
    return f"""从精修模组文本中提取每个场景的全部可执行互动。

已知场景列表:
{scene_list}

输出格式:
{{
  "interactions": [
    {{
      "id": "I1",
      "scene": "S1",
      "type": "调查",
      "name": "互动名称",
      "requirement": "前置条件声明（自然语言）",
      "trigger": "触发条件描述",
      "result": "结果描述",
      "clue": "线索（可选）",
      "side_effects": [
        {{"type": "flag_set", "key": "found_note", "value": true}}
      ],
      "enemy_ref": null,
      "weapon_ref": null,
      "skill_name": "关联技能（可选）",
      "difficulty": "regular"
    }}
  ]
}}

要求：
1. id 全局唯一 (I1, I2, I3...)
2. scene 使用给定列表中的 ID (S1, S2...)
3. enemy_ref 和 weapon_ref 全部填 null（等后续步骤处理）
4. requirement 使用自然语言描述前置条件
5. side_effects 中如果涉及 flag，key 的命名在此固化（后续步骤引用同一名称）
6. type 从以下选择：调查/搜索/对话/鉴定/使用物品/战斗/决策/潜行
7. difficulty 从以下选择：regular/hard/extreme
8. 提取原文中提到的所有互动，即使描述简略也要列出
9. 如果原文对某场景的互动描述不足，基于场景氛围合理补充

精修模组：
\"\"\"
{condensed_text}
\"\"\""""


def parse_step2a(condensed_text: str, scenes: list[dict], llm_call) -> dict:
    """从精修模组提取所有 interactions."""
    prompt = build_step2a_prompt(condensed_text, scenes)
    return llm_call(prompt, system=STEP2A_SYSTEM)
```

- [ ] **Step 2: Append Step 2b (events + auto_triggers) to layered_parser.py**

```python
# ═══════════════════════════════════════════════════════════════
#  Step 2b: Events
# ═══════════════════════════════════════════════════════════════

STEP2B_EVENTS_SYSTEM = """你是一个 TRPG 模组解析助手，专门提取全局不可逆事件。
你的任务是：从精修模组文本和已知的互动列表中提取所有全局事件。

重要原则：
- 事件的 requirement 使用自然语言声明，可引用已存在的 interaction ID 或 flag 名称
- 不可逆事件 = 一旦发生就永久改变世界状态的事件
- 仅输出 JSON，不要任何解释性文字"""


def build_step2b_events_prompt(
    condensed_text: str,
    scenes: list[dict],
    interactions: list[dict],
) -> str:
    scene_list = "\n".join(f"- {s['id']}: {s['name']}" for s in scenes)
    interaction_list = "\n".join(
        f"- {i['id']}: {i['name']} (场景 {i['scene']}, flag: {[s.get('key','') for s in i.get('side_effects',[]) if s.get('type')=='flag_set']})"
        for i in interactions
    )
    return f"""从精修模组文本中提取所有全局不可逆事件。

已知场景:
{scene_list}

已知互动及其 flag:
{interaction_list}

输出格式:
{{
  "events": [
    {{
      "id": "E1",
      "name": "事件名称",
      "trigger": "触发条件描述（自然语言）",
      "irreversible_impact": "不可逆影响描述",
      "requirement": "前置条件声明（自然语言，可引用已知 flag 或 interaction ID）"
    }}
  ]
}}

要求：
1. id 全局唯一 (E1, E2, E3...)
2. requirement 可引用已知的 interaction ID (如 I1) 或 flag 名称 (如 flag:found_key)
3. 不可逆事件包括：场景被破坏、NPC 死亡、关键物品销毁、时间节点等
4. 事件是全局的，不绑定特定场景

精修模组：
\"\"\"
{condensed_text}
\"\"\""""


def parse_step2b_events(
    condensed_text: str,
    scenes: list[dict],
    interactions: list[dict],
    llm_call,
) -> dict:
    prompt = build_step2b_events_prompt(condensed_text, scenes, interactions)
    return llm_call(prompt, system=STEP2B_EVENTS_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 2b: Auto-triggers
# ═══════════════════════════════════════════════════════════════

STEP2B_AT_SYSTEM = """你是一个 TRPG 模组解析助手，专门生成自动触发事件。
你的任务是：基于精修模组和已知互动，生成所有被动触发事件（替代传统的 hidden_info）。

重要原则：
- auto_trigger 是系统被动检测条件后自动揭示的信息或触发的事件
- effect_ref 留空（填 null），等待 Step 4 library 匹配
- 仅输出 JSON，不要任何解释性文字"""


def build_step2b_at_prompt(
    condensed_text: str,
    scenes: list[dict],
    interactions: list[dict],
) -> str:
    scene_list = "\n".join(f"- {s['id']}: {s['name']}" for s in scenes)
    interaction_list = "\n".join(
        f"- {i['id']}: {i['name']} (场景 {i['scene']})"
        for i in interactions
    )
    return f"""从精修模组文本中生成所有自动触发事件。

已知场景:
{scene_list}

已知互动:
{interaction_list}

输出格式:
{{
  "auto_triggers": [
    {{
      "id": "AT1",
      "name": "自动触发名称",
      "scene": "S1",
      "trigger_condition": "触发条件（自然语言，如：玩家进入场景且 flag:has_key 为 true）",
      "effect_type": "reveal_info",
      "effect_ref": null,
      "reveal_narrative": "揭示时的叙事文本"
    }}
  ]
}}

要求：
1. id 全局唯一 (AT1, AT2, AT3...)
2. scene 使用给定列表中的 ID
3. effect_type 从以下选择：reveal_info / spawn_enemy / grant_weapon / npc_state_change
4. effect_ref 全部填 null（等 Step 4 匹配 library）
5. trigger_condition 用自然语言描述，可引用 flag 名称或 event ID
6. 每个场景至少生成 0-2 个 auto_trigger

精修模组：
\"\"\"
{condensed_text}
\"\"\""""


def parse_step2b_at(
    condensed_text: str,
    scenes: list[dict],
    interactions: list[dict],
    llm_call,
) -> dict:
    prompt = build_step2b_at_prompt(condensed_text, scenes, interactions)
    return llm_call(prompt, system=STEP2B_AT_SYSTEM)
```

- [ ] **Step 3: Append Step 2c (L1 + L3) to layered_parser.py**

```python
# ═══════════════════════════════════════════════════════════════
#  Step 2c: L1 玩家可见层
# ═══════════════════════════════════════════════════════════════

STEP2C_L1_SYSTEM = """你是一个 TRPG 模组解析助手，专门提取「玩家可见层」信息。
你的任务是：从精修模组文本中提取每个场景的初始感知信息——玩家进入场景时无需任何检定即可直接感知的一切。

重要原则：
- 严格按照输出格式参考输出 json 文件
- 只描述无条件可见的内容（外观、声音、气味、氛围）
- 需要检定才能发现的信息 → 不放在这里
- NPC 只描述外貌和神态，不写隐藏动机"""


def build_step2c_l1_prompt(condensed_text: str, scenes: list[dict]) -> str:
    template = _load_template("l1_template.json")
    scene_list = "\n".join(f"- {s['id']}: {s['name']}" for s in scenes)
    return f"""从精修模组文本中提取每个场景的「玩家初始感知信息」。

已知场景列表（必须使用这些场景名作为 JSON key）:
{scene_list}

输出格式参考：
{template}

要求：
1. 每个场景使用其名称作为顶层 key（如"6号车厢"）
2. entry_narrative：玩家进入该场景时的开场叙事（KP 可直接朗读，80-200字）
3. atmosphere：场景氛围一句话总结
4. perceptible：玩家无需检定即可感知的元素列表
5. ambient_hints：微妙的环境线索列表
6. npc_appearances：当前场景 NPC 的外貌描述

重要：
- 仅输出 JSON，不要任何解释性文字
- 只写无条件可见的感知信息
- 需要检定才能发现的内容留给 L2 层
- 场景 key 名必须与给定列表中的 name 一致

精修模组：
\"\"\"
{condensed_text}
\"\"\""""


def parse_step2c_l1(condensed_text: str, scenes: list[dict], llm_call) -> dict:
    prompt = build_step2c_l1_prompt(condensed_text, scenes)
    return llm_call(prompt, system=STEP2C_L1_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 2c: L3 设计者层
# ═══════════════════════════════════════════════════════════════

STEP2C_L3_SYSTEM = """你是一个 TRPG 模组设计分析师，专门提取「设计者层」信息。
你的任务是：从精修模组文本中提取模组的设计意图、世界规则、场景设计目的和基调约束。

重要原则：
- 这是设计者层，描述「为什么」这个模组这样设计，而非「有什么」内容
- world_rules 是世界运行的物理/超自然法则
- scene_intents 描述每个场景的设计目的
- driving_force 是一切事件的根本驱动力"""


def build_step2c_l3_prompt(condensed_text: str, scenes: list[dict]) -> str:
    template = _load_template("l3_template.json")
    scene_list = "\n".join(f"- {s['id']}: {s['name']}" for s in scenes)
    return f"""从精修模组文本中提取「设计者层」信息（L3 层）。

已知场景列表:
{scene_list}

输出格式参考：
{template}

要求：
1. module_meta：模组元信息
2. world_rules：世界运行规则列表，每个含 id (WR1, WR2...), name, rule, scope, is_absolute
3. scene_intents：每个场景的设计意图，key 为场景名，value 含 purpose / key_threat (可选) / notes (可选)
4. ending_conditions：结局条件列表，每个含 id / condition / narrative
5. tone_constraints：全局叙事护栏，含 genre / forbidden / recommended / narrative_style
6. driving_force：一切事件的底层驱动力

重要：
- 仅输出 JSON，不要任何解释性文字
- 从原文中推断设计意图，即使原文没有明确声明
- scene_intents 的 key 必须覆盖所有已知场景

精修模组：
\"\"\"
{condensed_text}
\"\"\""""


def parse_step2c_l3(condensed_text: str, scenes: list[dict], llm_call) -> dict:
    prompt = build_step2c_l3_prompt(condensed_text, scenes)
    return llm_call(prompt, system=STEP2C_L3_SYSTEM)
```

- [ ] **Step 4: Add Step 2 prompt tests**

Add to `tests/test_module_designer.py`, updating the parser import:

```python
from module_designer.layered_parser import (
    build_step1a_prompt, build_step1b_prompt,
    build_step2a_prompt, build_step2b_events_prompt, build_step2b_at_prompt,
    build_step2c_l1_prompt, build_step2c_l3_prompt,
)
```

Append test functions:

```python
def test_build_step2a_prompt_structure():
    scenes = [{"id": "S1", "name": "6号车厢"}, {"id": "S2", "name": "7号车厢"}]
    prompt = build_step2a_prompt("精修模组内容", scenes)
    assert "精修模组内容" in prompt
    assert "interactions" in prompt
    assert "I1" in prompt
    assert "S1" in prompt
    assert "enemy_ref" in prompt
    assert "weapon_ref" in prompt
    assert "null" in prompt


def test_build_step2b_events_prompt_structure():
    scenes = [{"id": "S1", "name": "6号车厢"}]
    interactions = [{"id": "I1", "name": "搜查", "scene": "S1", "side_effects": []}]
    prompt = build_step2b_events_prompt("精修模组内容", scenes, interactions)
    assert "精修模组内容" in prompt
    assert "events" in prompt
    assert "E1" in prompt
    assert "I1" in prompt  # 注入了 interaction ID


def test_build_step2b_at_prompt_structure():
    scenes = [{"id": "S1", "name": "6号车厢"}]
    interactions = [{"id": "I1", "name": "搜查", "scene": "S1", "side_effects": []}]
    prompt = build_step2b_at_prompt("精修模组内容", scenes, interactions)
    assert "精修模组内容" in prompt
    assert "auto_triggers" in prompt
    assert "AT1" in prompt
    assert "reveal_info" in prompt
    assert "effect_ref" in prompt


def test_build_step2c_l1_prompt_structure():
    scenes = [{"id": "S1", "name": "6号车厢"}]
    prompt = build_step2c_l1_prompt("精修模组内容", scenes)
    assert "精修模组内容" in prompt
    assert "entry_narrative" in prompt
    assert "perceptible" in prompt
    assert "6号车厢" in prompt


def test_build_step2c_l3_prompt_structure():
    scenes = [{"id": "S1", "name": "6号车厢"}]
    prompt = build_step2c_l3_prompt("精修模组内容", scenes)
    assert "精修模组内容" in prompt
    assert "world_rules" in prompt
    assert "driving_force" in prompt
    assert "scene_intents" in prompt
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_module_designer.py -v -k "step2"
```

Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add src/module_designer/layered_parser.py tests/test_module_designer.py
git commit -m "feat(parser): add Step 2 prompt builders — interactions, events, auto_triggers, L1, L3"
```

---

### Task 6: Add Step 3 + Step 4 prompt builders to layered_parser.py

**Files:**
- Modify: `src/module_designer/layered_parser.py`
- Modify: `tests/test_module_designer.py`

- [ ] **Step 1: Append Step 3a (L2 依赖解析) to layered_parser.py**

```python
# ═══════════════════════════════════════════════════════════════
#  Step 3a: L2 依赖解析
# ═══════════════════════════════════════════════════════════════

STEP3A_SYSTEM = """你是一个 TRPG 逻辑验证助手，专门做模组信息的依赖解析和统一。
你的任务是：检查所有 interaction/event/auto_trigger，统一 flag 名称，补全 requirement 引用。

重要原则：
- 语义相同的 flag 合并为一个名称（如 flag:has_key 和 flag:found_key → 统一为一个）
- requirement 从自然语言声明补全为具体引用（指向 interaction ID / event ID / flag 名）
- 不删改任何内容的实质信息，只修正名称和引用
- 仅输出 JSON，不要任何解释性文字"""


def build_step3a_prompt(
    condensed_text: str,
    interactions: list[dict],
    events: list[dict],
    auto_triggers: list[dict],
) -> str:
    return f"""对以下模组中的所有 L2 内容做依赖解析和 flag 统一。

## 精修模组（参考上下文）
\"\"\"
{condensed_text}
\"\"\"

## Interactions
{json.dumps(interactions, ensure_ascii=False, indent=2)}

## Events
{json.dumps(events, ensure_ascii=False, indent=2)}

## Auto-triggers
{json.dumps(auto_triggers, ensure_ascii=False, indent=2)}

任务:
1. **Flag 统一**: 语义相同的 flag 合并为一个。例如 flag:has_key 和 flag:found_key 指同一件事 → 统一为 flag:found_key，所有引用处同步更新。
2. **Interaction requirement 补全**: 将自然语言声明转为引用已知实体（如 "需要先找到钥匙" → "flag:found_key AND interaction:I3"）。
3. **Event requirement 补全**: 同上。
4. **Auto-trigger condition 补全**: 同上。
5. **Interaction ↔ Event 依赖**: 互动需要事件已/未触发。
6. **Interaction ↔ Interaction 依赖**: 同一场景内互动执行顺序关系。
7. **Event ↔ Event 依赖**: 事件链顺序。
8. **Interaction ↔ Auto-trigger 依赖**: 被动触发对互动的引用。

输出格式:
{{
  "interactions": [{{ ...原字段..., "requirement": "补全后的引用" }}],
  "events": [{{ ...原字段..., "requirement": "补全后的引用" }}],
  "auto_triggers": [{{ ...原字段..., "trigger_condition": "补全后的引用" }}],
  "flag_mapping": {{"has_key": "found_key"}}
}}

仅输出 JSON。"""


def parse_step3a(
    condensed_text: str,
    interactions: list[dict],
    events: list[dict],
    auto_triggers: list[dict],
    llm_call,
) -> dict:
    prompt = build_step3a_prompt(condensed_text, interactions, events, auto_triggers)
    return llm_call(prompt, system=STEP3A_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 3b: L1 ↔ L2 交叉核对
# ═══════════════════════════════════════════════════════════════

STEP3B_SYSTEM = """你是一个 TRPG 一致性校对助手。
你的任务是：检查 L1 玩家可见层与 L2 的交叉引用是否正确，修正不一致。

重要原则：
- linked_interaction 必须指向 L2 中真实存在的 interaction name
- 场景名必须在所有层中一致
- 仅修正名称和引用，不改变实质内容
- 仅输出 JSON，不要任何解释性文字"""


def build_step3b_prompt(
    condensed_text: str,
    l1_data: dict,
    l2_completed: dict,
    l3_data: dict,
    step1_scenes: list[dict],
) -> str:
    scene_names = ", ".join(s['name'] for s in step1_scenes)
    return f"""核对 L1 与 L2 的交叉引用。

## 精修模组（参考上下文）
\"\"\"
{condensed_text}
\"\"\"

## 统一场景名（Step 1 确定）
{scene_names}

## L1 数据
{json.dumps(l1_data, ensure_ascii=False, indent=2)}

## L2 完整数据（已通过 Step 3a 补全依赖）
{json.dumps(l2_completed, ensure_ascii=False, indent=2)}

## L3 数据
{json.dumps(l3_data, ensure_ascii=False, indent=2)}

任务:
1. L1 场景名是否与统一场景名一致 → 不一致则修正
2. L1 linked_interaction 是否指向 L2 中存在的 interaction name → 不存在则修正为正确的名称或清空
3. 检查是否有 L1 感知元素应该关联 L2 互动但未关联 → 补充 linked_interaction
4. L3 scene_intents 的 key 是否覆盖所有场景 → 缺失则补充
5. 所有层的场景名统一

输出格式:
{{
  "l1_data": {{ ...修正后的 L1... }},
  "l3_data": {{ ...修正后的 L3... }}
}}

仅输出 JSON。"""


def parse_step3b(
    condensed_text: str,
    l1_data: dict,
    l2_completed: dict,
    l3_data: dict,
    step1_scenes: list[dict],
    llm_call,
) -> dict:
    prompt = build_step3b_prompt(condensed_text, l1_data, l2_completed, l3_data, step1_scenes)
    return llm_call(prompt, system=STEP3B_SYSTEM)


# ═══════════════════════════════════════════════════════════════
#  Step 4: Library 匹配
# ═══════════════════════════════════════════════════════════════

STEP4_SYSTEM = """你是一个 TRPG 游戏资源配置助手。
你的任务是：根据模组内容和场景需求，从给定的武器/敌人库中选择合适的资源填入占位符。

重要原则：
- 必须从提供的库列表中选择，不允许自创名称
- 若无合适的库条目，填 "none" 并说明原因
- 仅输出 JSON，不要任何解释性文字"""


def build_step4_prompt(
    interactions: list[dict],
    auto_triggers: list[dict],
    l2_descriptions: dict[str, str],
    scene_intents: dict,
    condensed_text: str,
    weapon_library_names: list[str],
    enemy_library_names: list[str],
) -> str:
    weapons_list = "\n".join(f"- {w}" for w in weapon_library_names)
    enemies_list = "\n".join(f"- {e}" for e in enemy_library_names)
    desc_list = "\n".join(f"- {sid}: {desc}" for sid, desc in l2_descriptions.items())
    return f"""为以下内容的 enemy_ref 和 weapon_ref 占位符填值。

## 可用武器库
{weapons_list}

## 可用敌人库
{enemies_list}

## 场景描述
{desc_list}

## L3 Scene Intents
{json.dumps(scene_intents, ensure_ascii=False, indent=2)}

## 精修模组（参考上下文）
\"\"\"
{condensed_text}
\"\"\"

## Interactions (含空占位符)
{json.dumps(interactions, ensure_ascii=False, indent=2)}

## Auto-triggers (含空占位符)
{json.dumps(auto_triggers, ensure_ascii=False, indent=2)}

任务:
1. 为每个 enemy_ref 占位符从可用敌人库中选择匹配项。无匹配填 "none"。
2. 为每个 weapon_ref 占位符从可用武器库中选择匹配项。无匹配填 "none"。
3. 为 auto_trigger 的 effect_ref 从库中选择匹配项。
4. 不允许自创名称。

输出格式:
{{
  "interactions": [{{ ...原字段..., "enemy_ref": "库中名称或none", "weapon_ref": "库中名称或none" }}],
  "auto_triggers": [{{ ...原字段..., "effect_ref": "库中名称或none" }}]
}}

仅输出 JSON。"""


def parse_step4(
    interactions: list[dict],
    auto_triggers: list[dict],
    l2_descriptions: dict[str, str],
    scene_intents: dict,
    condensed_text: str,
    weapon_library_names: list[str],
    enemy_library_names: list[str],
    llm_call,
) -> dict:
    prompt = build_step4_prompt(
        interactions, auto_triggers, l2_descriptions,
        scene_intents, condensed_text,
        weapon_library_names, enemy_library_names,
    )
    return llm_call(prompt, system=STEP4_SYSTEM)
```

- [ ] **Step 2: Add Step 3 + Step 4 prompt tests**

Add test functions to `tests/test_module_designer.py`:

```python
def test_build_step3a_prompt_structure():
    interactions = [{"id": "I1", "name": "搜查", "scene": "S1", "requirement": "需要先找到线索"}]
    events = [{"id": "E1", "name": "事件", "requirement": "interaction I1 完成后"}]
    auto_triggers = [{"id": "AT1", "name": "触发", "scene": "S1", "trigger_condition": "玩家进入场景"}]
    prompt = build_step3a_prompt("精修模组", interactions, events, auto_triggers)
    assert "I1" in prompt
    assert "E1" in prompt
    assert "AT1" in prompt
    assert "flag" in prompt.lower()
    assert "requirement" in prompt


def test_build_step3b_prompt_structure():
    l1 = {"6号车厢": {"entry_narrative": "测试"}}
    l2 = {"interactions": [{"id": "I1", "name": "搜查"}], "events": [], "auto_triggers": []}
    l3 = {"scene_intents": {"6号车厢": {"purpose": "测试"}}}
    scenes = [{"id": "S1", "name": "6号车厢"}]
    prompt = build_step3b_prompt("精修模组", l1, l2, l3, scenes)
    assert "linked_interaction" in prompt
    assert "6号车厢" in prompt
    assert "search" in prompt.lower() or "搜查" in prompt
    assert "scene_intents" in prompt


def test_build_step4_prompt_structure():
    interactions = [{"id": "I1", "name": "战斗", "enemy_ref": None, "weapon_ref": None}]
    auto_triggers = [{"id": "AT1", "name": "触发", "effect_ref": None}]
    prompt = build_step4_prompt(
        interactions, auto_triggers,
        {"S1": "测试场景"},
        {"6号车厢": {"purpose": "测试"}},
        "精修模组参考",
        ["手电筒", ".45自动手枪"],
        ["Clicker", "深潜者"],
    )
    assert "Clicker" in prompt
    assert "手电筒" in prompt
    assert ".45自动手枪" in prompt
    assert "enemy_ref" in prompt
    assert "weapon_ref" in prompt
    assert "effect_ref" in prompt
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_module_designer.py -v -k "step3 or step4"
```

Expected: 3 PASS

- [ ] **Step 4: Commit**

```bash
git add src/module_designer/layered_parser.py tests/test_module_designer.py
git commit -m "feat(parser): add Step 3a/3b/4 prompt builders — dependency resolution, L1-L2 cross-check, library matching"
```

---

### Task 7: Rewrite layered_pipeline.py — orchestration

**Files:**
- Modify: `src/module_designer/layered_pipeline.py`

- [ ] **Step 1: Write the orchestration pipeline**

Write `src/module_designer/layered_pipeline.py`:

```python
"""
四步渐进式管线编排层。

流程编排:
  Step 1a + 1b  并行
  Step 2a       先跑 (interactions)
  Step 2b + 2c  并行 (events + auto_triggers | L1 + L3)
  Step 3a → 3b  串行 (依赖解析 → L1-L2 交叉核对)
  Step 4        library 匹配

每步含 retry + fallback 保底策略。
管线完成后运行确定性 cross_validate 做最终验证。
"""
from __future__ import annotations
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from module_designer.layered_schema import validate_all, SchemaReport
from module_designer.layered_parser import (
    _is_valid_json_output, _with_fallback,
    parse_step1a, parse_step1b,
    parse_step2a, parse_step2b_events, parse_step2b_at,
    parse_step2c_l1, parse_step2c_l3,
    parse_step3a, parse_step3b, parse_step4,
)
# cross_validate_layers 在同一文件中定义，直接使用
cross_validate_layers  # 确定性 cross-validate 保留（同文件内函数）


class PipelineResult:
    """管线执行结果."""
    def __init__(self):
        self.step1_data: dict = {}
        self.l1_data: dict = {}
        self.l2_data: dict = {}
        self.l3_data: dict = {}
        self.schema_reports: dict[str, SchemaReport] = {}
        self.cross_ref_report = None
        self.fallbacks: list[str] = []

    @property
    def all_valid(self) -> bool:
        schema_ok = all(r.is_valid for r in self.schema_reports.values()) if self.schema_reports else False
        cross_ok = self.cross_ref_report.is_valid if self.cross_ref_report else True
        return schema_ok and cross_ok

    def summary(self) -> str:
        lines = ["═══ 管线结果 ═══"]
        if self.fallbacks:
            lines.append(f"保底触发: {len(self.fallbacks)} 处")
            for fb in self.fallbacks:
                lines.append(f"  ⚠ {fb}")
        for layer, report in self.schema_reports.items():
            status = "PASS" if report.is_valid else "FAIL"
            lines.append(f"  Schema {layer}: {status} ({len(report.errors)} errors, {len(report.warnings)} warnings)")
        if self.cross_ref_report:
            status = "PASS" if self.cross_ref_report.is_valid else "FAIL"
            lines.append(f"  交叉引用: {status} ({len(self.cross_ref_report.issues)} issues)")
        return "\n".join(lines)


def run_pipeline(
    content: str,
    llm_json: callable,
    llm_text: callable = None,
    *,
    weapon_lib=None,
    enemy_lib=None,
    max_retries: int = 3,
    verbose: bool = True,
) -> PipelineResult:
    """
    执行完整的四步渐进式解析管线。

    参数:
        content: 原始模组文档文本
        llm_json: LLM JSON 模式调用 (prompt, system) → dict
        llm_text: LLM 文本模式调用 (prompt, system) → str（Step 1b 用）
                 如果为 None，使用 llm_json
        weapon_lib: WeaponLibrary 实例（用于 library 名称列表 + 交叉验证）
        enemy_lib: EnemyLibrary 实例
        max_retries: 每步最大重试次数
        verbose: 是否打印进度

    返回:
        PipelineResult
    """
    if llm_text is None:
        llm_text = llm_json

    result = PipelineResult()

    # ── Step 1 ──────────────────────────────────────────────
    if verbose:
        print("═" * 50)
        print("[Step 1] 元信息提取 + 精修模组...")

    def _do_step1a():
        return parse_step1a(content, llm_json)
    def _do_step1b():
        return parse_step1b(content, llm_text)

    with ThreadPoolExecutor(max_workers=2) as ex:
        f1a = ex.submit(lambda: _with_fallback(
            _do_step1a, ["scenes", "characters"],
            {"module_meta": {}, "scenes": [], "characters": []},
            max_retries, verbose, "Step 1a",
        ))
        f1b = ex.submit(lambda: _with_fallback(
            _do_step1b, ["condensed_text"],
            {"condensed_text": ""},
            max_retries, verbose, "Step 1b",
        ))
        step1a = f1a.result()
        step1b = f1b.result()

    scenes = step1a.get("scenes", [])
    characters = step1a.get("characters", [])
    condensed_text = step1b.get("condensed_text", "")

    result.step1_data = {
        "module_meta": step1a.get("module_meta", {}),
        "scenes": scenes,
        "characters": characters,
        "condensed_text": condensed_text,
    }
    if step1a.get("_fallback"):
        result.fallbacks.append("Step 1a")
    if step1b.get("_fallback"):
        result.fallbacks.append("Step 1b")

    if verbose:
        print(f"  Step 1 完成: {len(scenes)} 场景, {len(characters)} 角色")
        if not condensed_text:
            print("  ⚠ condensed_text 为空！后续步骤可能失败")

    # ── Step 2a ──────────────────────────────────────────────
    if verbose:
        print("═" * 50)
        print("[Step 2a] Interactions 提取...")

    def _do_step2a():
        return parse_step2a(condensed_text, scenes, llm_json)
    step2a = _with_fallback(
        _do_step2a, ["interactions"],
        {"interactions": []},
        max_retries, verbose, "Step 2a",
    )
    interactions = step2a.get("interactions", [])
    if step2a.get("_fallback"):
        result.fallbacks.append("Step 2a")

    if verbose:
        print(f"  Step 2a 完成: {len(interactions)} interactions")

    # ── Step 2b + 2c ─────────────────────────────────────────
    if verbose:
        print("[Step 2b+2c] Events, Auto-triggers, L1, L3 (并行)...")

    def _do_events():
        return parse_step2b_events(condensed_text, scenes, interactions, llm_json)
    def _do_at():
        return parse_step2b_at(condensed_text, scenes, interactions, llm_json)
    def _do_l1():
        return parse_step2c_l1(condensed_text, scenes, llm_json)
    def _do_l3():
        return parse_step2c_l3(condensed_text, scenes, llm_json)

    with ThreadPoolExecutor(max_workers=4) as ex:
        f_ev = ex.submit(lambda: _with_fallback(
            _do_events, ["events"], {"events": []},
            max_retries, verbose, "Step 2b events",
        ))
        f_at = ex.submit(lambda: _with_fallback(
            _do_at, ["auto_triggers"], {"auto_triggers": []},
            max_retries, verbose, "Step 2b auto_triggers",
        ))
        f_l1 = ex.submit(lambda: _with_fallback(
            _do_l1, [], {},  # L1 key 是动态场景名，不能用固定列表校验；放空则 fallback 永不触发
            max_retries, verbose, "Step 2c L1",
        ))
        f_l3 = ex.submit(lambda: _with_fallback(
            _do_l3, ["world_rules", "driving_force"],
            {"world_rules": [], "driving_force": ""},
            max_retries, verbose, "Step 2c L3",
        ))
        events_data = f_ev.result()
        at_data = f_at.result()
        l1_data = f_l1.result()
        l3_data = f_l3.result()

    events = events_data.get("events", [])
    auto_triggers = at_data.get("auto_triggers", [])
    for fb_name, fb_data in [("Step 2b events", events_data),
                              ("Step 2b auto_triggers", at_data),
                              ("Step 2c L1", l1_data),
                              ("Step 2c L3", l3_data)]:
        if fb_data.get("_fallback"):
            result.fallbacks.append(fb_name)

    if verbose:
        print(f"  Step 2b 完成: {len(events)} events, {len(auto_triggers)} auto_triggers")
        print(f"  Step 2c 完成: {len(l1_data)} L1 场景, {len(l3_data.get('world_rules',[]))} 世界规则")

    # ── Step 3a ──────────────────────────────────────────────
    if verbose:
        print("═" * 50)
        print("[Step 3a] L2 依赖解析...")

    def _do_step3a():
        return parse_step3a(condensed_text, interactions, events, auto_triggers, llm_json)
    step3a = _with_fallback(
        _do_step3a, ["interactions"],
        {"interactions": interactions, "events": events, "auto_triggers": auto_triggers},
        max_retries, verbose, "Step 3a",
    )
    interactions = step3a.get("interactions", interactions)
    events = step3a.get("events", events)
    auto_triggers = step3a.get("auto_triggers", auto_triggers)
    if step3a.get("_fallback"):
        result.fallbacks.append("Step 3a")

    if verbose:
        print(f"  Step 3a 完成: flag_mapping={step3a.get('flag_mapping', {})}")

    # ── Step 3b ──────────────────────────────────────────────
    if verbose:
        print("[Step 3b] L1 ↔ L2 交叉核对...")

    l2_completed = {
        "interactions": interactions,
        "events": events,
        "auto_triggers": auto_triggers,
    }

    def _do_step3b():
        return parse_step3b(condensed_text, l1_data, l2_completed, l3_data, scenes, llm_json)
    step3b = _with_fallback(
        _do_step3b, ["l1_data"],
        {"l1_data": l1_data, "l3_data": l3_data},
        max_retries, verbose, "Step 3b",
    )
    l1_data = step3b.get("l1_data", l1_data)
    l3_data = step3b.get("l3_data", l3_data)
    if step3b.get("_fallback"):
        result.fallbacks.append("Step 3b")

    # ── Step 4 ──────────────────────────────────────────────
    if verbose:
        print("═" * 50)
        print("[Step 4] Library 匹配...")

    # 收集 L2 scene descriptions
    l2_descriptions = {}
    for inter in interactions:
        sid = inter.get("scene", "")
        if sid and sid not in l2_descriptions:
            l2_descriptions[sid] = ""
    # descriptions 暂为空（Step 2 未产出场景描述文本），若有则填入
    # 实际的 scene descriptions 在 Step 4 prompt 中精简处理

    weapon_names = []
    enemy_names = []
    try:
        if weapon_lib:
            weapon_names = [w.name for w in weapon_lib.list_all()]
    except Exception:
        pass
    try:
        if enemy_lib:
            enemy_names = [e.name for e in enemy_lib.list_all()]
    except Exception:
        pass

    scene_intents_for_step4 = l3_data.get("scene_intents", {})

    if weapon_names or enemy_names:
        def _do_step4():
            return parse_step4(
                interactions, auto_triggers, l2_descriptions,
                scene_intents_for_step4, condensed_text,
                weapon_names, enemy_names, llm_json,
            )
        step4 = _with_fallback(
            _do_step4, ["interactions"],
            {"interactions": interactions, "auto_triggers": auto_triggers},
            max_retries, verbose, "Step 4",
        )
        interactions = step4.get("interactions", interactions)
        auto_triggers = step4.get("auto_triggers", auto_triggers)
        if step4.get("_fallback"):
            result.fallbacks.append("Step 4")

        if verbose:
            print(f"  Step 4 完成: enemy/weapon refs 已填入")
    else:
        if verbose:
            print("  Step 4 跳过: 无 library 可用")

    # ── 最终: Schema 验证 + Cross-validate ─────────────────
    if verbose:
        print("═" * 50)
        print("[Final] Schema 验证 + 交叉引用检查...")

    l2_for_validation = {
        "scenes": {},  # interactions 尚未按 scene 组织，由 notebook 端消费时组装
        "events": events,
        "npc_profiles": l2_completed.get("npc_profiles", {}),
    }
    result.schema_reports = validate_all(l1_data, l2_for_validation, l3_data)

    # 确定性 cross-validate
    result.cross_ref_report = cross_validate_layers(
        l1_data, l2_for_validation, l3_data,
        weapon_lib=weapon_lib, enemy_lib=enemy_lib,
    )

    # 存储结果
    result.l1_data = l1_data
    result.l3_data = l3_data
    # L2 以松散方式存储（events + interactions + auto_triggers 尚未按 scene 组装）
    result.l2_data = {
        "interactions": interactions,
        "events": events,
        "auto_triggers": auto_triggers,
    }

    if verbose:
        print(result.summary())

    return result


def save_pipeline_result(result: PipelineResult, module_dir: str) -> None:
    """将管线结果保存到模块目录."""
    os.makedirs(module_dir, exist_ok=True)

    # L1
    path = os.path.join(module_dir, "l1_player.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result.l1_data, f, ensure_ascii=False, indent=2)
    print(f"  L1 → {path}")

    # L2 — 组装为标准格式
    interactions = result.l2_data.get("interactions", [])
    auto_triggers = result.l2_data.get("auto_triggers", [])

    scenes_by_id: dict[str, dict] = {}
    for inter in interactions:
        sid = inter.get("scene", "unknown")
        scenes_by_id.setdefault(sid, {
            "interactions": [], "encounters": [],
            "scene_weapons": [], "auto_triggers": [],
        })
        scenes_by_id[sid]["interactions"].append(inter)
    for at in auto_triggers:
        sid = at.get("scene", "unknown")
        scenes_by_id.setdefault(sid, {
            "interactions": [], "encounters": [],
            "scene_weapons": [], "auto_triggers": [],
        })
        scenes_by_id[sid]["auto_triggers"].append(at)

    l2_out = {
        "scenes": scenes_by_id,
        "events": result.l2_data.get("events", []),
        "npc_profiles": result.l2_data.get("npc_profiles", {}),
    }

    path = os.path.join(module_dir, "l2_keeper.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(l2_out, f, ensure_ascii=False, indent=2)
    print(f"  L2 → {path}")

    # L3
    path = os.path.join(module_dir, "l3_designer.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result.l3_data, f, ensure_ascii=False, indent=2)
    print(f"  L3 → {path}")
```

- [ ] **Step 2: Verify existing cross_validate_layers still works**

```bash
python -m pytest tests/test_module_designer.py -v -k "cross_validate"
```

Expected: Tests pass (may need minor updates for new schema field names).

- [ ] **Step 3: Commit**

```bash
git add src/module_designer/layered_pipeline.py
git commit -m "feat(pipeline): rewrite as 4-step orchestrator with parallel execution and fallback"
```

---

### Task 8: Integration — full test run and cleanup

**Files:**
- Modify: `tests/test_module_designer.py`

- [ ] **Step 1: Run the full test suite**

```bash
python -m pytest tests/ -v
```

Expected: All tests pass. If failures exist, fix before committing.

- [ ] **Step 2: Add a smoke integration test**

Add to `tests/test_module_designer.py`:

```python
def test_pipeline_result_summary_with_fallbacks():
    """验证 PipelineResult correctly reports fallbacks."""
    from module_designer.layered_pipeline import PipelineResult
    result = PipelineResult()
    result.fallbacks = ["Step 1a", "Step 3a"]
    result.l1_data = {"test": {}}
    result.l2_data = {"scenes": {}, "events": [], "npc_profiles": {}}
    result.l3_data = {}
    result.schema_reports = validate_all(result.l1_data, result.l2_data, result.l3_data)
    summary = result.summary()
    assert "Step 1a" in summary
    assert "Step 3a" in summary


def test_fallback_utility():
    """验证 _with_fallback 在 LLM 持续失败时返回保底数据."""
    from module_designer.layered_parser import _with_fallback
    call_count = [0]

    def failing_llm():
        call_count[0] += 1
        raise ValueError("LLM error")

    result = _with_fallback(
        failing_llm,
        required_keys=["scenes"],
        fallback_data={"scenes": []},
        max_retries=2,
        verbose=False,
        step_name="test",
    )
    assert call_count[0] == 2  # 2 retries
    assert result["_fallback"] is True
    assert result["scenes"] == []
```

- [ ] **Step 3: Run full test suite again**

```bash
python -m pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 4: Clean up old deprecated code references**

Remove any remaining `HiddenInfo` imports or references in test files or other modules:

```bash
grep -r "HiddenInfo\|hidden_info" src/ tests/ --include="*.py"
```

If any remaining references exist (outside of `archive/`), update them.

- [ ] **Step 5: Final commit**

```bash
git add tests/test_module_designer.py
git commit -m "test: add integration tests for fallback utility and pipeline result reporting"
```

---

## After Implementation

1. Run `python -m pytest tests/ -v` — should be 34+ new tests passing
2. Update NEXT-SESSION.md to mark the parser rewrite as complete
3. Next steps per spec: Step 1 content validation refinement (after seeing real LLM output quality)
