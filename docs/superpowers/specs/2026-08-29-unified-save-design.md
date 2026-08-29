# 统一存档设计（B1 三连 + F14 + E 簇占坑）

> 2026-08-29 与用户讨论拍板。来源：roadmap Step2 第 1 项（docs/superpowers/specs/2026-08-26-remaining-issues-roadmap-design.md §2）。
> 范围：B1 存读档三连修复 + F14 技能 checked 标记 + E 簇（F22 线索 / F25 narrator 记忆）入档结构占坑。存档格式只迁移一轮。

## 0. 背景

存档现状（核实于 HEAD `1eaaf3b`）：

- 保存：`ScenarioWorld.save_state`（scenario_core.py:1178）写 `version: 1` 全量快照（graph/world/memory/player_snapshot），F9 的 `san_seen_sources` 已入档；`game_loop.save_game`（:638）先写文件再读回补 `_meta.turn_number`（写两遍）；CLI `/save`（run_game.py:140）直接调 `world.save_state`，连 `_meta` 都不写
- B1①：`load_state`（scenario_core.py:1197）是 classmethod，重建 world 时没有模组库 → `EnemyManager.from_dict(data, None)` 抛异常被 `except: pass`（:1220）吞掉 → enemies=None；bosses 同款（:1238）；npcs 走 `except: pass`（:1228）但会先建空壳
- B1②：CLI 读档（run_game.py:148）`keeper.world = new_world`，但 `judge`/`curator`（keeper.py:108–109）与 `turn_monitor`（:130）在 `__init__` 持旧引用；前端读档（game_loop.py:663–665）逐属性 `setattr` 原地拷贝，靠遍历 `__dict__` 兜底
- B1③：NPC 注入实体随 graph 入档，但 `_npc_injected_at_ids` 不入档 → 读档后 `_inject_npc_at` 重复注入

已验证事实：`run_turn` 每回合重新读 `keeper.world`（game_loop.py:337），world 引用只散落在 keeper 内部三处（judge/curator/turn_monitor）。

## 1. 已确认的决策

| 决策点 | 结论 |
|---|---|
| B1② 路径统一 | **重绑**：`Keeper.set_world()` 显式重绑三处引用，CLI/前端统一走 `game_loop.load_game` |
| 存档时机 | **只在用户可输入时生效**（输入边界），不考虑回合进行中间态（用户拍板） |
| session_state 范围 | 最小集：`_npc_injected_at_ids`（B1③ 必修）+ `_recent_intents` + `_last_comms_time`（节流）；挂起交互（offer/standoff）视为中间态**不入档**，读档后自然退化；战斗回放字段（`_last_outcomes`/`_last_player_input`/`_combat_result_pending`）不入（CLI 战斗同步完成，档不可能夹在中间） |
| E 簇入档结构 | **最小占坑**：`clues`/`narrative_memory` 空容器 + additive-default 明文约定，Step3 填结构 |
| F14 | `Skill.checked: bool`，`check_skill` 成功时置位（COC7 成功使用才标记）；幕末成长检定属 Step3/U4 |
| 版本策略 | 写 v2；读 v1/v2 均接受，缺字段一律默认值 |

## 2. 存档格式 v2

```json
{
  "version": 2,
  "timestamp": "...",
  "graph": {...},
  "world": {
    "...": "现有字段不变（含 san_seen_sources）",
    "clues": [],
    "narrative_memory": []
  },
  "memory": {...},
  "player_snapshot": {
    "...": "卡格式 v2.2 不变",
    "skills": [{"name": "...", "base": 0, "value": 0, "category": "...",
                "is_occupation": false, "checked": false}]
  },
  "_meta": {
    "turn_number": 0,
    "session_state": {
      "npc_injected_at_ids": [],
      "recent_intents": [],
      "last_comms_time": 0
    }
  }
}
```

**additive-default 约定**（明文）：新增入档字段必须带默认值（`from_dict` 用 `.get(key, default)`），使旧档免迁移可读；只有破坏性变更（改语义/删字段/改类型）才升 `version` 并写迁移函数。此约定写入本文件即生效，Step3 各簇遵守。

**中间态不入档不变式**：`/save` 只在输入边界处理（CLI/前端现状即如此，本次固化为约定）；格式不含任何回合中间态（pending side effects / detect future / 战斗回放素材 / 挂起交互）。

## 3. B1 三修

### ③②① 顺序说明：先统一入口（②），库透传才有落点（①），③ 随 _meta 落地

**B1② 路径统一**

