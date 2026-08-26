# Step1 快修批 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收口 Step1 快修批 4 项:F11 库 schema 文档、F4 timed/effect 边界测试、F9 SAN 遭遇全局去重、F16 锁-钥匙链路测试锁定。

**Architecture:** 全部为小步快修,不动数据模型骨架。F9 在 ScenarioWorld 加一个入档的 `san_seen_sources: set[str]`;F16 纯测试(infra 已支持,不加机制);F11/F4 零产品代码。

**Tech Stack:** pytest(TDD)、现有 e2e helpers(`tests/e2e/helpers.py`)。

**约定:** 每 Task 收口跑 `pytest tests/ -q`;本批不改 prompt/parse/narrator,不跑 real_llm;收口同步 MAINTENANCE.md / docs/ISSUES.md;不提交无关脏文件(autosave、supplements、imp.py、test.py、.claude/)。

---

### Task 1: F11 库 schema 作者参考文档

**Files:**
- Create: `docs/library-schema.md`
- 参考(只读): `src/library/enemies.py:59-75`、`src/library/bosses.py:9-25`、`src/library/weapons.py:34-48`、`src/library/items.py:12-29`、`src/library/spells.py:19-36`、`src/game/combat.py:121-144`(parse_san_loss)、`src/game/judge.py:193-249`(effect 原子)、`data/library/core/items.json`

- [ ] **Step 1: 写 docs/library-schema.md**

