# Keeper 回合管线阶段化（R1）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `Keeper.process_turn`（~850 行 god function）拆为 5 个有契约的阶段 + 薄编排器 TurnRunner，行为基本不变（仅 W6 一处有意变更），每波 `pytest tests/ -q` 全绿。

**Architecture:** 见 spec `docs/superpowers/specs/2026-08-28-keeper-turn-pipeline-design.md`。阶段函数 `phase_x(ctx, acc, tools)` 返回 `Early(TurnResult) | Restart | None`；`TurnFrozenError` 冒泡由编排器统一转 FROZEN。`tools` 就是 Keeper 实例本身（facade + toolbox），world 共享可变。

**Tech Stack:** pytest、现有 e2e 基建（`tests/e2e/helpers.py: make_world / stub_keeper_llm`）。

**约定:**
- 基线（commit `0f95a3b`）：`pytest tests/ -q` = **341 passed, 20 deselected**。已知 flaky：`test_unresolved_use_becomes_creative`、`test_combat_phase_trigger`（复跑即过，勿修）。
- 每波一个 commit；每波同步 MAINTENANCE.md changelog 一行。
- 不提交无关脏文件（autosave、supplements、imp.py、test.py、.claude/）。
- 行号引用基于 commit `0f95a3b` 的 `src/game/agents/keeper.py`；每波搬迁后行号漂移，**以锚点注释字符串定位为准**。
- W1–W5 纯搬运零行为变更；W6 唯一变更波。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `src/game/turn/__init__.py` | 空（或 re-export TurnRunner） |
| `src/game/turn/context.py` | `TurnContext` / `TurnAccumulator` / `Early`（W0）；`Restart`（W6） |
| `src/game/turn/runner.py` | `TurnRunner`（W0 委托壳 → W6 循环编排器） |
| `src/game/turn/understand.py` | `phase_a_understand`（W1） |
| `src/game/turn/adjudicate.py` | `phase_b_adjudicate`（W2；W6 吞入作者门） |
| `src/game/turn/encounter.py` | `phase_c_encounter` + `EncounterContribution` + 两个 provider（W3） |
| `src/game/turn/enrich.py` | `phase_d_enrich`（W4） |
| `src/game/turn/finalize.py` | `phase_e_finalize`（W5） |
| `src/game/agents/keeper.py` | facade + toolbox，1702 → ~700 行 |

**阶段函数签名（全程不变）：**

```python
def phase_a_understand(ctx, acc, tools) -> "Early | None"      # W6 起亦可 raise（freeze 冒泡）
def phase_b_adjudicate(ctx, acc, tools) -> None                # W6 起 -> "Restart | None"
def phase_c_encounter(ctx, acc, tools) -> None
def phase_d_enrich(ctx, acc, tools) -> None
def phase_e_finalize(ctx, acc, tools) -> None                  # 结果写 acc.result
```

`tools` = Keeper 实例。阶段内 LLM 调用经 `tools._parse / tools._enrich / tools._run_time_agent / tools.turn_monitor`。

## 局部变量 → acc 字段映射（搬迁对照表）

| 现局部变量 | acc 字段 | 备注 |
|---|---|---|
| `raw` | `acc.raw` | pre_parse 可改写 |
| `pre_result` | `acc.pre_result` | diagnostics 用 |
| `parse_result` | `acc.parse_result` | |
| `npc_interact_entries` | `acc.npc_interact_entries` | B 的 has_substantive 用 |
| `other_entries` | `acc.other_entries` | 作者门 AuthorRequest 用 |
| `other_creative` / `has_substantive` / `non_npc_entries` | 不进 acc | A 内部瞬态 |
| `detect_future` / `executor` | `acc.detect_future` / `acc.executor` | A 发射 / B 收割 |
| `all_outcomes` | `acc.all_outcomes` | |
| `enrich_input` | `acc.enrich_input` | |
| `combat_entry` | `acc.combat_entry` | diagnostics 用 |
| `enemy_ctx` / `combat_candidates` 等 | 不进 acc | C 内部瞬态 |
| `standoff_prompt` | `acc.standoff_prompt` | |
| `combat_init_result` | `acc.combat_init_result` | |
| `boss_combat_init` / `boss_engaged_id` | `acc.boss_accounting` | C 记入 / E 消费（freeze 安全，见 spec §4.1） |
| `enrichment` / `ta_result` / `emphasis` / `enriched_summary` | 同名字段 | |
| `ending_result` | `acc.ending_result` | |
| `brief` | `acc.brief` | |
| `skill_detail` / `tier` / `msg` / `trait_enh` | 不进 acc | B 的 search 分支瞬态 |

