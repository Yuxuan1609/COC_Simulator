# U2 WorldChronicle 世界状态摘要层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 世界侧滚动编年史（facts/events/patches），本期唯一消费者 Author——让 Author patch 时看得到"已经发生了什么"。

**Architecture:** `WorldChronicle` 挂 `ScenarioWorld`（与 memory 平级）；game_loop 在 `keeper.process_turn` 返回后（game_loop.py:350 之后）调用 `record_turn`；facts 渲染时从 world 实时采集（零存储）；events 窗口 15；patches append-only。

**Tech Stack:** Python dataclass + deque + pytest。

**Spec:** `docs/superpowers/specs/2026-08-14-world-chronicle-design.md`

**关键边界：**
- keeper parse/enrich/narrator **不接** Chronicle；LLM 蒸馏只留接口（spec §5），本期不接线
- 玩家原话进 events（截断 60 字）；已完成实体结果文本截断 100 字；玩家状态裸数值
- 测试侧 `_collect_mech_line` 本期不动（后续顺手切源）
- 已确认字段：`ActionOutcome(intent/success/message/entity_id/entity_type/skill_tier)`（messages.py:39）、`TurnResult(status/brief/text/pending_interaction/combat_init/ending/npc_events)`（:265）、`GameClock(game_time/day/hour/time_of_day)`（clock.py:5）、NPCManager（get_following/get_in_scene/all_names/set_state）、钩子点 game_loop.py:350
- TDD；commit 英文 prefix + 中文描述；改代码后同步 MAINTENANCE.md

---

### Task 1: WorldChronicle 类 + 单测

**Files:**
- Modify: `src/scenario_core.py`（文件尾部新增类）
- Test: `tests/test_chronicle.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_chronicle.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def _make_world():
    from scenario_core import DirectedGraph, ScenarioWorld
    scenes = {"room_a": {"interactions": [], "auto_triggers": [], "from_here": [],
                         "to_here": [], "encounters": [], "scene_weapons": [],
                         "extra": {}, "description": ""}}
    return ScenarioWorld(DirectedGraph(scenes=scenes, events=[]), start_node="room_a")


def _make_result(entity_id="IT_SEARCH", tier="regular", msg="你找到了一把钥匙。"):
    from game.messages import (TurnResult, TurnStatus, NarratorBrief,
                               ActionOutcome, ActionIntent, SceneSnapshot)
    o = ActionOutcome(intent=ActionIntent(action="interaction"), success=True,
                      message=msg, entity_id=entity_id,
                      entity_type="interaction", skill_tier=tier)
    brief = NarratorBrief(action_outcomes=[o], ambient_changes=[],
                          scene_snapshot=None, suggested_emphasis="")
    return TurnResult(status=TurnStatus.COMPLETED, brief=brief)


def test_record_turn_appends_event_with_raw_input():
    from scenario_core import WorldChronicle
    w = _make_world()
    c = WorldChronicle()
    c.record_turn(1, "仔细检查地板缝", _make_result(), w)
    assert len(c.events) == 1
    e = c.events[0]
    assert e["turn"] == 1 and "仔细检查地板缝" in e["input"]
    assert e["entities"] == {"IT_SEARCH": "regular"}


def test_entity_results_truncated_100():
    from scenario_core import WorldChronicle
    w = _make_world()
    c = WorldChronicle()
    c.record_turn(1, "搜索", _make_result(msg="长" * 200), w)
    assert len(c.entity_results["IT_SEARCH"]) <= 100


def test_events_window_15():
    from scenario_core import WorldChronicle
    w = _make_world()
    c = WorldChronicle()
    for i in range(20):
        c.record_turn(i + 1, f"动作{i}", _make_result(), w)
    assert len(c.events) == 15
    assert c.events[0]["turn"] == 6, "最旧的 5 条必须出窗"


def test_record_patch():
    from scenario_core import WorldChronicle
    c = WorldChronicle()
    c.record_patch(turn=3, level="patch", entity_ids=["SI1", "SI2"],
                   new_scenes=[], justification="补" * 150)
    assert len(c.patches) == 1
    assert c.patches[0]["entity_ids"] == ["SI1", "SI2"]
    assert len(c.patches[0]["justification"]) <= 100


def test_serialization_roundtrip():
    from scenario_core import WorldChronicle
    w = _make_world()
    c = WorldChronicle()
    c.record_turn(1, "搜索", _make_result(), w)
    c.record_patch(turn=1, level="patch", entity_ids=["SI1"],
                   new_scenes=[], justification="test")
    back = WorldChronicle.from_dict(c.to_dict())
    assert back.events == c.events
    assert back.entity_results == c.entity_results
    assert back.patches == c.patches
    assert back.events_summary == ""


def test_render_for_author_contains_sections():
    from scenario_core import WorldChronicle
    from investigator import Investigator
    w = _make_world()
    w.set_player(Investigator(name="t"))
    c = WorldChronicle()
    c.record_turn(1, "搜索房间", _make_result(), w)
    text = c.render_for_author(w)
    assert "【世界真值】" in text and "【编年史】" in text
    assert "IT_SEARCH" in text and "搜索房间" in text
```

