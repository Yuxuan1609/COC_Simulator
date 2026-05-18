# Dependency Graph + Runtime State / Requirement 解析 Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `world.flags` dict with `dependency_graph` (static skeleton) + `runtime_state` (dynamic overlay), and rewrite requirement parsing with proper AND/OR logic.

**Architecture:** Two-layer state model. `dependency_graph` (nodes + edges from L2) is read-only after load — it defines entity dependencies. `runtime_state: Dict[str, NodeRuntimeState]` is written by Judge — it tracks completion, result tier, retries, and escalated difficulty. Requirement strings parse with `AND` at top level, `OR` at secondary level; edges handle simple AND dependencies structurally.

**Tech Stack:** Python 3.11+, dataclasses, regex-based requirement parser

---

## File Structure

| File | Role |
|---|---|
| `scenario_core.py` | `NodeRuntimeState`, `DependencyNode`, `DependencyEdge` dataclasses; `ScenarioWorld` owns `runtime_state` and `dependency_graph`; requirement parsing functions |
| `game/judge.py` | `_execute_entity` writes `runtime_state` instead of flags; uses new requirement parser |
| `game/agents/keeper.py` | `process_turn` passes `dependency_graph` to Judge; wires runtime_state into enrich |
| `prompts.py` | Entity format adapts to new requirement structure (already mostly done) |
| `game_loop.py` | `init_game` loads `dependency_graph` from L2 into `ScenarioWorld` |

`src/llm.py` is NOT modified — `evaluate_failure_penalty` / `evaluate_trait_enhancement` unchanged.

---

### Task 1: Define data structures in scenario_core.py

**Files:**
- Modify: `src/scenario_core.py`
- No test file needed (dataclass definitions)

- [ ] **Step 1: Add NodeRuntimeState, DependencyNode, DependencyEdge dataclasses**

Add after line 40 (after existing `Requirement` class):

```python
@dataclass
class DependencyNode:
    """Static node in the L2 dependency graph."""
    entity_id: str          # "I1"
    entity_type: str        # "interaction" | "auto_trigger" | "event"
    name: str = ""          # optional display name


@dataclass
class DependencyEdge:
    """Static edge in the L2 dependency graph. source depends on target."""
    source: str             # "I2" (who depends)
    target: str             # "I1" (on whom)
    dep_type: str = "interaction"
    condition: str = "success"  # "success" | "fail" | "completed" | "Uncompleted"


@dataclass
class NodeRuntimeState:
    """Dynamic runtime state for each entity. Written by Judge, read by requirement parser."""
    completed: bool = False
    result_tier: str = ""          # "" | "fumble" | "failure" | "regular" | "hard" | "extreme"
    retries: int = 0
    escalated_difficulty: str = "" # "hard" | "extreme"
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "from scenario_core import DependencyNode, DependencyEdge, NodeRuntimeState; s = NodeRuntimeState(); print('OK')"` from `src/`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/scenario_core.py
git commit -m "feat: add DependencyNode, DependencyEdge, NodeRuntimeState dataclasses"
```

---

### Task 2: Add runtime_state to ScenarioWorld, load dependency_graph

**Files:**
- Modify: `src/scenario_core.py` (ScenarioWorld class)

- [ ] **Step 1: Add runtime_state field + remove flags in ScenarioWorld.__init__**

In `ScenarioWorld.__init__` (line 679), replace:
```python
self.flags: Dict[str, bool] = {}
```
with:
```python
self.runtime_state: Dict[str, NodeRuntimeState] = {}
self.dependency_graph: Dict[str, Any] = {}
```

Also remove `self.requirement_resolver = RequirementResolver(self)` (line 686) — unused.

- [ ] **Step 2: Add methods to load/access dependency_graph and runtime_state**

Add after `__init__`:

```python
def load_dependency_graph(self, dep_graph: dict):
    """Load L2 dependency graph into runtime-ready structures."""
    self.dependency_graph = dep_graph
    nodes = dep_graph.get("nodes", {})
    # initialize runtime_state for every node
    for eid, node_data in nodes.items():
        if eid not in self.runtime_state:
            self.runtime_state[eid] = NodeRuntimeState()

