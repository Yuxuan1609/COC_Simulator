# 前端交互式战斗系统 v2 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 CLI `run_game.py` 的交互式逐轮战斗完整接入前端，左侧面板（场景卡）切换为战斗态势面板，玩家通过按钮/选项卡选择动作，后端执行单轮后返回新状态。

**Architecture:** 后端内存 session 缓存 CombatState，前端每轮发送动作选择给 `/api/combat/round`，后端执行单轮并返回新状态。`CombatSystem.run_single_round()` 提取自现有 `run_combat()` 的单轮逻辑。

**Tech Stack:** FastAPI + vanilla JS + HTMX（现有栈）+ CombatSystem（Python）

**Key precautions from DEBUG_JOURNAL:**
- **#53**: async 函数中绝不使用同步阻塞调用 — `asyncio.Queue` 已用于 WS，新增 API 都用 async
- **#52**: 序列化边界键名一致性 — 后端返回的 JSON 键名与前端消费侧逐键对照
- **#62**: LLM 只做布尔决策 — 战斗系统已遵循此原则，保持
- **#15, #20, #27**: 大块代码替换优先用 `Write` 而非 `Edit`，避免 Edit 截断/全角引号感染

---

## File Map

| File | Responsibility | Action |
|------|---------------|--------|
| `src/game/combat.py` | 战斗引擎核心 | 新增 `run_single_round()` |
| `frontend/routers/game.py` | 游戏 API 路由 | 新增 `/api/combat/start`, `/api/combat/round`；修改 `/api/game/turn` 去掉自动战斗 |
| `frontend/templates/game.html` | 游戏主页面 | 新增战斗面板 HTML + JavaScript 状态机 |

---

## Task 1: 后端 — 新增 `run_single_round()` 到 `CombatSystem`

**Files:**
- Modify: `src/game/combat.py`

**Background:** `run_combat()` 已经包含完整的自动战斗逻辑。我们需要提取"执行单轮"的能力，让前端可以逐轮交互。`_process_round()` 方法接近但缺少 LLM 修正和多目标处理。

**Design:** 新增 `run_single_round(combat_init, state, action_id, target_ids, player_extra)` 方法：
1. 直接使用传入的 `CombatState`（不复用 `_init_combat`，因为那会重置敌人 HP）
2. 执行单轮：玩家动作 → 敌人动作 → LLM 修正 → 伤害结算 → Phase 检查 → 结束判定
3. 生成本轮叙事摘要（用于日志展示）
4. 返回新状态和结果

- [ ] **Step 1.1: 新增 `run_single_round()` 方法**

在 `src/game/combat.py` 的 `CombatSystem` 类中，`run_combat()` 之后、`_generate_combat_narrative()` 之前插入：

