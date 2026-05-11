# call_deepseek 可配置参数设计

**日期**: 2026-05-11  
**范围**: `src/llm.py` — `call_deepseek` 函数

## 动机

当前 `call_deepseek` 硬编码了模型名称 (`deepseek-v4-pro`)、思考模式开关 (`thinking: enabled`) 和推理强度 (`reasoning_effort: high`)。在调试或切换模型时需要修改源码，不够灵活。

## 设计

### 新签名

```python
def call_deepseek(
    prompt: str, *,
    json_mode: bool = True,
    system: str = None,
    model: str | None = None,
    thinking: bool | None = None,
    reasoning_effort: str | None = None,
) -> dict | str:
```

### 默认值解析

| 参数 | 默认值 (当 None) | 说明 |
|------|------------------|------|
| `model` | `"deepseek-v4-pro"` | 与当前硬编码一致 |
| `thinking` | `True` | `extra_body={"thinking": {"type": "enabled"}}` |
| `reasoning_effort` | `"high"` | 与当前硬编码一致 |

`thinking=False` 时 `extra_body` 为 `{"thinking": {"type": "disabled"}}`。

### 向后兼容

所有现有调用无需修改，原有参数位置和含义不变。`json_mode` 和 `system` 保持不变。

### 不在范围内的改动

- `call_deepseek_json` / `call_deepseek_write` / `call_deepseek_summarize` 保持现有硬编码行为不变
- `notebook_simplified.ipynb` 和 `game_loop.py` 中的调用方不做任何修改

## 实现要点

1. 在 `json_mode=True` 和 `json_mode=False` 两个分支中，统一用解析后的 `_model`、`_thinking`、`_reasoning_effort` 替代硬编码值
2. `_thinking` 控制 `extra_body["thinking"]["type"]` 为 `"enabled"` 或 `"disabled"`
3. 参数全部为 keyword-only（在 `*` 之后），保留现有风格
