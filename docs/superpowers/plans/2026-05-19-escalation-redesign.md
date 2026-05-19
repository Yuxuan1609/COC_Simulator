# Escalation & Author 机制重设计 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace unconditional per-turn LLM escalation check with Parse-other→IntentDetect on-demand trigger; refactor Author to two-level response (Patch/StructuralEdit); add supplement pipeline; add WR0 toggle.

**Architecture:** Delete `escalation.py` entirely. New `intent_detector.py` runs in parallel with Enrich when Parse returns "other" entries. Author accepts `AuthorRequest` (replacing `EscalationRequest`), judges patch vs structural, returns `ModulePatch` or triggers `supplement_pipeline.py`. Keeper integrates both paths and recurses `process_turn`.

**Tech Stack:** Python 3.10+, `dataclasses`, no new dependencies.

---

### Task 1: Delete escalation.py and clean all imports

**Files:**
- Delete: `src/game/escalation.py`
- Modify: `src/game/agents/keeper.py:13` (import line)
- Modify: `src/game_loop.py:13` (import line)

- [ ] **Step 1: Delete escalation.py**

```bash
rm src/game/escalation.py
```

- [ ] **Step 2: Update keeper.py imports — remove EscalationPolicy/EscalationContext**

Read `src/game/agents/keeper.py` lines 1-16. Replace:

```python
from ..escalation import EscalationPolicy, EscalationContext
```

With nothing (delete the line).

- [ ] **Step 3: Update keeper.py constructor — remove escalation_policy parameter**

In `Keeper.__init__`, remove the `escalation_policy` parameter and its default. Remove `self.escalation_policy` assignment. Remove `self.escalation_history`.

Old:
```python
def __init__(
    self,
    world: ScenarioWorld,
    dependency_graph: dict | None = None,
    phase1: dict | None = None,
    escalation_policy: EscalationPolicy | None = None,
    npc_profiles: dict[str, Any] | None = None,
):
    self.world = world
    self.dependency_graph = dependency_graph or {}
    self.phase1 = phase1 or {}
    self.escalation_policy = escalation_policy or EscalationPolicy()
    self.npc_profiles = npc_profiles or {}
    ...
    self.escalation_history: list[str] = []
```

New:
```python
def __init__(
    self,
    world: ScenarioWorld,
    dependency_graph: dict | None = None,
    phase1: dict | None = None,
    npc_profiles: dict[str, Any] | None = None,
):
    self.world = world
    self.dependency_graph = dependency_graph or {}
    self.phase1 = phase1 or {}
    self.npc_profiles = npc_profiles or {}
    ...
```

- [ ] **Step 4: Update game_loop.py imports**

In `src/game_loop.py` line 13, remove:
```python
from game.escalation import EscalationPolicy
```

In `init_game()`, remove the escalation config loading block (lines 132-138):
```python
    escalation_policy = None
    try:
        with open(escalation_config_path, "r", encoding="utf-8") as f:
            escalation_policy = EscalationPolicy.from_dict(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        escalation_policy = EscalationPolicy()
```

And update the Keeper constructor call to remove `escalation_policy=`.

- [ ] **Step 5: Verify no remaining references**

```bash
grep -r "escalation" src/game/ src/game_loop.py --include="*.py" || echo "CLEAN"
```

