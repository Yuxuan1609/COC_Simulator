# 多动作识别设计

## 概述

修改 `build_action_prompt` 和 `handle_user_input`，使系统能从单次用户输入中识别多个连续意图（如"检查桌子然后去7号车厢"），返回 actions 数组并依次执行。

**处理模式：批量执行 → 统一后续** — 所有动作依次执行 → 一次事件判定 → 一次世界更新 → 一次叙事。

---

## `build_action_prompt` 改动

### 输出格式

从单个 action 对象改为 `actions` 数组：

```json
{
  "actions": [
    {
      "action": "interact",
      "interaction": "检查桌子",
      "skill_checks": ["侦查"],
      "reasoning": "玩家想检查桌子"
    },
    {
      "action": "move",
      "target": "7号车厢",
      "skill_checks": [],
      "reasoning": "然后前往7号车厢"
    }
  ]
}
```

### prompt 规则变更

- 原有 action 类型语义不变（move/interact/search/look/other）
- 新增：如果用户输入包含多个连续意图，按先后顺序拆分为多个 action
- 如果只有单一意图，`actions` 仍包含 1 个元素（向后兼容）
- 每个 action 的 `skill_checks` 只列当前动作需要的技能

---

## `handle_user_input` 改动

### 动作执行改为循环

```python
actions = action_data.get("actions", [])
if not actions:
    actions = [{"action": "other"}]

action_results = []
overall_success = True
for act in actions:
    action = act.get("action", "other")
    # ... 原有 if/elif 执行逻辑 ...
    action_results.append(action_result)
    if not success:
        overall_success = False
    # 失败不中断，继续执行后续动作

action_result = "\n".join(action_results)
```

### 边界规则

- 某个动作失败不影响后续动作执行（动作间默认不相关）
- 若 `actions` 为空数组或缺失，降级为 `[{"action": "other"}]`
- 技能鉴定仍按每个 action 独立提取和执行

---

## 下游影响

| 阶段 | 影响 |
|------|------|
| 阶段2（事件判定） | 不变，接收合并后的 `action_result` 和原始 `user_input` |
| 阶段1.5（世界更新） | 不变，基于合并后的 `action_result` |
| 阶段3（叙事生成） | 不变，基于合并后的 `action_result` |

---

## 涉及文件

| 文件 | 改动 |
|------|------|
| `notebooks/notebook_simplified.ipynb` cell `97f37a6dac767b62` | `build_action_prompt` prompt 规则更新、输出格式改为 `actions` 数组 |
| `notebooks/notebook_simplified.ipynb` cell `a75d484cd40fc0e1` | `handle_user_input` 动作执行改为循环，合并多个结果 |
