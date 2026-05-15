# 统一可触发实体格式 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 interaction / auto_trigger / event 统一为共享字段模型，用 `based_on` 标注派生关系

**Architecture:** 重构 `l2_keeper.py` 的 `AutoTrigger` 为统一字段；重写 Step 2b/3a/4 的 prompt 和 parser；更新模板、schema、pipeline；不触及 `scenario_core.py` / `game_loop.py`

**Tech Stack:** Python 3.12+, dataclasses, json

---

### Task 1: Update l2_template.json

**Files:**
- Modify: `data/templates/l2_template.json`

- [ ] **Step 1: Replace auto_triggers and events section in L2 template**

```json
{
  "scenes": {
    "6号车厢": {
      "description": "场景功能性描述（KP用）",
      "from_here": [{"target": "目标场景", "method": "通行方式", "requirement": "通行前置条件（可选）"}],
      "to_here": [{"source": "来源场景", "method": "通行方式", "requirement": "通行前置条件（可选）"}],
      "interactions": [
        {
          "id": "I1",
          "type": "关联技能名，不涉及填\"无\"",
          "name": "互动名称",
          "requirement": "前置条件声明（自然语言）",
          "trigger": "触发条件",
          "result": "结果描述（含线索信息）",
          "side_effects": ["自然语言描述的副作用"],
          "enemy_ref": null,
          "weapon_ref": null,
          "difficulty": "regular",
          "based_on": null
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
          "type": "关联技能名，不涉及填\"无\"",
          "name": "自动触发名称",
          "scene": "S1",
          "requirement": "前置条件声明（自然语言）",
          "trigger": "触发条件（自然语言）",
          "result": "触发后的结果描述",
          "side_effects": ["自然语言描述的副作用"],
          "enemy_ref": null,
          "weapon_ref": null,
          "difficulty": "regular",
          "based_on": "I1"
        }
      ],
      "extra": {}
    }
  },
  "events": [
    {
      "id": "E1",
      "type": "关联技能名，不涉及填\"无\"",
      "name": "事件名称",
      "requirement": "前置条件声明（自然语言）",
      "trigger": "触发条件描述",
      "result": "触发后的结果描述（含不可逆影响）",
      "side_effects": ["自然语言描述的副作用"],
      "difficulty": "regular",
      "based_on": "I1",
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

- [ ] **Step 2: Verify the file is valid JSON**

Run: `python -c "import json; json.load(open('data/templates/l2_template.json'))" && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add data/templates/l2_template.json
git commit -m "feat: unify triggerable entity format in L2 template — add based_on, remove effect_type/effect_ref/reveal_narrative, add type/difficulty/side_effects to events"
```

---

### Task 2: Refactor AutoTrigger dataclass in l2_keeper.py

**Files:**
- Modify: `src/module_designer/l2_keeper.py:66-100`
- Test: `tests/test_module_designer.py`

- [ ] **Step 1: Replace AutoTrigger with unified fields**

```python
@dataclass
class AutoTrigger:
    """自动触发事件（与 interaction 统一字段模型）."""
    id: str                      # AT1, AT2...
    name: str
    scene: str = ""              # 生效场景 ID (S1, S2...)
    type: str = ""               # 关联技能名，不涉及填"无"
    requirement: str = ""        # 前置条件（自然语言）
    trigger: str = ""            # 触发条件描述
    result: str = ""             # 触发后结果描述
    side_effects: list = field(default_factory=list)  # 自然语言字符串列表
    enemy_ref: str = ""          # Step 4 填入
    weapon_ref: str = ""         # Step 4 填入
    difficulty: str = ""         # None / regular / hard / extreme
    based_on: str = ""           # 派生来源 interaction ID
    extra: Optional[dict] = None

    def to_dict(self) -> dict:
        d = {
            "id": self.id, "name": self.name, "scene": self.scene,
            "type": self.type,
            "requirement": self.requirement,
            "trigger": self.trigger,
            "result": self.result,
            "side_effects": self.side_effects,
            "enemy_ref": self.enemy_ref,
            "weapon_ref": self.weapon_ref,
            "difficulty": self.difficulty,
            "based_on": self.based_on,
        }
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "AutoTrigger":
        return cls(
            id=data["id"], name=data["name"],
            scene=data.get("scene", ""),
            type=data.get("type", ""),
            requirement=data.get("requirement", ""),
            trigger=data.get("trigger", ""),
            result=data.get("result", ""),
            side_effects=data.get("side_effects", []),
            enemy_ref=data.get("enemy_ref", ""),
            weapon_ref=data.get("weapon_ref", ""),
            difficulty=data.get("difficulty", ""),
            based_on=data.get("based_on", ""),
            extra=data.get("extra"),
        )
