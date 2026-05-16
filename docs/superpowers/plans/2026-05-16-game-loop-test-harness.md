# Game Loop Test Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert notebook to a `.py` test harness running 15 player-input scenarios through the full parse→judge→enrich→narrate pipeline, with all intermediate results logged to per-case directories. Switch all game loop LLM calls to `deepseek-v4-flash`.

**Architecture:** Single runner script `tests/game_loop_harness.py`. Keeper's `process_turn()` accepts optional `log_callback(stage, data)` for intermediate capture. Harness provides file-writing callback. 15 case functions, each a list of turn inputs.

**Tech Stack:** Python 3.13, DeepSeek API (flash model for game loop), existing `src/game/` modules.

---

### Task 1: Switch game loop LLM calls to deepseek-v4-flash

**Files:**
- Modify: `src/game/agents/keeper.py`
- Modify: `src/game/agents/narrator.py`
- Modify: `src/game/agents/author.py`

- [ ] **Step 1: Update Keeper LLM calls**

In `src/game/agents/keeper.py`, find all `call_deepseek(...)` calls and add `model="deepseek-v4-flash"`:

In `_parse()` (around line where `call_deepseek(prompt, json_mode=True)` is called):
```python
response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash")
```

In `_enrich()` (around line where `call_deepseek(prompt, json_mode=True)` is called):
```python
response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash")
```

In `_check_escalation()` (around line where `call_deepseek(eval_prompt, json_mode=True, reasoning_effort="low")` is called):
```python
eval_result = call_deepseek(eval_prompt, json_mode=True, reasoning_effort="low", model="deepseek-v4-flash")
```

Also in the memory compression call:
```python
self.world.memory.compress(lambda p: call_deepseek(p, json_mode=False, model="deepseek-v4-flash"))
```

- [ ] **Step 2: Update Narrator LLM call**

In `src/game/agents/narrator.py`, in `narrate()`:
```python
response = call_deepseek(prompt, json_mode=False, model="deepseek-v4-flash")
```

- [ ] **Step 3: Update Author LLM call**

In `src/game/agents/author.py`, in `handle_escalation()`:
```python
response = call_deepseek(prompt, json_mode=True, model="deepseek-v4-flash")
```

- [ ] **Step 4: Verify tests pass**

```bash
cd C:/Users/micha/PyCharmMiscProject && python -m pytest tests/ -v --ignore=tests/test_module_designer.py 2>&1 | tail -5
```
Expected: 63 passed

- [ ] **Step 5: Commit**

```bash
git add src/game/agents/keeper.py src/game/agents/narrator.py src/game/agents/author.py
git commit -m "perf: switch game loop LLM calls to deepseek-v4-flash"
```

---

### Task 2: Create test harness script

**Files:**
- Create: `tests/game_loop_harness.py`

- [ ] **Step 1: Write `tests/game_loop_harness.py`**