注：`SceneSnapshot` 若构造必填字段过多，`NarratorBrief` 的 `scene_snapshot` 传 `None` 即可（dataclass 无校验）。

- [ ] **Step 2: 跑测试确认红**

Run: `python -X utf8 -m pytest tests/test_chronicle.py -x -q`
Expected: FAIL `ImportError: cannot import name 'WorldChronicle'`

- [ ] **Step 3: scenario_core.py 实现**

文件尾部追加：

```python
# ═══════════════════════════════════════════════════════════════
#  U2 WorldChronicle —— 世界状态摘要层（LLM 饲料，本期消费者=Author）
# ═══════════════════════════════════════════════════════════════

from collections import deque as _deque


class WorldChronicle:
    """滚动编年史：events(窗口15) + entity_results(截断100) + patches(append-only)。
    facts 不存储——render 时从 world 实时采集。
    events_summary 为 LLM 蒸馏预留字段（本期不接线，见 spec §5）。"""

    EVENTS_WINDOW = 15
    INPUT_MAX = 60
    TEXT_MAX = 100

    def __init__(self):
        self.events: _deque = _deque(maxlen=self.EVENTS_WINDOW)
        self.entity_results: dict[str, str] = {}
        self.patches: list[dict] = []
        self.events_summary: str = ""

    # ── 生产者 ──

    def record_turn(self, turn_number: int, raw_input: str, result, world) -> None:
        """每回合末由 game_loop 调用。result 为 keeper TurnResult。"""
        entry = {"turn": turn_number, "input": (raw_input or "")[:self.INPUT_MAX]}
        brief = getattr(result, "brief", None)
        outcomes = brief.action_outcomes if brief else []
        if outcomes:
            entry["intent"] = outcomes[0].intent.action
            ents = {o.entity_id: (o.skill_tier or ("ok" if o.success else "fail"))
                    for o in outcomes if o.entity_id}
            if ents:
                entry["entities"] = ents
            for o in outcomes:
                if o.entity_id and o.entity_type == "interaction" and o.message:
                    self.entity_results[o.entity_id] = o.message[:self.TEXT_MAX]
        ats = [o.entity_id for o in outcomes if o.entity_type == "auto_trigger"]
        if ats:
            entry["at"] = ats
        pend = getattr(result, "pending_interaction", None)
        if pend:
            entry["pending"] = pend.kind
        ci = getattr(result, "combat_init", None)
        if ci and ci.enemies:
            entry["combat"] = ["start:" + ",".join(
                getattr(e, "enemy_ref", "?") for e in ci.enemies)]
        ending = getattr(result, "ending", None)
        if ending:
            entry["ending"] = getattr(ending, "name", "") or str(ending)
        npc_events = getattr(result, "npc_events", None)
        if npc_events:
            entry["npc"] = [n[:40] for n in npc_events]
        self.events.append(entry)

    def record_patch(self, turn: int, level: str, entity_ids: list[str],
                     new_scenes: list[str], justification: str) -> None:
        self.patches.append({
            "turn": turn, "level": level, "entity_ids": list(entity_ids),
            "new_scenes": list(new_scenes),
            "justification": (justification or "")[:self.TEXT_MAX],
        })

    # ── LLM 蒸馏预留（本期不接线，spec §5）──

    def compress_events(self, llm_call) -> None:
        """将较旧事件蒸馏进 events_summary。接口预留，本期不实现。"""
        raise NotImplementedError("LLM 蒸馏为预留接口，本期不接线")

    # ── 消费者渲染 ──

    def render_for_author(self, world) -> str:
        parts = ["【世界真值】"]
        parts.append(f"  位置: {world.current_location}"
                     f"（已到访: {'→'.join(world.memory.visited) or '无'}）")
        parts.append(f"  时间: 第{world.clock.day + 1}天 {world.clock.time_of_day}"
                     f"（累计{world.clock.game_time}分钟）")
        p = world.player
        if p:
            weapons = "、".join(w.name for w in p.weapons) or "无"
            parts.append(f"  玩家: HP {p.derived.HP}/{p.derived.HP_MAX} "
                         f"SAN {p.derived.SAN}/{p.derived.SAN_MAX} "
                         f"MP {p.derived.MP} LUCK {p.stats.LUCK} | 武器: {weapons}")
        if world.enemies:
            for inst in world.enemies._instances.values():
                parts.append(f"  敌人: {inst.enemy_ref}@{inst.scene} "
                             f"状态={inst.status} flags={inst.flags}")
        if world.npcs:
            following = {n.name for n in world.npcs.get_following()}
            for name in world.npcs.all_names():
                npc = world.npcs.get(name)
                follow_mark = " [跟随中]" if name in following else ""
                parts.append(f"  NPC: {name}@{npc.scene} "
                             f"状态={npc.state}{follow_mark}")
        done = {eid: s for eid, s in world.runtime_state.items() if s.completed}
        if done:
            parts.append("  已完成实体:")
            for eid, s in done.items():
                result_text = self.entity_results.get(eid, "")
                line = f"    {eid}: {s.result_tier or 'ok'}"
                if result_text:
                    line += f" | {result_text}"
                parts.append(line)
        if world.scene_weapons:
            for scene, weps in world.scene_weapons.items():
                if weps:
                    parts.append(f"  场景武器: {scene} 剩余 "
                                 + "、".join(w.weapon_ref for w in weps))
        if self.patches:
            parts.append("【已注入内容】")
            for pt in self.patches:
                ids = "、".join(pt["entity_ids"]) or "（无实体）"
                scenes = "、".join(pt["new_scenes"])
                line = f"  T{pt['turn']} [{pt['level']}] {ids}"
                if scenes:
                    line += f" 新场景:{scenes}"
                parts.append(line)
        if self.events_summary:
            parts.append("【远期摘要】")
            parts.append(f"  {self.events_summary}")
        parts.append("【编年史】")
        for e in self.events:
            parts.append("  " + self._render_event(e))
        return "\n".join(parts)

    @staticmethod
    def _render_event(e: dict) -> str:
        segs = [f"T{e['turn']}", f'in="{e["input"]}"']
        for key, label in (("intent", "intent"), ("pending", "pending"),
                           ("move", "move"), ("standoff", "standoff"),
                           ("ending", "ending")):
            if e.get(key):
                segs.append(f"{label}={e[key]}")
        if e.get("entities"):
            segs.append("entities=" + ",".join(
                f"{k}:{v}" for k, v in e["entities"].items()))
        for key, label in (("at", "at"), ("spawn", "spawn"), ("boss", "boss"),
                           ("combat", "combat"), ("npc", "npc")):
            if e.get(key):
                segs.append(f"{label}={','.join(str(x) for x in e[key])}")
        return " | ".join(segs)

    # ── 序列化 ──

    def to_dict(self) -> dict:
        return {
            "events": list(self.events),
            "entity_results": dict(self.entity_results),
            "patches": list(self.patches),
            "events_summary": self.events_summary,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorldChronicle":
        c = cls()
        c.events = _deque(data.get("events", []), maxlen=cls.EVENTS_WINDOW)
        c.entity_results = dict(data.get("entity_results", {}))
        c.patches = list(data.get("patches", []))
        c.events_summary = data.get("events_summary", "")
        return c
```

