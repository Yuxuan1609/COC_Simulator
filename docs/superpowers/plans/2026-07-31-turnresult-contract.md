# TurnResult 契约实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `keeper.process_turn`（7 种 dict shape）与 `run_turn`（14 键 dict）统一为双层 dataclass 契约（TurnResult / PlayerTurnResult），引入一等挂起态，分离 enrich 呈现与事实，一次性迁移全部生产端与消费端。

**Architecture:** 内部契约 `TurnResult`（keeper→run_turn，带 TurnStatus 枚举 + PendingInteraction）+ 外层契约 `PlayerTurnResult`（run_turn→前端/CLI/工具）。SUSPENDED 仅表示回合阻塞（clarify）；`COMPLETED + pending_interaction` 表示回合完成但留有追问（offer/standoff）。

**Tech Stack:** Python 3.13 dataclasses、pytest、FastAPI。

**Spec:** `docs/superpowers/specs/2026-07-31-turnresult-contract-design.md`（含语义修正：offer/standoff 提问 = COMPLETED+pending，非 SUSPENDED）

**工作区：** 在 `.worktrees/turnresult-contract` worktree 中实施（参照 superpowers:using-git-worktrees），完成后合并回 main。

---

### Task 1: 契约类型定义（messages.py）

**Files:**
- Modify: `src/game/messages.py`（顶部 import 区 + 文件末尾追加）
- Test: `tests/test_turn_result_contract.py`（新建）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_turn_result_contract.py`：

```python
"""TurnResult / PlayerTurnResult contract unit tests."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from game.messages import (
    TurnStatus, PendingInteraction, EndingInfo, TurnDiagnostics,
    TurnResult, PlayerTurnResult,
)


class TestTurnResultInvariants:
    def test_suspended_requires_pending_interaction(self):
        with pytest.raises(ValueError):
            TurnResult(status=TurnStatus.SUSPENDED, text="问题？")

    def test_suspended_with_pending_ok(self):
        r = TurnResult(
            status=TurnStatus.SUSPENDED,
            text="你要怎么做？",
            pending_interaction=PendingInteraction(
                kind="clarify", question="你要怎么做？", interaction_id="clarify"),
        )
        assert r.status == TurnStatus.SUSPENDED
        assert r.pending_interaction.kind == "clarify"

    def test_brief_none_requires_text(self):
        with pytest.raises(ValueError):
            TurnResult(status=TurnStatus.COMPLETED)

    def test_completed_with_pending_interaction_ok(self):
        """offer/standoff: 回合完成 + 留有追问。"""
        from game.messages import NarratorBrief, SceneSnapshot
        brief = NarratorBrief(
            action_outcomes=[], ambient_changes=[],
            scene_snapshot=SceneSnapshot(
                location="房间", description="", exits=[],
                perceptible_interactions=[], visible_npcs=[]),
            suggested_emphasis="")
        r = TurnResult(
            status=TurnStatus.COMPLETED,
            brief=brief,
            pending_interaction=PendingInteraction(
                kind="weapon_offer", question="是否拾取？",
                interaction_id="weapon_offer"),
        )
        assert r.pending_interaction is not None

    def test_frozen_carries_message(self):
        r = TurnResult(status=TurnStatus.FROZEN,
                       text="系统异常", frozen_message="系统异常")
        assert r.status == TurnStatus.FROZEN

    def test_diagnostics_defaults(self):
        r = TurnResult(status=TurnStatus.COMPLETED, text="ok")
        assert r.diagnostics.combat_entry is None
        assert r.diagnostics.time_agent is None
        assert r.npc_events == []


class TestPlayerTurnResult:
    def test_minimal_construction(self):
        r = PlayerTurnResult(status=TurnStatus.COMPLETED, brief="b", narrative="n")
        assert r.game_over is False
        assert r.diagnostics == {}

    def test_ending_info(self):
        e = EndingInfo(name="结局A", narrative="你死了", game_over=True)
        r = PlayerTurnResult(status=TurnStatus.COMPLETED, brief="b",
                             narrative="n", ending=e, game_over=True)
        assert r.ending.name == "结局A"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_turn_result_contract.py -q -p no:cacheprovider`
Expected: FAIL，`ImportError: cannot import name 'TurnStatus'`

- [ ] **Step 3: 实现契约类型**

`src/game/messages.py` 顶部 import 区追加 `from enum import Enum`，文件末尾追加：

```python
class TurnStatus(Enum):
    COMPLETED = "completed"
    SUSPENDED = "suspended"
    FROZEN = "frozen"


@dataclass
class PendingInteraction:
    """回合挂起的待答问题。"""
    kind: str              # "weapon_offer" | "standoff" | "clarify"
    question: str          # 玩家可见问题文本
    interaction_id: str = ""  # resolver 路由键


@dataclass
class EndingInfo:
    name: str
    narrative: str
    game_over: bool = True


@dataclass
class TurnDiagnostics:
    """低频/调试数据统一入口。"""
    combat_entry: CombatEntryCheck | None = None
    time_agent: dict | None = None
    enrich_raw: dict | None = None
    pre_parse: PreParseResult | None = None


@dataclass
class TurnResult:
    """Keeper.process_turn 的内部契约返回。"""
    status: TurnStatus
    brief: NarratorBrief | None = None       # COMPLETED 且走完 pipeline 时必有
    text: str = ""                           # SUSPENDED→question；FROZEN→提示；简单路径文本
    pending_interaction: PendingInteraction | None = None
    combat_init: CombatInit | None = None
    ending: EndingInfo | None = None
    npc_events: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    frozen_message: str = ""
    diagnostics: TurnDiagnostics = field(default_factory=TurnDiagnostics)

    def __post_init__(self):
        if self.status == TurnStatus.SUSPENDED:
            if not self.pending_interaction:
                raise ValueError("SUSPENDED requires pending_interaction")
            if self.brief is not None:
                raise ValueError("SUSPENDED must not carry brief (turn blocked)")
        if self.brief is None and not self.text:
            raise ValueError("TurnResult requires text when brief is None")


@dataclass
class PlayerTurnResult:
    """run_turn 的玩家面契约返回。"""
    status: TurnStatus
    brief: str = ""
    narrative: str = ""
    pending_interaction: PendingInteraction | None = None
    player_snapshot: PlayerFacingSnapshot | None = None
    skill_results: list[dict] = field(default_factory=list)
    combat: dict | None = None               # 调用方战斗结算后回填
    combat_init: CombatInit | None = None
    ending: EndingInfo | None = None
    game_over: bool = False
    timestamp: str = ""
    diagnostics: dict = field(default_factory=dict)  # time_agent / npc_events / npcs_visible
```

注意：`PlayerFacingSnapshot` 已在 messages.py 中定义，直接使用。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_turn_result_contract.py -q -p no:cacheprovider`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/game/messages.py tests/test_turn_result_contract.py
git commit -m "feat: TurnResult/PlayerTurnResult contract types with status enum + invariants"
```

---

### Task 2: NarratorBrief.enriched_summary + enrich 呈现/事实分离

**Files:**
- Modify: `src/game/messages.py:62-67`（NarratorBrief）
- Modify: `src/game/curator.py:17-28`
- Modify: `src/prompts.py:601-650`（build_narrator_prompt）
- Modify: `src/game/agents/keeper.py`（Step 3.5 覆写块 ~:695-710；Step 5 curate 调用 ~:848；complete_combat_turn ~:930-945）
- Test: `tests/test_turn_result_contract.py`（追加）

- [ ] **Step 1: 写失败测试**

`tests/test_turn_result_contract.py` 追加：

```python
class TestEnrichedSummary:
    def test_curator_passes_enriched_summary(self):
        from game.messages import NarratorBrief
        from game.curator import Curator
        from unittest.mock import MagicMock
        world = MagicMock()
        node = MagicMock()
        node.description = "黑暗的房间"
        world._current_node.return_value = node
        world.current_location = "房间"
        world.get_possible_exits.return_value = []
        world.completed_interactions = {}
        world.npcs = None
        brief = Curator(world).assemble([], [], emphasis="", enriched_summary="合并叙事文本")
        assert brief.enriched_summary == "合并叙事文本"

    def test_curator_default_empty_summary(self):
        from game.curator import Curator
        from unittest.mock import MagicMock
        world = MagicMock()
        node = MagicMock()
        node.description = ""
        world._current_node.return_value = node
        world.current_location = "房间"
        world.get_possible_exits.return_value = []
        world.completed_interactions = {}
        world.npcs = None
        brief = Curator(world).assemble([], [], "")
        assert brief.enriched_summary == ""
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_turn_result_contract.py::TestEnrichedSummary -q -p no:cacheprovider`
Expected: FAIL，`TypeError: assemble() takes ... unexpected keyword 'enriched_summary'`

- [ ] **Step 3: 实现**

a) `src/game/messages.py` NarratorBrief 加字段：

```python
@dataclass
class NarratorBrief:
    """KP -> Narrator: curated ruling for narrative generation."""
    action_outcomes: list[ActionOutcome]
    ambient_changes: list[str]       # AT results perceptible to player
    scene_snapshot: SceneSnapshot
    suggested_emphasis: str          # what to highlight + tone direction
    enriched_summary: str = ""       # enrich 合并叙事（呈现层），空则回退 outcomes
```

b) `src/game/curator.py` assemble 加第 4 参：

```python
    def assemble(
        self,
        outcomes: list[ActionOutcome],
        ambient_changes: list[str],
        emphasis: str = "",
        enriched_summary: str = "",
    ) -> NarratorBrief:
        return NarratorBrief(
            action_outcomes=outcomes,
            ambient_changes=ambient_changes,
            scene_snapshot=self._build_snapshot(),
            suggested_emphasis=emphasis,
            enriched_summary=enriched_summary,
        )
```

c) `src/prompts.py:618-636` build_narrator_prompt 在【实体行动结果】前注入合并叙事（有则有主素材）：

```python
    enriched_block = ""
    if getattr(brief, "enriched_summary", ""):
        enriched_block = f"【合并叙事（enrich 产出，叙事主素材）】\n{brief.enriched_summary}\n\n"

    prompt = f"""{l1_ctx}