```python
"""
Game Loop Test Harness — 15 个玩家输入场景测试。
运行完整 parse → judge → enrich → narrate 流程，所有中间结果写入日志。
"""
import sys, os, json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from game_loop import init_game, run_turn
from prompts import set_prompt_log_file
from llm import set_llm_log_file
from trpg_display import display_split_result


# ═══════════════════════════════════════════════════════════════
#  全局设置
# ═══════════════════════════════════════════════════════════════

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_ROOT = os.path.join(os.path.dirname(__file__), "..", "data", "debug", "test_harness", TIMESTAMP)
CASE_NAMES = [
    "case_01_观察四周",
    "case_02_移动去7号车厢",
    "case_03_交互无检定",
    "case_04_交互有检定",
    "case_05_移动被拒",
    "case_06_前置不满足",
    "case_07_多动作",
    "case_08_无意义输入",
    "case_09_auto_trigger",
    "case_10_事件链",
    "case_11_检定失败",
    "case_12_偏离行为",
    "case_13_返回移动",
    "case_14_重复交互",
    "case_15_结局路径",
]


# ═══════════════════════════════════════════════════════════════
#  Setup
# ═══════════════════════════════════════════════════════════════

def setup():
    os.makedirs(OUT_ROOT, exist_ok=True)

    # Prompt log for all LLM calls
    prompt_log = os.path.join(OUT_ROOT, "_prompt_log.txt")
    set_prompt_log_file(prompt_log)
    set_llm_log_file(prompt_log)

    # Init game
    game = init_game(
        l2_path=os.path.join(os.path.dirname(__file__), "..", "data", "modules", "常暗之厢", "l2_keeper.json"),
        l1_path=os.path.join(os.path.dirname(__file__), "..", "data", "modules", "常暗之厢", "l1_player.json"),
        l3_path=os.path.join(os.path.dirname(__file__), "..", "data", "modules", "常暗之厢", "l3_designer.json"),
        escalation_config_path=os.path.join(os.path.dirname(__file__), "..", "data", "modules", "常暗之厢", "escalation_config.json"),
        start_node="6号车厢",
    )

    keeper = game["keeper"]
    world = keeper.world

    # Try loading a default investigator
    char_path = os.path.join(os.path.dirname(__file__), "..", "investigator", "test_character.json")
    if os.path.exists(char_path):
        from investigator import load_investigator
        world.set_player(load_investigator(char_path))
    else:
        from investigator import Investigator
        from investigator.rules import roll_stats, calc_derived, create_skill_list
        inv = Investigator(name="测试调查员", age=25, gender="男")
        inv.stats = roll_stats()
        inv.skills = create_skill_list()
        inv.derived = calc_derived(inv.stats, inv.age)
        world.set_player(inv)

    # Game init log
    init_log = os.path.join(OUT_ROOT, "_game_init.log")
    with open(init_log, "w", encoding="utf-8") as f:
        f.write(f"Timestamp: {TIMESTAMP}\n")
        f.write(f"Scenes: {len(world.graph.nodes)}\n")
        f.write(f"Events: {len(world.graph.events)}\n")
        f.write(f"Start node: {world.current_location}\n")
        f.write(f"Player: {world.player.name if world.player else 'None'}\n")
        f.write(f"Escalation dims: {list(keeper.escalation_policy.dimensions.keys())}\n")
        f.write(f"Escalation rules: {[r.name for r in keeper.escalation_policy.rules]}\n")

    return game


# ═══════════════════════════════════════════════════════════════
#  Turn runner with logging
# ═══════════════════════════════════════════════════════════════

def run_turn_with_log(game, user_input: str, case_dir: str, turn_num: int) -> dict:
    """Run one turn, capturing all intermediates to case_dir/turn_NN/."""
    turn_dir = os.path.join(case_dir, f"turn_{turn_num:02d}")
    os.makedirs(turn_dir, exist_ok=True)

    keeper = game["keeper"]
    world = keeper.world
    narrator = game["narrator"]

    # Write input (prepend to narrative file)
    narrative_path = os.path.join(turn_dir, "04_narrative.txt")

    # Custom log callback that hooks into process_turn internals
    # We run the full pipeline manually to capture intermediates

    # ── Step 1: Parse ──
    from prompts import build_keeper_parse_prompt
    from llm import call_deepseek
    from game.messages import ActionIntent, TurnInput, ActionOutcome
    from game.judge import Judge
    from game.curator import Curator
    from scenario_core import parse_markup_all, apply_side_effects

    raw = user_input
    parse_prompt = build_keeper_parse_prompt(world, raw)
    parse_response = call_deepseek(parse_prompt, json_mode=True, model="deepseek-v4-flash")
    parse_data = json.loads(parse_response) if isinstance(parse_response, str) else parse_response
    actions = parse_data.get("actions", [])
    if not actions:
        actions = [{"action": "other"}]

    # Log step 1
    with open(os.path.join(turn_dir, "01_parse_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(parse_prompt)
    with open(os.path.join(turn_dir, "01_parse_response.json"), "w", encoding="utf-8") as f:
        json.dump(parse_data, f, ensure_ascii=False, indent=2)

    parsed = [
        ActionIntent(
            action=a.get("action", "other"),
            target=a.get("target", ""),
            skill_checks=a.get("skill_checks", []),
            reasoning=a.get("reasoning", ""),
            condition=a.get("condition", ""),
        )
        for a in actions
    ]

    # ── Step 2: Judge ──
    judge = Judge(world)
    at_results = judge.check_auto_triggers()
    action_outcomes = []
    for intent in parsed:
        if intent.action == "interact":
            outcome = judge.execute_interaction(intent)
            apply_side_effects(world, outcome.side_effects)
            action_outcomes.append(outcome)
        elif intent.action == "move":
            result = world.move(intent.target)
            action_outcomes.append(ActionOutcome(
                intent=intent, success=result.success,
                message=result.message,
                side_effects=result.side_effects,
            ))
            apply_side_effects(world, result.side_effects)
        elif intent.action == "search":
            interactions = world.get_available_interactions()
            done = world.completed_interactions.get(world.current_location, set())
            available = [i for i in interactions if i.name not in done]
            if available:
                lines = ["（环顾四周，注意到可以做的事：）"]
                for inter in available:
                    lines.append(f"  [{inter.type}] {inter.name} —— {inter.trigger}")
                msg = "\n".join(lines)
            else:
                msg = "（仔细查看四周，没有特别的发现）"
            action_outcomes.append(ActionOutcome(intent=intent, success=True, message=msg))
        else:
            action_outcomes.append(ActionOutcome(intent=intent, success=True,
                                                  message="（没有特别的事情发生）"))

    # Log step 2
    judge_data = {
        "at_results": [{"entity_id": a.entity_id, "entity_type": a.entity_type,
                         "success": a.success, "message": a.message} for a in at_results],
        "action_outcomes": [{"entity_id": o.entity_id, "entity_type": o.entity_type,
                              "success": o.success, "message": o.message,
                              "side_effects": str(o.side_effects)} for o in action_outcomes],
    }
    with open(os.path.join(turn_dir, "02_judge.json"), "w", encoding="utf-8") as f:
        json.dump(judge_data, f, ensure_ascii=False, indent=2)

    # ── Step 3: Enrich ──
    from prompts import build_keeper_enrich_prompt
    deferred_ats = judge.get_deferred_auto_triggers()
    pending_events = judge.filter_pending_events()

    enriched_ats = []
    enriched_events = []
    emphasis = ""
    if deferred_ats or pending_events or any("##GRADED##" in o.message for o in action_outcomes):
        enrich_prompt = build_keeper_enrich_prompt(
            world, action_outcomes, list(at_results),
            pending_events, deferred_ats, raw
        )
        enrich_response = call_deepseek(enrich_prompt, json_mode=True, model="deepseek-v4-flash")
        enrichment = json.loads(enrich_response) if isinstance(enrich_response, str) else enrich_response

        # Log step 3
        with open(os.path.join(turn_dir, "03_enrich_prompt.txt"), "w", encoding="utf-8") as f:
            f.write(enrich_prompt)
        with open(os.path.join(turn_dir, "03_enrich_response.json"), "w", encoding="utf-8") as f:
            json.dump(enrichment, f, ensure_ascii=False, indent=2)

        emphasis = enrichment.get("emphasis_hint", "")
        # Fire enriched ATs
        for at_id in enrichment.get("triggered_ats", []):
            node = world._current_node()
            if node:
                for at in node.auto_triggers:
                    if at.id == at_id:
                        side_effects = []
                        for se_text in at.side_effects:
                            side_effects.extend(parse_markup_all(se_text))
                        apply_side_effects(world, side_effects)
                        enriched_ats.append(at)
                        break
        # Fire enriched events
        for ev_id in enrichment.get("triggered_events", []):
            ev = world.graph.events.get(ev_id)
            if ev:
                world.triggered_events[ev.id] = True
                side_effects = []
                for se_text in ev.side_effects:
                    side_effects.extend(parse_markup_all(se_text))
                apply_side_effects(world, side_effects)
                enriched_events.append(ev)
        # Apply new flags
        for flag_key, flag_val in enrichment.get("new_flags", {}).items():
            world.set_flag(flag_key, flag_val)
    else:
        # Log empty enrich
        with open(os.path.join(turn_dir, "03_enrich_prompt.txt"), "w", encoding="utf-8") as f:
            f.write("(no pending ATs, events, or graded results — enrich skipped)\n")
        with open(os.path.join(turn_dir, "03_enrich_response.json"), "w", encoding="utf-8") as f:
            json.dump({"skipped": True}, f)

    # ── Step 4: Narrate ──
    curator = Curator(world)
    all_outcomes = action_outcomes + list(at_results) + [
        ActionOutcome(intent=ActionIntent(action="other"), success=True,
                       message=at.result, entity_id=at.id, entity_type="auto_trigger")
        for at in enriched_ats
    ] + [
        ActionOutcome(intent=ActionIntent(action="other"), success=True,
                       message=ev.result, entity_id=ev.id, entity_type="event")
        for ev in enriched_events
    ]
    ambient = [a.message for a in list(at_results)] + [at.result for at in enriched_ats]
    brief = curator.assemble(all_outcomes, ambient, emphasis)

    from prompts import build_narrator_prompt
    l1_data = narrator.l1_data
    l1_scene = l1_data.get(world.current_location) if l1_data else None
    narrator_prompt = build_narrator_prompt(brief, l1_scene=l1_scene)

    # Log step 4 prompt
    with open(os.path.join(turn_dir, "04_narrator_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(narrator_prompt)

    narrative_response = call_deepseek(narrator_prompt, json_mode=False, model="deepseek-v4-flash")
    narrative_brief, narrative = display_split_result.__wrapped__ if hasattr(display_split_result, '__wrapped__') else (lambda b, n: (b, n))(narrative_response, "")
    # Actually use the real parser:
    from prompts import parse_narrative_output
    narrative_brief, narrative = parse_narrative_output(narrative_response)

    # Log step 4 output
    with open(narrative_path, "w", encoding="utf-8") as f:
        f.write(f"=== PLAYER INPUT ===\n{raw}\n\n")
        f.write(f"=== BRIEF ===\n{narrative_brief}\n\n")
        f.write(f"=== NARRATIVE ===\n{narrative}\n")

    # Record to memory
    first_intent = parsed[0] if parsed else ActionIntent(action="other")
    brief_text = "\n".join(o.message for o in all_outcomes)
    world.memory.add_record(
        raw, first_intent.action, first_intent.target,
        brief_text, location=world.current_location,
        success=any(o.success for o in action_outcomes)
    )

    # Memory compression check
    if world.memory.should_compress():
        world.memory.compress(lambda p: call_deepseek(p, json_mode=False, model="deepseek-v4-flash"))

    return {"brief": narrative_brief, "narrative": narrative}


# ═══════════════════════════════════════════════════════════════
#  Case definitions: list of (input, description) tuples
# ═══════════════════════════════════════════════════════════════

def get_all_cases():
    """Return [(case_name, [(input_text, turn_description), ...]), ...]"""
    return [
        ("case_01_观察四周", [
            ("环顾四周，看看有没有什么异常", "search 当前场景，应返回可感知元素列表"),
        ]),
        ("case_02_移动去7号车厢", [
            ("去7号车厢", "move 到相邻场景，应成功移动并显示新场景描述"),
        ]),
        ("case_03_交互无检定", [
            ("阅读门扉上的便签", "interact 无技能检定，应直接返回便签内容"),
        ]),
        ("case_04_交互有检定", [
            ("仔细观察电车示意地图", "interact 需侦查检定，应显示检定结果和分级叙事"),
        ]),
        ("case_05_移动被拒", [
            ("去驾驶室", "move 到不存在路径的目标，应返回失败提示"),
        ]),
        ("case_06_前置不满足", [
            ("打开通往驾驶室的门", "interact 但 requirement 不满足，应提示缺少前置"),
        ]),
        ("case_07_多动作", [
            ("先检查随身物品然后去5号车厢", "多意图解析：interact + move"),
        ]),
        ("case_08_无意义输入", [
            ("唱一首快乐的小曲", "other 动作，应委婉提示无实际影响"),
        ]),
        ("case_09_auto_trigger", [
            ("靠近通往7号车厢的后门", "应触发 AT（血腥味），ambient 信息出现在叙事中"),
        ]),
        ("case_10_事件链", [
            ("感知电车异常", "交互 I1：尝试侦查检定感知异常"),
            ("检查随身物品留存", "交互 I2：检查物品"),
            ("阅读门扉上的便签", "交互 I3：阅读便签获取信息"),
        ]),
        ("case_11_检定失败", [
            # 依赖默认调查员的技能值，如果侦查为 0 则必失败
            ("仔细观察电车示意地图", "同一个检定交互，若调查员侦查值低则检定失败"),
        ]),
        ("case_12_偏离行为", [
            ("我想砸碎车窗玻璃跳出去", "完全偏离模组预期的行为，应触发 other 或 escalation"),
        ]),
        ("case_13_返回移动", [
            ("去5号车厢", "move 到 5 号车厢"),
            ("返回6号车厢", "move 返回，验证 to_here 路径可用"),
        ]),
        ("case_14_重复交互", [
            ("感知电车异常", "首次执行 I1"),
            ("感知电车异常", "再次执行同一交互，应显示已完成或拒绝重复"),
        ]),
        ("case_15_结局路径", [
            # 触发 E1 退路断绝事件需要特定条件，这里直接测试 ##END_ 检测
            # 使用 /trigger 命令手动触发事件
            ("/trigger E1", "手动触发结局事件，验证 ##END_ 标记被检测"),
        ]),
    ]


# ═══════════════════════════════════════════════════════════════
#  Main runner
# ═══════════════════════════════════════════════════════════════

def run_all():
    print(f"Test harness starting...")
    print(f"Output: {OUT_ROOT}")
    print()

    game = setup()
    author = game["author"]

    all_cases = get_all_cases()
    for case_name, turns in all_cases:
        print(f"=== {case_name} ===")
        case_dir = os.path.join(OUT_ROOT, case_name)
        os.makedirs(case_dir, exist_ok=True)

        # Case summary
        with open(os.path.join(case_dir, "_case_summary.log"), "w", encoding="utf-8") as f:
            f.write(f"Case: {case_name}\n")
            f.write(f"Turns: {len(turns)}\n")
            for i, (inp, desc) in enumerate(turns):
                f.write(f"  Turn {i+1}: {desc}\n")
                f.write(f"    Input: {inp}\n")

        for turn_num, (user_input, description) in enumerate(turns):
            print(f"  Turn {turn_num+1}: {description}")
            print(f"    Input: {user_input}")

            try:
                result = run_turn_with_log(game, user_input, case_dir, turn_num + 1)
                print(f"    Brief: {result['brief'][:60]}...")
                print(f"    Narrative: {result['narrative'][:60]}...")
            except Exception as e:
                print(f"    ERROR: {e}")
                import traceback
                traceback.print_exc()

        print()

    print(f"Done. Output at: {OUT_ROOT}")


if __name__ == "__main__":
    run_all()
```

