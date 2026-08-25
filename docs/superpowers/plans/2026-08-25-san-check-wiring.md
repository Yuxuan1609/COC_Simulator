# 遭遇 SAN check 通路接线 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 接通断裂的 san_loss 数据链:战斗开始(目睹)+被敌方攻击命中(被攻击)两个时点执行 COC 7th 遭遇理智检定并扣 SAN(ISSUES P0,盘点 2026-08-25)。

**Architecture:** 纯函数(parse_san_loss 多情境解析 + _san_check_and_lose 检定掷骰)放 combat.py 模块级;两处接线:_init_combat(目睹,场内按 enemy_ref 去重,结果进 state.san_log 首轮渲染)与 _resolve_enemy_action 命中分支(被攻击,追加 action.narrative);战斗结束写回链路已就位(game_loop.py:793/run_game.py:534 player_san -> derived.SAN)。

**Tech Stack:** 纯 Python 标准库,pytest;utils.roll_formula 只吃骰式,纯数字公式用本地 helper 兼容。

**约定(执行者必读):**
- 测试命令 `python -m pytest <路径> -q`(系统 Python);全量基线 **294 passed / 20 deselected**(LLM flaky 复跑即过)
- **禁止 `git add -A` / `git add .`,禁止 `git stash`**(工作区有用户保留变更);git add 只写明确文件名
- 中文 commit,main 直提;MAINTENANCE.md 同 commit 更新(长行中文编辑用 Python 脚本+锚点)
- 行号以 2026-08-26 代码为准,编辑以内容锚点优先

## 设计决策(已拍板)

- **触发**:①战斗开始时对每个参战敌人(场内按 enemy_ref 去重,群组多实例只一次)做"目睹"check;②敌方攻击命中玩家时,若该敌人 san_loss 含"被攻击"组,额外 check 一次
- **去重**:跨战斗**不去重**(用户拍板先接链路;COC 全局首次目睹语义的优化在 ISSUES F9 跟踪)
- **检定语义**:COC 7th SAN check = D100 <= 当前 SAN 值为成功;成功掉成功损失,失败掉失败损失;无 tier/fumble(SAN check 无极难档)
- **库数据格式**:`"0/1D6"` 单组;`"0/1D4 (目睹), 1/1D6 (被攻击)"` 多组带自由文本注释。目睹组=注释不含"攻击"的第一组;被攻击组=注释含"攻击"的第一组
- **公式**:骰式("1D6")走 utils.roll_formula;纯数字("3"/"0")直接 int(roll_formula 不匹配纯数字会返 0,需兼容)
- **疯狂联动**:单次损失>=5 仅 log 提示(临时疯狂条件;F5 疯狂体系未实现),不做疯狂状态
- **SAN 下限 0**;san_log 渲染进首轮结果后清空(一次性)

---

### Task 1: 解析+检定纯函数

**Files:**
- Modify: `src/game/combat.py`(模块级函数,放 _apply_armor 附近 @96)
- Test: `tests/test_combat_smoke.py`(追加)

- [ ] **Step 1: 写失败测试**(tests/test_combat_smoke.py 末尾追加)

