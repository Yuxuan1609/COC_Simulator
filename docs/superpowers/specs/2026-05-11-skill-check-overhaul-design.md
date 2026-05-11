# Skill Check 系统全面更新 — 设计文档

**日期**: 2026-05-11  
**范围**: `src/investigator/models.py`, `src/game_loop.py`, `src/scenario_core.py`, `src/utils.py`, `data/skill_checks.json`

## 动机

当前 `SkillSystem` 为占位实现（始终返回成功），`_execute_single_action` 内调用技能鉴定但忽略返回值。需要实装 COC 7th 检定规则，将技能闸门从动作执行中分离，由 `Investigator` 类承担检定职责。

## 设计

### 检定规则（COC 7th）

- **投 D100**，结果 **≤ 技能值 → 成功**，**> 技能值 → 失败**
- **大成功**: 出目 01（当前版本暂不区分，预留 `difficulty` 参数接口）
- **大失败**: 96-100（当前版本暂不区分，预留）
- **未掌握技能**: 调查员技能列表中不存在该技能名 → 默认成功（避免因缺少冷门技能卡关）
- **难度扩展**: `check_skill()` 预置 `difficulty` 参数（`"regular"` / `"hard"` / `"extreme"`），当前仅实现 `regular`，`hard` 阈值 ≤½，`extreme` 阈值 ≤⅕ 为后续扩展预留

### 数据文件: `data/skill_checks.json`

技能名到属性的映射表，供 parser 等模块和未来属性对抗检定使用。

```json
[
  {
    "name": "侦查",
    "linked_attribute": "INT",
    "base_value": 25,
    "category": "感知"
  }
]
```

字段说明：
- `name`: 技能名（必须与 `Investigator.skills` 中的技能名匹配）
- `linked_attribute`: 关联属性（STR/CON/SIZ/DEX/APP/INT/POW/EDU），用于未来属性对抗
- `base_value`: COC 7th 标准基础值
- `category`: 技能分类（战斗/社交/知识/感知/操作/通用）

加载函数 `load_skill_checks()` 放在 `src/utils.py`，与 `load_occupations()`（位于 `rules.py`）区分，因为 parser 等模块也需要加载技能定义但不应依赖 `investigator.rules`。

### `Investigator` 新增方法

```python
def check_skill(self, skill_name: str, difficulty: str = "regular") -> tuple[bool, str]:
    """COC 7th 技能检定。返回 (是否成功, 结果描述)"""

def check_skills(self, skill_names: list[str]) -> tuple[bool, str]:
    """批量技能检定（AND 逻辑）。全部通过返回 True"""
```

- `check_skill`: 单技能检定，查找调查员技能列表，未找到默认成功
- `check_skills`: 批量检定，任一失败即整体失败，返回 `(False, 合并结果文本)`
- 结果文本格式: `"侦查检定：D100=45/60 ≤ 成功"` 或 `"格斗检定：D100=72/50 > 失败"`

### game_loop 流程变更

`_execute_single_action` 变为纯动作执行器，移除技能相关逻辑。

`handle_user_input` 中，每个 action 执行前新增 skill gate：

```
for act in scene_actions:
    ├─ condition 检查（已有，不变）
    ├─ skill gate（新增）
    │    ├─ 提取 act["skill_checks"]
    │    ├─ world.player.check_skills(names)
    │    ├─ all pass → 继续
    │    └─ any fail → 记录结果，跳过 _execute_single_action
    └─ _execute_single_action（移除内部 skill 逻辑后）
```

### 移除内容

| 位置 | 内容 |
|------|------|
| `scenario_core.py:214-225` | `SkillSystem` 类（整个类） |
| `game_loop.py:13` | `from scenario_core import SkillSystem` |
| `game_loop.py:29-31` | `_execute_single_action` 内 skill_checks 调用 |
| `investigator/models.py:114` | `skills_dict` docstring 中 `SkillSystem` 引用 |

### 保留

- `prompts.py:_build_skill_results()` — 纯函数，未来用于将检定结果注入叙事 prompt
- `investigator/models.py:skills_dict` — 属性本身保留，仅更新 docstring

## 改动清单

| # | 文件 | 操作 |
|---|------|------|
| 1 | `data/skill_checks.json` | 新建 |
| 2 | `src/utils.py` | 新增 `load_skill_checks()` |
| 3 | `src/investigator/models.py` | 新增 `check_skill()` / `check_skills()`；更新 `skills_dict` docstring |
| 4 | `src/game_loop.py` | skill gate 前置；移除 `SkillSystem` 导入；精简 `_execute_single_action` |
| 5 | `src/scenario_core.py` | 删除 `SkillSystem` 类及其注释块 |