{inv_info}
【玩家输入】{user_input or '（无）'}

【当前场景】{brief.scene_snapshot.location}
{brief.scene_snapshot.description}

【可通行方向】{', '.join(f"{e['target']}({e['method']})" for e in brief.scene_snapshot.exits)}

{enriched_block}【实体行动结果】
{entity_outcomes or '（无）'}
{'' if not flavor_outcomes else f'【即兴行为】\n{flavor_outcomes}'}
【环境变化】
{ambient_text}

【叙事强调】{brief.suggested_emphasis}
```

d) `src/game/agents/keeper.py` Step 3.5：删除覆写块，results 存为 `enriched_summary` 局部变量。将：

```python
        if enrichment:
            emphasis = enrichment.get("emphasis_hint", "")
            results = enrichment.get("results", "")
            if isinstance(results, str) and results and all_outcomes:
                updated = False
                for o in all_outcomes:
                    if o.success and o.entity_type != "auto_trigger":
                        o.message = results
                        updated = True
                        break
                if not updated:
                    all_outcomes[0].message = results
```

改为：

```python
        enriched_summary = ""
        if enrichment:
            emphasis = enrichment.get("emphasis_hint", "")
            results = enrichment.get("results", "")
            if isinstance(results, str):
                enriched_summary = results
```

e) `src/game/agents/keeper.py` Step 5 curate 调用（process_turn 内）：

```python
                lambda: self.curator.assemble(all_outcomes, ambient, emphasis, enriched_summary),
```

f) `src/game/agents/keeper.py` complete_combat_turn 内同样去覆写（`o.message = result_text` 块删除），`result_text` 改名为 `enriched_summary` 并传入 `self.curator.assemble(outcomes, ambient, emphasis, enriched_summary)`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_turn_result_contract.py -q -p no:cacheprovider`
Expected: 全部通过

- [ ] **Step 5: 回归确认无破坏**

Run: `python -m pytest tests/ -q -p no:cacheprovider --deselect tests/test_escalation_real.py`
Expected: 36 passed + 已知遗留 test_turn_monitor 1 failed（与基线一致）

- [ ] **Step 6: Commit**