**留在 Keeper 上的会话/回合态**（阶段经 `tools.` 访问，不进 acc）：`_warnings`、`_npc_events`、`_pending_side_effects`、`_pending_move`、`_standoff_pending`、`_weapon_offer`、`_weapon_offer_msg`、`_last_outcomes`、`_last_player_input`、`_combat_result_pending`、`_recent_intents`、`turn_number`。

---

### Task W0: turn/ 包骨架 + 委托壳

**Files:**
- Create: `src/game/turn/__init__.py`
- Create: `src/game/turn/context.py`
- Create: `src/game/turn/runner.py`
- Modify: `src/game/agents/keeper.py`（process_turn 改名 + 委托）

- [ ] **Step 1: 建 context.py**

```python
"""回合管线契约：上下文、累积器、控制信号。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from ..messages import EnrichInput, TurnInput, TurnResult


@dataclass
class TurnContext:
    """输入侧（只读）。raw 可被 pre_parse 改写。"""
    turn_input: TurnInput
    author: Any = None
    depth: int = 0
    raw: str = ""


@dataclass
class TurnAccumulator:
    """产出侧累积（= 原 process_turn 局部变量显式分组）。"""
    pre_result: Any = None
    parse_result: list = field(default_factory=list)
    npc_interact_entries: list = field(default_factory=list)
    other_entries: list = field(default_factory=list)
    detect_future: Any = None
    executor: Any = None
    all_outcomes: list = field(default_factory=list)
    enrich_input: EnrichInput = field(default_factory=EnrichInput)
    combat_entry: Any = None
    standoff_prompt: dict | None = None
    combat_init_result: Any = None
    boss_accounting: tuple | None = None       # (boss_engaged_id, boss_enemy)，E 在 curate 后消费
    enrichment: dict | None = None
    ta_result: dict | None = None
    emphasis: str = ""
    enriched_summary: str = ""
    ending_result: dict | None = None
    brief: Any = None
    result: TurnResult | None = None


@dataclass
class Early:
    """阶段早退信号：携带完整 TurnResult，编排器直接返回。"""
    result: TurnResult
```

`src/game/turn/__init__.py` 内容：`"""Turn pipeline stages (R1)."""`

- [ ] **Step 2: 建 runner.py（委托壳）**

```python
"""TurnRunner：回合编排器。W0 为委托壳，W6 起为循环编排器。"""
from __future__ import annotations

from monitor.turn_monitor import TurnFrozenError


class TurnRunner:
    def __init__(self, keeper):
        self.keeper = keeper

    def execute(self, turn_input, author=None):
        try:
            return self.keeper._run_turn_pipeline(turn_input, author, 0)
        except TurnFrozenError as e:
            return self.keeper._build_frozen_response(e)
```

- [ ] **Step 3: keeper.py 改造**

`process_turn`（149 行起）整体改名为 `_run_turn_pipeline(self, turn_input, author=None, _depth=0)`，函数体**一字不动**。新增：

```python
    def process_turn(self, turn_input: TurnInput, author: Any = None, _depth: int = 0) -> TurnResult:
        """Facade：委托 TurnRunner。_depth>0 为内部递归路径（W6 前）。"""
        if _depth:
            return self._run_turn_pipeline(turn_input, author, _depth)
        if not hasattr(self, "_runner"):
            from ..turn.runner import TurnRunner
            self._runner = TurnRunner(self)
        return self._runner.execute(turn_input, author)
```

注意 `_run_turn_pipeline` 体内现有的两处递归 `return self.process_turn(turn_input, author, _depth + 1)`（原 851/860 行）保持不动——经 `_depth>0` 分支直达 `_run_turn_pipeline`，不经过 runner。

- [ ] **Step 4: 验证**

Run: `pytest tests/ -q`
Expected: `341 passed, 20 deselected`（flaky 复跑即过）

- [ ] **Step 5: MAINTENANCE.md changelog + Commit**

changelog 一行：`R1-W0 turn/ 包骨架；process_turn→_run_turn_pipeline 改名委托 TurnRunner(keeper.py:149)`。

```bash
git add src/game/turn/ src/game/agents/keeper.py MAINTENANCE.md
git commit -m "refactor: R1-W0 turn package skeleton, process_turn delegates to TurnRunner"
```

---

### Task W1: A 理解阶段（understand.py）