```python
class TestSanCheckFunctions:
    """遭遇 SAN check 通路(ISSUES P0):解析+检定纯函数。"""

    def test_parse_san_loss_groups(self):
        from game.combat import parse_san_loss
        # 单组无注释
        assert parse_san_loss("0/1D6") == [("0", "1D6", "")]
        # 多组带情境注释
        got = parse_san_loss("0/1D4 (目睹), 1/1D6 (被攻击)")
        assert got == [("0", "1D4", "目睹"), ("1", "1D6", "被攻击")]
        # 注释自由文本
        assert parse_san_loss("0/1D2 (目睹他们空洞的眼神)") == [("0", "1D2", "目睹他们空洞的眼神")]
        # 空/坏格式
        assert parse_san_loss("") == []
        assert parse_san_loss(",,") == []
        assert parse_san_loss("乱码") == []

    def test_san_check_and_lose_success_and_fail(self, monkeypatch):
        from game import combat
        # SAN=50;强制 roll=30(<=50 成功):掉成功组(固定 2)
        monkeypatch.setattr(combat.random, "randint", lambda a, b: 30 if b == 100 else 1)
        loss, text = combat._san_check_and_lose(50, "2", "1D6")
        assert loss == 2 and "成功" in text and "2" in text
        # 强制 roll=80(>50 失败):掉失败组 1D6(randint 强制 1 点->骰面 d=6 取 1)
        loss, text = combat._san_check_and_lose(50, "2", "1D6")
        assert loss == 1 and "失败" in text
        # SAN=0:roll>=1 永失败
        loss, _ = combat._san_check_and_lose(0, "2", "3")
        assert loss == 3
        # 骰式公式
        monkeypatch.setattr(combat.random, "randint", lambda a, b: 80 if b == 100 else 2)
        loss, _ = combat._san_check_and_lose(50, "0", "2D6")
        assert loss == 4   # 2+2
```

注:monkeypatch `combat.random.randint` 时,`roll_formula` 在 utils 模块内用的是 `utils.random`,**不是** combat.random--需看 roll_formula 实现:它在 src/utils.py 用 random.randint。combat.py 顶部 `import random`?确认后:若 roll_formula 用 utils 的 random,测试应 patch `utils.random.randint`(或分别 patch 两处)。实现时以实际 import 为准调整 patch 目标,测试意图不变(成功/失败/骰式/固定值/SAN=0 五分支)。

- [ ] **Step 2: 确认失败**

Run: `python -m pytest tests/test_combat_smoke.py::TestSanCheckFunctions -q`
Expected: FAIL(parse_san_loss/_san_check_and_lose 不存在)

- [ ] **Step 3: 实现**(src/game/combat.py,_apply_armor 函数后追加)

```python
def _san_loss_roll(formula: str) -> int:
    """SAN 损失公式掷骰:纯数字直接取值,骰式走 roll_formula。"""
    s = str(formula).strip()
    if re.fullmatch(r"\d+", s):
        return int(s)
    return roll_formula(s)


def parse_san_loss(san_loss: str) -> list:
    """解析库 san_loss 字段 "0/1D4 (目睹), 1/1D6 (被攻击)"
    -> [(成功公式, 失败公式, 情境注释), ...]。空/坏组跳过。"""
    groups = []
    for part in (san_loss or "").split(","):
        part = part.strip()
        if not part:
            continue
        note = ""
        if "(" in part and part.endswith(")"):
            i = part.index("(")
            note = part[i + 1:-1]
            part = part[:i].strip()
        m = re.match(r"^(\S+?)\s*/\s*(\S+)$", part)
        if not m:
            continue
        groups.append((m.group(1), m.group(2), note))
    return groups


def _san_check_and_lose(san: int, success_formula: str, fail_formula: str) -> tuple:
    """COC 7th 遭遇理智检定:D100 <= 当前 SAN 为成功;成功掉 success、失败掉 fail。
    返回 (损失点数, 叙事文本)。单次损失>=5 记 log(临时疯狂条件,F5 未实现)。"""
    import logging
    roll = random.randint(1, 100)
    ok = roll <= san
    loss = max(0, _san_loss_roll(success_formula if ok else fail_formula))
    if loss >= 5:
        logging.getLogger("combat").info(
            "[san] 单次损失 %d >= 5(临时疯狂条件;疯狂体系 ISSUES F5 未实现)", loss)
    tier_txt = "成功" if ok else "失败"
    text = (f"理智检定{tier_txt}(D100={roll}/{san})"
            + (f"，失去 {loss} 点 SAN" if loss else "，未失去 SAN"))
    return loss, text
```

import 说明:combat.py 顶部应已有 `import random` 与 `from utils import roll_formula`(T9 统一过 roll_formula;若 roll_formula 是局部 import 则函数内 import);`re` 已有(_apply_armor 用)。以实际头部为准,缺则补。