```python
    def run_single_round(self, combat_init: CombatInit, state: CombatState,
                         action_id: str, target_ids: list[str],
                         player_extra: str = "") -> dict:
        """Execute one combat round interactively. Returns result dict with new state.

        This is the frontend-facing API — caller provides the current CombatState
        (with live HP/initiative/etc.), we execute one round and return updates.
        """
        import copy
        player = combat_init.player
        environment_actions = getattr(combat_init, 'environment_actions', [])
        available = self._get_player_actions(player, environment_actions)

        # Resolve action -> actual action_id
        if not action_id or not any(a["id"] == action_id for a in available):
            action_id = "punch"

        alive_enemies = [e for e in state.enemies
                        if getattr(e, 'hp', 1) > 0 and getattr(e, 'status', '') not in ('dead', 'defeated')]
        if not alive_enemies:
            state.finished = True
            return self._build_single_round_result(state, combat_init, player_extra)

        # Multi-attack target expansion
        match = next((a for a in available if a["id"] == action_id), None)
        multi = match.get("multi_attack", 1) if match else 1
        round_targets = list(target_ids) if target_ids else [alive_enemies[0].instance_id]
        if multi > len(round_targets):
            last = round_targets[-1] if round_targets else alive_enemies[0].instance_id
            round_targets = round_targets + [last] * (multi - len(round_targets))

        state.log = []
        state._player_dodging = False
        player_actions_this_round = []
        enemy_actions_this_round = []

        for iid in state.initiative_order:
            if iid == "player":
                for tgt in round_targets:
                    if not tgt:
                        tgt = alive_enemies[0].instance_id if alive_enemies else "unknown"
                    pa = self._resolve_player_action(state, player, action_id, tgt, environment_actions)
                    pa.round_num = state.round
                    state.log.append(pa)
                    state.full_log.append(pa)
                    player_actions_this_round.append({
                        "action_type": pa.action_type,
                        "target": pa.target,
                        "weapon": pa.weapon,
                        "roll": pa.roll,
                        "tier": pa.tier,
                        "damage": pa.damage,
                        "damage_type": getattr(pa, 'damage_type', '物理'),
                        "effects": [],
                    })
                    if state.finished:
                        break
                if state.finished:
                    break
                continue

            enemy = next((e for e in state.enemies if e.instance_id == iid), None)
            if not enemy or getattr(enemy, 'status', '') in ('dead', 'defeated') or getattr(enemy, 'hp', 1) <= 0:
                continue

            multi_e = getattr(enemy, 'multi_attack', 1)
            for _ in range(multi_e):
                ea = self._resolve_enemy_action(state, enemy, player)
                ea.round_num = state.round
                state.log.append(ea)
                state.full_log.append(ea)
                enemy_actions_this_round.append({
                    "actor": ea.actor,
                    "action_type": ea.action_type,
                    "roll": ea.roll,
                    "tier": ea.tier,
                    "damage": ea.damage,
                    "damage_type": getattr(ea, 'damage_type', '物理'),
                    "effects": [],
                })
                if state.player_hp <= 0:
                    state.finished = True
                    break
            if state.finished:
                break

        rresult = self._build_round_result(
            state, player_actions_this_round, enemy_actions_this_round, state.round
        )

        needs_llm = self._any_special_rules(combat_init, state.enemies)
        if needs_llm:
            boss_phase = state._boss_current_phase or ""
            snapshot = self._build_battle_snapshot(state, player, boss_phase)
            rresult = self._llm_correct_round(
                rresult, combat_init, state.enemies,
                player_extra, snapshot, boss_phase, player_actions_this_round
            )

            inv_context = getattr(player, 'personal_description', '') or ''
            if getattr(player, 'extra', ''):
                inv_context = (inv_context + '\n' + player.extra).strip()
            for ea_data in enemy_actions_this_round:
                old_dmg = ea_data.get("damage", 0)
                if old_dmg <= 0:
                    continue
                enemy_id = ea_data.get("actor", "")
                enemy = next((e for e in state.enemies
                             if getattr(e, 'instance_id', '') == enemy_id), None)
                if enemy and getattr(enemy, 'special_rules', ''):
                    corrected = self._llm_correct_enemy_round(
                        enemy, ea_data, player, player_extra, inv_context)
                    new_dmg = max(0, corrected.get("damage", old_dmg))
                    state.player_hp = max(0, state.player_hp + old_dmg - new_dmg)
                    ea_data["damage"] = new_dmg
                    if corrected.get("narrative"):
                        ea_data["effects"] = ea_data.get("effects", []) + [corrected["narrative"]]

        # Apply player damage to enemies
        for pa in player_actions_this_round:
            if pa.get("action_type") != "attack":
                continue
            dmg = pa.get("damage", 0)
            tgt_iid = pa.get("target", "")
            enemy = next((e for e in state.enemies if getattr(e, 'instance_id', '') == tgt_iid), None)
            if not enemy:
                continue
            corrected_dmg = rresult.get("player_damage", 0)
            try:
                effective = max(0, int(corrected_dmg if corrected_dmg is not None else dmg))
            except (ValueError, TypeError):
                effective = max(0, int(dmg) if dmg else 0)
            enemy.hp = max(0, getattr(enemy, 'hp', 10) - effective)

        # Phase check
        for enemy in state.enemies:
            if getattr(enemy, 'hp', 1) <= 0 or getattr(enemy, 'status', '') == 'dead':
                continue
            triggered = self._check_phase(state, enemy)
            if triggered:
                desc = self._apply_phase(state, enemy, triggered, getattr(enemy, 'phases', []))
                if desc:
                    rresult.setdefault("status_changes", []).append({
                        "entity_id": enemy.instance_id,
                        "field": "phase",
                        "old": "",
                        "new": triggered,
                    })

        # Check end conditions
        alive_after = [e for e in state.enemies
                      if getattr(e, 'hp', 1) > 0 and getattr(e, 'status', '') != 'dead']
        if not alive_after:
            state.finished = True
        if state.player_hp <= 0:
            state.finished = True

        state.round += 1
        return self._build_single_round_result(state, combat_init, player_extra)

    def _build_single_round_result(self, state: CombatState, combat_init, player_extra: str = "") -> dict:
        """Build result dict for a single round."""
        player = combat_init.player
        outcome = None
        game_over = False
        is_boss = any(getattr(e, 'boss_mechanics', '') for e in state.enemies)

        if state.finished:
            player_fled = any(
                a.actor == "player" and a.action_type == "flee" and a.success
                for a in state.full_log
            )
            if player_fled:
                outcome = "flee"
            elif state.player_hp <= 0:
                outcome = "loss"
                game_over = not is_boss
            elif state.round > 20:
                outcome = "draw"
            else:
                outcome = "win"

        # Generate round narrative (not full combat narrative — just a brief)
        round_narrative = ""
        if state.log:
            lines = []
            for a in state.log:
                actor = "调查员" if a.actor == "player" else a.actor
                if a.action_type == "attack":
                    s = "命中" if a.success else "未命中"
                    dmg = f" 造成{a.damage}点伤害" if a.success and a.damage > 0 else ""
                    lines.append(f"{actor} | {a.weapon} D100={a.roll} {s}{dmg}")
                elif a.action_type == "flee":
                    lines.append(f"{actor} | 逃跑 {'成功' if a.success else '失败'}")
                elif a.action_type == "dodge":
                    lines.append(f"{actor} | 回避")
                elif a.action_type in ("conceal", "aim", "charge"):
                    lines.append(f"{actor} | {a.action_type}")
            round_narrative = "\n".join(lines)

        return {
            "finished": state.finished,
            "outcome": outcome,
            "player_hp": state.player_hp,
            "player_hp_max": state.player_hp_max,
            "player_san": state.player_san,
            "enemies": self._serialize_enemies(state.enemies),
            "round_log": self._serialize_log(state.log),
            "round_narrative": round_narrative,
            "is_boss": is_boss,
            "game_over": game_over,
            "round": state.round,
        }

    @staticmethod
    def _serialize_enemies(enemies: list) -> list[dict]:
        return [
            {
                "instance_id": getattr(e, 'instance_id', ''),
                "enemy_ref": getattr(e, 'enemy_ref', ''),
                "hp": getattr(e, 'hp', 0),
                "hp_max": getattr(e, 'hp_max', getattr(e, 'hp', 0)),
                "status": getattr(e, 'status', ''),
                "quantity": getattr(e, 'quantity', 1),
                "attributes": getattr(e, 'attributes', {}),
                "boss_mechanics": getattr(e, 'boss_mechanics', ''),
                "special_rules": getattr(e, 'special_rules', ''),
                "phases": getattr(e, 'phases', []),
                "damage_multipliers": getattr(e, 'damage_multipliers', {}),
                "armor": getattr(e, 'armor', ''),
                "multi_attack": getattr(e, 'multi_attack', 1),
            }
            for e in enemies
        ]

    @staticmethod
    def _serialize_log(log: list[CombatAction]) -> list[dict]:
        return [
            {
                "actor": a.actor,
                "action_type": a.action_type,
                "weapon": a.weapon,
                "skill_name": a.skill_name,
                "skill_value": a.skill_value,
                "roll": a.roll,
                "tier": a.tier,
                "target": a.target,
                "damage": a.damage,
                "damage_type": getattr(a, 'damage_type', '物理'),
                "hp_before": a.hp_before,
                "hp_after": a.hp_after,
                "narrative": a.narrative,
                "success": a.success,
                "round_num": a.round_num,
            }
            for a in log
        ]
```