**Files:**
- Create: `src/game/turn/understand.py`
- Modify: `src/game/agents/keeper.py`

**搬迁范围（锚点）**：`_run_turn_pipeline` 体内，从 `raw = turn_input.raw_text`（原 151 行）到 intent 预发射块结束（原 330–338 行，`detect_future = executor.submit(...)`）。

- [ ] **Step 1: 写 phase_a_understand**

```python
"""A 理解：入口守卫 → LUCK → parse → NPC 对话 → use 归一 → intent 预发射。"""
from __future__ import annotations

from .context import Early


def phase_a_understand(ctx, acc, tools) -> Early | None:
    """返回 Early(早退) 或 None(继续)。产出写入 acc / tools 会话态。"""
```

搬入内容（顺序与现行一致，行号为原 keeper.py）：

1. 武器 offer 是/否（154–168）：早退改 `return Early(TurnResult(...))`；`offer_expired` 语义保留（非是/否→作废继续）
2. 直接拾取（170–175）：`return Early(...)`
3. 深度守卫（177–179）：`if ctx.depth >= MAX_ESCALATION_DEPTH: return Early(tools._process_deterministic_only(ctx.turn_input))`
4. 回合初始化（180–188）：`tools.turn_number += 1`、`tools._warnings.clear()` 等；`ctx.raw = turn_input.raw_text`（之后一律用 `acc`/`ctx.raw`）
5. `_inject_npc_at`（190–191）、LUCK（193–202）：`tools._inject_npc_at()` 等
6. parse 短路群（204–250）：use_hit / move / search / pre_parse / LLM parse；move 无效目标早退→`Early`；ambiguous→`Early(TurnResult(SUSPENDED...))`；parse 的 `try/except TurnFrozenError` **删除**，让它冒泡（runner 已兜底）
7. NPC 对话（252–302）：写 `tools._npc_events`、`acc.enrich_input`；纯对话 `return Early(...)`
8. use 归一（304–317）、intent 预发射（319–338）：写 `acc.parse_result` / `acc.npc_interact_entries` / `acc.other_entries` / `acc.detect_future` / `acc.executor`

瞬态变量（`non_npc_entries`、`other_creative`、`has_substantive`、`_FOLLOW_KEYWORDS`）保持函数局部。

- [ ] **Step 2: _run_turn_pipeline 改为调 phase_a**

```python
    def _run_turn_pipeline(self, turn_input, author=None, _depth=0):
        from ..turn.context import TurnContext, TurnAccumulator, Early
        from ..turn.understand import phase_a_understand
        ctx = TurnContext(turn_input=turn_input, author=author, depth=_depth,
                          raw=turn_input.raw_text)
        acc = TurnAccumulator()
        r = phase_a_understand(ctx, acc, self)
        if isinstance(r, Early):
            return r.result
        # ── 以下为尚未搬迁的 B–E 段（原 340 行起），raw/parse_result 等局部变量
        #    改为从 acc 读取：raw→acc 由 ctx.raw 提供；parse_result→acc.parse_result；...
        <原 340–999 行代码，按映射表把已搬走的局部变量替换为 acc 字段>
```

替换点（原行号）：`npc_interact_entries`（328 引用）、`other_entries`（835）、`parse_result`（341 循环）、`detect_future`/`executor`（816–826）。`enrich_input` 与 `all_outcomes` 在原 261–262 创建——现在由 acc 提供，删除原创建行，后续引用改 `acc.enrich_input` / `acc.all_outcomes`。

- [ ] **Step 3: 验证**

Run: `pytest tests/ -q`
Expected: `341 passed, 20 deselected`

- [ ] **Step 4: MAINTENANCE + Commit**

```bash
git add src/game/turn/understand.py src/game/agents/keeper.py MAINTENANCE.md
git commit -m "refactor: R1-W1 extract understand phase (guards/parse/npc/intent-prefetch)"
```

---

### Task W2: B 裁决阶段（adjudicate.py）

**Files:**
- Create: `src/game/turn/adjudicate.py`
- Modify: `src/game/agents/keeper.py`

**搬迁范围（锚点）**：`# Step 2: Judge — iterate over parse result entries`（原 340 行）到依赖图自动触发块结束（原 536–556 行）。

- [ ] **Step 1: 写 phase_b_adjudicate**