- `Keeper.set_world(self, new_world)`：`self.world = new_world`；`self.judge.world = new_world`；`self.curator.world = new_world`；`self.turn_monitor.world = new_world`
- `game_loop.load_game(game, path)` 改为：
  1. `ScenarioWorld.load_state(path, enemy_lib=…, boss_lib=…, npc_profiles=…)`（库从当前 `keeper.world` 取，见 B1①）
  2. `keeper.set_world(new_world)`
  3. `_meta` 恢复：`turn_number` + `keeper.load_session_state(meta.get("session_state", {}))`
  4. 前端 `game` dict 不持 world（经 keeper 访问），无需额外处理
- CLI `/load`（run_game.py:143–155）改调 `game_loop.load_game(game, path)`，删除手工 `keeper.world = new_world`
- 前端 `/load`（frontend/routers/game.py:227–233）已调 `load_game`，零改动自动获益

**B1① 库透传 + 删静默吞异常**

- `ScenarioWorld.load_state(cls, path, enemy_lib=None, boss_lib=None, npc_profiles=None)`
- enemies/bosses 恢复用传入的库；库缺失且存档有对应数据 → 收集 warning（不静默）
- `except: pass` 全删。失败分级：
  - 结构性损坏（版本不兼容 / JSON 坏 / graph 缺失）→ `raise`（读档失败，旧世界不动）
  - 单条引用失败（敌人/boss 名不在库）或库缺失 → 跳过该实例 + warning 收集进 `world.load_warnings: list[str]`（同时 `logging.warning`），由 `load_game` 打印/展示
- npcs 恢复用传入的 `npc_profiles`（默认 `{}`）

**B1③ 注入去重入档**

- Keeper 加两个接口：
  - `dump_session_state() -> dict`：`{"npc_injected_at_ids": sorted(...), "recent_intents": [...], "last_comms_time": ...}`
  - `load_session_state(data: dict)`：缺键一律默认值（空集/空列/0）
- `save_game` 写入 `_meta.session_state`；`load_game` 恢复

**`/save` 顺手统一**

- `save_game(game, path)` 成为唯一保存入口：一次性组包 `{version: 2, timestamp, graph, world, memory, player_snapshot, _meta}` 写一次（消除「写两遍」）
- CLI `/save`（run_game.py:140）改调 `game_loop.save_game`；`ScenarioWorld.save_state` 保留为底层方法但不再被入口直接调用

## 4. F14 技能成长标记

- `Skill`（investigator/models.py:41）加 `checked: bool = False`
- `check_skill`（models.py:226–245）成功时 `skill.checked = True`（含特质修正后改判成功的情况——以最终 tier 为准）
- serialization：`to_dict` skills 条目加 `"checked"`；`from_dict` 缺省 `False`（旧卡/旧档兼容）
- 角色卡导出（meta.version "2.2"）字段随 serialization 自动带 checked——卡格式向后兼容，不升卡版本

## 5. E 簇占坑

- `ScenarioWorld.to_dict` 加 `"clues": []` / `"narrative_memory": []`（现为常量空列表，无生产端）
- `from_dict` 读入并存为 `world.clues` / `world.narrative_memory`（默认空列表），供 Step3 消费侧直接挂
- 不设计字段结构（YAGNI）；Step3 E 簇开工时按真实需求填

## 6. 验收测试（新增，全在默认套件）

| 测试 | 锁定 |
|---|---|
| 存档回环 | save→load 后 current_location / runtime_state / clock / san_seen_sources / inventory 一致 |
| 引用重绑 | load 后 `keeper.judge.world is keeper.world`（curator/turn_monitor 同）且为新 world |
| 注入不重复 | 带 NPC bound 实体的档 save→load→再次 `_inject_npc_at` 后 node.interactions 无重复 id |
| 敌人带库恢复 | 有敌人实例的档 load 后 enemies 非 None、实例在场 |
| 无库 warning | 存档有敌人但当前会话无库 → load 成功、`world.load_warnings` 非空（不静默、不 raise） |
| v1 兼容 | 手工构造 version:1 存档（无 session_state/clues/checked）可读，字段默认值 |
| F14 | check_skill 成功 → checked=True；序列化回环保持；失败不置位 |

收尾：`pytest tests/ -q` 全绿；MAINTENANCE.md / docs/ISSUES.md（B1 移入已收口，F14 标注「标记已落，成长循环 Step3」）同步。

## 7. 非目标

- 幕末成长检定循环（Step3/U4）
- F22 线索实体 / F25 narrator 记忆的生产端（Step3 E 簇）
- 战斗中断恢复（F40，前端域）
- 存档槽位 UI / 撤销回滚（F37/F38，前端域）
- scenario_core.py 结构拆分（另排）