- [ ] **Step 1.2: 验证新方法的语法正确性**

Run:
```bash
cd "D:\COC simulator"
python -c "from src.game.combat import CombatSystem; cs = CombatSystem(); print('OK')"
```

Expected: 无报错，输出 `OK`

- [ ] **Step 1.3: Commit**

```bash
cd "D:\COC simulator"
git add src/game/combat.py
git commit -m "feat(combat): add run_single_round() for interactive frontend combat"
```

---

## Task 2: 后端 — 新增 combat API 路由

**Files:**
- Modify: `frontend/routers/game.py`

**Background:** 当前 `game.py` 的 `process_turn()` 在收到 `combat_init` 时自动执行完整战斗。需要改为：返回 `combat_init` 给前端，由前端驱动交互。新增两个 API：`/api/combat/start` 初始化战斗 session，`/api/combat/round` 执行单轮。

**Design:**
- `_combat_sessions: dict[str, CombatState]` 内存缓存（单进程足够）
- `POST /api/combat/start`：接收 combat_init 序列化数据，_init_combat，返回 session_id + 初始状态
- `POST /api/combat/round`：接收 session_id + action_id + target_ids + player_extra，run_single_round，更新 session，返回结果

- [ ] **Step 2.1: 新增 combat session 存储和辅助函数**