```python
"""B 裁决：judge 循环 + 依赖图自动触发。W6 起尾部吞入作者门。"""
from __future__ import annotations


def phase_b_adjudicate(ctx, acc, tools) -> None:
    """judge 各 entry 类型(interaction/event/use/move/search/other) + 依赖自动触发。
    产出: acc.all_outcomes / acc.enrich_input / tools._pending_side_effects /
    tools._pending_move / tools._weapon_offer(search 发现)。"""
```

逐分支原样搬运（interaction/event 340–386、use 387–399、move 400–422、search 423–495、other/unknown 496–534、依赖触发 536–556）。`self.` → `tools.`；局部变量按映射表改 acc。

- [ ] **Step 2: _run_turn_pipeline 接线**

在 `phase_a` 调用之后插入：

```python
        from ..turn.adjudicate import phase_b_adjudicate
        phase_b_adjudicate(ctx, acc, self)
        # ── 原 558 行起的 C–E 段：all_outcomes/enrich_input 引用改 acc 字段
```

- [ ] **Step 3: 验证**

Run: `pytest tests/ -q`
Expected: `341 passed, 20 deselected`

- [ ] **Step 4: MAINTENANCE + Commit**

```bash
git add src/game/turn/adjudicate.py src/game/agents/keeper.py MAINTENANCE.md
git commit -m "refactor: R1-W2 extract adjudicate phase (judge loop + dependency auto-trigger)"
```

---

### Task W3: C 遭遇阶段（encounter.py + provider 链）

**Files:**
- Create: `src/game/turn/encounter.py`
- Modify: `src/game/agents/keeper.py`

**搬迁范围（锚点）**：`# Step 2.5: Combat entry detection`（原 558 行）到吞对峙①结束（原 720–723 行）。

- [ ] **Step 1: 写 encounter.py（接口 + 两个 provider + 阶段函数）**

```python
"""C 遭遇：敌战入口 + Boss 接入。EncounterProvider 有序链，plugin 接入点。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class EncounterContribution:
    """单个 provider 的产出。"""
    combat_init: Any = None            # CombatInit；多 provider 时由编排逻辑合并
    standoff: dict | None = None
    outcomes: list = field(default_factory=list)         # 追加进 acc.all_outcomes
    enrich_entities: list[dict] = field(default_factory=list)  # 追加进 acc.enrich_input.entities
    boss_accounting: tuple | None = None  # (boss_id, boss_enemy)，E 在 curate 后消费


class EncounterProvider(Protocol):
    def probe(self, ctx, acc, tools) -> EncounterContribution | None: ...


class EnemyCombatProvider:
    """敌人上下文 → LLM 战斗入口判定 → 对峙播种 / CombatInit。
    （原 keeper.py 558–670）"""

    def probe(self, ctx, acc, tools) -> EncounterContribution | None:
        <原 558–670 行代码：enemy_ctx 检查、LLM 判定(异常→None)、
         avoidable→standoff 播种(tools._standoff_pending) / hostile→enter_combat+CombatInit；
         tools._last_player_input = ctx.raw（原 670）>


class SceneBossProvider:
    """Boss at/interaction 检查 + 合并 combat_init + 记账载荷记入 contribution。
    （原 keeper.py 672–718；记账仍不执行，仅记录载荷）"""

    def probe(self, ctx, acc, tools) -> EncounterContribution | None:
        <原 672–718 行代码；注意 711–718 的合并逻辑：若 acc.combat_init_result
         已有敌人则 append boss_enemy，否则整个替换；acc.boss_accounting =
         (boss_engaged_id, boss_enemy)>


_PROVIDERS = (EnemyCombatProvider(), SceneBossProvider())


def phase_c_encounter(ctx, acc, tools) -> None:
    for provider in _PROVIDERS:
        contribution = provider.probe(ctx, acc, tools)
        if contribution is None:
            continue
        acc.all_outcomes.extend(contribution.outcomes)
        acc.enrich_input.entities.extend(contribution.enrich_entities)
        if contribution.combat_init is not None:
            acc.combat_init_result = contribution.combat_init
        if contribution.standoff is not None:
            acc.standoff_prompt = contribution.standoff
        if contribution.boss_accounting is not None:
            acc.boss_accounting = contribution.boss_accounting
    # 吞对峙①（原 720–723）：F3 Boss 强制战吞掉对峙
    if acc.boss_accounting and acc.standoff_prompt:
        acc.standoff_prompt = tools._devour_standoff_for_boss(
            acc.standoff_prompt, acc.combat_init_result, acc.all_outcomes,
            acc.enrich_input)
```

注意原 720 的条件是 `if boss_combat_init and standoff_prompt`——W3 中等价为 `acc.boss_accounting and acc.standoff_prompt`（boss_accounting 有值即 boss_combat_init 构建成功）。