def get_runtime_state(self, entity_id: str) -> NodeRuntimeState:
    """Get or create runtime state for an entity."""
    if entity_id not in self.runtime_state:
        self.runtime_state[entity_id] = NodeRuntimeState()
    return self.runtime_state[entity_id]

def get_incoming_edges(self, entity_id: str) -> list[dict]:
    """Get all edges where source == entity_id (i.e., what entity_id depends on)."""
    edges = self.dependency_graph.get("edges", [])
    return [e for e in edges if e.get("source") == entity_id]
```

- [ ] **Step 3: Replace set_flag/get_flag with runtime_state operations**

Replace body of `set_flag`:
```python
def set_flag(self, key: str, value: bool = True):
    """DEPRECATED: Use runtime_state directly. Kept for backward compat during migration."""
    pass  # no-op; remove callers instead
```

Replace body of `get_flag`:
```python
def get_flag(self, key: str) -> bool:
    """DEPRECATED: Use runtime_state directly. Kept for backward compat during migration."""
    return False  # no-op; remove callers instead
```

Add `toggle_flag` as no-op too:
```python
def toggle_flag(self, key: str):
    """DEPRECATED: Use runtime_state directly."""
    pass
```

- [ ] **Step 4: Verify syntax**

Run: `python -c "from scenario_core import ScenarioWorld, DirectedGraph; w = ScenarioWorld(DirectedGraph(scenes={},events=[]), ''); print(w.runtime_state)"` from `src/`

Expected: `{}`

- [ ] **Step 5: Commit**

```bash
git add src/scenario_core.py
git commit -m "feat: add runtime_state + dependency_graph to ScenarioWorld, deprecate flags"
```

---

### Task 3: Implement requirement string parser (AND/OR logic)

**Files:**
- Modify: `src/scenario_core.py` (add module-level function)

- [ ] **Step 1: Write `parse_hard_requirement()` function**

Add after `_ENTITY_ID_RE` area in scenario_core.py (or in a clean spot near the top, after dataclass definitions):

```python
import re as _re

_ENTITY_ID_PATTERN = _re.compile(r'^[IEA]+\d+[a-z]?$')


def _extract_entity_id(text: str) -> str | None:
    """Extract entity ID from a cleaned group string. Returns None if no ID found."""
    match = _ENTITY_ID_PATTERN.match(text)
    return match.group(0) if match else None


def parse_hard_requirement(hard: str, runtime_state: dict) -> bool:
    """Parse the hard portion of a requirement string.

    Format:
        and_group ("AND" and_group)*
        and_group = or_group ("OR" or_group)*
        or_group  = entity_id (after stripping parens/spaces)

    Returns True if ALL AND groups pass.
    An AND group passes if ANY of its OR groups passes.
    An OR group passes if its entity_id is completed in runtime_state.
    Groups with no recognizable entity ID pass automatically (graceful degradation).
    """
    if not hard or not hard.strip():
        return True

    # Step 1: split top-level AND
    and_parts = _split_top_level(hard, "AND")

    for and_group in and_parts:
        # Step 2: split secondary OR
        or_parts = _split_top_level(and_group, "OR")

        or_pass = False
        for or_group in or_parts:
            # Step 3: clean and extract entity ID
            cleaned = _clean_group(or_group)
            eid = _extract_entity_id(cleaned)

            if eid is None:
                # No recognizable ID → pass this group (LLM-generator grace)
                or_pass = True
                break

            state = runtime_state.get(eid)
            if state and state.completed:
                or_pass = True
                break

        if not or_pass:
            return False  # This AND group failed entirely

    return True  # All AND groups passed


