# Skill Check 系统全面更新 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实装 COC 7th D100 技能检定规则，将 skill check 从 `_execute_single_action` 分离并合并到 `Investigator` 类，移除占位 `SkillSystem`。

**Architecture:** 检定逻辑内聚在 `Investigator.check_skill()` / `check_skills()`，`game_loop` 在动作执行前调用作为闸门。技能定义 JSON 由 `utils.load_skill_checks()` 加载。战斗检定预留 stub 方法。

**Tech Stack:** Python stdlib (`random`, `json`), 无新依赖

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `data/skill_checks.json` | 新建 | 45 项 COC 技能定义（名称、关联属性、基础值、分类） |
| `src/utils.py` | 修改 | 新增 `load_skill_checks()` 加载函数 |
| `src/investigator/models.py` | 修改 | 新增 `check_skill()` / `check_skills()` / `combat_check()` / `damage_roll()` |
| `src/game_loop.py` | 修改 | skill gate 前置；移除 `SkillSystem` 导入；精简 `_execute_single_action` |
| `src/scenario_core.py` | 修改 | 删除 `SkillSystem` 类 |

---

### Task 1: 创建 skill_checks.json 并添加加载函数

**Files:**
- Create: `data/skill_checks.json`
- Modify: `src/utils.py`

- [ ] **Step 1: 创建 data/skill_checks.json**

包含 COC 7th 全部 45 项标准技能，格式与 spec 一致：

```json
[
  {"name": "会计", "linked_attribute": "INT", "base_value": 5, "category": "知识"},
  {"name": "人类学", "linked_attribute": "INT", "base_value": 1, "category": "知识"},
  {"name": "估价", "linked_attribute": "INT", "base_value": 5, "category": "知识"},
  {"name": "考古学", "linked_attribute": "INT", "base_value": 1, "category": "知识"},
  {"name": "魅惑", "linked_attribute": "APP", "base_value": 15, "category": "社交"},
  {"name": "攀爬", "linked_attribute": "STR", "base_value": 20, "category": "操作"},
  {"name": "计算机使用", "linked_attribute": "INT", "base_value": 5, "category": "知识"},
  {"name": "信用评级", "linked_attribute": "INT", "base_value": 0, "category": "社交"},
  {"name": "克苏鲁神话", "linked_attribute": "INT", "base_value": 0, "category": "知识"},
  {"name": "乔装", "linked_attribute": "APP", "base_value": 5, "category": "社交"},
  {"name": "汽车驾驶", "linked_attribute": "DEX", "base_value": 20, "category": "操作"},
  {"name": "电气维修", "linked_attribute": "INT", "base_value": 10, "category": "操作"},
  {"name": "电子学", "linked_attribute": "INT", "base_value": 1, "category": "知识"},
  {"name": "话术", "linked_attribute": "APP", "base_value": 5, "category": "社交"},
  {"name": "格斗", "linked_attribute": "DEX", "base_value": 25, "category": "战斗"},
  {"name": "枪械", "linked_attribute": "DEX", "base_value": 20, "category": "战斗"},
  {"name": "急救", "linked_attribute": "INT", "base_value": 30, "category": "操作"},
  {"name": "历史", "linked_attribute": "EDU", "base_value": 5, "category": "知识"},
  {"name": "恐吓", "linked_attribute": "APP", "base_value": 15, "category": "社交"},
  {"name": "跳跃", "linked_attribute": "STR", "base_value": 20, "category": "操作"},
  {"name": "外语", "linked_attribute": "EDU", "base_value": 1, "category": "知识"},
  {"name": "母语", "linked_attribute": "EDU", "base_value": 50, "category": "知识"},
  {"name": "法律", "linked_attribute": "EDU", "base_value": 5, "category": "知识"},
  {"name": "图书馆使用", "linked_attribute": "INT", "base_value": 20, "category": "知识"},
  {"name": "聆听", "linked_attribute": "POW", "base_value": 20, "category": "感知"},
  {"name": "锁匠", "linked_attribute": "DEX", "base_value": 1, "category": "操作"},
  {"name": "机械维修", "linked_attribute": "INT", "base_value": 10, "category": "操作"},
  {"name": "医学", "linked_attribute": "EDU", "base_value": 1, "category": "知识"},
  {"name": "博物学", "linked_attribute": "INT", "base_value": 10, "category": "知识"},
  {"name": "导航", "linked_attribute": "INT", "base_value": 10, "category": "知识"},
  {"name": "神秘学", "linked_attribute": "INT", "base_value": 5, "category": "知识"},
  {"name": "操作重型机械", "linked_attribute": "DEX", "base_value": 1, "category": "操作"},
  {"name": "说服", "linked_attribute": "APP", "base_value": 10, "category": "社交"},
  {"name": "驾驶", "linked_attribute": "DEX", "base_value": 20, "category": "操作"},
  {"name": "心理学", "linked_attribute": "POW", "base_value": 10, "category": "感知"},
  {"name": "精神分析", "linked_attribute": "INT", "base_value": 1, "category": "知识"},
  {"name": "骑术", "linked_attribute": "DEX", "base_value": 5, "category": "操作"},
  {"name": "科学", "linked_attribute": "EDU", "base_value": 1, "category": "知识"},
  {"name": "妙手", "linked_attribute": "DEX", "base_value": 10, "category": "操作"},
  {"name": "潜行", "linked_attribute": "DEX", "base_value": 20, "category": "操作"},
  {"name": "侦查", "linked_attribute": "INT", "base_value": 25, "category": "感知"},
  {"name": "生存", "linked_attribute": "CON", "base_value": 10, "category": "操作"},
  {"name": "游泳", "linked_attribute": "STR", "base_value": 20, "category": "操作"},
  {"name": "投掷", "linked_attribute": "DEX", "base_value": 20, "category": "战斗"},
  {"name": "追踪", "linked_attribute": "INT", "base_value": 10, "category": "感知"}
]
```