```

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/ -x -q`
Expected: some tests may fail due to field name changes — will be fixed in later tasks

- [ ] **Step 3: Commit**

```bash
git add src/module_designer/l2_keeper.py
git commit -m "refactor: unify AutoTrigger fields with interaction model — add type/difficulty/side_effects/based_on, remove effect_type/effect_ref/reveal_narrative"
```

---

### Task 3: Update layered_schema.py

**Files:**
- Modify: `src/module_designer/layered_schema.py:70-110`

- [ ] **Step 1: Replace L2_INTERACTION_SCHEMA, L2_AUTO_TRIGGER_SCHEMA, L2_EVENT_SCHEMA**

```python
L2_DIFFICULTIES = {"regular", "hard", "extreme"}

L2_INTERACTION_SCHEMA = {
    "type": {"required": True},
    "name": {"required": True},
    "requirement": {"required": False},
    "trigger": {"required": False},
    "result": {"required": False},
    "side_effects": {"required": False},
    "skill_name": {"required": False},
    "difficulty": {"required": False, "values": L2_DIFFICULTIES},
    "based_on": {"required": False},
}

L2_AUTO_TRIGGER_SCHEMA = L2_INTERACTION_SCHEMA  # 统一字段模型

L2_ENCOUNTER_SCHEMA = {
    "enemy_ref": {"required": True},
    "trigger_condition": {"required": False},
    "initial_behavior": {"required": False},
    "quantity": {"required": False},
    "notes": {"required": False},
    "extra": {"required": False},
}

L2_SCENE_WEAPON_SCHEMA = {
    "weapon_ref": {"required": True},
    "location": {"required": False},
    "discovery_method": {"required": False},
    "extra": {"required": False},
}

L2_EVENT_SCHEMA = {
    "id": {"required": True},
    "name": {"required": True},
    "type": {"required": False},
    "requirement": {"required": False},
    "trigger": {"required": False},
    "result": {"required": False},
    "side_effects": {"required": False},
    "difficulty": {"required": False},
    "based_on": {"required": False},
    "extra": {"required": False},
}
```

Note: keep `L2_NPC_PROFILE_SCHEMA` and `L2_SCENE_SCHEMA` unchanged.

- [ ] **Step 2: Run tests**

Run: `python -m pytest tests/ -x -q`
Expected: schema validation tests should pass

- [ ] **Step 3: Commit**

```bash
git add src/module_designer/layered_schema.py
git commit -m "feat: unify L2 schemas — auto_trigger shares interaction schema, event gains type/difficulty/based_on, remove irreversible_impact"
```

---

### Task 4: Update Step 2a prompt — add based_on field

**Files:**
- Modify: `src/module_designer/layered_parser.py:262-321`

- [ ] **Step 1: Add based_on to STEP2A_SYSTEM**

Replace the existing `STEP2A_SYSTEM` (lines 248-259) with:

```python
STEP2A_SYSTEM = """你是一个 TRPG 模组解析助手，专门提取场景中的可执行互动和通行路径。
你的任务是：从精修模组文本中提取每个场景的全部互动选项，以及场景间的通行路径。

重要原则：
- enemy_ref 和 weapon_ref 留空（填 null），等待后续步骤匹配
- requirement 使用自然语言声明（如 "需要先找到钥匙"），不引用其他 ID
- 每个互动必须有唯一 id (I1, I2, I3...)，互动完成后其 id 即代表触发状态
- result 合并了结果描述和线索信息
- side_effects 是自然语言字符串列表，描述非状态性的副作用（如获得物品、属性变化、NPC状态变化）
- 结构化的状态追踪（如"已找到钥匙"）由互动本身的完成状态替代，不需要在 side_effects 中记录 flag
- based_on 始终为 null（Step 2b 会给派生实体填值）
- 通行路径记录每个场景的出边（from_here）和入边（to_here），包含通行方式和前置条件
- 仅输出 JSON，不要任何解释性文字"""
```

