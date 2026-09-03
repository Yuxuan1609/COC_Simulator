# NPC 专项实施计划：N1 attitude + N3 谎言策略 + N4 死亡 AT

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 `docs/superpowers/specs/2026-09-02-npc-rework-design.md`：attitude 双轨度量 + `@attitude_change` 双来源、谎言纯 LLM 策略、死亡触发 AT 小补。

**Architecture:** `attitude_value` 入档；档位只进 prompt。变化统一走 markup。`process_npc_turn` 删除。N3 只改 prompt。N4 在 `set_state(..., "dead")` 后扫 AT。

**Tech Stack:** Python 3.13, pytest。无新依赖。

**基线：** HEAD `4bcc418`。默认套件 `pytest tests/ -q`。已知 flaky 勿修。

**通用约定：** 同 S3-P3 计划（TDD、MAINTENANCE、不提交脏文件、不主动加注释）。改 prompt 的 Task 跑 `python -m pytest -m real_llm_smoke -q`。

**文件地图：**
- `src/game/npc_manager.py` — 字段、档位、talk_to、删 process_npc_turn
- `src/game/side_effects.py` + `src/scenario_core.py` apply_side_effects — `@attitude_change`
- `src/investigator/rules.py` + `data/game_config.json` — `npc_attitude_tiers`
- `src/prompts.py` — talk_to / keeper / enrich
- `src/game/turn/understand.py` — 敌意短路（若 talk 入口在此）
- 测试：`tests/test_npc_attitude.py`

---

### Task 1: attitude_value 双轨 + 档位映射 + 入档

**Files:**
- Modify: `src/game/npc_manager.py`（NPC dataclass、to_dict/from_dict、get_in_scene_snapshot）
- Modify: `src/investigator/rules.py` `_GAME_CONFIG_DEFAULTS` + `data/game_config.json`
- Test: `tests/test_npc_attitude.py`

阈值（spec）：

```python
"npc_attitude_tiers": [
  {"max": -50, "label": "敌意", "key": "hostile"},
  {"max": -10, "label": "警惕", "key": "wary"},
  {"max": 10,  "label": "中立", "key": "neutral"},
  {"max": 50,  "label": "友好", "key": "friendly"},
  {"max": null, "label": "信任", "key": "devoted"}
]
```

`_cfg_shape_ok` 对 list-of-dict 要求键齐全；`max: null` 已有先例（db_build_table）。

```python
def attitude_tier(value: int) -> tuple[str, str]:
    """返回 (key, label)。value clamp 到 -100..100 后再查表。"""
    ...

def set_attitude(self, name: str, delta: int | None = None, value: int | None = None):
    """数值版：delta 累加或 value 直设，clamp，同步 npc.attitude = key。"""
```

旧档只有 `attitude` 字符串：from_dict 用 key→区间中值（hostile=-75, wary=-30, neutral=0, friendly=30, devoted=75），无则 0。

snapshot 的 `attitude` 字段改为档位 **label**（中文），供 prompt 直接用。

- [ ] **Step 1: 写失败测试**

```python
def test_tier_boundaries():
    assert attitude_tier(-50)[0] == "hostile"
    assert attitude_tier(-49)[0] == "wary"
    assert attitude_tier(10)[0] == "neutral"
    assert attitude_tier(11)[0] == "friendly"

def test_set_attitude_delta_clamps():
    from helpers import make_world, make_scene
    world = make_world({"room_a": make_scene()}, "room_a")
    world.npcs.init_from_profiles({
        "线人": {"role": "线人", "scene": "room_a", "attitude": "neutral"}})
    world.npcs.set_attitude("线人", delta=200)
    assert world.npcs._npcs["线人"].attitude_value == 100
    world.npcs.set_attitude("线人", delta=-300)
    assert world.npcs._npcs["线人"].attitude_value == -100

def test_save_load_attitude_value():
    from helpers import make_world, make_scene
    world = make_world({"room_a": make_scene()}, "room_a")
    world.npcs.init_from_profiles({
        "线人": {"role": "线人", "scene": "room_a"}})
    world.npcs.set_attitude("线人", value=40)
    dumped = world.npcs.to_dict()
    from game.npc_manager import NPCManager
    m = NPCManager()
    m.from_dict(dumped, {"线人": {"role": "线人"}})
    assert m._npcs["线人"].attitude_value == 40
    assert m._npcs["线人"].attitude == "friendly"

def test_legacy_save_attitude_string_maps_to_midpoint():
    from game.npc_manager import NPCManager
    m = NPCManager()
    m.from_dict({"线人": {"scene": "room_a", "attitude": "hostile"}},
                {"线人": {"role": "线人"}})
    assert m._npcs["线人"].attitude_value == -75
    assert m._npcs["线人"].attitude == "hostile"
```