```bash
git add src/game/messages.py src/game/curator.py src/prompts.py src/game/agents/keeper.py tests/test_turn_result_contract.py
git commit -m "feat: NarratorBrief.enriched_summary — separate enrich presentation from outcome facts"
```

---

### Task 3: process_turn 返回点迁移为 TurnResult（7 处 + standoff 播种）

**Files:**
- Modify: `src/game/agents/keeper.py`（:138-162 offer应答、:177-190 快捷、:195-202 ambiguous、:257-261 NPC对话、:520-560 standoff、:676 结局扫描、:855-870 正常返回、_build_frozen_response :872-885、_process_deterministic_only :1279）
- Test: `tests/test_turn_result_contract.py`（追加集成测试）

**keeper.py 顶部 import 更新**：

```python
from ..messages import (
    ActionIntent, ActionOutcome, NarratorBrief,
    AuthorRequest, StructuralEdit, ModulePatch, TurnInput,
    CombatEntryCheck, StandoffMatch, CombatInit,
    TimeCommsPacket, EnrichInput,
    TurnStatus, TurnResult, PendingInteraction, EndingInfo, TurnDiagnostics,
)
```

- [ ] **Step 1: 写失败测试（返回路径契约）**

`tests/test_turn_result_contract.py` 追加（复用 test_p0_pipeline_fixes 的基建模式）：

```python
class TestProcessTurnReturnsContract:
    """process_turn 各返回路径产出合法 TurnResult。"""
    import json as _json
    from types import SimpleNamespace as _SNS

    def _scene(self, interactions=None, exits=None):
        return {
            "interactions": interactions or [], "auto_triggers": [],
            "from_here": exits or [], "to_here": [], "encounters": [],
            "scene_weapons": [], "extra": {}, "description": "",
        }

    def _stub_llm(self, keeper, monkeypatch, parse_results=None):
        from game.messages import PreParseResult
        calls = list(parse_results or [[{"type": "other", "text": "站着不动"}]])
        keeper.pre_parse.disambiguate = lambda *a, **k: PreParseResult(
            clarity="clear", interpretation="", question="", resolved_text="")
        keeper._parse = lambda raw: calls.pop(0) if len(calls) > 1 else calls[0]
        keeper._enrich = lambda e, r: {"results": "", "reasoning": "", "emphasis_hint": ""}
        keeper._run_time_agent = lambda a, r: {"time_delta": 0, "narrative_hint": ""}
        monkeypatch.setattr("game.agents.keeper.call_deepseek",
                            lambda *a, **k: self._json.dumps(
                                {"enter_combat": False, "enemy_instance_ids": [],
                                 "reasoning": ""}, ensure_ascii=False))

    def test_ambiguous_returns_suspended(self, monkeypatch):
        from scenario_core import DirectedGraph, ScenarioWorld
        from game.messages import TurnInput, PreParseResult
        from game.agents.keeper import Keeper
        world = ScenarioWorld(DirectedGraph(
            scenes={"room_a": self._scene()}, events=[]), start_node="room_a")
        keeper = Keeper(world)
        keeper.pre_parse.disambiguate = lambda *a, **k: PreParseResult(
            clarity="ambiguous", interpretation="模糊", question="你想检查哪里？",
            resolved_text="")
        result = keeper.process_turn(TurnInput(raw_text="看看"), author=None)
        assert result.status == TurnStatus.SUSPENDED
        assert result.pending_interaction.kind == "clarify"
        assert result.pending_interaction.question == "你想检查哪里？"

    def test_normal_turn_returns_completed_with_brief(self, monkeypatch):
        from scenario_core import DirectedGraph, ScenarioWorld
        from game.messages import TurnInput
        from game.agents.keeper import Keeper
        world = ScenarioWorld(DirectedGraph(
            scenes={"room_a": self._scene()}, events=[]), start_node="room_a")
        keeper = Keeper(world)
        self._stub_llm(keeper, monkeypatch)
        result = keeper.process_turn(TurnInput(raw_text="四处看看"), author=None)
        assert result.status == TurnStatus.COMPLETED
        assert result.brief is not None
        assert hasattr(result.brief, "action_outcomes")

    def test_move_shortcut_invalid_target_returns_completed_text(self, monkeypatch):
        from scenario_core import DirectedGraph, ScenarioWorld
        from game.messages import TurnInput
        from game.agents.keeper import Keeper
        world = ScenarioWorld(DirectedGraph(
            scenes={"room_a": self._scene()}, events=[]), start_node="room_a")
        keeper = Keeper(world)
        result = keeper.process_turn(
            TurnInput(raw_text="", action_type="move", action_target="不存在的场景"),
            author=None)
        assert result.status == TurnStatus.COMPLETED
        assert result.brief is None
        assert "无法移动" in result.text

    def test_standoff_seeds_pending_and_interaction(self, monkeypatch, tmp_path):
        """standoff 提问：COMPLETED + pending_interaction，且播种 _standoff_pending。"""
        import json
        from scenario_core import DirectedGraph, ScenarioWorld
        from game.messages import TurnInput
        from game.agents.keeper import Keeper
        from library.enemies import EnemyLibrary, LibraryEnemy
        lib = EnemyLibrary()
        lib._enemies["深潜者"] = LibraryEnemy.from_dict({
            "name": "深潜者", "type": "怪物",
            "attributes": {"CON": 50, "SIZ": 50}, "armor": "",
            "attacks": [], "special_abilities": [], "san_loss": "0",
            "description": "", "combat_behavior": "",
        })
        world = ScenarioWorld(DirectedGraph(
            scenes={"room_a": self._scene()}, events=[]),
            start_node="room_a", enemy_library=lib)
        inst = world.enemies.spawn("深潜者", "room_a", 1)
        inst.flags = ["avoidable"]
        keeper = Keeper(world)
        self._stub_llm(keeper, monkeypatch)
        monkeypatch.setattr("game.agents.keeper.call_deepseek",
                            lambda *a, **k: json.dumps(
                                {"enter_combat": True, "enemy_instance_ids": [],
                                 "reasoning": "遭遇"}, ensure_ascii=False))
        result = keeper.process_turn(TurnInput(raw_text="继续前进"), author=None)
        assert result.status == TurnStatus.COMPLETED
        assert result.pending_interaction is not None
        assert result.pending_interaction.kind == "standoff"
        assert keeper._standoff_pending is not None, "必须播种 _standoff_pending"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_turn_result_contract.py::TestProcessTurnReturnsContract -q -p no:cacheprovider`