- [ ] **Step 2: 在 src/utils.py 末尾添加 load_skill_checks()**

```python
# ── 技能检定定义加载 ──

def load_skill_checks(path: str = "data/skill_checks.json") -> list:
    """加载技能检定定义表，返回列表 [{name, linked_attribute, base_value, category}, ...]"""
    import json
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
```

- [ ] **Step 3: 验证 — 加载 JSON 并检查结构**

```bash
cd src && python -c "
from utils import load_skill_checks
skills = load_skill_checks('../data/skill_checks.json')
print(f'Loaded {len(skills)} skills')
for s in skills[:3]:
    print(f'  {s[\"name\"]} -> {s[\"linked_attribute\"]}')
print('OK')
"
```
Expected: `Loaded 45 skills` + 前三个技能输出 + `OK`

- [ ] **Step 4: 提交**

```bash
git add data/skill_checks.json src/utils.py
git commit -m "feat: add skill_checks.json data file and load_skill_checks()"
```

---

### Task 2: 为 Investigator 添加技能检定方法

**Files:**
- Modify: `src/investigator/models.py`
- Modify: `src/investigator/__init__.py` (确认导出)

- [ ] **Step 1: 在 models.py 顶部添加 random 导入**

在 `import math` 之后添加：
```python
import random
```

- [ ] **Step 2: 在 Investigator 类中添加 check_skill() 方法**

在 `get_skill_value()` 方法之后（line 127 之后），`_recalc_derived` 之前插入：

```python
    # ── 技能检定（COC 7th D100 规则）──

    def check_skill(self, skill_name: str, difficulty: str = "regular") -> tuple[bool, str]:
        """
        COC 7th 技能检定：投掷 D100，结果 ≤ 技能值则为成功。

        difficulty（预留，当前仅实现 regular）:
          - "regular": 阈值 = 技能值
          - "hard":    阈值 = floor(技能值 / 2)
          - "extreme": 阈值 = floor(技能值 / 5)

        若调查员未拥有该技能，默认判定成功（避免缺少冷门技能卡关）。
        返回 (是否成功, 结果描述文本)。
        """
        skill = self.get_skill(skill_name)
        if skill is None:
            return True, f"{skill_name}（未掌握，默认判定成功）"

        roll = random.randint(1, 100)

        # 难度修正（模板代码，hard/extreme 待后续实装）
        threshold = skill.value
        if difficulty == "hard":
            threshold = skill.value // 2
        elif difficulty == "extreme":
            threshold = skill.value // 5

        success = roll <= threshold
        op = "≤" if success else ">"
        detail = f"{skill_name}检定：D100={roll}/{threshold} {op} {'成功' if success else '失败'}"
        return success, detail

    def check_skills(self, skill_names: list[str]) -> tuple[bool, str]:
        """
        批量技能检定（AND 逻辑）。全部通过返回 (True, 合并结果文本)；
        任一失败返回 (False, 合并结果文本)。
        """
        results = []
        all_pass = True
        for name in skill_names:
            ok, msg = self.check_skill(name)
            results.append(msg)
            if not ok:
                all_pass = False
        return all_pass, "；".join(results)
```