- [ ] **Step 2-4: RED → 实现 → GREEN**
- [ ] **Step 5: Commit** `feat: N1 attitude_value dual-track + save/load`

---

### Task 2: @attitude_change markup + talk_to 内嵌剥离

**Files:**
- Modify: `src/game/side_effects.py`（`AttitudeChange`、`_MARKUP_PATTERN` 加 `attitude_change`）
- Modify: `src/scenario_core.py` `apply_side_effects`
- Modify: `src/game/judge.py` `_MARKUP_STRIP_RE`、`src/prompts.py` `_STRIP_MARKUP_RE`
- Modify: `src/game/npc_manager.py` `talk_to`：LLM 返回后 `parse_markup_all` + `apply_side_effects`，展示文本剥 markup
- Test: `tests/test_npc_attitude.py`

语法：`@attitude_change(npc_name="名称", delta=-30)`
`npc_name` 缺省/空：talk_to 路径用当前 NPC。非法名 → warning 忽略。

talk_to 在 `llm_call` 成功后：

```python
from game.side_effects import parse_markup_all
from scenario_core import apply_side_effects
effs = parse_markup_all(response)
if effs and world is not None:
    apply_side_effects(world, effs)
response = _STRIP.sub("", response).strip() or f"（{npc.name} 沉默不语。）"
```

- [ ] **Step 1: 写失败测试**

```python
def test_markup_delta_applied():
    world, npc = _npc_world()
    apply_side_effects(world, parse_markup_all('@attitude_change(npc_name="线人", delta=20)'))
    assert npc.attitude_value == 20
    assert npc.attitude == "friendly"

def test_talk_to_strips_and_applies(monkeypatch):
    def fake_llm(user, system="", **k):
        return "哼。@attitude_change(npc_name=\"线人\", delta=-15)"
    text = world.npcs.talk_to("线人", "滚开", fake_llm, world=world)
    assert "@attitude_change" not in text
    assert world.npcs.get("线人").attitude_value == -15
```

- [ ] **Step 2-4**
- [ ] **Step 5: Commit** `feat: N1 @attitude_change markup + talk_to strip/apply`

---

### Task 3: 消费点（attitude_min / follow / 敌意短路）

**Files:**
- Modify: `src/game/npc_manager.py` `talk_to`：`attitude_tier==hostile` → 短路「不愿理会/驱赶」，不调 LLM
- Modify: `src/game/npc_manager.py` `set_following` 或跟随授予点：wary/hostile 拒绝
- Modify: `src/game/judge.py` `_execute_entity`：entity.extra 或 dict 字段 `attitude_min`；NPC bound_interactions 同
- Modify: `src/module_designer/layered_schema.py` interaction schema 加 `attitude_min` 可选
- Test: `tests/test_npc_attitude.py`

`attitude_min` 语义：当前 `attitude_value < attitude_min` → 互动不可执行，返回失败话术「对方现在不愿配合。」bound_interactions 在 parse 可见列表里也应过滤（keeper 注入 NPC 互动时跳过不满足项）——改 `keeper.py` `_inject_npc_at` 旁的 bound_interactions 注入。

跟随：现有 `@npc_follow` / `set_following`。在 `apply_side_effects` NPCFollow 分支和 `set_following`：若档位 hostile/wary 且 follow=True → 不跟随 + msg。