Expected: FAIL（`AttributeError: 'dict' object has no attribute 'status'`）

- [ ] **Step 3: 迁移 7 个返回点**

a) **offer 应答**（keeper.py:138-162，PICKUP/IGNORE 两个 return）：

```python
                names = "、".join(w["weapon_ref"] for w in offer_list)
                return TurnResult(status=TurnStatus.COMPLETED, text=f"你拾起了{names}。")
            names = "、".join(w["weapon_ref"] for w in offer_list)
            return TurnResult(status=TurnStatus.COMPLETED, text=f"你忽略了{names}。")
```

b) **快捷路径非法目标**（:180-186）：

```python
            if not target:
                return TurnResult(status=TurnStatus.COMPLETED,
                                  text="（移动目标未指定。）",
                                  npc_events=list(self._npc_events))
            exits = self.world.get_possible_exits()
            valid_targets = {e.target for e in exits}
            if target not in valid_targets:
                return TurnResult(status=TurnStatus.COMPLETED,
                                  text=f"（无法移动到「{target}」。）",
                                  npc_events=list(self._npc_events))
```

c) **ambiguous**（:195-202）：

```python
        if pre_result.clarity == "ambiguous":
            return TurnResult(
                status=TurnStatus.SUSPENDED,
                text=pre_result.question,
                pending_interaction=PendingInteraction(
                    kind="clarify", question=pre_result.question,
                    interaction_id="clarify"),
                diagnostics=TurnDiagnostics(pre_parse=pre_result),
            )
```

注意：`pre_result` 需要在 process_turn 局部可用以填入 diagnostics（正常路径）。将 `pre_result` 初始化为 `None` 于快捷分支前，正常分支赋值；快捷路径 diagnostics.pre_parse 为 None。

d) **NPC 纯对话**（:257-261）：

```python
            if not non_npc_entries:
                dialogue_text = self._npc_events[-1] if self._npc_events else ""
                return TurnResult(status=TurnStatus.COMPLETED,
                                  text=dialogue_text,
                                  npc_events=list(self._npc_events))
```

e) **standoff 创建点播种**（:546-560 区域，`standoff_prompt = {...}` 之后）追加：

```python
                self._standoff_pending = standoff_prompt  # 播种，供 continue_standoff 消费
```

f) **正常返回**（:855-870）。`standoff_prompt` 局部变量改为构建 PendingInteraction：

```python
        standoff_pending = None
        if standoff_prompt:
            standoff_pending = PendingInteraction(
                kind="standoff",
                question=f"你还有最后一次机会避免与{standoff_prompt['current_group']}的战斗——你要怎么做？",
                interaction_id="standoff",
            )

        return TurnResult(
            status=TurnStatus.COMPLETED,
            brief=brief,
            pending_interaction=standoff_pending,
            combat_init=combat_init_result,
            ending=EndingInfo(**ending_result) if ending_result else None,
            npc_events=list(self._npc_events),
            warnings=list(self._warnings),
            diagnostics=TurnDiagnostics(
                combat_entry=combat_entry,
                time_agent=ta_result,
                enrich_raw=enrichment,
                pre_parse=pre_result,
            ),
        )
```

（原 dict 中的 `combat_entry`/`time_agent`/`enrich` 键移入 diagnostics；`standoff_prompt` 键消失。）

g) **_build_frozen_response**（:872-885）：

```python
    def _build_frozen_response(self, exc: TurnFrozenError) -> TurnResult:
        return TurnResult(
            status=TurnStatus.FROZEN,
            text=str(exc),
            frozen_message=str(exc),
            npc_events=list(self._npc_events),
        )
```

h) **_process_deterministic_only**（:1279）：

```python
        brief = self.curator.assemble(all_outcomes, ambient, "")
        return TurnResult(status=TurnStatus.COMPLETED, brief=brief)
```

- [ ] **Step 4: 运行新契约测试确认通过**

Run: `python -m pytest tests/test_turn_result_contract.py -q -p no:cacheprovider`
Expected: 全部通过

- [ ] **Step 5: 更新 P0 测试到新契约**

`tests/test_p0_pipeline_fixes.py` 三处：

- `TestCombatEntryEmptyCandidates`：`result = keeper.process_turn(...)` 后
  ```python
  assert result.status == TurnStatus.COMPLETED
  assert result.combat_init is None
  ```
  （import 区加 `from game.messages import TurnStatus`）
- `TestBossEventPath`：`combat_init = result.get("combat_init")` → `combat_init = result.combat_init`
- `TestAuthorRecursionPreservesPending`：无需改（只断言 item_manager）

Run: `python -m pytest tests/test_p0_pipeline_fixes.py -q -p no:cacheprovider`
Expected: 6 passed

- [ ] **Step 6: Commit**

```bash
git add src/game/agents/keeper.py tests/test_turn_result_contract.py tests/test_p0_pipeline_fixes.py
git commit -m "feat: process_turn returns TurnResult — all 7 return sites + standoff_pending seeding"
```

---

### Task 4: complete_combat_turn / continue_standoff 迁移