- [ ] **Step 4: 跑测试确认绿**

Run: `python -X utf8 -m pytest tests/test_chronicle.py -q`
Expected: 6 passed（若 NPC/Boss 字段名不符，按 `npc_manager.py`/`enemy_manager.py` 实际属性微调 render）

- [ ] **Step 5: Commit**

```bash
git add src/scenario_core.py tests/test_chronicle.py
git commit -m "feat: U2 WorldChronicle——events 窗口15 + entity_results 截断 + patches 清单 + Author 渲染器"
```

---

### Task 2: ScenarioWorld 挂载 + 序列化

**Files:**
- Modify: `src/scenario_core.py:684` 附近（`self.memory = MemoryManager()` 后）
- Test: `tests/test_chronicle.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_world_has_chronicle():
    w = _make_world()
    from scenario_core import WorldChronicle
    assert isinstance(w.chronicle, WorldChronicle)


def test_world_chronicle_in_save():
    """世界序列化必须带 chronicle（若 ScenarioWorld 有 to_dict 通路）。"""
    w = _make_world()
    w.chronicle.record_patch(turn=1, level="patch", entity_ids=["SI1"],
                             new_scenes=[], justification="x")
    assert hasattr(w, "chronicle")
    # 存档通路探查：若 ScenarioWorld 无 to_dict，本测试只验证挂载点可序列化
    d = w.chronicle.to_dict()
    assert d["patches"][0]["entity_ids"] == ["SI1"]
```