在 `frontend/routers/game.py` 的全局变量区域（约第19-25行之后）插入：

```python
# ── Combat session storage (in-memory, per-process) ──
_combat_sessions: dict[str, "CombatState"] = {}


def _serialize_combat_init(combat_init) -> dict:
    """Serialize CombatInit to dict for JSON response."""
    return {
        "enemies": _serialize_enemies(combat_init.enemies),
        "scene": combat_init.scene,
        "initiative_context": combat_init.initiative_context,
        "environment_actions": getattr(combat_init, 'environment_actions', []),
        "player_action": combat_init.player_action,
        "player_targets": getattr(combat_init, 'player_targets', []),
        "player_extra": getattr(combat_init, 'player_extra', ''),
    }


def _deserialize_combat_init(data: dict, player) -> "CombatInit":
    """Reconstruct CombatInit from dict + live player object."""
    from game.messages import CombatInit
    enemies = []
    for e_data in data.get("enemies", []):
        enemies.append(_deserialize_enemy(e_data))
    return CombatInit(
        enemies=enemies,
        player=player,
        scene=data.get("scene", ""),
        initiative_context=data.get("initiative_context", ""),
        environment_actions=data.get("environment_actions", []),
        player_action=data.get("player_action", ""),
        player_targets=data.get("player_targets", []),
        player_extra=data.get("player_extra", ""),
    )


def _serialize_enemies(enemies: list) -> list[dict]:
    return [
        {
            "instance_id": getattr(e, 'instance_id', ''),
            "enemy_ref": getattr(e, 'enemy_ref', ''),
            "hp": getattr(e, 'hp', 0),
            "hp_max": getattr(e, 'hp_max', getattr(e, 'hp', 0)),
            "status": getattr(e, 'status', ''),
            "quantity": getattr(e, 'quantity', 1),
            "attributes": getattr(e, 'attributes', {}),
            "boss_mechanics": getattr(e, 'boss_mechanics', ''),
            "special_rules": getattr(e, 'special_rules', ''),
            "phases": getattr(e, 'phases', []),
            "damage_multipliers": getattr(e, 'damage_multipliers', {}),
            "armor": getattr(e, 'armor', ''),
            "multi_attack": getattr(e, 'multi_attack', 1),
            "attacks": _serialize_attacks(getattr(e, 'attacks', [])),
            "dex": getattr(e, 'dex', 50),
            "dodge_bonus": getattr(e, 'dodge_bonus', 0),
        }
        for e in enemies
    ]


def _deserialize_enemy(data: dict):
    """Deserialize enemy dict to a lightweight object."""
    from dataclasses import dataclass, field
    from typing import Any

    @dataclass
    class _DeserializedEnemy:
        instance_id: str = ""
        enemy_ref: str = ""
        hp: int = 0
        hp_max: int = 0
        status: str = ""
        quantity: int = 1
        attributes: dict = field(default_factory=dict)
        boss_mechanics: str = ""
        special_rules: str = ""
        phases: list = field(default_factory=list)
        damage_multipliers: dict = field(default_factory=dict)
        armor: str = ""
        multi_attack: int = 1
        attacks: list = field(default_factory=list)
        dex: int = 50
        dodge_bonus: int = 0

    return _DeserializedEnemy(**data)


def _serialize_attacks(attacks: list) -> list[dict]:
    result = []
    for a in attacks:
        if isinstance(a, dict):
            result.append(dict(a))
        else:
            result.append({
                "name": getattr(a, 'name', '攻击'),
                "damage": getattr(a, 'damage', {"dice_n": 1, "dice_d": 3, "bonus": 0, "use_db": False}),
                "skill_name": getattr(a, 'skill_name', '格斗'),
                "skill_value": getattr(a, 'skill_value', 50),
                "weight": getattr(a, 'weight', 1),
            })
    return result


def _deserialize_combat_state(data: dict) -> "CombatState":
    """Reconstruct CombatState from JSON dict."""
    from game.combat import CombatState, CombatAction
    state = CombatState()
    state.round = data.get("round", 1)
    state.player_hp = data.get("player_hp", 0)
    state.player_hp_max = data.get("player_hp_max", 0)
    state.player_san = data.get("player_san", 0)
    state.initiative_order = data.get("initiative_order", [])
    state.is_player_turn = data.get("is_player_turn", True)
    state.finished = data.get("finished", False)
    state._player_dodging = data.get("_player_dodging", False)
    state._player_concealed = data.get("_player_concealed", False)
    state._player_aiming = data.get("_player_aiming", False)
    state._player_charged = data.get("_player_charged", False)
    state._boss_current_phase = data.get("_boss_current_phase", "")
    state._boss_hp_max = data.get("_boss_hp_max", 0)

    for e_data in data.get("enemies", []):
        state.enemies.append(_deserialize_enemy(e_data))

    for a_data in data.get("full_log", []):
        ca = CombatAction()
        for k, v in a_data.items():
            if hasattr(ca, k):
                setattr(ca, k, v)
        state.full_log.append(ca)

    return state
```