**Files:**
- Modify: `src/game/agents/keeper.py` complete_combat_turn（:908-945）
- Modify: `src/game_loop.py` continue_standoff（:590-665）
- Test: `tests/test_turn_result_contract.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
class TestStandoffContinuation:
    def test_continue_standoff_returns_turn_result(self, monkeypatch, tmp_path):
        """process_turn 产生 standoff 后，continue_standoff 消费并返回 TurnResult。"""
        import json
        from scenario_core import DirectedGraph, ScenarioWorld
        from game.messages import TurnInput
        from game.agents.keeper import Keeper
        from game_loop import continue_standoff
        from library.enemies import EnemyLibrary, LibraryEnemy
        from investigator import Investigator

        lib = EnemyLibrary()
        lib._enemies["深潜者"] = LibraryEnemy.from_dict({
            "name": "深潜者", "type": "怪物",
            "attributes": {"CON": 50, "SIZ": 50}, "armor": "",
            "attacks": [], "special_abilities": [], "san_loss": "0",
            "description": "", "combat_behavior": "",
        })
        scene = {
            "interactions": [], "auto_triggers": [], "from_here": [],
            "to_here": [], "encounters": [], "scene_weapons": [],
            "extra": {}, "description": "",
        }
        world = ScenarioWorld(DirectedGraph(
            scenes={"room_a": scene}, events=[]),
            start_node="room_a", enemy_library=lib)
        world.set_player(Investigator(name="测试员", age=25, gender="男"))
        inst = world.enemies.spawn("深潜者", "room_a", 1)
        inst.flags = ["avoidable"]

        keeper = Keeper(world)
        from game.messages import PreParseResult
        keeper.pre_parse.disambiguate = lambda *a, **k: PreParseResult(
            clarity="clear", interpretation="", question="", resolved_text="")
        keeper._parse = lambda raw: [{"type": "other", "text": raw}]
        keeper._enrich = lambda e, r: {"results": "", "reasoning": "", "emphasis_hint": ""}
        keeper._run_time_agent = lambda a, r: {"time_delta": 0, "narrative_hint": ""}
        monkeypatch.setattr("game.agents.keeper.call_deepseek",
                            lambda *a, **k: json.dumps(
                                {"enter_combat": True, "enemy_instance_ids": [],
                                 "reasoning": "遭遇"}, ensure_ascii=False))
        turn = keeper.process_turn(TurnInput(raw_text="前进"), author=None)
        assert turn.pending_interaction is not None
        assert turn.pending_interaction.kind == "standoff"

        # standoff match LLM：不匹配 → 敌人转 hostile，返回 TurnResult
        monkeypatch.setattr(
            "game.agents.keeper.call_deepseek",
            lambda *a, **k: json.dumps(
                {"matched": False, "skill_name": "", "reason": ""},
                ensure_ascii=False))
        result = continue_standoff(keeper, "我举起双手")
        assert isinstance(result, TurnResult)
        assert result.status == TurnStatus.COMPLETED
        assert result.combat_init is not None or result.text
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_turn_result_contract.py::TestStandoffContinuation -q -p no:cacheprovider`
Expected: FAIL（`isinstance(result, TurnResult)` 失败 / `_standoff_pending` 未播种在 Task 3 已修，此处若 Task 3 已完成则是 dict vs TurnResult 断言失败）

- [ ] **Step 3: 实现**

a) `keeper.py` complete_combat_turn 返回 TurnResult（:908-945）：

```python
    def complete_combat_turn(self, original_input: str, combat_result: dict) -> TurnResult | None:
        """After combat resolves, replay enrich→curate with combat result injected."""
        if not self._last_outcomes:
            return None
        outcomes = list(self._last_outcomes)
        self._last_outcomes = []

        cr_outcome = combat_result.get("outcome", "")
        cr_label = {"win": "胜利", "loss": "败北", "flee": "逃脱", "draw": "平局"}.get(cr_outcome, cr_outcome)
        outcomes.append(ActionOutcome(
            intent=ActionIntent(action="combat"), success=(cr_outcome == "win"),
            message=f"战斗{cr_label}。{combat_result.get('narrative', '')}"[:200],
            entity_id="COMBAT_RESULT", entity_type="combat_result",
        ))

        enrich_entities = [
            {"entity_type": "combat_result", "id": "COMBAT_RESULT",
             "name": f"战斗{cr_label}", "result": combat_result.get("narrative", "")[:200],
             "success": cr_outcome == "win", "skill_tier": ""}
        ]
        enrichment = self._enrich(enrich_entities, original_input) if enrich_entities else None

        emphasis = enrichment.get("emphasis_hint", "") if enrichment else ""
        enriched_summary = ""
        if enrichment:
            r = enrichment.get("results", "")
            if isinstance(r, str):
                enriched_summary = r

        ambient = [o.message for o in outcomes if o.entity_type == "auto_trigger"]
        brief = self.curator.assemble(outcomes, ambient, emphasis, enriched_summary)
        return TurnResult(
            status=TurnStatus.COMPLETED,
            brief=brief,
            diagnostics=TurnDiagnostics(enrich_raw=enrichment),
        )
```

b) `game_loop.py` continue_standoff 返回 TurnResult。保留内部 combat 内联执行（B5 不在本计划），将最终 dict 改为：

```python
    result = keeper.resolve_standoff(s, player_input)
    # ... combat_init 构建逻辑不变 ...
    # ... combat 内联执行逻辑不变（cr / HP回写 / exit_combat / complete_combat_turn）...

    # 末尾：
    brief = None
    text = result.get("message", "")
    completed = result.get("combat_completed")
    if isinstance(completed, TurnResult):
        brief = completed.brief
    next_pending = None
    if result.get("next_standoff"):
        next_pending = PendingInteraction(
            kind="standoff", question=result["next_standoff"],
            interaction_id="standoff")
    return TurnResult(
        status=TurnStatus.COMPLETED,
        brief=brief,
        text=text,
        pending_interaction=next_pending,
        combat_init=result.get("combat_init"),
        npc_events=list(keeper._npc_events),
    )
```

注意 import：`from game.messages import TurnStatus, TurnResult, PendingInteraction`（game_loop.py 顶部 messages import 行更新）。
注意 `complete_combat_turn` 现在返回 TurnResult 或 None，`continue_standoff` 中 `result["combat_completed"] = completed if completed else None` 赋值逻辑相应调整（直接存 TurnResult 对象到局部变量，不再塞进 dict）。

c) `continue_standoff` 中 `keeper.complete_combat_turn(...)` 调用（:674）改为：

```python
        completed = None
        if keeper._last_player_input:
            completed = keeper.complete_combat_turn(keeper._last_player_input, combat_result)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_turn_result_contract.py -q -p no:cacheprovider`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/game/agents/keeper.py src/game_loop.py tests/test_turn_result_contract.py