Expected: Only references to `MAX_ESCALATION_DEPTH` and `_handle_uncovered_intent` (which we haven't renamed yet in this task). The old `EscalationPolicy`/`EscalationContext`/`escalation.py` references should be gone.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: delete escalation.py, clean EscalationPolicy imports"
```

---

### Task 2: Update messages.py — new types, remove EscalationRequest

**Files:**
- Modify: `src/game/messages.py`

- [ ] **Step 1: Add IntentResult dataclass**

Add before the existing dataclasses:

```python
@dataclass
class IntentResult:
    """Detector output — does the player's 'other' action carry narrative intent?"""
    needs_author: bool
    intent: str = ""          # one-line: what the player wants to accomplish
    reasoning: str = ""       # why this warrants escalation
```

- [ ] **Step 2: Add AuthorRequest dataclass**

```python
@dataclass
class AuthorRequest:
    """Detector → Author: player intent worth acting on."""
    other_texts: list[str]       # original "other" entry text(s) from Parse
    intent: str                  # Detector output
    reasoning: str               # Detector output
    scene_context: dict          # Keeper extracts from world
```

- [ ] **Step 3: Update StructuralEdit dataclass**

Replace the existing empty `StructuralEdit`:

```python
@dataclass
class StructuralEdit:
    """Author → Keeper: structural expansion needed. Triggers supplement pipeline."""
    supplement_path: str = ""       # supplements/<timestamp>/
    l3_updates: dict = field(default_factory=dict)
    entry_scene: str = ""
    exit_scene: str = ""
    justification: str = ""
```

- [ ] **Step 4: Remove EscalationRequest and EscalationContext**

Delete the `EscalationRequest` dataclass (was used by old _check_escalation). It is now replaced by `AuthorRequest`.

- [ ] **Step 5: Commit**

```bash
git add src/game/messages.py
git commit -m "feat: add IntentResult, AuthorRequest; update StructuralEdit; remove EscalationRequest"
```

---

### Task 3: Add wr0_enabled to ScenarioWorld

**Files:**
- Modify: `src/scenario_core.py`

- [ ] **Step 1: Add wr0_enabled field**

In `ScenarioWorld.__init__`, add the field (defaults to False):

```python
# In ScenarioWorld.__init__:
self.wr0_enabled: bool = False  # set at game start by player choice, immutable
```

Add it in the constructor signature:

```python
def __init__(self, graph: DirectedGraph, start_node: str,
             background_story: str = "",
             wr0_enabled: bool = False):
    ...
    self.wr0_enabled = wr0_enabled
```

- [ ] **Step 2: Add wr0 to to_dict and from_dict**

In `to_dict()`, add to the returned dict:
```python
"wr0_enabled": self.wr0_enabled,
```

In `from_dict()`, add restoration:
```python
world.wr0_enabled = data.get("wr0_enabled", False)
```

- [ ] **Step 3: Commit**

```bash
git add src/scenario_core.py
git commit -m "feat: add wr0_enabled to ScenarioWorld with save/load support"
```

---

### Task 4: Create IntentDetector

**Files:**
- Create: `src/game/intent_detector.py`

- [ ] **Step 1: Write the test file scaffold**

Create `tests/test_intent_detector.py`:

```python
"""Quasi-unit tests for IntentDetector — LLM calls are mocked."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import json
from game.intent_detector import IntentDetector, IntentResult


def _mock_call_deepseek(prompt, json_mode, model, system, reasoning_effort=None,
                        fallback_schema=None):
    """Simulate LLM responses for detector tests."""
    # Flavored behavior — not meaningful
    if "唱首歌" in prompt or "讲笑话" in prompt:
        return json.dumps({"has_intent": False, "intent": "", "reasoning": "纯角色扮演行为"})
    # Meaningful intent
    if "对话" in prompt or "黑影" in prompt:
        return json.dumps({
            "has_intent": True,
            "intent": "玩家试图与黑暗中的存在进行交流",
            "reasoning": "模组中没有与存在沟通的机制，这是全新的叙事路径"
        })
    # Default: not meaningful
    return json.dumps({"has_intent": False, "intent": "", "reasoning": ""})


def test_detector_flavor_behavior(monkeypatch):
    """Pure RP like singing should not trigger author."""
    import game.intent_detector as mod
    monkeypatch.setattr(mod, "call_deepseek", _mock_call_deepseek)

    detector = IntentDetector()
    result = detector.detect("唱了一首快乐的小曲", {"location": "测试房间"})

    assert isinstance(result, IntentResult)
    assert result.needs_author is False


def test_detector_meaningful_intent(monkeypatch):
    """Narrative-breaking intent should trigger author."""
    import game.intent_detector as mod
    monkeypatch.setattr(mod, "call_deepseek", _mock_call_deepseek)

    detector = IntentDetector()
    result = detector.detect("试图和远处那个黑影对话", {"location": "7号车厢"})

    assert result.needs_author is True
    assert len(result.intent) > 0
    assert len(result.reasoning) > 0


def test_detector_empty_other(monkeypatch):
    """Empty input should not trigger."""
    import game.intent_detector as mod
    monkeypatch.setattr(mod, "call_deepseek", _mock_call_deepseek)

    detector = IntentDetector()
    result = detector.detect("", {"location": "测试房间"})

    assert result.needs_author is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd tests && python -m pytest test_intent_detector.py -v
```

Expected: ModuleNotFoundError for `game.intent_detector`.

- [ ] **Step 3: Implement IntentDetector**

```python
"""IntentDetector — lightweight LLM check for meaningful 'other' player input."""
from __future__ import annotations
import json
from dataclasses import dataclass

from llm import call_deepseek


@dataclass
class IntentResult:
    """Detector output."""
    needs_author: bool
    intent: str = ""
    reasoning: str = ""


class IntentDetector:
    """Lightweight LLM detector: does an 'other' action carry real narrative intent?

    Runs in parallel with Enrich when Parse returns 'other' entries.
    Uses flash model with minimal prompt for fast yes/no + one-line description.
    """

    def detect(self, other_text: str, world_snapshot: dict) -> IntentResult:
        """Judge whether 'other' text warrants Author attention."""
        if not other_text or not other_text.strip():
            return IntentResult(needs_author=False)

        prompt = self._build_prompt(other_text, world_snapshot)
        response = call_deepseek(
            prompt, json_mode=True, model="deepseek-v4-flash",
            reasoning_effort="low",
            system="你是一个TRPG游戏状态监控者。判断玩家输入是否有值得KP关注的叙事意图。",
            fallback_schema={"has_intent": False, "intent": "", "reasoning": ""},
        )
        data = json.loads(response) if isinstance(response, str) else response
        return IntentResult(
            needs_author=data.get("has_intent", False),
            intent=data.get("intent", ""),
            reasoning=data.get("reasoning", ""),
        )

    def _build_prompt(self, other_text: str, world_snapshot: dict) -> str:
        return f"""判断以下玩家行为是纯角色扮演/情绪表达，还是有实际叙事意图（玩家想对游戏世界产生改变）。

【当前位置】{world_snapshot.get('location', '')}
【NPC状态】{json.dumps(world_snapshot.get('npc_states', {}), ensure_ascii=False)}

【玩家行为】{other_text}

纯角色扮演的例子：唱歌、讲笑话、自言自语、情绪表达、无目标的小动作。
有叙事意图的例子：试图与NPC/怪物交流、破坏场景物品、使用模组未提及的道具、开辟新的行动路径。

返回 JSON：
{{
  "has_intent": true/false,
  "intent": "如有意图，一句话描述玩家想达成什么",
  "reasoning": "如有意图，为什么这需要创作者介入而非正常KP裁决"
}}

直接输出 JSON。"""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd tests && python -m pytest test_intent_detector.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/game/intent_detector.py tests/test_intent_detector.py
git commit -m "feat: add IntentDetector — lightweight LLM check for meaningful 'other' input"
```

---

### Task 5: Refactor Author — handle_request, two-level response, WR0-aware prompt

**Files:**
- Modify: `src/game/agents/author.py`
- Modify: `src/prompts.py` (build_author_prompt)

- [ ] **Step 1: Update author.py — new handle_request method**

```python
"""Author agent — owns L3, creates ModulePatch or triggers StructuralEdit."""
from __future__ import annotations
from typing import Any
import json

from ..messages import AuthorRequest, ModulePatch, StructuralEdit
from prompts import build_author_prompt, build_author_structural_prompt
from llm import call_deepseek


class Author:
    """Author agent. Owns L3, only faces KP.

    Two-level response:
    - Patch: fill module gaps within existing scenes
    - StructuralEdit: trigger supplement pipeline for new scenes/content

    Must never: make rulings, output to player, touch L1.
    WR0 applies independently — see _build_prompt.
    """

    def __init__(self, l3_data: Any):
        self.l3_data = l3_data
        self.history: list[dict] = []  # {intent, level, justification, turn}

    def handle_request(self, request: AuthorRequest, turn_number: int = 0) -> ModulePatch | StructuralEdit:
        """Process an AuthorRequest. Returns ModulePatch (patch or reject) or StructuralEdit."""
        self.history.append({
            "intent": request.intent,
            "turn": turn_number,
        })

        prompt = self._build_prompt(request)
        response = call_deepseek(
            prompt, json_mode=True, model="deepseek-v4-flash",
            reasoning_effort="max",
            system="你是一个优秀的TRPG模组创作者，擅长根据游戏中突发情况动态扩展模组内容。"
                   "你的创作应与既有风格保持一致。",
            fallback_schema={
                "level": "patch",
                "entities": [],
                "scene_descriptions": {},
                "justification": "",
                "entry_scene": "",
                "exit_scene": "",
            },
        )
        data = json.loads(response) if isinstance(response, str) else response

        level = data.get("level", "patch")
        justification = data.get("justification", "")

        self.history[-1]["level"] = level
        self.history[-1]["justification"] = justification

        if level == "structural":
            return StructuralEdit(
                entry_scene=data.get("entry_scene", request.scene_context.get("location", "")),
                exit_scene=data.get("exit_scene", ""),
                justification=justification,
            )
        else:
            # patch or reject (entities=[] means reject)
            return ModulePatch(
                entities=data.get("entities", []),
                scene_descriptions=data.get("scene_descriptions", {}),
                justification=justification,
            )

    def update_l3(self, l3_updates: dict):
        """Merge supplement L3 updates into existing L3 data."""
        if isinstance(self.l3_data, dict):
            self.l3_data.update(l3_updates)

    def _build_prompt(self, request: AuthorRequest) -> str:
        return build_author_prompt(request, self.l3_data)
```

- [ ] **Step 2: Update prompts.py — new build_author_prompt**

Replace the old `build_author_prompt(request, l3_data)` in `src/prompts.py`:

```python
def build_author_prompt(request, l3_data) -> str:
    """Author: judges patch/structural level, generates content."""
    l3_ctx = _build_l1l3_context(
        l3_data=l3_data,
        scene_name=request.scene_context.get("location", ""),
    )

    wr0_enabled = request.scene_context.get("wr0_enabled", False)
    wr0_line = (
        "【WR0 创作者豁免】开启 — 你拥有完全创作自由，可突破任何世界规则。"
        if wr0_enabled else
        "【WR0 状态】关闭 — 扩展内容必须与既有世界规则、基调、L3设计意图保持一致。"
    )

    prompt = f"""{l3_ctx}

【当前场景】
  位置：{request.scene_context.get('location', '')}
  描述：{request.scene_context.get('description', '')}
  可用场景：{', '.join(request.scene_context.get('available_scenes', []))}
  NPC状态：{json.dumps(request.scene_context.get('npc_states', {}), ensure_ascii=False)}

【玩家意图】
  玩家想做什么：{request.intent}
  升级原因：{request.reasoning}
  玩家原话：{'; '.join(request.other_texts)}

{wr0_line}

请评估此意图的范围并生成响应：

1. 判断级别：
   - patch：行为合理但模组未覆盖 → 在当前可用场景中添加 entity
   - structural：行为完全超出模组范围，需要结构性扩展（新场景、新结局）

2. 如果 patch：
   {{
     "level": "patch",
     "entities": [
       {{
         "id": "SI1",
         "entity_type": "interaction",
         "scene": "场景名",
         "name": "entity名称",
         "type": "关联技能名或留空",
         "requirement": "",
         "trigger": "触发描述",
         "result": "结果描述",
         "side_effects": [],
         "graded_result": null,
         "difficulty": "regular"
       }}
     ],
     "scene_descriptions": {{}},
     "justification": "L3层面理由"
   }}

3. 如果 structural（触发补充管线）：
   {{
     "level": "structural",
     "entry_scene": "玩家当前场景",
     "exit_scene": "出口场景名或空",
     "justification": "为什么需要结构性扩展，引用L3设计意图"
   }}

4. 如果玩家意图违反世界规则且 WR0 关闭 → 打回：
   {{
     "level": "patch",
     "entities": [],
     "scene_descriptions": {{}},
     "justification": "为什么拒绝。格式: REJECTED: 具体原因"
   }}

规则：
- 只添加必要的entity，不要过度扩充
- structural 仅在玩家行为确实需要时才使用
- side_effects 使用 @function(param=value) 语法
- justification 必须引用L3设计意图
- entity ID 使用 S_ 前缀（SI1, SAT1, SE1 等）
- 直接输出 JSON
"""
    _show_prompt("Author", prompt)
    return prompt
```

- [ ] **Step 3: Remove old EscalationRequest import from author.py**

The old `from ..messages import EscalationRequest` import should already be gone — the new code imports `AuthorRequest`. Verify.

- [ ] **Step 4: Commit**

```bash
git add src/game/agents/author.py src/prompts.py
git commit -m "refactor: Author.handle_request with two-level response (patch/structural) and WR0-aware prompt"
```

---

### Task 6: Create supplement pipeline

**Files:**
- Create: `src/module_designer/supplement_pipeline.py`

- [ ] **Step 1: Implement supplement pipeline**

```python
"""Supplement pipeline — lightweight module generation triggered by Author StructuralEdit.

Input: player intent + base L3 + entry/exit scenes
Output: l1_supp.json + l2_supp.json + l3_supp.json in supplements/<timestamp>/

Step 1: 3 parallel LLM calls (flash + max reasoning)
  1a: scenes + interactions + auto_triggers
  1b: events + scene_movements
  1c: L1 player-facing layer

Step 2: assemble + cross-validate + @markup standardize (1 call)
"""
from __future__ import annotations
import json
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from llm import call_deepseek
from module_designer.layered_parser import _clean_json, _load_template
from module_designer.layered_schema import validate_all


def run_supplement_pipeline(
    player_intent: str,
    reasoning: str,
    base_l3: dict,
    entry_scene: str,
    exit_scene: str = "",
    output_dir: str = "",
    module_name: str = "",
) -> dict:
    """Run lightweight supplement pipeline. Returns {"l1": ..., "l2": ..., "l3": ...}."""

    if not output_dir:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join("data", "modules", module_name, "supplements", ts)
    os.makedirs(output_dir, exist_ok=True)

    # Build shared context for Step 1 sub-steps
    l3_summary = _summarize_l3(base_l3)
    shared_context = {
        "player_intent": player_intent,
        "reasoning": reasoning,
        "entry_scene": entry_scene,
        "exit_scene": exit_scene,
        "l3_summary": l3_summary,
    }

    # Step 1: 3 parallel LLM calls
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_step_1a, shared_context): "1a_scenes",
            executor.submit(_step_1b, shared_context): "1b_events",
            executor.submit(_step_1c, shared_context): "1c_l1",
        }
        results = {}
        for future in as_completed(futures):
            name = futures[future]
            results[name] = future.result()

    scenes_data = results.get("1a_scenes", {})
    events_data = results.get("1b_events", {})
    l1_data = results.get("1c_l1", {})

    # Step 2: assemble + validate
    l2_data = _step_2_assemble(scenes_data, events_data, shared_context)
    l3_data = _build_l3_supp(base_l3, shared_context)

    # Final deterministic validation
    report = validate_all(l1_data, l2_data, l3_data, strict=False)
    if not report.is_valid:
        print(f"[supplement_pipeline] Validation warnings: {report.summary()}")

    # Save
    for name, data in [("l1_supp.json", l1_data), ("l2_supp.json", l2_data),
                        ("l3_supp.json", l3_data)]:
        path = os.path.join(output_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return {"l1": l1_data, "l2": l2_data, "l3": l3_data, "output_dir": output_dir}


def _summarize_l3(l3: dict) -> str:
    """Extract key L3 constraints for supplement generation."""
    tc = l3.get("tone_constraints", {})
    parts = []
    if isinstance(tc, dict):
        parts.append(f"类型：{tc.get('genre', '')}")
        parts.append(f"叙事风格：{tc.get('narrative_style', '')}")
        forbidden = tc.get('forbidden', [])
        if forbidden:
            parts.append(f"禁止：{', '.join(forbidden)}")
        required = tc.get('required', [])
        if required:
            parts.append(f"必须包含：{', '.join(required)}")
    parts.append(f"核心驱动力：{l3.get('driving_force', '')}")
    return "\n".join(parts)


def _step_1a(context: dict) -> dict:
    """Generate new scenes with interactions + auto_triggers."""
    prompt = f"""你是TRPG模组创作者。基于以下信息生成补充场景。

【L3约束】
{context['l3_summary']}

【玩家意图】
意图：{context['player_intent']}
原因：{context['reasoning']}

【出入口】
入口场景：{context['entry_scene']}
出口场景：{context.get('exit_scene') or '由你决定'}

请生成1-3个新场景，每个场景含interactions和auto_triggers。
Entity ID使用S_前缀：SS1=场景1, SI1=interaction1, SAT1=AT1。
requirement字段使用entity ID字符串（如"SI1 AND SI2"）。

返回 JSON：
{{
  "scenes": {{
    "SS1_场景名": {{
      "description": "场景描述",
      "interactions": [
        {{"id": "SI1", "entity_type": "interaction", "scene": "SS1_场景名",
          "name": "动作名", "type": "技能名或空", "requirement": "", "trigger": "触发条件",
          "result": "结果描述", "side_effects": [], "graded_result": null, "difficulty": "regular"}}
      ],
      "auto_triggers": [],
      "from_here": [{{"target": "出口场景", "method": "通行方式", "requirement": ""}}],
      "to_here": [{{"source": "{context['entry_scene']}", "method": "通行方式", "requirement": ""}}],
      "extra": {{}}
    }}
  }}
}}

直接输出 JSON。"""
    response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
                             reasoning_effort="max",
                             system="你是TRPG模组创作者。生成结构化的新场景内容。",
                             fallback_schema={"scenes": {}})
    return json.loads(response) if isinstance(response, str) else response


def _step_1b(context: dict) -> dict:
    """Generate events + scene movements."""
    prompt = f"""你是TRPG模组创作者。基于以下信息生成补充事件和场景连接。

【L3约束】
{context['l3_summary']}

【玩家意图】
意图：{context['player_intent']}
原因：{context['reasoning']}

【出入口】
入口：{context['entry_scene']}
出口：{context.get('exit_scene') or '由你决定'}

生成全局事件（可选）和新场景之间的通行连接。
Event ID使用SE_前缀。

返回 JSON：
{{
  "events": [
    {{"id": "SE1", "entity_type": "event", "name": "事件名", "type": "",
      "requirement": "", "trigger": "触发条件", "result": "事件结果",
      "side_effects": [], "graded_result": null, "difficulty": "None"}}
  ]
}}

直接输出 JSON。"""
    response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
                             reasoning_effort="max",
                             system="你是TRPG模组创作者。生成事件和场景通行结构。",
                             fallback_schema={"events": []})
    return json.loads(response) if isinstance(response, str) else response


def _step_1c(context: dict) -> dict:
    """Generate L1 player-facing layer."""
    prompt = f"""你是TRPG模组创作者。生成新场景的玩家可见层（L1）。

【L3约束】
{context['l3_summary']}

【玩家意图】
意图：{context['player_intent']}

生成L1格式的场景描述，键名为场景中文名。
每个场景包含：description（场景描述）、atmosphere（氛围）、mood（情绪基调）、
perceptible（可无条件感知的元素列表）、ambient_hints（环境暗示）。

返回 JSON：
{{
  "新场景名": {{
    "description": "场景描述",
    "atmosphere": "氛围",
    "mood": "情绪基调",
    "perceptible": ["可感知元素"],
    "ambient_hints": ["环境暗示"],
    "npc_appearances": {{}}
  }}
}}

直接输出 JSON。"""
    response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash",
                             reasoning_effort="max",
                             system="你是TRPG模组创作者。生成玩家可见的场景描述层。",
                             fallback_schema={})
    return json.loads(response) if isinstance(response, str) else response


def _step_2_assemble(scenes_data: dict, events_data: dict, context: dict) -> dict:
    """Assemble L2 structure from Step 1 outputs."""
    scenes = scenes_data.get("scenes", {})
    events = events_data.get("events", [])

    # Build minimal dependency_graph
    dep_nodes = {}
    dep_edges = []
    for scene_name, scene_data in scenes.items():
        for entity_list_name in ("interactions", "auto_triggers"):
            for ent in scene_data.get(entity_list_name, []):
                eid = ent.get("id", "")
                etype = ent.get("entity_type", "")
                if eid:
                    dep_nodes[eid] = {"entity_id": eid, "entity_type": etype, "name": ent.get("name", "")}
                    req = ent.get("requirement", "")
                    if req:
                        for req_id in _extract_entity_ids(req):
                            if req_id not in dep_nodes:
                                dep_nodes[req_id] = {"entity_id": req_id, "entity_type": "", "name": ""}

    for ev in events:
        eid = ev.get("id", "")
        if eid:
            dep_nodes[eid] = {"entity_id": eid, "entity_type": "event", "name": ev.get("name", "")}

    for scene_name, scene_data in scenes.items():
        for entity_list_name in ("interactions", "auto_triggers"):
            for ent in scene_data.get(entity_list_name, []):
                eid = ent.get("id", "")
                req = ent.get("requirement", "")
                if eid and req:
                    for req_id in _extract_entity_ids(req):
                        dep_edges.append({
                            "source": eid, "target": req_id,
                            "dep_type": "", "condition": "completed",
                        })

    # Scene names map (internal ID → Chinese name)
    scene_names = {}
    for sid, sdata in scenes.items():
        scene_names[sid] = sid  # S_ IDs are already the scene keys

    # NPC profiles: empty for supplement (reuses base module NPCs)
    return {
        "scenes": scenes,
        "events": events,
        "npc_profiles": {},
        "dependency_graph": {
            "nodes": dep_nodes,
            "edges": dep_edges,
        },
        "_scene_names": scene_names,
        "_phase1": {},
    }


def _build_l3_supp(base_l3: dict, context: dict) -> dict:
    """Build supplement L3 — mostly inherits base L3 with optional adjustments."""
    return {
        "module_meta": {
            **base_l3.get("module_meta", {}),
            "supplement_of": base_l3.get("module_meta", {}).get("name", ""),
            "generated_for": context["player_intent"],
        },
        "world_rules": base_l3.get("world_rules", {}),
        "scene_intents": base_l3.get("scene_intents", {}),
        "ending_conditions": base_l3.get("ending_conditions", []),
        "tone_constraints": base_l3.get("tone_constraints", {}),
        "characters": base_l3.get("characters", {}),
        "driving_force": base_l3.get("driving_force", ""),
    }


def _extract_entity_ids(req_str: str) -> list[str]:
    """Extract entity IDs (I1, AT2, E3, etc.) from a requirement string."""
    import re
    return re.findall(r'[ISEA]+\d+[a-z]?', req_str)
```

- [ ] **Step 2: Commit**

```bash
git add src/module_designer/supplement_pipeline.py
git commit -m "feat: add supplement pipeline — lightweight 2-step module generation"
```

---

### Task 7: Refactor Keeper — _handle_uncovered_intent, parallel scheduling, _integrate_supplement

**Files:**
- Modify: `src/game/agents/keeper.py`

- [ ] **Step 1: Update Keeper.__init__ — init IntentDetector, remove escalation fields**

```python
from ..intent_detector import IntentDetector

class Keeper:
    MAX_ESCALATION_DEPTH = 3

    def __init__(
        self,
        world: ScenarioWorld,
        dependency_graph: dict | None = None,
        phase1: dict | None = None,
        npc_profiles: dict[str, Any] | None = None,
    ):
        self.world = world
        self.dependency_graph = dependency_graph or {}
        self.phase1 = phase1 or {}
        self.npc_profiles = npc_profiles or {}
        self.intent_detector = IntentDetector()

        self.judge = Judge(world)
        self.curator = Curator(world)
        self.turn_number = 0
        self._warnings: list[str] = []
        # Track recent escalation intents to suppress duplicates
        self._recent_intents: list[str] = []  # last N intent strings
        self._intent_cooldown: int = 3         # turns before same intent re-triggers
```

- [ ] **Step 2: Replace process_turn escalation block**

Replace the block from the `# Step 4: Escalation check` comment through the end of the escalation handling (lines 165-177 in the current file) with the new parallel scheduling logic.

The new `process_turn` core loop:

```python
    def process_turn(self, turn_input: TurnInput, author: Any = None, _depth: int = 0) -> dict:
        if _depth >= self.MAX_ESCALATION_DEPTH:
            return self._process_deterministic_only(turn_input)
        self.turn_number += 1
        raw = turn_input.raw_text
        self._warnings.clear()

        # Step 1: Parse
        parse_result = self._parse(raw)

        # Launch IntentDetector early if there are "other" entries
        other_entries = [e for e in parse_result if e.get("type") == "other"]
        detect_future = None
        if other_entries and author:
            other_text = "; ".join(e.get("text", "") for e in other_entries)
            world_snapshot = self._build_world_snapshot()
            from concurrent.futures import ThreadPoolExecutor
            executor = ThreadPoolExecutor(max_workers=1)
            detect_future = executor.submit(
                self.intent_detector.detect, other_text, world_snapshot
            )

        # Step 2: Judge (deterministic, fast)
        all_outcomes = []
        judged_entities = []
        for entry in parse_result:
            entry_type = entry.get("type", "")
            if entry_type in ("auto_trigger", "interaction", "event"):
                eid = entry.get("id", "")
                entity = self._find_entity_by_id(eid)
                if not entity:
                    continue
                intent = ActionIntent(
                    action=entry_type if entry_type != "auto_trigger" else "other",
                    target=entity.name if entry_type == "interaction" else "",
                )
                outcome = self.judge._execute_entity(entity, intent=intent)
                self._apply_side_effects(outcome.side_effects)
                all_outcomes.append(outcome)
                if outcome.success:
                    judged_entities.append({
                        "entity_type": entity.entity_type,
                        "id": entity.id,
                        "name": entity.name,
                        "result": outcome.message,
                        "success": True,
                        "skill_tier": outcome.skill_tier,
                    })
            elif entry_type == "move":
                target = entry.get("target", "")
                result = self.world.move(target)
                all_outcomes.append(ActionOutcome(
                    intent=ActionIntent(action="move", target=target),
                    success=result.success, message=result.message,
                    side_effects=result.side_effects,
                ))
                self._apply_side_effects(result.side_effects)
            elif entry_type == "search":
                ...  # search handling unchanged
            else:
                # "other" — IntentDetector handles this (see below)
                pass

        # Step 3: Enrich (LLM) — runs concurrently with IntentDetector wait
        emphasis = ""
        enrichment = None
        if judged_entities:
            enrichment = self._enrich(judged_entities, raw)
            emphasis = enrichment.get("emphasis_hint", "")
            results = enrichment.get("results", {})
            for o in all_outcomes:
                eid = o.entity_id
                if eid in results:
                    o.message = results[eid]

        # Step 4: IntentDetector decision point
        if detect_future:
            intent_result = detect_future.result()
            executor.shutdown(wait=False)

            if intent_result.needs_author and author:
                # Suppress duplicate intents within cooldown window
                intent_key = intent_result.intent.strip().lower()
                if intent_key not in [i.lower() for i in self._recent_intents[-3:]]:
                    self._recent_intents.append(intent_key)
                    request = AuthorRequest(
                        other_texts=[e.get("text", "") for e in other_entries],
                        intent=intent_result.intent,
                        reasoning=intent_result.reasoning,
                        scene_context=self._build_scene_context_for_author(),
                    )
                    response = author.handle_request(request, self.turn_number)

                    if isinstance(response, StructuralEdit):
                        # Trigger supplement pipeline
                        response = self._integrate_supplement(response, author)
                        if response.supplement_path:
                            return self.process_turn(turn_input, author, _depth + 1)
                        # If supplement failed, fall through to normal flow
                    elif isinstance(response, ModulePatch):
                        if response.entities:
                            self._integrate_patch(response)
                            self._warnings.append(
                                f"模组已动态扩展：{response.justification[:60]}")
                            return self.process_turn(turn_input, author, _depth + 1)
                        else:
                            # Author rejected — inject a player-visible narrative hint
                            # so the player isn't met with dead silence after waiting
                            rejection_msg = response.justification
                            if rejection_msg.startswith("REJECTED:"):
                                rejection_msg = rejection_msg[9:].strip()
                            all_outcomes.append(ActionOutcome(
                                intent=ActionIntent(action="other"), success=True,
                                message=f"（你尝试了，但{rejection_msg}）"))

        # Ending detection
        ...
        # Memory
        ...
        # Curate
        ...
```

- [ ] **Step 3: Add _build_world_snapshot helper**

```python
    def _build_world_snapshot(self) -> dict:
        """Lightweight snapshot for IntentDetector."""
        return {
            "location": self.world.current_location,
            "npc_states": dict(self.world.npc_states),
        }
```

- [ ] **Step 4: Add _build_scene_context_for_author helper**

```python
    def _build_scene_context_for_author(self) -> dict:
        """Build scene_context for AuthorRequest."""
        node = self.world._current_node()
        return {
            "location": self.world.current_location,
            "description": node.description if node else "",
            "available_scenes": list(self.world.graph.nodes.keys()),
            "npc_states": dict(self.world.npc_states),
            "runtime_summary": {
                eid: s.result_tier
                for eid, s in self.world.runtime_state.items()
                if s.completed
            },
            "wr0_enabled": self.world.wr0_enabled,
        }
```

- [ ] **Step 5: Add _integrate_supplement method**

```python
    def _integrate_supplement(self, structural_edit: StructuralEdit, author) -> StructuralEdit:
        """Run supplement pipeline and integrate results into world graph."""
        try:
            from module_designer.supplement_pipeline import run_supplement_pipeline
            result = run_supplement_pipeline(
                player_intent="",  # filled in by pipeline from context
                reasoning="",
                base_l3=author.l3_data,
                entry_scene=structural_edit.entry_scene,
                exit_scene=structural_edit.exit_scene,
                module_name="",  # derive from current world if needed
            )

            # Merge L2: new scenes + events into graph
            l2 = result["l2"]
            graph = self.world.graph

            for scene_name, scene_data in l2.get("scenes", {}).items():
                self._load_scene_into_graph(scene_name, scene_data)

            for ev in l2.get("events", []):
                eid = ev["id"]
                if eid not in graph.events:
                    graph.events[eid] = Entity(
                        id=eid, entity_type="event",
                        name=ev["name"], type=ev.get("type", ""),
                        requirement=ev.get("requirement", ""), trigger=ev.get("trigger", ""),
                        result=ev.get("result", ""), side_effects=ev.get("side_effects", []),
                        graded_result=ev.get("graded_result"), difficulty=ev.get("difficulty", ""),
                    )

            # Entry scene connection: add from_here edge from structural_edit.entry_scene
            if structural_edit.entry_scene in graph.nodes:
                first_new_scene = next(iter(l2.get("scenes", {}).keys()), None)
                if first_new_scene:
                    entry_node = graph.nodes[structural_edit.entry_scene]
                    already_connected = any(
                        e.target == first_new_scene for e in entry_node.edges
                    )
                    if not already_connected:
                        from scenario_core import Edge
                        entry_node.edges.append(Edge(
                            target=first_new_scene, method="深入探索",
                            requirement="",
                        ))

            # Merge L1 — Narrator needs this, passed via Keeper
            # (Keeper stores merged_l1 for Narrator to access)
            if not hasattr(self, '_merged_l1'):
                self._merged_l1 = {}
            if hasattr(self, 'narrator_l1'):
                self.narrator_l1.update(result["l1"])
            else:
                self._merged_l1.update(result["l1"])

            # Merge dependency_graph
            supp_dep = l2.get("dependency_graph", {})
            for eid, ndata in supp_dep.get("nodes", {}).items():
                if eid not in self.world.dependency_graph.get("nodes", {}):
                    self.world.dependency_graph.setdefault("nodes", {})[eid] = ndata
            existing_edges = {(e.get("source"), e.get("target"))
                            for e in self.world.dependency_graph.get("edges", [])}
            for edge in supp_dep.get("edges", []):
                key = (edge.get("source"), edge.get("target"))
                if key not in existing_edges:
                    self.world.dependency_graph.setdefault("edges", []).append(edge)
                    existing_edges.add(key)

            # Init runtime_state for new entities
            for eid in supp_dep.get("nodes", {}):
                self.world.get_runtime_state(eid)

            # Update L3
            author.update_l3(result["l3"])

            structural_edit.supplement_path = result.get("output_dir", "")
            structural_edit.l3_updates = result["l3"]
        except Exception as e:
            self._warnings.append(f"补充管线失败（{e}），继续正常流程。")
            structural_edit.supplement_path = ""

        return structural_edit

    def _load_scene_into_graph(self, scene_name: str, scene_data: dict):
        """Load a single scene dict into DirectedGraph."""
        from scenario_core import Entity, Edge, Node
        graph = self.world.graph

        interactions = [
            Entity(
                id=inter["id"], entity_type=inter.get("entity_type", "interaction"),
                name=inter["name"], scene=inter.get("scene", scene_name),
                type=inter.get("type", ""), requirement=inter.get("requirement", ""),
                trigger=inter.get("trigger", ""), result=inter.get("result", ""),
                side_effects=inter.get("side_effects", []),
                graded_result=inter.get("graded_result"), difficulty=inter.get("difficulty", ""),
            )
            for inter in scene_data.get("interactions", [])
        ]
        auto_triggers = [
            Entity(
                id=at["id"], entity_type=at.get("entity_type", "auto_trigger"),
                name=at["name"], scene=at.get("scene", scene_name),
                type=at.get("type", ""), requirement=at.get("requirement", ""),
                trigger=at.get("trigger", ""), result=at.get("result", ""),
                side_effects=at.get("side_effects", []),
                graded_result=at.get("graded_result"), difficulty=at.get("difficulty", ""),
            )
            for at in scene_data.get("auto_triggers", [])
        ]

        from_edges = [
            Edge(target=conn["target"], method=conn.get("method", ""),
                 requirement=conn.get("requirement", ""))
            for conn in scene_data.get("from_here", [])
        ]
        to_edges = [
            Edge(target=conn.get("source", conn.get("target", "")),
                 method=conn.get("method", ""),
                 requirement=conn.get("requirement", ""))
            for conn in scene_data.get("to_here", [])
        ]

        graph.nodes[scene_name] = Node(
            node_id=scene_name,
            description=scene_data.get("description", ""),
            edges=from_edges,
            to_here=to_edges,
            interactions=interactions,
            auto_triggers=auto_triggers,
            encounters=scene_data.get("encounters", []),
            scene_weapons=scene_data.get("scene_weapons", []),
            extra=scene_data.get("extra", {}),
        )
```

- [ ] **Step 6: Commit**

```bash
git add src/game/agents/keeper.py
git commit -m "refactor: Keeper — IntentDetector parallel scheduling, _integrate_supplement, remove escalation"
```

---

### Task 8: Update Game Loop — WR0 config passing

**Files:**
- Modify: `src/game_loop.py`

- [ ] **Step 1: Add WR0 to init_game and ScenarioWorld construction**

In `init_game()`, add `wr0_enabled` parameter (default False):

```python
def init_game(l2_path: str, l1_path: str, l3_path: str,
              escalation_config_path: str,
              start_node: str = "6号车厢",
              wr0_enabled: bool = False) -> dict[str, Any]:
```

Update `ScenarioWorld` construction:
```python
    world = ScenarioWorld(graph, start_node=start_node, wr0_enabled=wr0_enabled)
```

Remove `escalation_policy` from Keeper construction:
```python
    keeper = Keeper(
        world,
        dependency_graph=l2.get("dependency_graph"),
        phase1=l2.get("_phase1"),
        npc_profiles=l2.get("npc_profiles"),
    )
```

Also pass L1 data to keeper so Narrator can access merged supplements:
```python
    keeper.narrator_l1 = l1  # Keeper holds reference for supplement merging
```

The `escalation_config_path` parameter can be kept for backward compatibility (ignored) or removed. Keep it for now with a deprecation note:

```python
def init_game(l2_path: str, l1_path: str, l3_path: str,
              escalation_config_path: str = "",  # deprecated, kept for compat
              start_node: str = "6号车厢",
              wr0_enabled: bool = False) -> dict[str, Any]:
```

- [ ] **Step 2: Commit**

```bash
git add src/game_loop.py
git commit -m "feat: add wr0_enabled to init_game; remove EscalationPolicy from Keeper init"
```

---

### Task 9: Create Author flow quasi-unit-test

**Files:**
- Create: `tests/test_author_flow.py`

- [ ] **Step 1: Write the test file**

```python
"""Quasi-unit tests for Author intervention flow — all LLM calls mocked.

Covers the complete chain: IntentDetector → Author → Keeper integration.
Each test injects mock LLM responses via monkeypatch to simulate different scenarios.

Test scenarios:
  A. No "other" in parse → zero LLM overhead
  B. "other" + flavor behavior → Detector says no, normal flow
  C. "other" + meaningful → Detector says yes → Author patch → integrate → recurse
  D. "other" + meaningful → Author rejects (entities=[]) → normal flow
  E. "other" + meaningful → Author structural → supplement pipeline → integrate
  F. Duplicate intent suppression (same intent within cooldown)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import json
import pytest
from unittest.mock import patch, MagicMock
from scenario_core import (
    DirectedGraph, ScenarioWorld, Entity, Node, Edge,
    NodeRuntimeState, parse_markup_all, resolve_graded_result,
)
from game.messages import (
    ActionIntent, ActionOutcome, TurnInput, NarratorBrief,
    AuthorRequest, IntentResult, ModulePatch, StructuralEdit,
)
from game.intent_detector import IntentDetector
from game.agents.keeper import Keeper
from game.agents.author import Author
from game.judge import Judge
from game.curator import Curator


# ═══════════════════════════════════════════════════════════════
#  Test fixtures
# ═══════════════════════════════════════════════════════════════

def _make_test_world():
    """Minimal ScenarioWorld with one scene, one interaction."""
    scenes = {
        "测试房间": {
            "interactions": [
                {
                    "id": "I1", "entity_type": "interaction",
                    "name": "检查桌子", "scene": "测试房间",
                    "type": "侦查", "requirement": "", "trigger": "检查桌子",
                    "result": "##GRADED##",
                    "side_effects": [],
                    "graded_result": {
                        "on_failure": "没发现什么",
                        "on_regular": "发现了一些东西",
                        "on_hard": "发现了很多东西",
                        "on_extreme": "完全理解了",
                    },
                    "difficulty": "regular",
                }
            ],
            "auto_triggers": [],
            "from_here": [],
            "to_here": [],
            "encounters": [],
            "scene_weapons": [],
            "description": "一个测试房间",
            "extra": {},
        }
    }
    graph = DirectedGraph(scenes=scenes, events=[])
    world = ScenarioWorld(graph, start_node="测试房间")
    world.load_dependency_graph({"nodes": {}, "edges": []})
    return world


def _make_test_author():
    """Minimal Author with L3 data."""
    l3 = {
        "module_meta": {"name": "test"},
        "world_rules": {},
        "scene_intents": {},
        "ending_conditions": [],
        "tone_constraints": {
            "genre": "恐怖",
            "narrative_style": "克苏鲁",
            "forbidden": [],
            "required": [],
        },
        "characters": {},
        "driving_force": "逃离",
    }
    return Author(l3)


def _mock_llm_json(return_data: dict):
    """Create a mock call_deepseek that returns a JSON dict."""
    def _mock(prompt, json_mode=True, model="", system="", reasoning_effort="",
              fallback_schema=None):
        return json.dumps(return_data)
    return _mock


# ═══════════════════════════════════════════════════════════════
#  Test A: No "other" — zero overhead
# ═══════════════════════════════════════════════════════════════

def test_no_other_zero_overhead(monkeypatch):
    """Parse returns only entity matches — no IntentDetector call, no Author call."""
    world = _make_test_world()
    keeper = Keeper(world)

    parse_calls = 0
    def _count_parse(prompt, json_mode=True, model="", system="", reasoning_effort="",
                     fallback_schema=None):
        nonlocal parse_calls
        parse_calls += 1
        return json.dumps({"actions": [{"type": "interaction", "id": "I1"}]})

    monkeypatch.setattr("game.agents.keeper.call_deepseek", _count_parse)

    detect_called = [False]
    original_detect = keeper.intent_detector.detect
    def _no_detect(*args, **kwargs):
        detect_called[0] = True
        return original_detect(*args, **kwargs)
    keeper.intent_detector.detect = _no_detect

    # Run process_turn without author (no escalation possible)
    turn = TurnInput(raw_text="检查桌子")
    result = keeper.process_turn(turn, author=None)

    assert not detect_called[0], "Detector should not be called when no 'other' in parse"
    assert result["escalation"] is None


# ═══════════════════════════════════════════════════════════════
#  Test B: "other" + flavor → Detector says no
# ═══════════════════════════════════════════════════════════════

def test_other_flavor_no_escalation(monkeypatch):
    """Player sings a song → Detector says needs_author=False → normal flow."""
    world = _make_test_world()
    keeper = Keeper(world)
    author = _make_test_author()

    parse_response = {"actions": [{"type": "other", "text": "唱了一首快乐的小曲"}]}
    detect_response = {"has_intent": False, "intent": "", "reasoning": "纯角色扮演"}

    call_count = [0]
    def _mock_call(prompt, json_mode=True, model="", system="", reasoning_effort="",
                   fallback_schema=None):
        call_count[0] += 1
        if call_count[0] == 1:  # Parse
            return json.dumps(parse_response)
        elif call_count[0] == 2:  # Detector
            return json.dumps(detect_response)
        return json.dumps({})

    monkeypatch.setattr("game.agents.keeper.call_deepseek", _mock_call)
    monkeypatch.setattr("game.intent_detector.call_deepseek", _mock_call)

    turn = TurnInput(raw_text="唱了一首快乐的小曲")
    result = keeper.process_turn(turn, author=author)

    # Should complete normally without escalation
    assert result["escalation"] is None


# ═══════════════════════════════════════════════════════════════
#  Test C: "other" + meaningful → Author patch → integrate
# ═══════════════════════════════════════════════════════════════

def test_other_meaningful_author_patch(monkeypatch):
    """Player tries new action → Detector triggers → Author returns patch → integrated."""
    world = _make_test_world()
    keeper = Keeper(world)
    author = _make_test_author()

    call_seq = [0]
    def _mock_call(prompt, json_mode=True, model="", system="", reasoning_effort="",
                   fallback_schema=None):
        call_seq[0] += 1
        n = call_seq[0]
        if "判断以下玩家行为是纯角色扮演" in prompt:
            return json.dumps({
                "has_intent": True,
                "intent": "玩家想检查座椅底下的暗格",
                "reasoning": "模组中未覆盖此搜索点",
            })
        elif "请评估此意图的范围" in prompt:
            return json.dumps({
                "level": "patch",
                "entities": [{
                    "id": "SI1", "entity_type": "interaction",
                    "scene": "测试房间", "name": "检查座椅底下",
                    "type": "侦查", "requirement": "", "trigger": "玩家弯腰检查座椅底部",
                    "result": "你发现了一个隐藏的暗格",
                    "side_effects": [], "graded_result": None, "difficulty": "regular",
                }],
                "scene_descriptions": {},
                "justification": "座椅底下是合理的搜索点，模组未覆盖",
            })
        elif n == 1:  # Parse
            return json.dumps({"actions": [{"type": "other", "text": "检查座椅底下有没有暗格"}]})
        else:  # Enrich on recursion
            return json.dumps({"results": {}, "reasoning": "", "emphasis_hint": ""})

    monkeypatch.setattr("game.agents.keeper.call_deepseek", _mock_call)
    monkeypatch.setattr("game.intent_detector.call_deepseek", _mock_call)

    turn = TurnInput(raw_text="检查座椅底下有没有暗格")
    result = keeper.process_turn(turn, author=author)

    # After integration, SI1 should exist in the scene
    node = world.graph.nodes.get("测试房间")
    entity_names = [e.name for e in (node.interactions if node else [])]
    assert "检查座椅底下" in entity_names, f"Patch entity not integrated. Found: {entity_names}"


# ═══════════════════════════════════════════════════════════════
#  Test D: Author rejects → entities=[] → normal flow
# ═══════════════════════════════════════════════════════════════

def test_other_author_rejects(monkeypatch):
    """Player tries something world-rule-breaking, WR0=off, Author rejects."""
    world = _make_test_world()
    keeper = Keeper(world)
    author = _make_test_author()

    call_seq = [0]
    def _mock_call(prompt, json_mode=True, model="", system="", reasoning_effort="",
                   fallback_schema=None):
        call_seq[0] += 1
        n = call_seq[0]
        if "判断以下玩家行为是纯角色扮演" in prompt:
            return json.dumps({
                "has_intent": True,
                "intent": "玩家想一拳打碎墙壁",
                "reasoning": "这是对场景的破坏性行为",
            })
        elif "请评估此意图的范围" in prompt:
            return json.dumps({
                "level": "patch",
                "entities": [],
                "scene_descriptions": {},
                "justification": "REJECTED: 墙壁是列车结构，无法用拳头打碎",
            })
        elif n == 1:  # Parse
            return json.dumps({"actions": [{"type": "other", "text": "一拳打碎车厢墙壁"}]})
        else:  # Enrich
            return json.dumps({"results": {}, "reasoning": "", "emphasis_hint": ""})

    monkeypatch.setattr("game.agents.keeper.call_deepseek", _mock_call)
    monkeypatch.setattr("game.intent_detector.call_deepseek", _mock_call)

    turn = TurnInput(raw_text="一拳打碎车厢墙壁")
    result = keeper.process_turn(turn, author=author)

    # Should complete normally (escalation None, no entities added)
    assert result["escalation"] is None
    node = world.graph.nodes["测试房间"]
    # No new entity should have been added
    assert len(node.interactions) == 1  # Only original I1


# ═══════════════════════════════════════════════════════════════
#  Test E: Duplicate intent suppression
# ═══════════════════════════════════════════════════════════════

def test_duplicate_intent_suppressed(monkeypatch):
    """Same intent within cooldown window should not re-trigger Author."""
    world = _make_test_world()
    keeper = Keeper(world)
    author = _make_test_author()

    author_call_count = [0]

    detect_seq = [0]
    def _mock_detect(other_text, world_snapshot):
        detect_seq[0] += 1
        return IntentResult(
            needs_author=True,
            intent="玩家想和NPC对话",
            reasoning="未覆盖的交流行为",
        )

    author_seq = [0]
    def _mock_author(request, turn_number=0):
        author_seq[0] += 1
        author_call_count[0] += 1
        return ModulePatch(
            entities=[{
                "id": f"SI_auto_{author_seq[0]}",
                "entity_type": "interaction",
                "scene": "测试房间",
                "name": f"对话_{author_seq[0]}",
                "type": "", "requirement": "", "trigger": "",
                "result": "NPC回应了",
                "side_effects": [], "graded_result": None, "difficulty": "regular",
            }],
            scene_descriptions={},
            justification="test",
        )

    keeper.intent_detector.detect = _mock_detect
    original_handle = author.handle_request
    author.handle_request = _mock_author

    call_seq = [0]
    def _mock_llm(prompt, json_mode=True, model="", system="", reasoning_effort="",
                  fallback_schema=None):
        call_seq[0] += 1
        if call_seq[0] <= 2:  # Parse for first turn
            return json.dumps({"actions": [{"type": "other", "text": "和乘务员聊聊吧"}]})
        else:  # Enrich
            return json.dumps({"results": {}, "reasoning": "", "emphasis_hint": ""})

    monkeypatch.setattr("game.agents.keeper.call_deepseek", _mock_llm)

    # First call: should trigger Author
    turn1 = TurnInput(raw_text="和乘务员聊聊吧")
    result1 = keeper.process_turn(turn1, author=author)
    assert author_call_count[0] == 1

    # Simulate next turn with same intent
    keeper._recent_intents.append("玩家想和npc对话")
    keeper._recent_intents.append("玩家想和npc对话")

    # Second call: should NOT trigger Author (suppressed by cooldown)
    call_seq[0] = 0  # reset
    turn2 = TurnInput(raw_text="和乘务员再聊聊")
    result2 = keeper.process_turn(turn2, author=author)
    assert author_call_count[0] == 1, f"Expected still 1, got {author_call_count[0]}"

    # Cleanup
    author.handle_request = original_handle


# ═══════════════════════════════════════════════════════════════
#  Test F: AuthorRequest field integrity
# ═══════════════════════════════════════════════════════════════

def test_author_request_fields():
    """AuthorRequest carries all required fields correctly."""
    req = AuthorRequest(
        other_texts=["唱了一首歌", "试图对话"],
        intent="沟通意图",
        reasoning="未覆盖的社交行为",
        scene_context={
            "location": "测试房间",
            "description": "昏暗的房间",
            "available_scenes": ["测试房间", "走廊"],
            "npc_states": {"乘务员": "清醒"},
            "runtime_summary": {"I1": "regular"},
            "wr0_enabled": False,
        },
    )
    assert len(req.other_texts) == 2
    assert req.scene_context["wr0_enabled"] is False
    assert req.scene_context["available_scenes"] == ["测试房间", "走廊"]


# ═══════════════════════════════════════════════════════════════
#  Test G: _integrate_supplement entry/exit connections
# ═══════════════════════════════════════════════════════════════

def test_integrate_supplement_connects_entry():
    """_integrate_supplement adds from_here edge from entry scene."""
    world = _make_test_world()
    keeper = Keeper(world)
    author = _make_test_author()

    # Mock supplement pipeline to return minimal data
    def _mock_pipeline(**kwargs):
        return {
            "l1": {"新场景": {"description": "新场景", "atmosphere": "", "mood": "",
                              "perceptible": [], "ambient_hints": [], "npc_appearances": {}}},
            "l2": {
                "scenes": {
                    "新场景": {
                        "description": "全新的区域",
                        "interactions": [],
                        "auto_triggers": [],
                        "from_here": [],
                        "to_here": [{"source": "测试房间", "method": "走进去", "requirement": ""}],
                        "encounters": [], "scene_weapons": [], "extra": {},
                    }
                },
                "events": [],
                "npc_profiles": {},
                "dependency_graph": {"nodes": {}, "edges": []},
                "_scene_names": {},
                "_phase1": {},
            },
            "l3": {"module_meta": {}, "world_rules": {}, "scene_intents": {},
                   "ending_conditions": [], "tone_constraints": {}, "characters": {},
                   "driving_force": ""},
            "output_dir": "/tmp/test_supp",
        }

    import module_designer.supplement_pipeline as sp
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(sp, "run_supplement_pipeline", _mock_pipeline)

    se = StructuralEdit(entry_scene="测试房间", exit_scene="", justification="测试")
    result = keeper._integrate_supplement(se, author)

    # Verify new scene exists in graph
    assert "新场景" in world.graph.nodes
    # Verify entry scene has edge to new scene
    entry_node = world.graph.nodes["测试房间"]
    targets = [e.target for e in entry_node.edges]
    assert "新场景" in targets, f"Entry scene should connect to new scene. Edges: {targets}"
    assert result.supplement_path == "/tmp/test_supp"

    monkeypatch.undo()


# ═══════════════════════════════════════════════════════════════
#  Test H: Keeper._build_scene_context_for_author
# ═══════════════════════════════════════════════════════════════

def test_build_scene_context_for_author():
    """_build_scene_context_for_author returns all required keys."""
    world = _make_test_world()
    world.wr0_enabled = True
    world.npc_states["乘务员"] = "清醒"
    world.runtime_state["I1"] = NodeRuntimeState(completed=True, result_tier="regular")

    keeper = Keeper(world)
    ctx = keeper._build_scene_context_for_author()

    assert ctx["location"] == "测试房间"
    assert ctx["description"] == "一个测试房间"
    assert "测试房间" in ctx["available_scenes"]
    assert ctx["npc_states"] == {"乘务员": "清醒"}
    assert ctx["runtime_summary"] == {"I1": "regular"}
    assert ctx["wr0_enabled"] is True
```

- [ ] **Step 2: Run tests**

```bash
cd tests && python -m pytest test_author_flow.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_author_flow.py
git commit -m "test: add Author flow quasi-unit-tests (A-H), all LLM calls mocked"
```

---

### Task 10: Final integration verification

**Files:**
- Verify: `src/game/` all files
- Verify: `tests/` all tests

- [ ] **Step 1: Run existing test harness**

```bash
cd tests && python game_loop_harness.py
```

Expected: 7 turns complete. Check output for errors. (Note: harness uses its own inline judge/enrich logic, not Keeper.process_turn directly — verify it still works.)

- [ ] **Step 2: Run all new tests**

```bash
cd tests && python -m pytest test_intent_detector.py test_author_flow.py -v
```

Expected: All tests pass.

- [ ] **Step 3: Verify no broken imports**

```bash
cd src && python -c "
from game.agents.keeper import Keeper
from game.agents.author import Author
from game.intent_detector import IntentDetector, IntentResult
from game.messages import AuthorRequest, ModulePatch, StructuralEdit
from module_designer.supplement_pipeline import run_supplement_pipeline
print('All imports OK')
"
```

- [ ] **Step 4: Commit final state**

```bash
git add -A
git commit -m "chore: final integration verification after escalation redesign"
```