- [ ] **Step 2: Add based_on to build_step2a_prompt interaction format**

Replace the interaction format section (lines 274-285) — add `based_on` field:

```python
      "enemy_ref": null,
      "weapon_ref": null,
      "difficulty": "regular",
      "based_on": null
```

Add to requirements list (after current item 12):

```
13. based_on 始终填 null（派生关系由 Step 2b 标注）
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_module_designer.py::test_build_step2a_prompt_structure -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/module_designer/layered_parser.py
git commit -m "feat: add based_on field to Step 2a interaction format, always null at this stage"
```

---

### Task 5: Rewrite Step 2b events prompt and parser

**Files:**
- Modify: `src/module_designer/layered_parser.py:328-387`

- [ ] **Step 1: Replace STEP2B_EVENTS_SYSTEM**

```python
STEP2B_EVENTS_SYSTEM = """你是一个 TRPG 模组解析助手，专门提取全局不可逆事件。
你的任务是：从精修模组文本和已知互动中派生全局事件。事件是跨场景的、不可逆的世界级变化。

重要原则：
- 事件使用与 interaction 相同的统一字段模型（id, type, name, requirement, trigger, result, side_effects, difficulty, based_on）
- 事件无 scene 字段（全局事件不绑定特定场景）
- based_on 只能指向已知的 interaction ID（因为 Step 2b 并行，不能指向 auto_trigger 或其他 event）
- type 填写关联技能名（如"侦察"），不涉及填"无"
- result 需包含不可逆性描述（如"此事件不可逆：...")
- 仅输出 JSON，不要任何解释性文字"""
```

- [ ] **Step 2: Replace build_step2b_events_prompt**

```python
def build_step2b_events_prompt(
    condensed_text: str,
    scenes: list[dict],
    interactions: list[dict],
) -> str:
    scene_list = "\n".join(f"- {s['id']}: {s['name']}" for s in scenes)
    interaction_list = "\n".join(
        f"- {i['id']}: {i['name']} → {i.get('result', '')} (场景 {i['scene']})"
        for i in interactions
    )
    return f"""从精修模组文本中提取所有全局不可逆事件。

已知场景:
{scene_list}

已知互动（事件只能基于这些互动派生，based_on 必须指向其 ID）:
{interaction_list}

输出格式:
{{
  "events": [
    {{
      "id": "E1",
      "type": "关联技能名，不涉及填\"无\"",
      "name": "事件名称",
      "requirement": "前置条件声明（自然语言，可引用 interaction ID）",
      "trigger": "触发条件描述（自然语言）",
      "result": "触发后的结果描述（含不可逆性标注）",
      "side_effects": ["自然语言描述的副作用"],
      "difficulty": "None/regular/hard/extreme",
      "based_on": "I1"
    }}
  ]
}}

要求：
1. id 全局唯一 (E1, E2, E3...)
2. based_on 只能指向已知的 interaction ID (如 I1)，若此事件不是从特定互动派生的则填空字符串
3. result 中如果此事件不可逆，需明确标注"不可逆："并描述影响
4. type 选择关联的技能检定名称，不涉及填"无"
5. difficulty 从以下选择：None/regular/hard/extreme；不涉及检定则为 None
6. 不可逆事件包括：场景被破坏、NPC 死亡、关键物品销毁、时间节点等
7. 事件是全局的，不绑定特定场景（无 scene 字段）

精修模组：
\"\"\"
{condensed_text}
\"\"\""""
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_module_designer.py::test_build_step2b_events_prompt_structure -v`
Expected: may FAIL (test needs update for new format) — will fix in Task 9

- [ ] **Step 4: Commit**

```bash
git add src/module_designer/layered_parser.py
git commit -m "feat: rewrite Step 2b events prompt — unified fields, based_on, remove irreversible_impact"
```

---

### Task 6: Rewrite Step 2b auto_trigger prompt and parser

**Files:**
- Modify: `src/module_designer/layered_parser.py:394-458`

- [ ] **Step 1: Replace STEP2B_AT_SYSTEM**