- [ ] **Step 3: 在 Investigator 类末尾添加战斗检定预留 stub**

在 `__repr__` 方法之前（line 163 之前）插入：

```python
    # ── 战斗技能鉴定（预留，当前未实装）──

    def combat_check(self, weapon_name: str, target: "Investigator") -> tuple[bool, str]:
        """战斗技能鉴定（预留）。实装时需实现：武器技能检定 + DB 加值 + 闪避对抗。"""
        raise NotImplementedError("战斗系统尚未实现")

    def damage_roll(self, weapon_name: str) -> tuple[int, str]:
        """伤害掷骰（预留）。实装时需实现：伤害公式解析（如 1D3+DB）+ DB 应用。"""
        raise NotImplementedError("战斗系统尚未实现")
```

- [ ] **Step 4: 更新 skills_dict docstring**

将 line 112-114:
```python
    @property
    def skills_dict(self) -> Dict[str, int]:
        """返回 {技能名: 当前值} 映射，兼容 game_loop / SkillSystem"""
        return {s.name: s.value for s in self.skills}
```

改为:
```python
    @property
    def skills_dict(self) -> Dict[str, int]:
        """返回 {技能名: 当前值} 映射"""
        return {s.name: s.value for s in self.skills}
```

- [ ] **Step 5: 验证 — 技能检定基本功能**

```bash
cd src && python -c "
from investigator import Investigator
from investigator.rules import roll_stats, calc_derived, create_skill_list

inv = Investigator(name='Test', age=25)
inv.stats = roll_stats()
inv.skills = create_skill_list()
inv.derived = calc_derived(inv.stats, inv.age)

# 测试已知技能
ok, msg = inv.check_skill('侦查')
print(f'Known skill: ok={ok}, msg={msg}')

# 测试未知技能
ok, msg = inv.check_skill('灵感')
print(f'Unknown skill: ok={ok}, msg={msg}')

# 测试批量
ok, msg = inv.check_skills(['侦查', '图书馆使用'])
print(f'Multi skill: ok={ok}, msg={msg[:80]}...')

# 测试战斗 stub
try:
    inv.combat_check('徒手', inv)
except NotImplementedError as e:
    print(f'Combat stub: {e}')

print('OK')
"
```
Expected: 含 `OK` 输出（检定结果因随机掷骰而异，但无异常）

- [ ] **Step 6: 提交**

```bash
git add src/investigator/models.py
git commit -m "feat: add check_skill/check_skills to Investigator, combat stubs"
```

---

### Task 3: 重构 game_loop — 分离 skill gate 与 action 执行

**Files:**
- Modify: `src/game_loop.py`

- [ ] **Step 1: 移除 SkillSystem 导入**

删除 line 13:
```python
from scenario_core import SkillSystem
```

- [ ] **Step 2: 精简 _execute_single_action，移除技能鉴定逻辑**

删除 lines 29-31:
```python
    skill_checks = act.get("skill_checks", [])
    if skill_checks and world.player:
        SkillSystem.check_multiple(world.player, skill_checks)
```

- [ ] **Step 3: 修改 handle_user_input 中的动作执行循环，添加 skill gate**

将 lines 103-112:
```python
    for act in scene_actions:
        condition = act.get("condition", "")
        if condition:
            result = f"（无法执行：{condition}）"
            success = False
        else:
            result, success = _execute_single_action(act, world, location)
        action_results.append(result)
        if not success:
            overall_success = False
```

替换为:
```python
    for act in scene_actions:
        condition = act.get("condition", "")
        if condition:
            result = f"（无法执行：{condition}）"
            success = False
        else:
            # ═══ 技能闸门（COC 7th D100 检定）═══
            skill_checks = act.get("skill_checks", [])
            if skill_checks and world.player:
                all_pass, skill_result = world.player.check_skills(skill_checks)
                if not all_pass:
                    action_results.append(skill_result)
                    overall_success = False
                    continue
            result, success = _execute_single_action(act, world, location)
        action_results.append(result)
        if not success:
            overall_success = False
```

