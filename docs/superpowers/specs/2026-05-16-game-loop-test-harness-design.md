# Game Loop — Test Harness Design

**日期**: 2026-05-16
**状态**: 设计完成，待实施

---

## 1. Purpose

Convert the Jupyter notebook into a `.py` test harness that runs ~15 player-input scenarios through the full `parse → judge → enrich → narrate` pipeline with real LLM calls. All intermediate results logged to per-case directories for manual review. No assertions — purely observational debugging.

Additionally: switch all game loop LLM calls to `deepseek-v4-flash` model.

---

## 2. File

`tests/game_loop_harness.py` — single runner script. No pytest, no assertions.

## 3. Output Structure

```
data/debug/test_harness/<timestamp>/
├── _game_init.log              # Scene graph stats, agent init info
├── _prompt_log.txt             # All LLM prompt/response pairs (standard prompt log)
├── case_01_<name>/
│   ├── _case_summary.log       # What this case tests
│   └── turn_01/
│       ├── 01_parse_prompt.txt
│       ├── 01_parse_response.json
│       ├── 02_judge.json
│       ├── 03_enrich_prompt.txt
│       ├── 03_enrich_response.json
│       ├── 04_narrator_prompt.txt
│       └── 04_narrative.txt
├── case_02_<name>/
│   └── turn_01/ ...
├── ...
└── case_15_<name>/
```

### Per-turn files

| # | File | Content |
|---|------|---------|
| 1 | `01_parse_prompt.txt` | LLM prompt sent to Keeper Parse |
| 2 | `01_parse_response.json` | LLM response — `{actions: [{action, target, skill_checks, reasoning}]}` |
| 3 | `02_judge.json` | AT check results + interaction execution outcomes + side effects applied |
| 4 | `03_enrich_prompt.txt` | LLM prompt sent to Keeper Enrich |
| 5 | `03_enrich_response.json` | LLM response — `{triggered_ats, triggered_events, enriched_results, new_flags, emphasis_hint}` |
| 6 | `04_narrator_prompt.txt` | LLM prompt sent to Narrator |
| 7 | `04_narrative.txt` | Final output: brief result + immersive narrative |

---

## 4. 15 Test Cases

| # | Name | Input | Tests |
|---|------|-------|-------|
| 1 | 观察四周 | `"环顾四周，看看有没有什么异常"` | search → L1 context in narrative |
| 2 | 移动 | `"去7号车厢"` | move to adjacent scene |
| 3 | 交互无检定 | `"阅读门扉上的便签"` | interact with no skill check |
| 4 | 交互有检定 | `"仔细观察电车示意地图"` | interact + 侦查检定 |
| 5 | 移动被拒 | `"去驾驶室"` (no direct path) | move failure |
| 6 | 前置不满足 | `"打开上锁的门"` (需要钥匙标记) | unmet requirement |
| 7 | 多动作 | `"先检查随身物品然后去5号车厢"` | multi-intent parse |
| 8 | 无意义输入 | `"唱一首歌"` | other/unmapped → graceful response |
| 9 | Auto-trigger | `"靠近后门"` (触发嗅觉AT) | AT fires + ambient |
| 10 | 事件链 | 连续 I1+I2+I3 until event triggers | event trigger matching |
| 11 | 检定失败 | 使用侦查0的角色检查 | failed skill check |
| 12 | 偏离行为 | `"我想砸碎车窗跳出去"` | unmapped player action |
| 13 | 返回移动 | 从7号车厢返回6号车厢 | to_here path |
| 14 | 重复交互 | 对已完成交互再次执行 | already-completed behavior |
| 15 | 结局路径 | 触发坏结局事件 | ending marker detection |

---

## 5. Model Change

All `call_deepseek()` calls in `src/game/` switch to `model="deepseek-v4-flash"`:

| File | Method | Change |
|------|--------|--------|
| `agents/keeper.py` | `_parse()` | `model="deepseek-v4-flash"` |
| `agents/keeper.py` | `_enrich()` | `model="deepseek-v4-flash"` |
| `agents/keeper.py` | `_check_escalation()` | `model="deepseek-v4-flash"` |
| `agents/narrator.py` | `narrate()` | `model="deepseek-v4-flash"` |
| `agents/author.py` | `handle_escalation()` | `model="deepseek-v4-flash"` |

---

## 6. Script Structure

```python
# tests/game_loop_harness.py
# Single runner: init, run 15 cases, log everything

def setup(out_dir):
    """Init game once. Returns game dict."""

def log_turn(case_dir, turn_num, ...):
    """Write 7 files per turn."""

def run_case(game, case_name, turns):
    """Run one case with N turns, log all intermediates."""

def run_all():
    """Setup, run all 15 cases."""

if __name__ == "__main__":
    run_all()
```

Each case is a list of `(input_text, description)` tuples. `run_case` iterates through turns, calling the real `run_turn()` but with hooks to capture intermediates before/after each stage.