- [ ] **Step 2: _run_turn_pipeline 接线**

phase_b 之后插入 `phase_c_encounter(ctx, acc, self)`；后续段引用改 acc（`combat_entry`→diagnostics 用，`standoff_prompt`/`combat_init_result`/`boss_combat_init`/`boss_engaged_id` 在 E 段改为读 acc）。

E 段原 977–983 记账块暂改读 `acc.boss_accounting`：

```python
        if acc.boss_accounting and acc.combat_init_result:
            boss_engaged_id, boss_enemy = acc.boss_accounting
            if boss_enemy:
                self.world.enemies.register(boss_enemy)
                self.world.enemies.add_to_combat(boss_enemy.instance_id)
                self.world.bosses.set_active(boss_engaged_id)
                self.world.bosses.mark_spawned(boss_engaged_id)
```

- [ ] **Step 3: 验证**

Run: `pytest tests/ -q`
Expected: `341 passed, 20 deselected`

- [ ] **Step 4: MAINTENANCE + Commit**

```bash
git add src/game/turn/encounter.py src/game/agents/keeper.py MAINTENANCE.md
git commit -m "refactor: R1-W3 extract encounter phase with EncounterProvider chain"
```

---

### Task W4: D 充实阶段（enrich.py）

**Files:**
- Create: `src/game/turn/enrich.py`
- Modify: `src/game/agents/keeper.py`

**搬迁范围（锚点）**：`# Step 3: [Enrich(LLM) ∥ TimeAgent(LLM)]` 前的 `_combat_result_pending` 注入块（原 728–739）到时压通信块结束（原 786–813）。

- [ ] **Step 1: 写 phase_d_enrich**

```python
"""D 充实：战斗结果注入 → enrich ∥ time_agent → advance_time → ending扫描① → 时压。"""
from __future__ import annotations


def phase_d_enrich(ctx, acc, tools) -> None:
    """产出: acc.enrichment / acc.ta_result / acc.emphasis / acc.enriched_summary /
    acc.ending_result(首次扫描) / world.advance_time 副作用 / 时压 outcome。"""
```

搬入（原行号）：战斗结果注入（728–739，`tools._combat_result_pending`）、enrich∥TA（741–766，`tools.turn_monitor.execute_parallel`，内部调 `tools._enrich` / `tools._run_time_agent`）、结果收集 + `tools._scan_ending` 第一次（768–784）、时压通信（786–813）。

- [ ] **Step 2: 接线**——phase_c 之后插入 `phase_d_enrich(ctx, acc, self)`；后续段 `emphasis`/`enriched_summary`/`ta_result`/`enrichment`/`ending_result` 引用改 acc。

- [ ] **Step 3: 验证**

Run: `pytest tests/ -q`
Expected: `341 passed, 20 deselected`

- [ ] **Step 4: MAINTENANCE + Commit**

```bash
git add src/game/turn/enrich.py src/game/agents/keeper.py MAINTENANCE.md
git commit -m "refactor: R1-W4 extract enrich phase (enrich∥TA, time advance, time pressure)"
```

---

### Task W5: E 收尾阶段（finalize.py）

**Files:**
- Create: `src/game/turn/finalize.py`
- Modify: `src/game/agents/keeper.py`

**搬迁范围（锚点）**：作者门块**之后**的 `# ── Apply all deferred side effects + move`（原 878–879）到 `return TurnResult(...)`（原 985–999）。作者门块（原 815–876）本波**留在 keeper 内联**，W6 才动。

- [ ] **Step 1: 写 phase_e_finalize**

```python
"""E 收尾：落账 → ending② → warnings → event型Boss → 吞对峙② → curate → Boss记账 → assemble。"""
from __future__ import annotations


def phase_e_finalize(ctx, acc, tools) -> None:
    """结果写 acc.result(TurnResult)。curate 的 TurnFrozenError 冒泡（runner 兜底）。"""
```

搬入（原行号）：`tools._apply_pending()`（879）、ending 二次扫描（882–883）、warnings→outcomes（886–889）、event 型 Boss（891–917）、吞对峙②（922–924，`enrich_input` 参数传 None）、curate（926–935，**删除**局部 try/except TurnFrozenError，冒泡）、memory 压缩线程（938–945）、weapon offer 注入 brief（948–954）、`tools._last_outcomes = list(acc.all_outcomes)`（956）、standoff/offer → PendingInteraction（958–973）、Boss 记账（977–983，读 acc.boss_accounting）、assemble `acc.result = TurnResult(...)`（985–999）。