- [ ] **Step 4: 验证 — 导入 game_loop 确认无语法错误**

```bash
cd src && python -c "
from game_loop import handle_user_input, _execute_single_action
print('import OK')
"
```
Expected: `import OK`

- [ ] **Step 5: 提交**

```bash
git add src/game_loop.py
git commit -m "refactor: separate skill gate from _execute_single_action"
```

---

### Task 4: 删除 SkillSystem 占位类

**Files:**
- Modify: `src/scenario_core.py`

- [ ] **Step 1: 删除 SkillSystem 类定义**

删除 `src/scenario_core.py` lines 210-225:
```python
# ═══════════════════════════════════════════════════════════════
#  技能鉴定系统
# ═══════════════════════════════════════════════════════════════

class SkillSystem:
    """技能鉴定系统 —— 当前为占位实现，始终返回成功"""

    @staticmethod
    def check(player: Player, skill_name: str) -> Tuple[bool, str]:
        """执行单项技能鉴定。占位：始终成功。"""
        return True, f"{skill_name}鉴定成功"

    @staticmethod
    def check_multiple(player: Player, skill_names: List[str]) -> Dict[str, Tuple[bool, str]]:
        """批量执行技能鉴定"""
        return {name: SkillSystem.check(player, name) for name in skill_names}
```

- [ ] **Step 2: 验证 — 确认 SkillSystem 已移除，scenario_core 仍可导入**

```bash
cd src && python -c "
from scenario_core import DirectedGraph, ScenarioWorld, MemoryManager, RequirementResolver
print('scenario_core import OK')

# 确认 SkillSystem 已删除
try:
    from scenario_core import SkillSystem
    print('ERROR: SkillSystem still exists')
except ImportError:
    print('SkillSystem removed OK')
"
```
Expected: `scenario_core import OK` + `SkillSystem removed OK`

- [ ] **Step 3: 验证 — game_loop 仍可导入（不再依赖 SkillSystem）**

```bash
cd src && python -c "
from game_loop import handle_user_input
print('game_loop import OK (no SkillSystem dependency)')
"
```
Expected: `game_loop import OK (no SkillSystem dependency)`

- [ ] **Step 4: 提交**

```bash
git add src/scenario_core.py
git commit -m "refactor: remove SkillSystem placeholder class"
```

---

### Task 5: 集成验证

**Files:** 无修改，仅验证

- [ ] **Step 1: 完整导入链验证**

```bash
cd src && python -c "
from investigator import Investigator, load_investigator
from investigator.rules import roll_stats, calc_derived, create_skill_list
from scenario_core import DirectedGraph, ScenarioWorld
from game_loop import handle_user_input
from prompts import build_action_prompt, build_event_prompt, build_narrative_prompt, _build_skill_results
from utils import load_skill_checks

print('All modules imported OK')
"
```
Expected: `All modules imported OK`

- [ ] **Step 2: 技能检定端到端流程验证**

```bash
cd src && python -c "
from investigator import Investigator
from investigator.rules import roll_stats, calc_derived, create_skill_list

# 创建调查员
inv = Investigator(name='E2E Test', age=30)
inv.stats = roll_stats()
inv.skills = create_skill_list()
inv.derived = calc_derived(inv.stats, inv.age)

# 模拟 game_loop skill gate 流程
skill_names = ['侦查', '聆听']
all_pass, msg = inv.check_skills(skill_names)
print(f'Skill gate result: all_pass={all_pass}')
print(f'  {msg}')

# 模拟未知技能（应默认成功）
ok, msg = inv.check_skill('灵感')
assert ok is True, 'Unknown skill should default to success'
print(f'Unknown skill default: ok={ok}')

# 验证战斗 stub
try:
    inv.combat_check('徒手', inv)
    assert False, 'Should have raised'
except NotImplementedError:
    print('Combat stub: NotImplementedError OK')

print('E2E verification passed')
"
```
Expected: `E2E verification passed`

- [ ] **Step 3: 提交**

```bash
git add -A
git commit -m "test: add integration verification for skill check system"
```