```python
STEP2B_AT_SYSTEM = """你是一个 TRPG 模组解析助手，专门生成自动触发事件。
你的任务是：基于精修模组和已知互动，生成所有被动触发事件（auto_trigger）。

重要原则：
- auto_trigger 使用与 interaction 相同的统一字段模型（id, scene, type, name, requirement, trigger, result, side_effects, enemy_ref, weapon_ref, difficulty, based_on）
- auto_trigger 绑定特定场景（scene 字段必填）
- based_on 只能指向已知的 interaction ID（因为 Step 2b 并行，不能指向其他 auto_trigger 或 event）
- enemy_ref 和 weapon_ref 留空（填 null），等待 Step 4 library 匹配
- 只生成被动触发的事件，不要生成玩家主动互动
- 仅输出 JSON，不要任何解释性文字"""
```

- [ ] **Step 2: Replace build_step2b_at_prompt**

```python
def build_step2b_at_prompt(
    condensed_text: str,
    scenes: list[dict],
    interactions: list[dict],
) -> str:
    scene_list = "\n".join(f"- {s['id']}: {s['name']}" for s in scenes)
    interaction_list = "\n".join(
        f"- {i['id']}: {i['name']} → {i.get('result', '')} (场景 {i['scene']})"
        for i in interactions
    )
    return f"""从精修模组文本中生成所有自动触发事件。

已知场景:
{scene_list}

已知互动（auto_trigger 只能基于这些互动派生，based_on 必须指向其 ID）:
{interaction_list}

输出格式:
{{
  "auto_triggers": [
    {{
      "id": "AT1",
      "scene": "S1",
      "type": "关联技能名，不涉及填\"无\"",
      "name": "自动触发名称",
      "requirement": "前置条件声明（自然语言，可引用 interaction ID）",
      "trigger": "触发条件（自然语言，如：玩家进入场景且 I1 已完成）",
      "result": "触发后的结果描述",
      "side_effects": ["自然语言描述的副作用"],
      "enemy_ref": null,
      "weapon_ref": null,
      "difficulty": "None/regular/hard/extreme",
      "based_on": "I1"
    }}
  ]
}}

要求：
1. id 全局唯一 (AT1, AT2, AT3...)
2. scene 使用给定列表中的 ID
3. based_on 只能指向已知的 interaction ID (如 I1)，标注此 auto_trigger 从哪个互动派生
4. enemy_ref 和 weapon_ref 全部填 null（等 Step 4 匹配 library）
5. trigger 用自然语言描述触发条件，可引用已知的 interaction ID (如 I1) 或 event ID (如 E1)
6. type 选择关联的技能检定名称，不涉及填"无"
7. difficulty 从以下选择：None/regular/hard/extreme；不涉及检定则为 None
8. 每个场景至少生成 0-2 个 auto_trigger

精修模组：
\"\"\"
{condensed_text}
\"\"\""""
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_module_designer.py::test_build_step2b_at_prompt_structure -v`
Expected: may FAIL (test checks for old field names like `reveal_info`, `effect_ref`) — will fix in Task 9

- [ ] **Step 4: Commit**

```bash
git add src/module_designer/layered_parser.py
git commit -m "feat: rewrite Step 2b AT prompt — unified fields, based_on, remove effect_type/effect_ref/reveal_narrative"
```

---

### Task 7: Update Step 3a — side_effects structuring + based_on dependency resolution

**Files:**
- Modify: `src/module_designer/layered_parser.py:582-643`

- [ ] **Step 1: Replace STEP3A_SYSTEM**

```python
STEP3A_SYSTEM = """你是一个 TRPG 逻辑验证助手，专门做模组信息的依赖解析和统一。
你的任务是：检查所有 interaction/event/auto_trigger，解析 side_effects，利用 based_on 整理依赖关系，补全 requirement 引用。

重要原则：
- based_on 已标注派生关系（event/auto_trigger 的 based_on 指向派生的 interaction）
- requirement 从自然语言声明补全为具体引用（指向 interaction ID 或 event ID）
- 如果 event 和 auto_trigger 的 requirement/trigger 出现冲突，以 condensed_text 为准修正
- 不删改任何内容的实质信息，只修正名称和引用
- 互动完成即代表状态变更，不需要单独的 flag/标记
- 仅输出 JSON，不要任何解释性文字"""
```

- [ ] **Step 2: Replace build_step3a_prompt**