git commit -m "feat: complete_combat_turn/continue_standoff return TurnResult"
```

---

### Task 5: run_turn → PlayerTurnResult + 应答分发 + debug 命令

**Files:**
- Modify: `src/game_loop.py` run_turn（:297-506）、_handle_spawn_command（:44-143）
- Test: `tests/test_turn_result_contract.py`（追加 run_turn 映射测试）

- [ ] **Step 1: 写失败测试**

```python
class TestRunTurnContract:
    def test_run_turn_returns_player_turn_result(self, monkeypatch):
        """run_turn 产出 PlayerTurnResult；SUSPENDED 透传 pending_interaction。"""
        from types import SimpleNamespace
        from game_loop import run_turn
        from game.messages import TurnStatus, TurnResult, PendingInteraction

        fake_keeper = SimpleNamespace(
            turn_number=1,
            _weapon_offer=None,
            _standoff_pending=None,
            process_turn=lambda ti, author=None: TurnResult(
                status=TurnStatus.SUSPENDED,
                text="你想检查哪里？",
                pending_interaction=PendingInteraction(
                    kind="clarify", question="你想检查哪里？",
                    interaction_id="clarify"),
            ),
        )
        fake_world = SimpleNamespace(player=None)
        fake_keeper.world = fake_world
        game = {"keeper": fake_keeper, "narrator": SimpleNamespace(),
                "author": None}
        result = run_turn(game, "看看")
        assert isinstance(result, PlayerTurnResult)
        assert result.status == TurnStatus.SUSPENDED
        assert result.pending_interaction.kind == "clarify"
        assert result.narrative == "你想检查哪里？"
```

注意：run_turn 开头有 `_check_autosave(game)` 与 `set_current_round`——测试中 autosave flag 默认为 False 直接跳过；`set_current_round` 无副作用。`from game.messages import PlayerTurnResult` 需加入测试 import。

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_turn_result_contract.py::TestRunTurnContract -q -p no:cacheprovider`
Expected: FAIL（run_turn 仍返回 dict / keeper mock 缺属性报错——按报错补 SimpleNamespace 属性直至失败原因为"返回 dict 而非 PlayerTurnResult"）

- [ ] **Step 3: 实现 run_turn 改造**

a) **standoff 应答分发**（run_turn 开头，debug 命令检查之后、process_turn 之前）：

```python
    # Pending standoff: route input to resolver instead of normal turn
    if getattr(keeper, "_standoff_pending", None):
        result = continue_standoff(keeper, user_input)
    else:
        result = keeper.process_turn(turn_input, author=author)
```

b) **run_turn 主体改造**——`result["brief"]` 等访问改为属性；核心映射逻辑：

```python
    result = ...  # TurnResult（process_turn 或 continue_standoff）
    brief = result.brief
    if brief is not None and hasattr(brief, "action_outcomes"):
        display_brief = brief.enriched_summary or "\n".join(
            o.message for o in brief.action_outcomes)
    else:
        display_brief = result.text

    combat_init = result.combat_init

    # skill_results 提取逻辑不变（brief 为 None 时为空列表）
    ...
```

c) **narrator 调用条件**：`if brief is not None and hasattr(brief, 'scene_snapshot'):` 走 narrate；否则 `narrative_brief = display_brief; narrative = result.text`（SUSPENDED/FROZEN/NPC对话/简单路径）。

d) **weapon offer 提示拼接**（keeper._weapon_offer 检查块）改为读 `result.pending_interaction`：

```python
    if result.pending_interaction and result.pending_interaction.kind == "weapon_offer":
        wp_text = result.pending_interaction.question
        if wp_text not in (narrative or ""):
            narrative = (narrative or "") + ("\n\n" if narrative else "") + wp_text
            if not narrative_brief:
                narrative_brief = wp_text
```

e) **ending/game_over**：`ending = result.ending`（EndingInfo 或 None）；`"game_over": bool(ending and ending.game_over)`。

f) **返回 PlayerTurnResult**：

```python
    return PlayerTurnResult(
        status=result.status,
        brief=narrative_brief,
        narrative=narrative,
        pending_interaction=result.pending_interaction,
        player_snapshot=player_snapshot,
        skill_results=skill_results,
        combat=None,   # 调用方战斗结算后回填
        combat_init=combat_init,
        ending=result.ending,
        game_over=bool(result.ending and result.ending.game_over),
        timestamp=datetime.now().strftime("%H:%M:%S"),
        diagnostics={
            "time_agent": result.diagnostics.time_agent,
            "npc_events": result.npc_events,
            "npcs_visible": npcs_visible,
        },
    )
```

（删除 `full`/`scene_update`/`standoff_prompt`/`time_agent`/`npcs_visible`/`npc_events` 顶层键。`full_text` 拼接逻辑删除。`npcs_visible` 构建逻辑保留但移入 diagnostics。）

g) **FROZEN 映射**：`result.status == TurnStatus.FROZEN` 时 narrative_brief/narrative = `result.frozen_message`，跳过 narrator。

h) **_handle_spawn_command 13 个返回点**：`{"brief": x, "narrative": y, "full": z}` 统一改为：

```python
return PlayerTurnResult(status=TurnStatus.COMPLETED, brief=x, narrative=y)
```

（`full` 键删除——前端/CLI 均不消费。run_turn 中 `if cmd_result: return cmd_result` 不变。）

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_turn_result_contract.py -q -p no:cacheprovider`
Expected: 全部通过

- [ ] **Step 5: Commit**

```bash
git add src/game_loop.py tests/test_turn_result_contract.py
git commit -m "feat: run_turn returns PlayerTurnResult + standoff answer dispatch + debug commands migrated"
```

---

### Task 6: 前端 router 迁移

**Files:**
- Modify: `frontend/routers/game.py`（/api/game/turn :237-405、frozen 处理 :320-334、combat/round complete_combat_turn 消费 :873-894、死代码 :928-937）
- Test: `tests/test_frontend_contract.py`（新建，TestClient）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_frontend_contract.py`：

```python
"""Frontend router consumes PlayerTurnResult correctly."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient

from game.messages import (
    TurnStatus, TurnResult, PlayerTurnResult, PendingInteraction,
)


@pytest.fixture
def client():
    from frontend.server import app
    return TestClient(app)


def test_turn_endpoint_forwards_pending_interaction(client):
    fake_result = PlayerTurnResult(
        status=TurnStatus.COMPLETED,
        brief="你发现了手枪。",
        narrative="桌上有一把手枪。是否拾取？",
        pending_interaction=PendingInteraction(
            kind="weapon_offer", question="是否拾取？（是/否）",
            interaction_id="weapon_offer"),
        skill_results=[], timestamp="12:00:00",
    )
    fake_game = SimpleNamespace()
    with patch("frontend.routers.game.get_game", return_value=fake_game), \
         patch("game_loop.run_turn", return_value=fake_result):
        resp = client.post("/api/game/turn", data={"user_input": "搜索桌子"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["pending_interaction"]["kind"] == "weapon_offer"
    assert data["pending_interaction"]["question"] == "是否拾取？（是/否）"
    assert "standoff_prompt" not in data
    assert "full" not in data
    assert "time_agent" not in data
```