- [ ] **Step 2: 跑测试确认红**

Run: `python -X utf8 -m pytest tests/test_chronicle.py -q -k "world_has or world_chronicle"`
Expected: FAIL `AttributeError: 'ScenarioWorld' object has no attribute 'chronicle'`

- [ ] **Step 3: 挂载**

`src/scenario_core.py:684`（`self.memory = MemoryManager()` 下一行）插：

```python
        self.chronicle = WorldChronicle()
```

再探查存档通路：`grep -n "to_dict\|save_state\|from_dict" src/scenario_core.py | head`——若 ScenarioWorld 有 to_dict/from_dict 或独立 save 模块（`grep -rn "def save_state\|def load_state" src/`），在其中加 `chronicle` 键的存取（`"chronicle": self.chronicle.to_dict()` / `WorldChronicle.from_dict(data.get("chronicle", {}))`）。注意：存读档有 3 个已知 🔴 bug 未修（队列最后），本步只加键、不修旧账。

- [ ] **Step 4: 跑测试确认绿 + 全量回归**

Run: `python -X utf8 -m pytest tests/test_chronicle.py -q` → 8 passed
Run: `python -X utf8 -m pytest tests/ -q --ignore=tests/e2e/test_scenarios.py --ignore=tests/e2e/test_escalation_real.py` → 86 passed（无回归）

- [ ] **Step 5: Commit**

```bash
git add src/scenario_core.py tests/test_chronicle.py
git commit -m "feat: U2 ScenarioWorld 挂载 chronicle + 序列化入档"
```

---

### Task 3: game_loop 接线（record_turn）

**Files:**
- Modify: `src/game_loop.py:350` 附近
- Test: `tests/e2e/test_deterministic.py`（追加 TestChronicleWiring）

- [ ] **Step 1: 写失败测试**

```python
class TestChronicleWiring:  # U2: game_loop 每回合写编年史
    def test_turn_recorded_with_move(self, monkeypatch):
        """跑一回合 move → chronicle.events 含该回合，facts 位置已更新。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world = make_world({
            "room_a": make_scene(exits=[{"target": "room_b", "method": "步行",
                                         "requirement": ""}]),
            "room_b": make_scene(),
        }, "room_a")
        _player(world)
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch)
        game = make_game(keeper)

        loc_before = world.current_location
        run_turn(game, "前往room_b", action_type="move", action_target="room_b")
        assert len(world.chronicle.events) == 1, "回合必须入编年史"
        e = world.chronicle.events[0]
        assert e["turn"] == 1 and "前往room_b" in e["input"]
        assert world.chronicle.events[0].get("move") == "room_a→room_b" or \
            world.current_location != loc_before, "移动必须可观测"
```