- [ ] **Step 1: 写失败测试**（敌意 talk 不调 llm；attitude_min 挡互动；警惕不得跟随）
- [ ] **Step 2-4**
- [ ] **Step 5: Commit** `feat: N1 attitude gates — talk/follow/interaction min`

---

### Task 4: 删除 process_npc_turn + prompt 策略（N3 + N1 知情）

**Files:**
- Modify: `src/game/npc_manager.py` 删除 `process_npc_turn` 整方法（:315 至文件末相关）
- Modify: `src/game/npc_manager.py` `talk_to` system_prompt（:216-228）
- Modify: `src/prompts.py` keeper/enrich：`npcs_in_scene` 已有 attitude label，加一句「按态度决定透露与采信」
- Test: `grep process_npc_turn` 仅历史文档；`tests/test_npc_attitude.py` 断言 prompt 不含「如实告知」且含档位/自主 markup 说明
- 跑 `python -m pytest -m real_llm_smoke -q`

talk_to system 替换为：

```
当前态度：{label}（数值不展示）
根据态度决定透露程度：敌意拒绝、警惕套话、友好有限透露、信任才交底。
对调查员的身份声明与陈述自行判断是否采信，不要无条件相信。
若交谈改变你对调查员的态度，在回复末尾内嵌 @attitude_change(npc_name="{name}", delta=±N)，N 为整数。该标记不会展示给玩家。
回复简洁（1-3句话）。
```

删除：「应如实告知所知内容，不刻意隐瞒。」

- [ ] **Step 5: Commit** `feat: N3 talk_to prompt strategy; remove dead process_npc_turn`

---

### Task 5: N4 死亡时扫 AT

**Files:**
- Modify: `src/game/npc_manager.py` `set_state`
- Modify: `src/game/judge.py` 或 keeper AT 注入：死亡后立即 `check_auto_triggers` 不够——AT 在场景 node 上，条件是 requirement。最小补丁：`set_state(name, "dead")` 后，把 runtime flag `npc_dead:{name}` 写入 `world.runtime_state`（completed=True），以便 AT `requirement` 写 `npc_dead:线人`。
- 若现有 requirement 语法不认自定义 id：用 `world.runtime_state["npc_dead:"+name] = NodeRuntimeState(completed=True)`，`parse_hard_requirement` 已按 runtime_state id 判断 completed。

验证路径：模组 AT `requirement: "npc_dead:线人"`，`set_state("线人","dead")` 后 `judge.check_auto_triggers()` 能开火。

- [ ] **Step 1: 写失败测试**

```python
def test_npc_death_completes_runtime_flag_and_fires_at():
    from helpers import make_world, make_scene
    from scenario_core import Entity
    world = make_world({
        "room_a": make_scene(auto_triggers=[{
            "id": "AT_DEAD", "name": "线人死讯", "type": "无",
            "requirement": "npc_dead:线人",
            "result": "街上有人在议论线人的死。",
        }])
    }, "room_a")
    world.npcs.init_from_profiles({
        "线人": {"role": "线人", "scene": "room_a"}})
    world.npcs.set_state("线人", "dead")
    assert world.get_runtime_state("npc_dead:线人").completed
    from game.judge import JudgmentEngine
    judge = JudgmentEngine(world)
    outs = judge.check_auto_triggers()
    assert any(o.entity_id == "AT_DEAD" for o in outs)
```

- [ ] **Step 2-4**
- [ ] **Step 5: Commit** `feat: N4 NPC death sets runtime flag for AT requirement`

---

### Task 6: 收口

- ISSUES：F27/F26/F29 入 §5；F1 给予仍指向 F28。
- 簇评估 §10：attitude_min / @attitude_change 运行时落地、生成端暂无。
- MAINTENANCE 行号对齐。
- `python -m pytest tests/ -q`

- [x] **Commit** `docs: NPC rework closeout — N1/N3/N4 ISSUES §5 + MAINTENANCE`