- [ ] **Step 4: 确认通过**

Run: `python -m pytest tests/test_combat_smoke.py::TestSanCheckFunctions -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/game/combat.py tests/test_combat_smoke.py MAINTENANCE.md
git commit -m "feat: san_loss 解析+遭遇理智检定纯函数(P0 断链接线 1/2)"
```

### Task 2: 两处接线 + 首轮渲染 + e2e

**Files:**
- Modify: `src/game/combat.py`(CombatState 加 san_log 字段 @131 区域;_init_combat @670;_resolve_enemy_action @1073 命中分支;_build_single_round_result @535)
- Test: `tests/test_combat_smoke.py`(追加)、`tests/e2e/test_deterministic.py`(追加 1 场景)

- [ ] **Step 1: 写失败测试**

tests/test_combat_smoke.py 追加(参照该文件现有战斗构造 helper;敌人对象可用 SimpleNamespace/enemy_manager 的 EnemyInstance,以现有测试模式为准):

```python
class TestSanCheckWiring:
    """遭遇 SAN check 接线:目睹(战斗开始)+被击中。"""

    def _enemy(self, san_loss="0/1D6"):
        # 按现有测试的敌人构造方式(SimpleNamespace 带 instance_id/enemy_ref/
        # attributes/hp/quantity/san_loss 等必要字段);找不到现成模式则用
        # game.enemy_manager.EnemyInstance(...)
        ...

    def test_witness_check_at_combat_start(self, monkeypatch):
        """开战目睹:每个 enemy_ref 一次(群组多实例去重),SAN 扣减进 state。"""
        from game import combat
        monkeypatch.setattr(combat.random, "randint", lambda a, b: 90 if b == 100 else 1)
        # roll=90>SAN -> 失败组 1D6 强制 1 点
        engine = ...  # 现有测试的 CombatSystem 构造方式
        state = engine._init_combat(带 1 个 san_loss="0/1D6" 敌人的 CombatInit)
        assert state.player_san == 初始SAN - 1
        assert any("理智检定失败" in s for s in state.san_log)

    def test_witness_check_group_dedup_in_combat(self, monkeypatch):
        """同场同 enemy_ref 多实例(quantity 3)只 check 一次。"""
        ...  # quantity=3 的敌人,断言 san_log 只 1 条该 ref 记录

    def test_witness_check_empty_san_loss(self):
        """san_loss 空的敌人不做 check(san_log 无记录,SAN 不变)。"""
        ...

    def test_attacked_check_on_hit(self, monkeypatch):
        """敌方命中且 san_loss 含'被攻击'组:额外 check,narrative 含理智检定。"""
        # 构造 state 走 _resolve_enemy_action(参照现有 _resolve_enemy_action 测试),
        # 敌 san_loss="1/1D6 (被攻击)";强制命中+强制失败骰
        ...断言 action.narrative 含 "理智检定" 且 state.player_san 相应扣减

    def test_attacked_check_no_group(self):
        """san_loss 无'被攻击'组:命中不追加 check。"""
        ...
```

(具体构造方式以 test_combat_smoke.py 现有测试为准--该文件 33+ 测试已有 CombatSystem/_init_combat/CombatInit 的成熟构造模式,照抄改参;上面是断言意图清单。)

tests/e2e/test_deterministic.py 追加:

```python
class TestSanCheckE2E:
    def test_combat_with_san_loss_enemy(self, monkeypatch):
        """e2e:带 san_loss 敌人开战,SAN check 发生且叙事可见,战后 SAN 写回。"""
        # make_world + stub_keeper_llm 走"攻击敌人"触发战斗(参照现有战斗 e2e 场景,
        # 如 TestTimedAndCombatEffectsE2E 的石肤减伤场景构造);
        # 敌人库注入 san_loss="0/1D6" 的敌人;断言:
        # 1) 战斗首轮结果文本含 "理智检定"
        # 2) 战后 player.derived.SAN <= 战前 SAN(宽断言,成功组 0 也可能不掉)
        ...
```