- [ ] **Step 2: 接线**

```python
        # 作者门块（原 815–876 仍内联在此）
        from ..turn.finalize import phase_e_finalize
        phase_e_finalize(ctx, acc, self)
        return acc.result
```

- [ ] **Step 3: 验证**

Run: `pytest tests/ -q`
Expected: `341 passed, 20 deselected`

- [ ] **Step 4: MAINTENANCE + Commit**

```bash
git add src/game/turn/finalize.py src/game/agents/keeper.py MAINTENANCE.md
git commit -m "refactor: R1-W5 extract finalize phase (apply/post-boss/curate/assemble)"
```

---

### Task W6: 作者门迁移 + Restart 循环化（唯一变更波）

**Files:**
- Modify: `src/game/turn/context.py`（加 `Restart`）
- Modify: `src/game/turn/runner.py`（委托壳 → 循环编排器）
- Modify: `src/game/turn/adjudicate.py`（吞入作者门）
- Modify: `src/game/agents/keeper.py`（删除内联作者门 + `_depth` 递归路径）
- Test: `tests/e2e/test_deterministic.py`（新增 `TestAuthorRecursion`）

**有意变更**：作者门从 enrich 后（原 815–876）迁到 B 尾部。修复：递归路径 advance_time 双涨、被弃帧白跑 combat-entry/enrich/TA。已知微差：作者拒绝 outcome 现会进 combat-entry prompt 与 enrich 输入（原 enrich 追加为死写）。

- [ ] **Step 1: 先写 4 条新测试（TDD red）**

加到 `tests/e2e/test_deterministic.py` 尾部。复用 `tests/e2e/helpers.py` 的 `make_world`/`make_scene`/`stub_keeper_llm` 与 `tests/test_p0_pipeline_fixes.py:180–222` 的递归 fixture 模式：

```python
class TestAuthorRecursion:
    """W6：作者门迁至 B 尾部后的递归语义锁定。"""

    def _recursion_world(self):
        from tests.e2e.helpers import make_world, make_scene
        world = make_world({"room_a": make_scene()}, start_node="room_a")
        from investigator import Investigator
        world.set_player(Investigator(name="测试员", age=25, gender="男"))
        return world

    def _accept_author(self):
        from types import SimpleNamespace
        from game.messages import ModulePatch
        patch = ModulePatch(
            entities=[{"id": "NEW1", "entity_type": "interaction", "name": "墙壁回音",
                       "scene": "room_a", "type": "无", "requirement": "",
                       "trigger": "听回音", "result": "墙回应了你。",
                       "side_effects": [], "difficulty": "None"}],
            scene_descriptions={}, justification="作者补充了墙壁回音")
        return SimpleNamespace(time_pressure=None, l3_data={},
                               handle_request=lambda req, turn: patch)

    def _stub_creative_other(self, keeper, monkeypatch, time_delta=0):
        from tests.e2e.helpers import stub_keeper_llm
        stub_keeper_llm(keeper, monkeypatch, time_delta=time_delta,
                        parse_results=[[{"type": "other", "impact": "creative",
                                         "text": "对着墙打一套拳"}]])
        from types import SimpleNamespace
        keeper.intent_detector.detect = lambda *a, **k: SimpleNamespace(
            needs_author=True, intent="练拳", reasoning="r")

    def test_recursion_advances_time_once(self, monkeypatch):
        """递归路径 TA 只运行一次（旧行为：外帧+内帧双涨）。"""
        from game.agents.keeper import Keeper
        from game.messages import TurnInput
        world = self._recursion_world()
        keeper = Keeper(world)
        self._stub_creative_other(keeper, monkeypatch, time_delta=60)
        t0 = world.clock.game_time
        keeper.process_turn(TurnInput(raw_text="对着墙打一套拳"),
                            author=self._accept_author())
        assert world.clock.game_time - t0 == 60, (
            f"期望推进 60（TA 单次），实际 {world.clock.game_time - t0}")

    def test_recursion_runs_enrich_once(self, monkeypatch):
        """递归路径 enrich 只运行一次（旧行为：外帧白跑一次）。"""
        from game.agents.keeper import Keeper
        from game.messages import TurnInput
        world = self._recursion_world()
        keeper = Keeper(world)
        self._stub_creative_other(keeper, monkeypatch)
        calls = {"n": 0}
        def counting_enrich(e, r):
            calls["n"] += 1
            return {"results": "", "reasoning": "", "emphasis_hint": ""}
        keeper._enrich = counting_enrich
        keeper.process_turn(TurnInput(raw_text="对着墙打一套拳"),
                            author=self._accept_author())
        assert calls["n"] == 1, f"期望 enrich 1 次，实际 {calls['n']}"

    def test_author_rejection_outcome_present(self, monkeypatch):
        """作者拒绝 → 拒绝信息进 outcomes（新旧行为一致，回归锁）。"""
        from types import SimpleNamespace
        from game.agents.keeper import Keeper
        from game.messages import TurnInput, ModulePatch
        world = self._recursion_world()
        keeper = Keeper(world)
        self._stub_creative_other(keeper, monkeypatch)
        author = SimpleNamespace(
            time_pressure=None, l3_data={},
            handle_request=lambda req, turn: ModulePatch(
                entities=[], scene_descriptions={},
                justification="REJECTED: 不合理"))
        result = keeper.process_turn(TurnInput(raw_text="对着墙打一套拳"),
                                     author=author)
        assert any("你尝试了" in o.message for o in result.brief.action_outcomes)

    def test_escalation_depth_guard(self, monkeypatch):
        """intent 每次不同（绕过冷却）→ 深度守卫触发 deterministic-only。"""
        from types import SimpleNamespace
        from game.agents.keeper import Keeper
        from game.messages import TurnInput
        world = self._recursion_world()
        keeper = Keeper(world)
        self._stub_creative_other(keeper, monkeypatch)
        counter = {"n": 0}
        def detect(*a, **k):
            counter["n"] += 1
            return SimpleNamespace(needs_author=True,
                                   intent=f"练拳{counter['n']}", reasoning="r")
        keeper.intent_detector.detect = detect
        result = keeper.process_turn(TurnInput(raw_text="对着墙打一套拳"),
                                     author=self._accept_author())
        assert result.brief is not None
        assert any("没有什么特别的事情发生" in o.message
                   for o in result.brief.action_outcomes)
```