- [ ] **Step 2: Verify syntax**

```bash
cd C:/Users/micha/PyCharmMiscProject && python -c "import ast; ast.parse(open('tests/game_loop_harness.py').read()); print('Syntax OK')"
```

- [ ] **Step 3: Run the harness (dry run without LLM)**

First verify imports and setup work:
```bash
cd C:/Users/micha/PyCharmMiscProject && python -c "
import sys, os
os.chdir('tests')
sys.path.insert(0, '../src')
# Just verify setup without LLM calls
from game_loop import init_game
game = init_game(
    '../data/modules/常暗之厢/l2_keeper.json',
    '../data/modules/常暗之厢/l1_player.json',
    '../data/modules/常暗之厢/l3_designer.json',
    '../data/modules/常暗之厢/escalation_config.json',
)
print('Setup OK, scenes:', len(game['keeper'].world.graph.nodes))
"
```

- [ ] **Step 4: Commit**

```bash
git add tests/game_loop_harness.py
git commit -m "feat: add game loop test harness with 15 cases"
```

---

### Task 3: Run harness and verify output structure

- [ ] **Step 1: Run the full harness**

```bash
cd C:/Users/micha/PyCharmMiscProject/tests && python game_loop_harness.py
```

This will make ~15 * N LLM calls (each case has 1-N turns, each turn makes 2-3 LLM calls). Estimated 40-50 total LLM calls.

- [ ] **Step 2: Verify output structure**

```bash
cd C:/Users/micha/PyCharmMiscProject && ls data/debug/test_harness/$(ls -t data/debug/test_harness/ | head -1)/
```

Should show: `_game_init.log`, `_prompt_log.txt`, `case_01_观察四周/`, ..., `case_15_结局路径/`

- [ ] **Step 3: Spot-check one case**

```bash
cd C:/Users/micha/PyCharmMiscProject && ls data/debug/test_harness/$(ls -t data/debug/test_harness/ | head -1)/case_01_观察四周/turn_01/
```

Should show: `01_parse_prompt.txt`, `01_parse_response.json`, `02_judge.json`, `03_enrich_prompt.txt`, `03_enrich_response.json`, `04_narrator_prompt.txt`, `04_narrative.txt`