注意：若 `get_game`/`run_turn` 的 import 路径与上不同（router 内 `from game_loop import run_turn`），patch 目标应为 `"frontend.routers.game.run_turn"` 或以实际导入方式为准——实施时先运行按报错调整 patch 目标。router 中 `run_turn` 是函数内局部 import（`from game_loop import run_turn`），因此 patch `"game_loop.run_turn"` 有效。

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_frontend_contract.py -q -p no:cacheprovider`
Expected: FAIL（`data["pending_interaction"]` KeyError / TypeError）

- [ ] **Step 3: 实现**

a) `/api/game/turn` 响应构建（game.py:336-405）改为属性访问：

```python
    narrative = turn.narrative if turn else ""
    brief = turn.brief if turn else ""

    combat_init = turn.combat_init if turn else None
    combat = turn.combat if turn else None
    combat_init_data = None
    if combat_init and combat_init.enemies and not combat:
        combat_init_data = { ... }  # 序列化逻辑不变

    skill_results = turn.skill_results if turn else []
    game_over = turn.game_over if turn else False
    from dataclasses import asdict
    ending = asdict(turn.ending) if turn and turn.ending else None
    timestamp = turn.timestamp if turn else ""
    player_snapshot = turn.player_snapshot if turn else None
    pending_data = asdict(turn.pending_interaction) if turn and turn.pending_interaction else None
    status = turn.status.value if turn else "completed"
```

返回 dict 改为：

```python
    return {
        "status": status,
        "brief": brief,
        "narrative": narrative,
        "narrative_html": narrative_html,
        "pending_interaction": pending_data,
        "combat": combat,
        "combat_init": combat_init_data,
        "skill_results": skill_results,
        "game_over": game_over,
        "ending": ending,
        "timestamp": timestamp,
        "player_snapshot": player_snapshot,
        "turn_dynamic_text": turn_dynamic_text,
    }
```

b) frozen 处理（game.py:320-334）：`turn.get("game_frozen")` → `turn.status == TurnStatus.Frozen`（import TurnStatus 后用值比较 `turn.status.value == "frozen"`），`frozen_message` 取 `turn.narrative`。

c) combat/round 中 `complete_combat_turn` 消费（game.py:873-894）：

```python
        completed = keep.complete_combat_turn(keep._last_player_input, combat_result)
        if completed and completed.brief:
            combat_completed_brief = "\n".join(
                o.message for o in completed.brief.action_outcomes)
            # narrator 调用逻辑不变，输入为 completed.brief
```

（原代码读 `completed.get("brief")`/`completed.get("enrich")` → 改为 `completed.brief`/`completed.diagnostics.enrich_raw`。）

d) 删除死代码 game.py:928-937（return 之后不可达段）。

e) `frontend/templates/game.html` JS：`handleTurnResponse` 中追加 pending_interaction 展示：

```javascript
if (data.pending_interaction && data.pending_interaction.question) {
    // 问题已在 narrative 中时跳过；否则追加到叙事区
    if (!data.narrative || !data.narrative.includes(data.pending_interaction.question)) {
        appendNarrative(`<div class="pending-question">${data.pending_interaction.question}</div>`);
    }
}
```

（具体 DOM 函数名以 game.html 现有为准——实施时按现有 `finishCombat`/叙事追加模式适配。）

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_frontend_contract.py -q -p no:cacheprovider`
Expected: 通过

- [ ] **Step 5: Commit**

```bash
git add frontend/routers/game.py frontend/templates/game.html tests/test_frontend_contract.py
git commit -m "feat: frontend router consumes PlayerTurnResult, forwards pending_interaction"
```

---

### Task 7: CLI（run_game.py）迁移

**Files:**
- Modify: `run_game.py:155-190`（主循环 turn 结果消费）

- [ ] **Step 1: 改造消费代码**

```python
        result = run_turn(game, user_input, weapon_lib, enemy_lib, injector)

        combat_init = result.combat_init
        if combat_init and combat_init.enemies:
            combat_result = _run_interactive_combat(combat_init, world, keeper)
            result.combat = combat_result
            if combat_result and combat_result.get("outcome"):
                # 叙事拼接逻辑不变，操作 result.narrative / result.brief 属性
                ...
                if combat_result.get("game_over"):
                    result.game_over = True

        ending = result.ending
        if ending:
            ...  # ending.get("narrative") → ending.narrative

        ts = result.timestamp
        _print_turn_output(result.player_snapshot, result.brief, result.narrative)

        # SUSPENDED：打印问题，继续循环（下一输入由 run_turn 内部分发）
        if result.status == TurnStatus.SUSPENDED:
            continue

        if result.game_over:
            break
```

（`from game.messages import TurnStatus` 加入 import。）

- [ ] **Step 2: 语法 + 导入验证**

Run: `python -c "import ast; ast.parse(open('run_game.py', encoding='utf-8').read())"`
Expected: 无输出（语法 OK）

- [ ] **Step 3: Commit**

```bash
git add run_game.py
git commit -m "feat: CLI consumes PlayerTurnResult attributes"
```

---

### Task 8: llm_player + harness 迁移

**Files:**
- Modify: `src/llm_player.py:252-285`
- Modify: `tests/test_harness_parallel.py:350-380`
- Modify: `tests/game_loop_harness.py:86-130`（run_turn_with_log 结果访问）

- [ ] **Step 1: llm_player.py 消费点改造**

```python
        result = run_turn(game, user_input, weapon_lib, enemy_lib, injector)
        brief = result.brief
        narrative = result.narrative
        skill_results = result.skill_results
        ending = result.ending
        combat = result.combat
        npc_events = result.diagnostics.get("npc_events", [])
        ...
        last_snapshot = result.player_snapshot
        ...
        log_entry = {
            ...
            "npcs_visible": result.diagnostics.get("npcs_visible", {"in_scene": [], "following": []}),
            "time_agent": result.diagnostics.get("time_agent"),
        }
```