- [ ] **Step 2: 跑新测试确认红绿分布**

Run: `pytest tests/e2e/test_deterministic.py::TestAuthorRecursion -v`
Expected: `test_recursion_advances_time_once` 与 `test_recursion_runs_enrich_once` **FAIL**（旧行为双涨/两次）；另两条 PASS（回归锁）。

注意：若 red 测试意外 PASS，说明旧行为并非如预期——停下来核对 `advance_time`/`_enrich` 的实际调用路径，不要强行改断言。

- [ ] **Step 3: context.py 加 Restart**

```python
class Restart:
    """作者门接受 → 编排器落账后从 A 重跑（循环，非递归调用）。"""
```

- [ ] **Step 4: runner.py 改循环编排器**

```python
"""TurnRunner：回合编排器（五宏阶段 + Restart 循环）。"""
from __future__ import annotations

from config import MAX_ESCALATION_DEPTH
from monitor.turn_monitor import TurnFrozenError
from .context import TurnContext, TurnAccumulator, Early, Restart


class TurnRunner:
    def __init__(self, keeper):
        self.keeper = keeper

    def execute(self, turn_input, author=None):
        from .understand import phase_a_understand
        from .adjudicate import phase_b_adjudicate
        from .encounter import phase_c_encounter
        from .enrich import phase_d_enrich
        from .finalize import phase_e_finalize
        tools = self.keeper
        depth = 0
        while True:
            ctx = TurnContext(turn_input=turn_input, author=author, depth=depth,
                              raw=turn_input.raw_text)
            acc = TurnAccumulator()
            try:
                for phase in (phase_a_understand, phase_b_adjudicate,
                              phase_c_encounter, phase_d_enrich,
                              phase_e_finalize):
                    r = phase(ctx, acc, tools)
                    if isinstance(r, Early):
                        return r.result
                    if isinstance(r, Restart):
                        tools._apply_pending()   # 保持现语义：重入前落账
                        break
                else:
                    return acc.result
            except TurnFrozenError as e:
                return tools._build_frozen_response(e)
            depth += 1
            if depth >= MAX_ESCALATION_DEPTH:
                return tools._process_deterministic_only(turn_input)
```

- [ ] **Step 5: 作者门搬入 adjudicate.py**

把 keeper 内联的作者门块（原 815–876：`if detect_future:` 到 rejection 分支结束）搬为 `phase_b_adjudicate` 尾部：

