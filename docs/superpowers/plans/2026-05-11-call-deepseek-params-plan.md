# call_deepseek 可配置参数 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `call_deepseek` 增加 `model`、`thinking`、`reasoning_effort` 三个可选参数，保持向后兼容。

**Architecture:** 仅在 `src/llm.py` 的 `call_deepseek` 函数签名新增三个 keyword-only 参数，用 `None` 哨兵值保持默认行为不变。`json_mode=True` 和 `json_mode=False` 两个分支共享同一套参数解析逻辑。

**Tech Stack:** Python, OpenAI SDK (DeepSeek API)

---

### Task 1: 为 call_deepseek 增加可配置参数

**Files:**
- Modify: `src/llm.py:66-118`

- [ ] **Step 1: 修改函数签名和参数解析**

将当前签名 (line 66-67):
```python
def call_deepseek(prompt: str, *, json_mode: bool = True,
                  system: str = None) -> dict | str:
```

替换为:
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

然后在函数体开头（`if json_mode:` 之前）加入默认值解析逻辑:
```python
    _model = model if model is not None else "deepseek-v4-pro"
    _reasoning_effort = reasoning_effort if reasoning_effort is not None else "high"
    _thinking = thinking if thinking is not None else True
```

- [ ] **Step 2: 在 json_mode=True 分支中用变量替换硬编码值**

将:
```python
        model = "deepseek-v4-pro"
```
改为删除（移到上方统一解析），并将 `response = client.chat.completions.create(` 中的:
```python
            model=model,
```
改为:
```python
            model=_model,
```

将:
```python
            reasoning_effort="high",
```
改为:
```python
            reasoning_effort=_reasoning_effort,
```

将:
```python
            extra_body={"thinking": {"type": "enabled"}}
```
改为:
```python
            extra_body={"thinking": {"type": "enabled" if _thinking else "disabled"}}
```

- [ ] **Step 3: 在 json_mode=False 分支中用变量替换硬编码值**

同样的三处替换：
- `model = "deepseek-v4-pro"` → 删除此行
- `model=model` → `model=_model`
- `reasoning_effort="high"` → `reasoning_effort=_reasoning_effort`
- `extra_body={"thinking": {"type": "enabled"}}` → `extra_body={"thinking": {"type": "enabled" if _thinking else "disabled"}}`

- [ ] **Step 4: 验证 — 导入模块确认无语法错误**

```bash
cd src && python -c "from llm import call_deepseek; print('import OK')"
```
Expected: `import OK`

- [ ] **Step 5: 验证 — 默认参数签名兼容性**

```bash
cd src && python -c "
from llm import call_deepseek
import inspect
sig = inspect.signature(call_deepseek)
print('json_mode default:', sig.parameters['json_mode'].default)
print('model default:', sig.parameters['model'].default)
print('thinking default:', sig.parameters['thinking'].default)
print('reasoning_effort default:', sig.parameters['reasoning_effort'].default)
"
```
Expected: 各默认值分别为 `True`, `None`, `None`, `None`

- [ ] **Step 6: 提交**

```bash
git add src/llm.py
git commit -m "feat: add model, thinking, reasoning_effort params to call_deepseek"
```