```python
def build_step3a_prompt(
    condensed_text: str,
    interactions: list[dict],
    events: list[dict],
    auto_triggers: list[dict],
) -> str:
    return f"""对以下模组中的所有 L2 内容做依赖解析、side_effect 结构化和冲突解决。

## 精修模组（参考上下文）
\"\"\"
{condensed_text}
\"\"\"

## Interactions
{json.dumps(interactions, ensure_ascii=False, indent=2)}

## Events（based_on 指向派生的 interaction，无 scene）
{json.dumps(events, ensure_ascii=False, indent=2)}

## Auto-triggers（based_on 指向派生的 interaction，有 scene）
{json.dumps(auto_triggers, ensure_ascii=False, indent=2)}

任务:
1. **Side_effect 结构化**: 将 interaction/event/auto_trigger 的 side_effects 从自然语言字符串列表解析为结构化对象列表。类型包括：
   - item_gain: {{"type": "item_gain", "item_name": "物品名"}}
   - stat_change: {{"type": "stat_change", "stat_name": "SAN/HP/...", "delta": -1}}
   - spawn_enemy: {{"type": "spawn_enemy", "enemy_ref": "敌人名", "scene": "场景ID", "trigger_condition": "触发条件", "quantity": 1}}
   - grant_item: {{"type": "grant_item", "item_ref": "武器/物品名", "scene": "场景ID"}}
   - npc_state_change: {{"type": "npc_state_change", "npc_name": "NPC名", "new_state": "新状态"}}
   无法归入以上类型的非结构性副作用直接保留字符串。
2. **基于 based_on 验证依赖**: 检查每条 event/auto_trigger 的 based_on 是否正确指向存在的 interaction。若 based_on 指向不存在的 ID，修正或清空。
3. **Interaction requirement 补全**: 将自然语言声明转为引用已知 interaction ID（如 "需要先找到钥匙" → "interaction:I3"）。
4. **Event requirement 补全**: 同上，可引用 interaction ID 或 event ID。
5. **Auto-trigger trigger 补全**: 同上。
6. **冲突解决**: 如果 event 和 auto_trigger 的 requirement/trigger 出现矛盾，以 condensed_text 为准修正。

输出格式:
{{
  "interactions": [{{ ...原字段..., "requirement": "补全后的引用", "side_effects": [结构化对象或字符串] }}],
  "events": [{{ ...原字段..., "requirement": "补全后的引用", "side_effects": [结构化对象或字符串] }}],
  "auto_triggers": [{{ ...原字段..., "trigger": "补全后的引用", "side_effects": [结构化对象或字符串] }}]
}}

仅输出 JSON。"""
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_module_designer.py::test_build_step3a_prompt_structure -v`
Expected: may FAIL (test checks for `flag` in prompt lowercase) — will fix in Task 9

- [ ] **Step 4: Commit**

```bash
git add src/module_designer/layered_parser.py
git commit -m "feat: update Step 3a — side_effects structuring, based_on validation, conflict resolution, remove flag unification"
```

---

### Task 8: Update Step 4 — extend to auto_triggers + skill standardization

**Files:**
- Modify: `src/module_designer/layered_parser.py:719-777`
- Modify: `src/module_designer/layered_pipeline.py:425-455`

- [ ] **Step 1: Update STEP4_SYSTEM**

```python
STEP4_SYSTEM = """你是一个 TRPG 游戏资源配置助手。
你的任务是：根据模组内容和场景需求，从给定的武器/敌人库中选择合适的资源填入占位符，并标准化技能名。

重要原则：
- 必须从提供的库列表中选择，不允许自创名称
- 若无合适的库条目，填 "none"
- 技能名必须从提供的标准技能列表中选择，不允许自创
- 仅输出 JSON，不要任何解释性文字"""
```

- [ ] **Step 2: Update build_step4_prompt signature and body**

Add `skill_names` parameter and skill standardization task:

```python
def build_step4_prompt(
    interactions: list[dict],
    auto_triggers: list[dict],
    l2_descriptions: dict[str, str],
    scene_intents: dict,
    condensed_text: str,
    weapon_library_names: list[str],
    enemy_library_names: list[str],
    skill_names: list[str],
) -> str:
    weapons_list = "\n".join(f"- {w}" for w in weapon_library_names)
    enemies_list = "\n".join(f"- {e}" for e in enemy_library_names)
    skills_list = "\n".join(f"- {s}" for s in skill_names)
    desc_list = "\n".join(f"- {sid}: {desc}" for sid, desc in l2_descriptions.items())
    return f"""为以下内容的 enemy_ref、weapon_ref 占位符填值，并标准化 type 技能名。

## 可用武器库
{weapons_list}

## 可用敌人库
{enemies_list}

## 标准技能列表（type 必须从此列表中选择）
{skills_list}

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
1. 为每个 enemy_ref 占位符从可用敌人库中选择匹配项。无匹配填 "none"。event（无 scene）跳过。
2. 为每个 weapon_ref 占位符从可用武器库中选择匹配项。无匹配填 "none"。event（无 scene）跳过。
3. 为每个 type 字段从标准技能列表中选择最匹配的技能名（如 "侦查"→"侦察"）。不涉及技能检定的 type 保持"无"不变。
4. 不允许自创名称。

输出格式:
{{
  "interactions": [{{ ...原字段..., "enemy_ref": "库中名称或none", "weapon_ref": "库中名称或none", "type": "标准技能名或\"无\"" }}],
  "auto_triggers": [{{ ...原字段..., "enemy_ref": "库中名称或none", "weapon_ref": "库中名称或none", "type": "标准技能名或\"无\"" }}]
}}

仅输出 JSON。"""
```

- [ ] **Step 3: Update parse_step4 signature**

```python
def parse_step4(
    interactions: list[dict],
    auto_triggers: list[dict],
    l2_descriptions: dict[str, str],
    scene_intents: dict,
    condensed_text: str,
    weapon_library_names: list[str],
    enemy_library_names: list[str],
    skill_names: list[str],
    llm_call,
) -> dict:
    prompt = build_step4_prompt(
        interactions, auto_triggers, l2_descriptions,
        scene_intents, condensed_text,
        weapon_library_names, enemy_library_names, skill_names,
    )
    return llm_call(prompt, system=STEP4_SYSTEM)
```

- [ ] **Step 4: Update pipeline to pass skill_names to Step 4**

In `layered_pipeline.py`, add skill loading before Step 4:

```python
    # 加载技能名列表
    skill_names = []
    try:
        import json as _json, os as _os
        skill_path = _os.path.join(_os.path.dirname(__file__), "..", "..", "data", "skill_checks.json")
        with open(skill_path, "r", encoding="utf-8") as _f:
            skill_checks = _json.load(_f)
            skill_names = sorted(set(s["name"] for s in skill_checks))
    except Exception:
        pass

    scene_intents_for_step4 = l3_data.get("scene_intents", {})

    if weapon_names or enemy_names or skill_names:
        def _do_step4():
            return parse_step4(
                interactions, auto_triggers, l2_descriptions,
                scene_intents_for_step4, condensed_text,
                weapon_names, enemy_names, skill_names, llm_json,
            )
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/ -x -q`
Expected: some tests may fail — fixed in Task 9

- [ ] **Step 6: Commit**

```bash
git add src/module_designer/layered_parser.py src/module_designer/layered_pipeline.py
git commit -m "feat: extend Step 4 to auto_triggers and add skill name standardization"
```

---

### Task 9: Update tests for new field formats

**Files:**
- Modify: `tests/test_module_designer.py:330-394`

- [ ] **Step 1: Update test_build_step2a_prompt_structure**

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
    assert "based_on" in prompt
    assert "scene_movements" in prompt
```

- [ ] **Step 2: Update test_build_step2b_events_prompt_structure**

```python
def test_build_step2b_events_prompt_structure():
    scenes = [{"id": "S1", "name": "6号车厢"}]
    interactions = [{"id": "I1", "name": "搜查", "scene": "S1", "side_effects": [], "result": "找到线索"}]
    prompt = build_step2b_events_prompt("精修模组内容", scenes, interactions)
    assert "精修模组内容" in prompt
    assert "events" in prompt
    assert "E1" in prompt
    assert "I1" in prompt
    assert "type" in prompt
    assert "difficulty" in prompt
    assert "based_on" in prompt
    assert "side_effects" in prompt