内容骨架(各表字段名以 loader dataclass 为准,示例从 data/library/core/*.json 摘真实条目):

```markdown
# 库 Schema 作者参考

> 面向模组/素材作者:五库全字段 + 写法约定。字段语义以 src/library/*.py 的 dataclass 为唯一事实源,本文档是作者视角索引。

## 1. 放置约定
- 核心库: data/library/core/{enemies,bosses,weapons,items,spells}.json(随仓库)
- 扩展库: 模组扩展经 load_extension(path) 加载,与核心同 schema;同名条目扩展覆盖核心
- 顶层结构: {"<复数名>": [条目, ...]}(如 {"items": [...]})

## 2. enemies(敌人)
| 字段 | 类型 | 说明 |
|---|---|---|
| name | str | 主键,模组 enemy_ref 引用此名 |
| type | str | 类型标签 |
| attributes | dict | STR/CON/DEX/POW 等 |
| armor | str | 护甲描述(只作用敌方) |
| attacks | list | [{name, skill_name, skill_value, damage, weight, notes}];damage 可为 "1D6" 或 {dice_n,dice_d,bonus,use_db};skill_value>0 时命中判定用库值,否则 (DEX+POW)//2 |
| special_abilities | list | [{name, desc}] 目前仅进 judgment prompt,无数值执行(F12) |
| san_loss | str | 多情境格式,见 §7 |
| combat_behavior | str | 支持 [flag] 前缀,见 §8 |
| description / flags / multi_attack / damage_multipliers / dodge_bonus / special_rules / phases / status | | flags 进 runtime flag 集;multi_attack 每回合攻击次数;damage_multipliers 如 {"火": 2.0};dodge_bonus 加在命中技能值上;status 默认 hostile |

## 3. bosses
在 enemies 字段之上多 boss_mechanics(str,半接:prompt 可见、数值不执行)。其余同 enemies。

## 4. weapons
| name | str | 主键 |
| skill_name | str | 技能名,归一映射见 skill_config legacy_map |
| damage | dict/str | 同敌人 damage |
| range / shots / malfunction | | 目前纯展示/未接线(F13-①②⑤ 长期 TODO) |
| era / rarity / damage_type / armor_piercing / attack_bonus / multi_attack / special_rules / description | | armor_piercing 已接线;attack_bonus 已接线 |

## 5. items
| id | str | 主键 |
| name / aliases | | 匹配用 |
| category | str | consumable/tool/document/clothing/key/misc |
| impact | str | L0/L1/L2 默认档 |
| use_semantic | str | consume/equip/read/tool/none |
| stackable | bool | |
| check | dict | {skill, type} 使用检定(如开锁工具→锁匠) |
| on_use | list[str] | @markup 序列 |
| on_success/on_failure/on_hard/on_extreme | str | 分级结果文本 |
| refund_on_fail | bool | 失败是否返还 |
| constraints / effect | | effect 原子数组,见 §6 |

## 6. spells
id/name/aliases/category(combat|exploration)/impact/cost{mp,san}/on_use/on_success 分级/refund_on_fail/constraints/effect/weight。

## 7. san_loss 多情境格式
"成功公式/失败公式 (情境), ..." 逗号分组,如 `"0/1D4 (目睹), 1/1D6 (被攻击)"`。
- 目睹组(情境注释不含"攻击"):开战时每个 enemy_ref 全局首次目睹 check 一次(F9 去重后跨场不重复)
- 被攻击组(注释含"攻击"):敌方命中时 check,同场同 enemy_ref 只首次命中触发
- 解析: src/game/combat.py parse_san_loss;空/坏组跳过

## 8. combat_behavior [flag] 前缀
combat_behavior 文本支持 [flag] 前缀被运行时剥离并转入行为 flag(加载期处理,src/library/enemies.py from_dict);剩余文本进 judgment prompt。

## 9. effect 原子(8 类)
items/spells 的 effect 数组,原子 type ∈ {heal, mp_change, markup, timed, damage, buff, control, narrative}。
- 探索侧(judge._execute_effect_atoms):heal/mp_change/timed/markup/narrative 生效;damage 跳过+日志;buff/control 降级为文本
- 战斗侧:buff(减伤 reduce+rounds)/control(controlled_rounds)生效
- 未知 type:降级进结果文本+告警,不报错

## 10. 配方:锁-钥匙
- 锁 = interaction entity:{type: "锁匠", difficulty, graded_result};检定成功后运行时 mark_completed(锁id)
- 门 = 出口 requirement 写锁实体 id(裸 ID 硬条件,如 "IT_LOCK"),或 requirement 写 `item:具体钥匙名` 做钥匙硬门
- 物品"开锁工具"(LOCKPICKS)的 check 指向锁匠技能,可与锁实体配合叙事
- 反模式:requirement 写泛名 `item:钥匙` → 任意同名物品都能过
```

- [ ] **Step 2: 校验文档与代码一致**

逐个字段对照 src/library/*.py dataclass 与 data/library/core/*.json 实例,确认无臆造字段、无遗漏已接线字段。

- [ ] **Step 3: Commit**

```bash
git add docs/library-schema.md
git commit -m "docs: library schema author reference (F11)"
```

---

### Task 2: F4 timed/effect 边界测试补齐

**Files:**
- Create: `tests/test_effect_edge_cases.py`
- 被测: `src/game/judge.py:193`(`_execute_effect_atoms`)、`src/scenario_core.py:1665-1668`(timed 渲染兜底)

- [ ] **Step 1: 写失败测试**

```python
"""F4: effect 原子防御分支断言(探索侧降级/跳过/未知 type/timed 渲染兜底)。零 API。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'e2e'))

import logging
from helpers import make_scene, make_world


def _player(world):
    from investigator import Investigator
    inv = Investigator(name="测试员", age=25, gender="男")
    world.set_player(inv)
    return inv


def _judge(world):
    from game.judge import Judge
    return Judge(world)


class TestExploreSideDegrade:
    def test_damage_atom_skipped_in_exploration(self, caplog):
        """damage 原子探索侧跳过+日志,不改 HP。"""
        world = make_world({"room_a": make_scene()}, "room_a")
        inv = _player(world)
        hp_before = inv.derived.HP
        with caplog.at_level(logging.WARNING, logger="game.judge"):
            msgs = _judge(world)._execute_effect_atoms(
                [{"type": "damage", "delta": 5}], inv)
        assert inv.derived.HP == hp_before
        assert msgs == []
        assert any("damage" in r.message for r in caplog.records)

    def test_buff_atom_degrades_to_text_in_exploration(self):
        """buff 原子探索侧降级为文本行,不进 temporary_effects。"""
        world = make_world({"room_a": make_scene()}, "room_a")
        inv = _player(world)
        msgs = _judge(world)._execute_effect_atoms(
            [{"type": "buff", "description": "力量涌现"}], inv)
        assert msgs == ["力量涌现"]

    def test_unknown_type_degrades_into_result(self, caplog):
        """未知 type 降级进结果文本 + 告警,不抛异常。"""
        world = make_world({"room_a": make_scene()}, "room_a")
        inv = _player(world)
        with caplog.at_level(logging.WARNING, logger="game.judge"):
            msgs = _judge(world)._execute_effect_atoms(
                [{"type": "teleport", "text": "瞬移"}], inv)
        assert any("teleport" in r.message for r in caplog.records)


class TestTimedRenderFallback:
    def test_render_missing_expire_at_and_description(self):
        """timed_effects 缺 expire_at 按 0 兜底;缺 description 的条目不渲染。"""
        world = make_world({"room_a": make_scene()}, "room_a")
        inv = _player(world)
        inv.timed_effects = [
            {"id": "A", "description": "亢奋"},               # 缺 expire_at
            {"id": "B", "expire_at": world.clock.game_time + 60},  # 缺 description
        ]
        text = world.chronicle.render_for_author(world)
        assert "亢奋" in text and "剩0分钟" in text
        assert "剩60分钟" not in text, "无 description 条目不得渲染"
```

注:`render_for_author` 是 WorldChronicle 的方法(scenario_core.py:1654),经 `world.chronicle` 访问;timed 渲染行在其内部(scenario_core.py:1665-1668)。

- [ ] **Step 2: 跑测试确认通过(防御分支已存在,预期直接绿)**

Run: `pytest tests/test_effect_edge_cases.py -v`
Expected: 4 passed。若某条红,说明该防御分支已漂移,按红的断言修产品代码。

- [ ] **Step 3: Commit**

```bash
git add tests/test_effect_edge_cases.py
git commit -m "test: F4 effect-atom edge branch assertions"
```

---

### Task 3: F9 SAN 遭遇全局去重

**Files:**
- Modify: `src/scenario_core.py`(`ScenarioWorld.__init__` ~663 本体状态区、`to_dict` ~1117、`from_dict` ~1143)
- Modify: `src/game/combat.py`(`CombatState` 字段区 ~201、`_init_combat` 目睹循环 787-803、被攻击 check ~1227)
- Test: `tests/test_combat_smoke.py`(单元)与 `tests/e2e/test_deterministic.py`(存读档回环)

**设计:** 目睹组(注释不含"攻击")→ `world.san_seen_sources` 全局去重(入档);被攻击组 → `state.san_attacked_refs` 场内去重(修 multi_attack 每命中叠加)。

- [ ] **Step 1: 写失败测试(tests/test_combat_smoke.py 追加)**

骰子确定性:`monkeypatch combat_mod.random.randint` 钉死(TestEnemyAttackSkillValue 同款手法);san_loss 用定值公式 `"0/2 (目睹), 1/3 (被攻击)"` 避开 roll_formula 随机。world 用最小 stub(combat 只 getattr `san_seen_sources`),序列化回环由 Step 5 的 e2e 覆盖。

```python
class TestSanWitnessDedup:  # F9: 目睹全局去重 + 被攻击场内去重
    """san_seen_sources 入档全局去重;被攻击组同场同 ref 只首命中 check。"""

    class _SeenWorld:
        """最小 world stub:combat 仅读 san_seen_sources。"""
        def __init__(self, seen):
            self.san_seen_sources = set(seen)

    def _witness_init(self, monkeypatch, world, roll=99):
        import game.combat as combat_mod
        from game.messages import CombatInit
        monkeypatch.setattr(combat_mod.random, "randint", lambda a, b: roll)
        enemy = _TestEnemy("深潜者", hp=10, armor="0", instance_id="E_DS_1",
                           san_loss="0/2 (目睹), 1/3 (被攻击)")
        player = _make_investigator(san=60)
        cs = CombatSystem(world=world)
        state = cs._init_combat(CombatInit(
            enemies=[enemy], player=player,
            scene="测试房间", initiative_context=""))
        return state

    def test_witness_first_time_checks_and_records(self, monkeypatch):
        """首次目睹:check 发生(roll=99>60 失败掉 2),ref 写入 seen 集。"""
        world = self._SeenWorld(set())
        state = self._witness_init(monkeypatch, world)
        assert any("深潜者" in line for line in state.san_log), "首次目睹必须记 san_log"
        assert state.player_san == 58, f"失败掉 2,实际 {state.player_san}"
        assert "深潜者" in world.san_seen_sources, "目睹后必须写入全局 seen"

    def test_witness_skipped_when_ref_seen_globally(self, monkeypatch):
        """enemy_ref 已在 san_seen_sources → 不再 check,SAN 不变。"""
        world = self._SeenWorld({"深潜者"})
        state = self._witness_init(monkeypatch, world)
        assert state.san_log == [], f"已目睹不得再 check,实际 {state.san_log}"
        assert state.player_san == 60

    def test_witness_without_world_still_checks_per_combat(self, monkeypatch):
        """world=None(旧调用方)→ 退化为场内去重,不炸。"""
        state = self._witness_init(monkeypatch, None)
        assert any("深潜者" in line for line in state.san_log)

    def test_attacked_group_deduped_per_combat(self, monkeypatch):
        """同场同 ref 多次命中,'被攻击'组只首命中 check 一次。"""
        import game.combat as combat_mod
        monkeypatch.setattr(combat_mod.random, "randint", lambda a, b: 50)
        enemy = _TestEnemy("深潜者", hp=20, armor="0", instance_id="E_DS_2",
                           san_loss="0/2 (目睹), 1/3 (被攻击)",
                           attacks=[{"name": "爪击", "skill_name": "格斗",
                                     "skill_value": 99, "damage": "1D3"}])
        state = CombatState(enemies=[enemy])
        state.player_hp = 20
        state.player_san = 60
        cs = CombatSystem()
        player = _make_investigator(san=60)
        a1 = cs._resolve_enemy_action(state, enemy, player)
        a2 = cs._resolve_enemy_action(state, enemy, player)
        assert "恐惧侵蚀" in a1.narrative, "首次命中必须触发被攻击 check"
        assert "恐惧侵蚀" not in a2.narrative, "同场同 ref 第二次命中不得再 check"
        assert state.player_san == 59, \
            f"被攻击组成功掉 1 且只掉一次,实际 {state.player_san}"
```

- [ ] **Step 2: 跑测试确认红**

Run: `pytest tests/test_combat_smoke.py::TestSanWitnessDedup -v`
Expected: FAIL(`_SeenWorld` 的 seen 被忽略 / 目睹未去重 / `san_attacked_refs` 不存在)

- [ ] **Step 3: 实现**

`src/scenario_core.py`:
```python
# __init__ 本体状态区(self._mp_regen_acc 附近)追加:
self.san_seen_sources: set[str] = set()   # F9: 目睹 SAN 全局去重(入档)

# to_dict return dict 追加:
"san_seen_sources": sorted(self.san_seen_sources),

# from_dict 恢复 clock 之前追加:
world.san_seen_sources = set(data.get("san_seen_sources", []))
```

`src/game/combat.py`:
```python
# CombatState 字段区(san_log 之后)追加:
san_attacked_refs: set = field(default_factory=set)  # F9: 被攻击组场内去重

# _init_combat 目睹循环(787-803)改为:
seen_refs = set()
global_seen = getattr(self.world, "san_seen_sources", None) if self.world is not None else None
for e in expanded_enemies:
    ref = getattr(e, 'enemy_ref', '') or e.instance_id
    if ref in seen_refs or (global_seen is not None and ref in global_seen):
        continue
    seen_refs.add(ref)
    groups = parse_san_loss(getattr(e, 'san_loss', '') or '')
    witness = next((g for g in groups if "攻击" not in g[2]),
                   groups[0] if groups else None)
    if not witness:
        continue
    loss, text = _san_check_and_lose(state.player_san, witness[0], witness[1])
    state.player_san = max(0, state.player_san - loss)
    state.san_log.append(f"你遭遇{ref}：{text}。")
    if global_seen is not None:
        global_seen.add(ref)

# 被攻击 check(~1227)改为:
groups = parse_san_loss(getattr(enemy, "san_loss", "") or "")
attacked = next((g for g in groups if "攻击" in g[2]), None)
attacked_ref = getattr(enemy, 'enemy_ref', '') or getattr(enemy, 'instance_id', '')
if attacked and attacked_ref not in state.san_attacked_refs:
    state.san_attacked_refs.add(attacked_ref)
    loss, text = _san_check_and_lose(state.player_san, attacked[0], attacked[1])
    state.player_san = max(0, state.player_san - loss)
    action.narrative += f" 恐惧侵蚀：{text}。"
```

同时更新 787 行注释(去掉"跨场不去重--现状记录"字样,改为 F9 已收口说明)。

- [ ] **Step 4: 跑测试确认绿**

Run: `pytest tests/test_combat_smoke.py -v`
Expected: 全绿(含 TestSanWitnessDedup 3 条)

- [ ] **Step 5: 存读档回环测试(tests/e2e/test_deterministic.py 追加)**

```python
class TestSanSeenPersistence:  # F9 入档
    def test_san_seen_sources_roundtrip(self):
        """san_seen_sources 经 to_dict/from_dict 回环保持。"""
        from scenario_core import DirectedGraph, ScenarioWorld
        graph = DirectedGraph(scenes={"room_a": make_scene()}, events=[])
        world = ScenarioWorld(graph, start_node="room_a")
        world.san_seen_sources = {"深潜者", "食尸鬼"}
        data = world.to_dict()
        graph2 = DirectedGraph(scenes={"room_a": make_scene()}, events=[])
        world2 = ScenarioWorld.from_dict(data, graph2)
        assert world2.san_seen_sources == {"深潜者", "食尸鬼"}

    def test_san_seen_sources_default_empty_on_old_save(self):
        """旧档无该字段 → 默认空集,不炸。"""
        from scenario_core import DirectedGraph, ScenarioWorld
        graph = DirectedGraph(scenes={"room_a": make_scene()}, events=[])
        world = ScenarioWorld.from_dict({"current_location": "room_a"}, graph)
        assert world.san_seen_sources == set()
```

- [ ] **Step 6: 跑默认套件**

Run: `pytest tests/ -q`
Expected: 全绿(328+N passed)

- [ ] **Step 7: Commit**

```bash
git add src/scenario_core.py src/game/combat.py tests/test_combat_smoke.py tests/e2e/test_deterministic.py
git commit -m "feat: F9 global SAN witness dedup via persisted san_seen_sources"
```

---

### Task 4: F16 锁-钥匙链路测试锁定

**Files:**
- Test: `tests/e2e/test_deterministic.py`(追加,模式参照 `TestFailureEscalation` 423-461 与 `TestMoveSuccess` 210-231)
- 不加机制、不动真实模组。infra 依据:出口硬条件 `parse_hard_requirement`(scenario_core.py:1030)查 `runtime_state[锁id].completed`;锁 = interaction entity,`type: "锁匠"`(judge.py:344),检定成功 `mark_completed`(judge.py:256)。

- [ ] **Step 1: 写测试并直接跑通(infra 已支持,预期绿;若红则记录断链点并最小修)**

```python
class TestLockKeyFlow:  # F16: 锁-钥匙 infra 链路锁定(不加机制)
    def _lock_world(self):
        lock = {
            "id": "IT_LOCK", "entity_type": "interaction",
            "name": "撬锁", "scene": "room_a",
            "type": "锁匠", "requirement": "", "trigger": "撬锁",
            "result": "##GRADED##",
            "graded_result": {"on_failure": "锁纹丝不动。",
                              "on_regular": "锁开了。",
                              "on_hard": "锁开了。", "on_extreme": "锁开了。"},
            "side_effects": [], "difficulty": "regular", "time_condition": [],
        }
        world = make_world({
            "room_a": make_scene(
                interactions=[lock],
                exits=[{"target": "room_b", "method": "步行",
                        "requirement": "IT_LOCK"}]),
            "room_b": make_scene(),
        }, "room_a")
        return world

    def test_door_blocked_before_unlock(self, monkeypatch):
        """开锁前:出口硬条件挡住移动。"""
        world = self._lock_world()
        _player(world)
        blocked = world.move("room_b")
        assert not blocked.success, "锁未完成前移动必须被挡"
        assert world.current_location == "room_a"

    def test_lockpick_success_unlocks_door(self, monkeypatch):
        """撬锁检定成功 → mark_completed → 同一出口即时通过。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world = self._lock_world()
        inv = _player(world)
        inv.check_skill = lambda skill, diff: (True, f"{skill}检定：D100=10/50", "regular")
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "interaction", "id": "IT_LOCK"}]])
        game = make_game(keeper)

        r = run_turn(game, "撬锁")
        assert_player_turn_contract(r)
        assert world.is_entity_completed("IT_LOCK"), "检定成功必须翻转锁的 completed"

        ok = world.move("room_b")
        assert ok.success and world.current_location == "room_b", \
            "锁已开,移动必须即时通过"

    def test_lockpick_failure_keeps_door_shut(self, monkeypatch):
        """撬锁失败 → 门保持关闭(与 TestFailureEscalation 难度升级不冲突)。"""
        from game_loop import run_turn
        from game.agents.keeper import Keeper

        world = self._lock_world()
        inv = _player(world)
        inv.check_skill = lambda skill, diff: (False, f"{skill}检定：D100=98/10", "failure")
        keeper = Keeper(world)
        stub_keeper_llm(keeper, monkeypatch,
                        parse_results=[[{"type": "interaction", "id": "IT_LOCK"}]])
        game = make_game(keeper)

        r = run_turn(game, "撬锁")
        assert_player_turn_contract(r)
        assert not world.is_entity_completed("IT_LOCK")
        assert not world.move("room_b").success
```

- [ ] **Step 2: 跑测试**

Run: `pytest tests/e2e/test_deterministic.py::TestLockKeyFlow -v`
Expected: 3 passed。若红,断链点最可能在:① interaction 成功路径未走 mark_completed;② 出口 requirement 的裸 ID 未被 `_extract_entity_id` 识别。按红点最小修产品代码并在 ISSUES 记录。

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_deterministic.py
git commit -m "test: F16 lock-key infra chain locked by e2e tests"
```

---

### Task 5: 收口(ISSUES / MAINTENANCE / 全量回归)

- [ ] **Step 1: 更新 docs/ISSUES.md**

- F11、F4、F9、F16 从活跃区移入 §5 已收口(各一行,含 commit 号)
- F9 行注明:目睹组全局去重入档;被攻击组场内去重解 multi_attack 叠加;F5/F8 联动仍跟踪
- F16 行注明:降级为测试锁定+文档配方,未加机制;若 Step2/3 真实模组需要更强锁语义再开新项

- [ ] **Step 2: 更新 MAINTENANCE.md**

changelog 记 4 项;scenario_core(san_seen_sources 字段/序列化行号)、combat(目睹循环/被攻击 check 行号)函数记录同步。

- [ ] **Step 3: 全量默认套件**

Run: `pytest tests/ -q`
Expected: 全绿。

- [ ] **Step 4: Commit**

```bash
git add docs/ISSUES.md MAINTENANCE.md
git commit -m "docs: close step1 quick-fix batch (F11/F4/F9/F16)"
```