- [ ] **Step 2.2: 新增 `POST /api/combat/start`**

在 `frontend/routers/game.py` 中，在 `@router.get("/api/game/state")` 之后（约第721行后）插入：

```python

@router.post("/api/combat/start")
async def combat_start(request: Request):
    """Initialize a combat session from a CombatInit object.

    Request body JSON:
        {"combat_init": {... serialized CombatInit ...}}
    """
    import json, uuid
    from game.combat import CombatSystem
    from game.messages import CombatInit

    body = await request.body()
    data = json.loads(body.decode("utf-8")) if body else {}
    combat_init_data = data.get("combat_init", {})

    game = get_game()
    if game is None:
        return JSONResponse({"error": "游戏未初始化"}, status_code=400)

    player = game["keeper"].world.player
    if not player:
        return JSONResponse({"error": "未设置调查员"}, status_code=400)

    # Reconstruct CombatInit
    combat_init = _deserialize_combat_init(combat_init_data, player)

    # Run init
    cs = CombatSystem()
    state = cs._init_combat(combat_init)

    # Store session
    session_id = str(uuid.uuid4())[:8]
    _combat_sessions[session_id] = state

    # Build available actions for the player
    available = cs._get_player_actions(player, getattr(combat_init, 'environment_actions', []))
    actions = [{"id": a["id"], "label": a["label"], "multi_attack": a.get("multi_attack", 1),
                "damage_type": a.get("damage_type", "物理")}
               for a in available]

    return {
        "session_id": session_id,
        "state": cs._serialize_single_round_state(state),
        "actions": actions,
    }


@router.post("/api/combat/round")
async def combat_round(request: Request):
    """Execute one combat round.

    Request body JSON:
        {"session_id": "...", "action_id": "...", "target_ids": [...], "player_extra": "..."}
    """
    import json
    from game.combat import CombatSystem

    body = await request.body()
    data = json.loads(body.decode("utf-8")) if body else {}
    session_id = data.get("session_id", "")

    state = _combat_sessions.get(session_id)
    if not state:
        return JSONResponse({"error": "战斗会话不存在或已过期"}, status_code=400)

    game = get_game()
    if game is None:
        return JSONResponse({"error": "游戏未初始化"}, status_code=400)

    player = game["keeper"].world.player
    if not player:
        return JSONResponse({"error": "未设置调查员"}, status_code=400)

    action_id = data.get("action_id", "punch")
    target_ids = data.get("target_ids", [])
    player_extra = data.get("player_extra", "")

    # Reconstruct combat_init (we need it for LLM correction context)
    # Store combat_init alongside state in session? For now, we reconstruct minimally.
    # Since we need the original combat_init for _any_special_rules and LLM context,
    # let's store it in session too.
    pass  # Will be handled in step 2.3
```