def _split_top_level(text: str, sep: str) -> list[str]:
    """Split by separator but respect parenthesized groups as atomic units."""
    # Simple approach: split by sep, then merge any parts where parentheses
    # are unbalanced back into the preceding group.
    parts = text.split(sep)
    result = []
    buf = []
    for part in parts:
        buf.append(part)
        joined = sep.join(buf)
        if joined.count("(") == joined.count(")"):
            result.append(joined.strip())
            buf = []
    if buf:
        result.append(sep.join(buf).strip())
    return [r for r in result if r]


def _clean_group(text: str) -> str:
    """Strip parentheses, spaces, and Chinese punctuation from a group."""
    return text.strip().strip("()（） \t")
```

- [ ] **Step 2: Verify logic with test cases**

Run: `python -c "` from `src/`:

```python
from scenario_core import parse_hard_requirement, NodeRuntimeState

# Test 1: simple ID
rs = {}
rs["I1"] = NodeRuntimeState(completed=True)
assert parse_hard_requirement("I1", rs) == True

# Test 2: OR
rs2 = {"I12a": NodeRuntimeState(completed=True), "I12b": NodeRuntimeState(completed=False)}
assert parse_hard_requirement("(I12a OR I12b)", rs2) == True

# Test 3: OR with fail
rs3 = {"I12a": NodeRuntimeState(completed=False), "I12b": NodeRuntimeState(completed=False)}
assert parse_hard_requirement("(I12a OR I12b)", rs3) == False

# Test 4: AND
rs4 = {"I1": NodeRuntimeState(completed=True), "I9": NodeRuntimeState(completed=False)}
assert parse_hard_requirement("I1 AND I9", rs4) == False

# Test 5: empty
assert parse_hard_requirement("", {}) == True

# Test 6: no-ID
assert parse_hard_requirement("调查员持有光源", {}) == True

print("All tests passed")
```

Expected: `All tests passed`

- [ ] **Step 3: Commit**

```bash
git add src/scenario_core.py
git commit -m "feat: add parse_hard_requirement with AND/OR logic"
```

---

### Task 4: Implement edge-based dependency checking

**Files:**
- Modify: `src/scenario_core.py` (add to ScenarioWorld)

- [ ] **Step 1: Add `check_edge_requirements` method to ScenarioWorld**

Add to ScenarioWorld class:

```python
def check_edge_requirements(self, entity_id: str) -> tuple[bool, str]:
    """Check if all incoming dependency edges for entity_id are satisfied.

    Returns (met: bool, reason: str).
    Each edge is an AND condition: ALL edges must pass.
    OR logic is handled by requirement string parsing (parse_hard_requirement).
    """
    edges = self.get_incoming_edges(entity_id)
    if not edges:
        return True, ""

    for edge in edges:
        target_id = edge.get("target", "")
        condition = edge.get("condition", "completed")
        target_state = self.get_runtime_state(target_id)

        if condition == "success":
            if target_state.result_tier not in ("regular", "hard", "extreme"):
                # Try to look up name for a friendlier message
                target_name = edge.get("target_name", target_id)
                return False, f"需要成功完成「{target_name}」"
        elif condition == "completed":
            if not target_state.completed:
                target_name = edge.get("target_name", target_id)
                return False, f"需要先完成「{target_name}」"
        elif condition == "fail":
            if target_state.result_tier not in ("failure", "fumble"):
                return False, f"需要「{edge.get('target_name', target_id)}」结果为失败"
        elif condition == "Uncompleted":
            if target_state.completed:
                target_name = edge.get("target_name", target_id)
                return False, f"需要「{target_name}」未完成"

    return True, ""
```

- [ ] **Step 2: Verify edge checking with test**

Run: `python -c "` from `src/`:

```python
from scenario_core import ScenarioWorld, DirectedGraph, NodeRuntimeState

w = ScenarioWorld(DirectedGraph(scenes={}, events=[]), "")
w.dependency_graph = {
    "edges": [
        {"source": "I2", "target": "I1", "condition": "success"},
        {"source": "I18", "target": "I12a", "condition": "success"},
        {"source": "I18", "target": "I12b", "condition": "success"},
        {"source": "E2", "target": "I11", "condition": "Uncompleted"},
    ]
}

# I2 depends on I1 success — I1 succeeded
w.runtime_state["I1"] = NodeRuntimeState(completed=True, result_tier="regular")
met, _ = w.check_edge_requirements("I2")
assert met, "I2 should pass"

# I18 depends on I12a OR I12b (but edges are AND) — only I12a done
w.runtime_state["I12a"] = NodeRuntimeState(completed=True, result_tier="regular")
w.runtime_state["I12b"] = NodeRuntimeState(completed=False)
met, _ = w.check_edge_requirements("I18")
assert not met, "I18 should fail: one edge unmet (I12b not done)"

# Both done
w.runtime_state["I12b"] = NodeRuntimeState(completed=True, result_tier="regular")
met, _ = w.check_edge_requirements("I18")
assert met, "I18 should pass: both edges met"

# No edges
met, _ = w.check_edge_requirements("I99")
assert met, "no edges → pass"

print("All edge checks passed")
```

Expected: `All edge checks passed`

- [ ] **Step 3: Commit**

```bash
git add src/scenario_core.py
git commit -m "feat: add check_edge_requirements for AND-semantic dependency gating"
```

---

### Task 5: Migrate judge.py from flags to runtime_state

**Files:**
- Modify: `src/game/judge.py`

- [ ] **Step 1: Rewrite `_set_completion_flag` to write runtime_state**

Replace (line 73-76):
```python
def _set_completion_flag(self, entity: Entity):
    """Set world flag when entity completes."""
    flag_key = f"{entity.id}_done"
    self.world.set_flag(flag_key, True)
```

With:
```python
def _set_completion_flag(self, entity: Entity):
    """Mark entity completed in runtime_state."""
    state = self.world.get_runtime_state(entity.id)
    state.completed = True
```

- [ ] **Step 2: Rewrite `_is_entity_completed` to read runtime_state**

Replace (line 88-94):
```python
def _is_entity_completed(self, entity) -> bool:
    """Check if an entity has been completed/triggered."""
    if entity.entity_type == "event":
        return self.world.is_event_triggered(entity.id)
    scene = entity.scene or ""
    done = self.world.completed_interactions.get(scene, set())
    return entity.name in done
```

With:
```python
def _is_entity_completed(self, entity) -> bool:
    """Check if an entity has been completed/triggered via runtime_state."""
    if entity.entity_type == "event":
        return self.world.is_event_triggered(entity.id)
    state = self.world.runtime_state.get(entity.id)
    if state:
        return state.completed
    scene = entity.scene or ""
    done = self.world.completed_interactions.get(scene, set())
    return entity.name in done
```

- [ ] **Step 3: Rewrite escalated_difficulty and retries to use runtime_state**

Replace the escalated difficulty check (lines 119-122):
```python
difficulty = entity.difficulty if entity.difficulty not in ("None", "", None) else "regular"
escalated_key = f"{entity.id}_difficulty"
if self.world.flags.get(escalated_key):
    difficulty = self.world.flags[escalated_key]
```

With:
```python
difficulty = entity.difficulty if entity.difficulty not in ("None", "", None) else "regular"
state = self.world.get_runtime_state(entity.id)
if state.escalated_difficulty:
    difficulty = state.escalated_difficulty
```

Replace the failure penalty block (lines 166-181):
```python
if not skill_passed:
    # Failure penalty: retry tracking + difficulty escalation
    retry_key = f"{entity.id}_retries"
    retries = self.world.flags.get(retry_key, 0)

    # First failure: escalate difficulty by one level
    if retries == 0:
        new_diff = _escalate_difficulty(difficulty)
        if new_diff != difficulty:
            self.world.set_flag(escalated_key, new_diff)
            skill_detail += f"\n  [难度递增] {difficulty} → {new_diff}"
            log_skill_result(skill_detail)

    retries += 1
    self.world.set_flag(retry_key, retries)
    self.world.set_flag(f"{entity.id}_failed", True)
```