（`ending` 为 EndingInfo：原 `ending.get("name")` → `ending.name`，全文 grep `ending.get` 一并改。）

- [ ] **Step 2: test_harness_parallel.py 改造**

```python
            "has_standoff": (
                turn_result.pending_interaction is not None
                and turn_result.pending_interaction.kind == "standoff"),
            "time_agent": turn_result.diagnostics.get("time_agent")
                if isinstance(turn_result, PlayerTurnResult)
                else turn_result.diagnostics.time_agent,
        standoff_pending = (
            turn_result.pending_interaction
            if turn_result.pending_interaction
               and turn_result.pending_interaction.kind == "standoff"
            else None)
        if standoff_pending and i + 1 < len(inputs):
            # 下一输入由 run_turn 内部 standoff 分发处理，无需显式 continue_standoff
```

注意：harness 原来显式调 `continue_standoff`——现在 run_turn 已内置分发，harness 只需像普通输入一样喂下一条。若 harness 直接调 `keeper.process_turn`（未经 run_turn），则仍需显式 `continue_standoff`，按实际代码适配。

- [ ] **Step 3: game_loop_harness.py 改造**

`run_turn_with_log` 中 `turn_result.get(...)` 访问改为属性/diagnostics，具体键按实际代码逐个替换（brief/narrative/full→删除 full 引用/player_snapshot/skill_results/time_agent→diagnostics）。

- [ ] **Step 4: 运行 harness 相关测试**

Run: `python -m pytest tests/test_harness_stability.py tests/test_harness_parallel.py -q -p no:cacheprovider`
Expected: 通过（stability 使用 mock 模式；parallel 若需真实 LLM 则跳过或按基线行为）

- [ ] **Step 5: Commit**

```bash
git add src/llm_player.py tests/test_harness_parallel.py tests/game_loop_harness.py
git commit -m "feat: llm_player + harness consume PlayerTurnResult"
```

---

### Task 9: 既有测试迁移（escalation_real + 全库 grep 清扫）

**Files:**
- Modify: `tests/test_escalation_real.py`（process_turn 结果访问）
- 检查: `src/audit_player_log.py`（预期无需改，验证即可）

- [ ] **Step 1: 全库旧键残留扫描**

Run:
```bash
grep -rn '\.get("standoff_prompt"\|\["standoff_prompt"\]\|"game_frozen"\|result\.get("time_agent"\|turn\.get("time_agent"' src/ tests/ frontend/ run_game.py
```
Expected: 无残留（有则逐个迁移）

- [ ] **Step 2: test_escalation_real.py 改造**

逐 case 检查 `process_turn` 返回的消费方式（`result.get("enrich")` → `result.diagnostics.enrich_raw`；`result["brief"]` → `result.brief` 等），按实际代码替换。该文件为真实 LLM 测试，改造后运行一次对比基线（A/C/D/E 4 个失败为基线遗留，不得新增失败）：

Run: `python -m pytest tests/test_escalation_real.py -q -p no:cacheprovider`
Expected: 与基线一致（1 passed, 4 failed——相同 case 相同失败原因，不新增失败）

- [ ] **Step 3: audit_player_log.py 验证**

Run: `grep -n "standoff_prompt\|time_agent\|npc_events\|game_frozen" src/audit_player_log.py`
确认其读取的是日志文件而非 turn 结果；若有个别 turn dict 访问则迁移。

- [ ] **Step 4: Commit**

```bash
git add tests/test_escalation_real.py src/audit_player_log.py
git commit -m "test: migrate escalation tests to TurnResult contract"
```

---

### Task 10: 全量回归 + 集成冒烟

- [ ] **Step 1: 全量测试**

Run: `python -m pytest tests/ -q -p no:cacheprovider --deselect tests/test_escalation_real.py`
Expected: 全部通过（test_turn_monitor 1 个基线遗留失败除外；新增契约测试全绿）

- [ ] **Step 2: llm_player mock 冒烟（3 回合）**

Run: `python src/llm_player.py --mock --turns 3`（参数以 llm_player 实际 CLI 为准，实施时 `python src/llm_player.py --help` 确认）
Expected: 端到端 3 回合无异常，输出日志含 diagnostics 数据

- [ ] **Step 3: 前端手工冒烟检查单**

- 启动 `uvicorn frontend.server:app --reload`，开始游戏
- 普通行动回合：叙事正常渲染
- 搜索发现武器：出现"是否拾取"问题，回答"是"后拾取成功（offer 应答路径）
- 模糊输入：返回澄清问题（SUSPENDED 路径）
- `/health` 等 slash 命令正常

- [ ] **Step 4: 最终 Commit + 合并**

```bash
git commit -m "test: TurnResult contract full regression pass" --allow-empty
# 按 finishing-a-development-branch 流程合并回 main 并清理 worktree
```

---

## Self-Review 记录

**Spec 覆盖**：
- §1 内部契约 → Task 1+3 ✓
- §2 外层契约 → Task 1+5 ✓
- §3 enriched_summary → Task 2 ✓
- §4 生产端 5 处 → Task 3/4/5 ✓
- §5 消费端 9 处 → Task 6/7/8/9 ✓（audit_player_log 为验证项）
- §6 错误处理 → Task 1（不变量）/5（FROZEN 映射）/6（前端 frozen）✓
- §7 测试策略 → Task 1/3/4/5 契约单测 + Task 10 回归/冒烟 ✓
- standoff_pending 播种（spec 修正）→ Task 3 Step 3e + Task 4 测试 ✓
- run_turn 应答分发（spec §4）→ Task 5 Step 3a ✓

**类型一致性**：TurnStatus/PendingInteraction/EndingInfo/TurnDiagnostics/TurnResult/PlayerTurnResult 在 Task 1 定义，后续 Task 引用一致；`enriched_summary` 在 Task 2（Curator/NarratorBrief）与 Task 3/4/5（keeper/run_turn）间一致；`complete_combat_turn` 返回 `TurnResult | None`，Task 4/6 消费一致。