（move 字段的写入依赖接线实现——若选择在 record_turn 内对比位置，则断言 `e["move"] == "room_a→room_b"`。）

- [ ] **Step 2: 跑测试确认红**

Run: `python -X utf8 -m pytest tests/e2e/test_deterministic.py::TestChronicleWiring -x -q`
Expected: FAIL（events 为空）

- [ ] **Step 3: game_loop.py 接线**

`src/game_loop.py:350` 后：

```python
        result = keeper.process_turn(turn_input, author=author)
        # U2：编年史记录（SUSPENDED 早退路径在其 return 前也需记录——见下）
        _loc_before = ...  # 需在 process_turn 前捕获
```

具体做法——在 `keeper.process_turn` 调用**前**捕获 `loc_before = world.current_location`，调用**后**：

```python
        if result.status != TurnStatus.FROZEN:
            world.chronicle.record_turn(keeper.turn_number, user_input, result, world)
            if world.current_location != loc_before and world.chronicle.events:
                world.chronicle.events[-1]["move"] = f"{loc_before}→{world.current_location}"
```

注意 SUSPENDED 早退分支（:352-361）在 process_turn 之后同样经过此处则自动覆盖；若 SUSPENDED 在该行之前 return，则把 record 调用放在 process_turn 紧邻的下一行（任何 return 之前）。FROZEN 不计回合（输入锁定）。

- [ ] **Step 4: 跑测试确认绿 + 全量回归**

Run: `python -X utf8 -m pytest tests/e2e/test_deterministic.py -q` → 全绿
Run: 全量默认套件 → 无回归

- [ ] **Step 5: Commit**

```bash
git add src/game_loop.py tests/e2e/test_deterministic.py
git commit -m "feat: U2 game_loop 接线——每回合写编年史（含移动轨迹）"
```

---

### Task 4: patches 记录 + Author 上下文注入

**Files:**
- Modify: `src/game/agents/keeper.py:1448`（`_build_scene_context_for_author`）、`_integrate_patch`（:1518 附近）与 `_integrate_supplement`（:1464）返回前
- Modify: `src/prompts.py:741`（`build_author_prompt`）
- Test: `tests/test_chronicle.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_author_prompt_contains_chronicle():
    """Author prompt 必须含编年史块（facts + events + patches）。"""
    from prompts import build_author_prompt
    from scenario_core import WorldChronicle

    w = _make_world()
    c = WorldChronicle()
    c.record_turn(1, "撬开地板", _make_result(), w)
    c.record_patch(turn=1, level="patch", entity_ids=["SI1"],
                   new_scenes=[], justification="补缺")
    rendered = c.render_for_author(w)

    class _Req:
        intent = "看看地板下有什么"
        reasoning = "模组未覆盖"
        other_texts = ["撬开地板"]
        scene_context = {"location": "room_a", "description": "",
                         "available_scenes": ["room_a"], "npc_states": {},
                         "runtime_summary": {}, "wr0_enabled": False,
                         "chronicle": rendered}
    prompt = build_author_prompt(_Req(), {"world_rules": [], "driving_force": "找出真相"})
    assert "【世界编年史】" in prompt
    assert "IT_SEARCH" in prompt and "SI1" in prompt
```

- [ ] **Step 2: 跑测试确认红**

Run: `python -X utf8 -m pytest tests/test_chronicle.py -q -k "author_prompt"`
Expected: FAIL（无【世界编年史】块）

- [ ] **Step 3: 实现**

3a. `keeper.py:_build_scene_context_for_author`（:1448）返回 dict 加键：

```python
            "chronicle": self.world.chronicle.render_for_author(self.world),
```