```

- [ ] **Step 3: Update test_build_step2b_at_prompt_structure**

```python
def test_build_step2b_at_prompt_structure():
    scenes = [{"id": "S1", "name": "6号车厢"}]
    interactions = [{"id": "I1", "name": "搜查", "scene": "S1", "side_effects": [], "result": "找到线索"}]
    prompt = build_step2b_at_prompt("精修模组内容", scenes, interactions)
    assert "精修模组内容" in prompt
    assert "auto_triggers" in prompt
    assert "AT1" in prompt
    assert "based_on" in prompt
    assert "enemy_ref" in prompt
    assert "weapon_ref" in prompt
    assert "difficulty" in prompt
    assert "type" in prompt
    # OLD fields should NOT be in prompt
    assert "effect_type" not in prompt
    assert "effect_ref" not in prompt
    assert "reveal_narrative" not in prompt
```

- [ ] **Step 4: Update test_build_step3a_prompt_structure**

```python
def test_build_step3a_prompt_structure():
    interactions = [{"id": "I1", "name": "搜查", "scene": "S1", "requirement": "需要先找到线索", "side_effects": [], "result": "找到线索"}]
    events = [{"id": "E1", "name": "事件", "requirement": "interaction I1 完成后", "type": "无", "difficulty": "None", "based_on": "I1", "side_effects": [], "result": "..."}]
    auto_triggers = [{"id": "AT1", "name": "触发", "scene": "S1", "trigger": "玩家进入场景", "type": "无", "based_on": "I1", "side_effects": [], "result": "..."}]
    prompt = build_step3a_prompt("精修模组", interactions, events, auto_triggers)
    assert "I1" in prompt
    assert "E1" in prompt
    assert "AT1" in prompt
    assert "based_on" in prompt
    assert "side_effects" in prompt
    # flag related content should not be prominent
    assert "结构化" in prompt or "item_gain" in prompt
```

- [ ] **Step 5: Run all tests**

Run: `python -m pytest tests/ -x -q`
Expected: 44 passed

- [ ] **Step 6: Commit**

```bash
git add tests/test_module_designer.py
git commit -m "test: update tests for unified triggerable entity format"
```

---

### Task 10: Final verification and integration test

**Files:**
- Verify: all modified files
- No code changes

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: all tests pass

- [ ] **Step 2: Verify imports work**

```bash
cd C:/Users/micha/PyCharmMiscProject && python -c "
import sys; sys.path.insert(0, 'src')
from module_designer.l2_keeper import AutoTrigger
from module_designer.layered_schema import L2_AUTO_TRIGGER_SCHEMA, L2_EVENT_SCHEMA
from module_designer.layered_parser import (
    build_step2a_prompt, build_step2b_events_prompt, build_step2b_at_prompt,
    build_step3a_prompt, build_step4_prompt,
)

# AutoTrigger has new fields
at = AutoTrigger(id='AT1', name='test', scene='S1', type='侦察', based_on='I1')
d = at.to_dict()
assert 'based_on' in d
assert 'effect_type' not in d
assert 'reveal_narrative' not in d
assert 'type' in d
assert 'difficulty' in d
print('AutoTrigger OK')

# Step 4 prompt accepts skill_names
prompt = build_step4_prompt(
    [{'id': 'I1', 'name': 'test', 'scene': 'S1', 'result': '', 'side_effects': [], 'type': '侦察', 'difficulty': 'regular', 'based_on': '', 'enemy_ref': None, 'weapon_ref': None, 'requirement': '', 'trigger': ''}],
    [{'id': 'AT1', 'name': 'test', 'scene': 'S1', 'result': '', 'side_effects': [], 'type': '侦察', 'difficulty': 'regular', 'based_on': 'I1', 'enemy_ref': None, 'weapon_ref': None, 'requirement': '', 'trigger': ''}],
    {'S1': 'desc'},
    {},
    'condensed',
    ['sword'],
    ['ghost'],
    ['侦察', '急救'],
)
assert '侦察' in prompt
assert '技能' in prompt
print('Step 4 OK')
print('All integration checks passed!')
"
```
Expected: `All integration checks passed!`

- [ ] **Step 3: Verify L2 template is valid**

Run: `python -c "import json; d=json.load(open('data/templates/l2_template.json')); at=d['scenes']['6号车厢']['auto_triggers'][0]; assert 'based_on' in at; assert 'effect_type' not in at; print('Template OK')"`
Expected: `Template OK`

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete unified triggerable entity format — all tests pass, integration verified"
```