- [ ] **Step 2: 确认失败**

Run: `python -m pytest tests/test_combat_smoke.py::TestSanCheckWiring tests/e2e/test_deterministic.py::TestSanCheckE2E -q`
Expected: FAIL(san_log 属性不存在/接线缺失)

- [ ] **Step 3: 实现**

(a) CombatState dataclass 加字段(temporary_effects 行后):
```python
    san_log: list[str] = field(default_factory=list)   # 开局目睹 SAN check 叙事行(2026-08-26 遭遇通路)
```

(b) `_init_combat`:CombatState 构造+先攻排序完成后、返回前(或 first_actor 判定后)追加:
```python
        # 遭遇 SAN check(目睹):开战对每个 enemy_ref 一次(群组多实例去重;
        # 跨场不去重--现状记录,全局去重见 ISSUES F9)
        seen_refs = set()
        for e in expanded_enemies:
            ref = getattr(e, "enemy_ref", "") or e.instance_id
            if ref in seen_refs:
                continue
            seen_refs.add(ref)
            groups = parse_san_loss(getattr(e, "san_loss", "") or "")
            witness = next((g for g in groups if "攻击" not in g[2]),
                           groups[0] if groups else None)
            if not witness:
                continue
            loss, text = _san_check_and_lose(
                state.player_san, witness[0], witness[1])
            state.player_san = max(0, state.player_san - loss)
            state.san_log.append(f"你遭遇{getattr(e, 'enemy_ref', e.instance_id)}：{text}。")
```

(c) `_build_single_round_result`:lines 构建后、return 前追加(一次性渲染):
```python
        if getattr(state, "san_log", None):
            lines = list(state.san_log) + lines
            state.san_log = []
```
(以该函数实际 lines 变量名/结构为准,意图:开局目睹行插在轮叙事最前,渲染一次即清。)

(d) `_resolve_enemy_action` 命中分支(damage 结算+state.player_hp 更新后):
```python
            # 被攻击情境 SAN check(库 san_loss 含"被攻击"组时;2026-08-26 遭遇通路)
            groups = parse_san_loss(getattr(enemy, "san_loss", "") or "")
            attacked = next((g for g in groups if "攻击" in g[2]), None)
            if attacked:
                loss, text = _san_check_and_lose(
                    state.player_san, attacked[0], attacked[1])
                state.player_san = max(0, state.player_san - loss)
                action.narrative += f" 恐惧侵蚀：{text}。"
```

- [ ] **Step 4: 确认通过**

Run: `python -m pytest tests/test_combat_smoke.py tests/e2e/test_deterministic.py -q`
Expected: 全绿

- [ ] **Step 5: 全量回归+提交**

Run: `python -m pytest tests/ -q`
Expected: 294+新增 全绿(flaky 复跑)

```bash
git add src/game/combat.py tests/test_combat_smoke.py tests/e2e/test_deterministic.py MAINTENANCE.md
git commit -m "feat: 遭遇 SAN check 接线(目睹+被击中,san_loss 库数据激活,P0 收口)"
```

- [ ] **Step 6: ISSUES 收口**

docs/ISSUES.md:§5 已收口追加一行(2026-08-26 遭遇 SAN check 断链->接通:F9 去重跟踪);随上或单独 docs commit。

---

## Self-Review 记录

- 覆盖:用户拍板范围=触发(战斗开始+被击中)+不去重(F9 跟踪)+疯狂只 log(F5 跟踪)。✓
- 写回链路已就位(game_loop.py:793/run_game.py:534),战斗内扣 state.player_san 即回写,无需新增。✓
- 已知风险:①monkeypatch random 的 patch 目标(combat.random vs utils.random)需按实际 import 调整;②test_combat_smoke 现有构造模式照抄,断言意图已给;③roll 竞技场(_resolve_enemy_action 的 roll=96+ 场景)与 SAN check 无交互(SAN check 独立 D100)。✓