3b. `prompts.py:build_author_prompt`：`scene_ctx` 组装后（约 :814 `scene_ctx = "\n".join(scene_parts)` 之后）加：

```python
    chronicle_text = sc.get("chronicle", "")
    chronicle_ctx = f"【世界编年史】\n{chronicle_text}" if chronicle_text else ""
```

并把它插进最终 prompt 的 `{scene_ctx}` 之后、`{intent_ctx}` 之前：

```python
    prompt = f"""{l3_ctx}

{scene_ctx}

{chronicle_ctx}

{intent_ctx}
...
```

3c. patches 记录——`keeper._integrate_patch` 与 `_integrate_supplement` 成功集成后（return 前）：

```python
        self.world.chronicle.record_patch(
            turn=self.turn_number,
            level="structural" if isinstance(...) else "patch",  # 按所在函数写死
            entity_ids=[e.get("id", "") for e in patch.entities],  # supplement 路径用新实体 id 列表
            new_scenes=[],  # supplement 路径填新场景名列表
            justification=patch.justification,
        )
```

（两个函数各自写死 level；entity_ids/new_scenes 按各自参数取。Author 打回 reject 不记录。）

- [ ] **Step 4: 跑测试确认绿 + 全量回归**

Run: `python -X utf8 -m pytest tests/test_chronicle.py -q` → 9 passed
Run: 全量默认套件 → 无回归

- [ ] **Step 5: Commit**

```bash
git add src/game/agents/keeper.py src/prompts.py tests/test_chronicle.py
git commit -m "feat: U2 Author 接入——prompt 注入编年史块 + patch/supplement 注入记录"
```

---

### Task 5: 场景层验证 + 文档同步

**Files:**
- Modify: `MAINTENANCE.md`（scenario_core 加 WorldChronicle 条目、game_loop/keeper/prompts 行号更新）
- Modify: `UPDATES.md`（U2 完成记录；readme.md U2 行标 ✅）
- Test: 场景层 + 实连层（escalation 路径直接吃到 Author 上下文变化）

- [ ] **Step 1: 场景层 S-D 实跑**

Run: `python -X utf8 tests/e2e/run_scenario.py tests/e2e/scenarios/full_clear.yaml`
Expected: VERDICT PASS（Chronicle 对玩家侧零影响，不应有回归）

- [ ] **Step 2: 实连层 escalation（Author 真实面）**

Run: `python -X utf8 -m pytest tests/e2e/test_escalation_real.py -q -m real_llm`
Expected: 5/5（Author prompt 变了，case C/E 有真实波动——若失败看日志确认是波动还是编年史格式问题）

- [ ] **Step 3: 文档同步 + Commit**

MAINTENANCE.md 加 WorldChronicle 条目（record_turn/record_patch/render_for_author/to_dict/from_dict + 行号）；UPDATES.md 记完成；readme.md:356 U2 行标 ✅。

```bash
git add MAINTENANCE.md UPDATES.md readme.md
git commit -m "docs: U2 完成记录——场景层/escalation 实连验证"
```

---

## Self-Review 记录

- Spec 覆盖：§1 架构→Task 1/2/3；§2 facts→Task 1 render；§3 events（带原话 60 字截断）→Task 1/3；§4 patches→Task 4；§5 蒸馏接口→Task 1（compress_events 预留）；§6 序列化→Task 1/2；§7 Author 接入→Task 4；§8 文件表→Task 1-5；§9 不做项→计划未包含
- 类型一致性：`record_turn(turn_number, raw_input, result, world)` 在 Task 1 定义、Task 3 调用一致；`record_patch(turn, level, entity_ids, new_scenes, justification)` Task 1 定义、Task 4 调用一致；`render_for_author(world)` Task 1/4 一致
- 已知留白：测试侧 `_collect_mech_line` 切源（spec 标注后续）；combat=end 事件本期抓不到（战斗结算走 complete_combat_turn 回放路径）；boss engage/spawn 事件不经 all_outcomes（走 enrich_input/side_effects），本期 events 对这两类只有 entities/pending 间接投影——三者后续一起补