With:
```python
if not skill_passed:
    # Failure penalty: retry tracking + difficulty escalation via runtime_state
    state = self.world.get_runtime_state(entity.id)
    retries = state.retries

    # First failure: escalate difficulty by one level
    if retries == 0:
        new_diff = _escalate_difficulty(difficulty)
        if new_diff != difficulty:
            state.escalated_difficulty = new_diff
            skill_detail += f"\n  [难度递增] {difficulty} → {new_diff}"
            log_skill_result(skill_detail)

    state.retries = retries + 1
```

- [ ] **Step 4: Replace `_evaluate_requirement` flag:xxx handler**

Replace lines 298-302 (the `flag:` handling in `_evaluate_requirement`):
```python
if req.startswith("flag:"):
    flag_name = req[5:]
    if self.world.flags.get(flag_name, False):
        return True, ""
    return False, f"需要满足条件「{flag_name}」"
```

With (flag:xxx not used in new L2, safe to remove):
```python
if req.startswith("flag:"):
    # Legacy: flag-based requirements are no longer used in new L2 format.
    # Kept for backward compatibility only.
    return True, ""
```

- [ ] **Step 5: Verify syntax**

Run: `python -c "from game.judge import Judge; print('OK')"` from `src/`

- [ ] **Step 6: Commit**

```bash
git add src/game/judge.py
git commit -m "refactor: migrate Judge from world.flags to runtime_state"
```

---

### Task 6: Rewrite requirement evaluation in judge.py to use parse_hard_requirement

**Files:**
- Modify: `src/game/judge.py`

- [ ] **Step 1: Rewrite `_evaluate_requirement` to use new parser**

Replace the entire `_evaluate_requirement` method (lines 284-338, from `def _evaluate_requirement` to the end of the method before `_is_simple_requirement`):

```python
def _evaluate_requirement(self, req: str) -> tuple[bool, str]:
    """Evaluate hard requirement string using AND/OR parser + edge graph.

    Order:
    1. Check dependency_graph edges (structural AND)
    2. Parse hard requirement string (AND/OR + entity IDs)
    3. No ID found → pass (LLM-generated natural language, soft condition)
    """
    req = req.strip()
    if not req:
        return True, ""

    # Step 1: string-based AND/OR parsing FIRST (handles OR semantics)
    # Must come before edge check because edges are AND-only; requirement strings
    # may use OR to relax edge constraints (e.g. I18: edges AND {I12a, I12b} but
    # requirement string "(I12a OR I12b)" — string wins)
    from scenario_core import parse_hard_requirement
    met = parse_hard_requirement(req, self.world.runtime_state)
    if met:
        return True, ""

    # Step 2: edge-based dependency check (structural AND, secondary)
    entity_id = getattr(self, '_current_entity_id', '')
    if entity_id:
        met, msg = self.world.check_edge_requirements(entity_id)
        if not met:
            return False, msg

    return True, ""
```

- [ ] **Step 2: Set _current_entity_id before calling _evaluate_requirement**

In `_execute_entity`, add before the requirement check (before line 99):
```python
# Track current entity for edge-based dependency resolution
self._current_entity_id = entity.id
```

- [ ] **Step 3: Simplify `_is_simple_requirement` and `_check_simple_requirement`**

Since the new parser handles everything deterministically, simplify:

```python
def _is_simple_requirement(self, req: str) -> bool:
    hard, _ = self._split_requirement(req)
    if not hard:
        return True
    # Any hard string with recognizable IDs or logical operators can be parsed
    if "OR" in hard or "AND" in hard:
        return True
    if _ENTITY_ID_RE.match(hard.strip().strip("()（）")):
        return True
    return False

def _check_simple_requirement(self, entity: Entity) -> bool:
    if not entity.requirement or not entity.requirement.strip():
        return True
    hard, _ = self._split_requirement(entity.requirement)
    if not hard:
        return True
    if self._is_simple_requirement(hard):
        met, _ = self._evaluate_requirement(hard)
        return met
    return False
```

- [ ] **Step 4: Verify syntax**