等等，我意识到一个问题：`_build_single_round_result` 和 `_serialize_single_round_state` 还没定义。而且 `run_single_round` 返回的是 dict，但 state 本身也需要被序列化后存储/传递。让我重新思考存储方案。

实际上，最简洁的方式是：后端存储 `(combat_init, state)` 元组在 session 中。但 combat_init 包含 player 对象（不可序列化）。

替代方案：只存储 `state`，而 combat_init 通过 `get_game()` 实时重建——因为 combat_init 中的 enemies 可以从 world.enemies 获取，player 就是 world.player，scene 就是 world.current_location。

但 `combat_init.enemies` 是展开后的 enemies（_c0, _c1...），world.enemies 中的是群组。所以 combat_init 不能完全从 world 重建。

更简洁的方案：session 中存储 `state` + `combat_init_data`（原始 enemies 的序列化 dict）。combat_init 重建时用 world.player + combat_init_data。

或者：我们可以把 combat_init 的序列化数据也存到 session 中。

```python
_combat_sessions: dict[str, tuple[CombatState, dict]] = {}  # (state, combat_init_data)
```

但 CombatState 本身包含不可序列化的 CombatAction 对象。

实际上，最简单的方式是：不序列化 state 到 JSON，而是直接在后端内存中保持 Python 对象引用。前端只需要传 session_id，后端直接用内存中的对象。

这是最好的方案！修改 session 存储：

```python
_combat_sessions: dict[str, dict] = {}  # {session_id: {"state": CombatState, "combat_init_data": dict, "player_ref": Investigator}}
```

这样 `/api/combat/round` 时直接取出内存对象使用，不需要任何序列化。

但 `/api/combat/start` 返回给前端的状态需要序列化，以便前端展示敌人 HP 等。所以 start 时序列化一次，round 时也序列化返回结果。

好，让我重写方案。

修改 Step 2.2：

```python
# ── Combat session storage (in-memory, per-process) ──
# Each entry: {"state": CombatState, "combat_init_data": dict, "player": Investigator}
_combat_sessions: dict[str, dict] = {}


def _serialize_enemies_for_frontend(enemies: list) -> list[dict]:
    return [
        {
            "instance_id": getattr(e, 'instance_id', ''),
            "enemy_ref": getattr(e, 'enemy_ref', ''),
            "hp": getattr(e, 'hp', 0),
            "hp_max": getattr(e, 'hp_max', getattr(e, 'hp', 0)),
            "status": getattr(e, 'status', ''),
            "attributes": getattr(e, 'attributes', {}),
            "boss_mechanics": getattr(e, 'boss_mechanics', ''),
            "special_rules": getattr(e, 'special_rules', ''),
            "armor": getattr(e, 'armor', ''),
            "multi_attack": getattr(e, 'multi_attack', 1),
        }
        for e in enemies
    ]


def _serialize_combat_state_for_frontend(state) -> dict:
    """Serialize CombatState fields needed by frontend."""
    return {
        "round": state.round,
        "player_hp": state.player_hp,
        "player_hp_max": state.player_hp_max,
        "player_san": state.player_san,
        "enemies": _serialize_enemies_for_frontend(state.enemies),
        "initiative_order": state.initiative_order,
        "finished": state.finished,
    }


def _deserialize_enemies_for_combat(enemy_data_list: list) -> list:
    """Deserialize enemy dicts to objects usable by CombatSystem."""
    from dataclasses import dataclass, field
    from typing import Any

    @dataclass
    class _Enemy:
        instance_id: str = ""
        enemy_ref: str = ""
        hp: int = 0
        hp_max: int = 0
        status: str = ""
        quantity: int = 1
        attributes: dict = field(default_factory=dict)
        boss_mechanics: str = ""
        special_rules: str = ""
        phases: list = field(default_factory=list)
        damage_multipliers: dict = field(default_factory=dict)
        armor: str = ""
        multi_attack: int = 1
        attacks: list = field(default_factory=list)
        dex: int = 50
        dodge_bonus: int = 0
        flags: list = field(default_factory=list)

    enemies = []
    for data in enemy_data_list:
        e = _Enemy()
        for k, v in data.items():
            if hasattr(e, k):
                setattr(e, k, v)
        enemies.append(e)
    return enemies
```