```python
def phase_b_adjudicate(ctx, acc, tools):
    <W2 的 judge 循环 + 依赖触发>
    # ── 作者门（W6 自 keeper 迁入；原 815–876）──
    if acc.detect_future:
        <原样收割逻辑：turn_monitor.execute_step("intent_detect", ...)、
         executor.shutdown、cooldown、AuthorRequest、author.handle_request>
        if StructuralEdit 且 supplement_path:
            return Restart()      # 原: self._apply_pending(); return process_turn(depth+1)
        if ModulePatch 且 entities:
            return Restart()      # 同上
        # rejection：outcome + enrich 实体追加（原样），继续
    return None
```

keeper 侧删除内联作者门块；`process_turn` 的 `_depth>0` 分支与 `_run_turn_pipeline` 一并删除——facade 简化为：

```python
    def process_turn(self, turn_input: TurnInput, author: Any = None, _depth: int = 0) -> TurnResult:
        """Facade：委托 TurnRunner（_depth 参数保留兼容，不再使用）。"""
        if not hasattr(self, "_runner"):
            from ..turn.runner import TurnRunner
            self._runner = TurnRunner(self)
        return self._runner.execute(turn_input, author)
```

`_run_turn_pipeline` 删除后，其内残留的全部管线代码应已搬空——删除前确认 keeper.py 中不再有任何 A–E 段代码残留。

- [ ] **Step 6: 验证**

Run: `pytest tests/e2e/test_deterministic.py::TestAuthorRecursion -v` → 4 passed
Run: `pytest tests/ -q` → `341 + 4 new passed, 20 deselected`（flaky 复跑）
Run: `pytest tests/test_p0_pipeline_fixes.py -v` → 全绿（既有递归用例 `test_p0...` Author ModulePatch 路径不回归）

- [ ] **Step 7: MAINTENANCE + Commit**

```bash
git add src/game/turn/ src/game/agents/keeper.py tests/e2e/test_deterministic.py MAINTENANCE.md
git commit -m "refactor: R1-W6 author gate moves into adjudicate; recursion loop-ified; TA/enrich single-run on recursion"
```

---

### Task W7: facade 定型 + 收口

**Files:**
- Modify: `src/game/agents/keeper.py`（session_state 分组）
- Modify: `MAINTENANCE.md`、`docs/ISSUES.md`

- [ ] **Step 1: 会话态显式分组**

`Keeper.__init__` 中把会话态字段收拢（加注释分组，不改字段名——零行为变更）：

```python
        # ── session_state（跨回合；B1 存档设计将以此分组为入档单元）──
        self._weapon_offer = None
        self._weapon_offer_msg = ""
        self._standoff_pending = None
        self._combat_result_pending = None
        self._last_outcomes = []
        self._last_player_input = ""
        self._npc_injected_at_ids = set()
        self._recent_intents = []
```

（仅挪动 `__init__` 内的赋值位置并加注释；不改任何读写点。）

- [ ] **Step 2: 行数验收**

Run: `python -c "print(sum(1 for _ in open('src/game/agents/keeper.py', encoding='utf-8')))"`
Expected: ≤ ~800 行

- [ ] **Step 3: MAINTENANCE.md 全面刷新**

keeper.py 新行号、turn/ 包各文件职责与函数行号、process_turn→TurnRunner 调用关系。ISSUES.md：R1 从 §3 重构队列移入 §5 已收口（注明 keeper 阶段化完成、combat.py/scenario_core.py 拆分另排）。

- [ ] **Step 4: 全量回归**

Run: `pytest tests/ -q`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add src/game/agents/keeper.py MAINTENANCE.md docs/ISSUES.md
git commit -m "docs: R1 closure — keeper turn pipeline staged, session_state grouped"
```

---

## Self-Review 记录

- Spec 覆盖：§1 契约(W0/W6) §2 DAG(W1–W5) §3 Provider(W3) §4 变更(W6) §5 排布(各 W) §6 波次(Tasks) §7 风险(各步注意事项)——全覆盖
- Boss 记账：W3 起经 `acc.boss_accounting` 传递、E 在 curate 后消费（freeze 安全），与 spec §4.1 修正后一致
- 类型一致：`Early`（W0 定义，W1+ 使用）、`Restart`（W6 定义并使用）、`EncounterContribution`（W3）、phase 签名全程一致
- 行为不变约束：W1–W5 仅 `self.`→`tools.`、局部变量→acc 字段、两处 freeze try/except 改冒泡（runner 兜底等价）；W6 变更点均已列测试锁定