Run: `python -c "from game.judge import Judge; print('OK')"` from `src/`

- [ ] **Step 5: Commit**

```bash
git add src/game/judge.py
git commit -m "refactor: rewrite requirement evaluation with AND/OR parser + edge gating"
```

---

### Task 7: Wire up dependency_graph loading in init_game and Keeper

**Files:**
- Modify: `src/game_loop.py`
- Modify: `src/game/agents/keeper.py`

- [ ] **Step 1: Load dependency_graph into ScenarioWorld in init_game**

In `init_game` (game_loop.py), after line 173 (`world = ScenarioWorld(...)`), add:

```python
# Load dependency graph into world for runtime state tracking
dep_graph = l2.get("dependency_graph", {})
world.load_dependency_graph(dep_graph)
```

- [ ] **Step 2: Update Keeper to use world's runtime_state instead of own dependency_graph**

In Keeper.__init__, the `self.dependency_graph` attribute can remain for prompt building. But add a comment that the authoritative source is `self.world.dependency_graph`:

```python
self.world = world
# dependency_graph is now owned by world; keep reference here for backward compat
self.dependency_graph = dependency_graph or {}
```

- [ ] **Step 3: Verify full import chain**

Run: `python -c "from game_loop import init_game; print('OK')"` from `src/`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/game_loop.py src/game/agents/keeper.py
git commit -m "feat: load dependency_graph into ScenarioWorld from init_game"
```

---

### Task 8: Clean up stale flag consumers

**Files:**
- Modify: `src/scenario_core.py` (RequirementResolver, _are_requirements_met)
- Modify: `src/prompts.py` (flag check in prompt builder)

- [ ] **Step 1: Update `_are_requirements_met` in ScenarioWorld**

Replace the flag:xxx check in `_are_requirements_met` (line 764):
```python
if hard.startswith("flag:"):
    return self.flags.get(hard[5:], False)
```

With (but this whole method may be unused):
```python
if hard.startswith("flag:"):
    # Legacy: not used in new L2. Treat as unmet for safety.
    return False
```

- [ ] **Step 2: Update RequirementResolver to use runtime_state**

In RequirementResolver (lines 637, 653), replace:
```python
if not self.world.flags.get(req.ref_name, False):
```

With:
```python
state = self.world.runtime_state.get(req.ref_name)
if not state or not state.completed:
```

- [ ] **Step 3: Update prompts.py flag check**

In `prompts.py` line ~382, replace:
```python
met = world.flags.get(hard[5:], False)
```

With:
```python
from scenario_core import parse_hard_requirement
met = parse_hard_requirement(hard, world.runtime_state)
```

- [ ] **Step 4: Verify syntax**

Run: `python -c "from prompts import build_keeper_parse_prompt; print('OK')"` from `src/`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/scenario_core.py src/prompts.py
git commit -m "refactor: clean up stale flag consumers, route to runtime_state"
```

---

### Task 8.5: Add soft requirement LLM fallback

**Files:**
- Modify: `src/llm.py` (add `evaluate_soft_requirement`)

- [ ] **Step 1: Add `evaluate_soft_requirement` function**

Add to `src/llm.py` after `evaluate_failure_penalty`:

```python
def evaluate_soft_requirement(expr: str, inv_desc: str, scene_desc: str) -> dict:
    """LLM fallback for soft requirements (after ||).

    Evaluates narrative conditions like "调查员持有光源" or "已知晓大嘴的存在"
    that cannot be resolved deterministically.

    Returns {"met": bool, "reason": str}
    """
    if not expr or not expr.strip():
        return {"met": True, "reason": ""}

    prompt = f"""你是 TRPG 规则裁判。判断当前调查员是否满足给定的叙事条件。

【调查员】
  描述：{inv_desc or '（无）'}

【场景】
  {scene_desc or '（无）'}

【条件】
  {expr}

条件仅涉及叙事性判断（物品持有、知识状态、NPC关系等）。
若条件和调查员的当前状况、已有物品或已知信息相符则判定为满足。
不确定时倾向于判定为满足（避免过度卡关）。

返回 JSON：
{{"met": true, "reason": "简短理由"}}
或
{{"met": false, "reason": "简短理由"}}

直接输出 JSON。"""
    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {"role": "system", "content": "你是一个TRPG规则裁判。仅输出JSON。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
        max_tokens=200,
        extra_body={"thinking": {"type": "disabled"}},
    )
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```json"):
        raw = raw[7:-3].strip()
    elif raw.startswith("```"):
        raw = raw[3:-3].strip()
    try:
        result = json.loads(raw)
        return {"met": result.get("met", True), "reason": result.get("reason", "")}
    except json.JSONDecodeError:
        return {"met": True, "reason": "JSON解析失败，默认通过"}