然后 `/api/combat/start`：

```python
@router.post("/api/combat/start")
async def combat_start(request: Request):
    import json, uuid
    from game.combat import CombatSystem
    from game.messages import CombatInit

    body = await request.body()
    data = json.loads(body.decode("utf-8")) if body else {}
    combat_init_data = data.get("combat_init", {})

    game = get_game()
    if game is None:
        return JSONResponse({"error": "游戏未初始化"}, status_code=400)

    player = game["keeper"].world.player
    if not player:
        return JSONResponse({"error": "未设置调查员"}, status_code=400)

    # Reconstruct CombatInit with live player
    enemies = _deserialize_enemies_for_combat(combat_init_data.get("enemies", []))
    combat_init = CombatInit(
        enemies=enemies,
        player=player,
        scene=combat_init_data.get("scene", ""),
        initiative_context=combat_init_data.get("initiative_context", ""),
        environment_actions=combat_init_data.get("environment_actions", []),
        player_action=combat_init_data.get("player_action", ""),
        player_targets=combat_init_data.get("player_targets", []),
        player_extra=combat_init_data.get("player_extra", ""),
    )

    cs = CombatSystem()
    state = cs._init_combat(combat_init)

    session_id = str(uuid.uuid4())[:8]
    _combat_sessions[session_id] = {
        "state": state,
        "combat_init": combat_init,
    }

    available = cs._get_player_actions(player, getattr(combat_init, 'environment_actions', []))
    actions = [{"id": a["id"], "label": a["label"],
                "multi_attack": a.get("multi_attack", 1),
                "damage_type": a.get("damage_type", "物理")}
               for a in available]

    return {
        "session_id": session_id,
        "state": _serialize_combat_state_for_frontend(state),
        "actions": actions,
    }
```

`/api/combat/round`：

```python
@router.post("/api/combat/round")
async def combat_round(request: Request):
    import json
    from game.combat import CombatSystem

    body = await request.body()
    data = json.loads(body.decode("utf-8")) if body else {}
    session_id = data.get("session_id", "")

    session = _combat_sessions.get(session_id)
    if not session:
        return JSONResponse({"error": "战斗会话不存在或已过期"}, status_code=400)

    state = session["state"]
    combat_init = session["combat_init"]
    action_id = data.get("action_id", "punch")
    target_ids = data.get("target_ids", [])
    player_extra = data.get("player_extra", "")

    cs = CombatSystem()
    result = cs.run_single_round(combat_init, state, action_id, target_ids, player_extra)

    # Update session with mutated state
    session["state"] = state

    return {
        "session_id": session_id,
        "state": _serialize_combat_state_for_frontend(state),
        "finished": result["finished"],
        "outcome": result["outcome"],
        "round_log": result["round_log"],
        "round_narrative": result["round_narrative"],
        "is_boss": result["is_boss"],
        "game_over": result["game_over"],
        "round": result["round"],
    }
```

这个方案好多了。但还有一个问题：Step 1.1 中 `run_single_round` 调用了 `_build_single_round_result` 和 `_serialize_enemies`，但 `_serialize_single_round_state` 还没定义。我需要调整 Step 1.1 的方法签名，让它不依赖这些辅助方法，或者把这些辅助方法也加进去。

实际上，我可以让 `run_single_round` 返回一个更简单的 dict，而序列化逻辑放在 router 中。

修改 `run_single_round` 的返回部分：

```python
        return {
            "finished": state.finished,
            "outcome": outcome,
            "player_hp": state.player_hp,
            "player_hp_max": state.player_hp_max,
            "player_san": state.player_san,
            "enemies": state.enemies,  # 返回原始对象列表，router 负责序列化
            "round_log": state.log,     # 返回 CombatAction 列表
            "round_narrative": round_narrative,
            "is_boss": is_boss,
            "game_over": game_over,
            "round": state.round,
        }
```

然后 router 中自己序列化 enemies 和 log。

好的，让我重写整个计划，确保一致性。

这个计划文档已经非常长了。让我现在直接写完它。但我也意识到，我不需要一次性写完整的计划文档——用户已经说了