```

- [ ] **Step 2: Wire into Judge._execute_entity for soft requirements**

In `judge.py`, after the hard requirement check passes, add soft requirement evaluation when the requirement contains `||`:

In `_execute_entity`, after the requirement check block (after line ~101), add:

```python
# Soft requirement: LLM evaluation for narrative conditions (after ||)
if entity.requirement and entity.requirement.strip():
    _, soft = self._split_requirement(entity.requirement)
    if soft and self.world.player:
        inv_desc = getattr(self.world.player, 'personal_description', '') or \
                   getattr(self.world.player, 'description', '')
        scene_desc = self.world.get_current_description()
        from llm import evaluate_soft_requirement
        eval_result = evaluate_soft_requirement(soft, inv_desc, scene_desc)
        if not eval_result.get("met", True):
            return ActionOutcome(
                intent=intent or ActionIntent(action="other"),
                success=False,
                message=eval_result.get("reason", f"不满足条件：{soft}"),
                entity_id=entity.id, entity_type=entity.entity_type
            )
```

- [ ] **Step 3: Verify syntax**

Run: `python -c "from llm import evaluate_soft_requirement; print('OK')"` from `src/`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/llm.py src/game/judge.py
git commit -m "feat: add evaluate_soft_requirement LLM fallback for narrative conditions"
```

---

### Task 10: Final cleanup — remove deprecated methods

**Files:**
- Modify: `src/scenario_core.py`

- [ ] **Step 1: Remove deprecated set_flag/get_flag/toggle_flag**

Remove the no-op stub methods from ScenarioWorld:

```python
# Remove set_flag, get_flag, toggle_flag methods entirely
# Search and remove lines 872-879
```

- [ ] **Step 2: Remove unused RequirementResolver**

Remove line 686 (`self.requirement_resolver = RequirementResolver(self)`) from `__init__`.

- [ ] **Step 3: Verify syntax**

Run: `python -c "from scenario_core import ScenarioWorld; print('OK')"` from `src/`

- [ ] **Step 4: Commit**

```bash
git add src/scenario_core.py
git commit -m "refactor: remove deprecated set_flag/get_flag/toggle_flag and RequirementResolver"
```

---

### Task 11: Run test harness and fix regressions

**Files:**
- Modify: `tests/game_loop_harness.py` (if needed)
- Check: test harness output

- [ ] **Step 1: Run test harness**

```bash
cd C:/Users/micha/PyCharmMiscProject && python tests/game_loop_harness.py
```

Expected: 15/15 cases pass (or identify specific failures)

- [ ] **Step 2: Fix any regression from new requirement parser**

Common failure points:
- Entity with `requirement=""` not passing (should pass)
- Entity IDs not in runtime_state (need lazy init via `get_runtime_state`)
- I18: edges are AND {I12a, I12b} but requirement string is `(I12a OR I12b)`. Task 6 handles this by checking string OR first, then edge AND second — verify this works.

If edge-based AND check is too strict for entities where only OR is intended: ensure `parse_hard_requirement` correctly reads runtime_state completed flags.

- [ ] **Step 3: Re-run until green, then final commit**

```bash
git add -A
git commit -m "fix: test harness pass after dependency graph + runtime_state migration"
```
