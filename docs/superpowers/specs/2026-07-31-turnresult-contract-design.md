# TurnResult 契约设计

> 日期：2026-07-31
> 状态：已评审（待实施）
> 前置：P0 修复（4725d5a）、P1 清理（71fb86a）、现状地图梳理

## 背景与问题

`keeper.process_turn` 目前有 7 个返回路径，产出 5 种不同的 dict shape（2/3/8/11 键不等），`brief` 字段时而是 `str` 时而是 `NarratorBrief`。`run_turn` 再拼出 14 键 dict，其中 `full`/`scene_update` 完全无消费者，`standoff_prompt` 在 HTTP 边界被丢弃（standoff 在生产环境不可达），`time_agent`/`npc_events`/`npcs_visible` 仅离线工具使用。消费端（前端 router、CLI、llm_player、harness）全靠 `hasattr`/`.get` 防御。

同时，enrich 合并叙事覆写第一个成功 outcome 的 message（B1），导致 narrator 输入混杂、outcome 事实丢失。

## 设计决策（已确认）

| 决策点 | 结论 |
|--------|------|
| 契约覆盖范围 | **双层**：内部 `TurnResult`（keeper→run_turn）+ 外层 `PlayerTurnResult`（run_turn→消费端） |
| 挂起态表达 | **一等公民**：`status=SUSPENDED` + `PendingInteraction` |
| 死键处理 | 删除 `full`/`scene_update`；`standoff_prompt` 由挂起态取代；低频键收进 `diagnostics` |
| enrich 语义 | 合并叙事进 `NarratorBrief.enriched_summary` 独立字段，outcomes 保持原文 |
| 契约形态 | 扁平 dataclass + `TurnStatus` 枚举（与 messages.py 风格一致） |
| 迁移策略 | **一次性切换**：同一实施计划内改完所有生产方与消费方 |

**关键设计洞察**：武器 offer（等"是/否"）、standoff（等对策）、pre-parse ambiguous（等澄清）是同构的"回合挂起等待玩家回答"，统一由 `PendingInteraction` 表达。本计划只做**契约面**：挂起的"提问侧"全部改为 SUSPENDED 返回；"应答侧"暂留现有位置（process_turn 开头拦截 / `continue_standoff`），由 run_turn 按 `interaction_id` 分发到现有处理器。统一的 resolver 注册表属于后续"中断机制"计划。

## 设计

### 1. 内部契约（`keeper.process_turn` 返回）

```python
class TurnStatus(Enum):
    COMPLETED = "completed"    # 回合完整走完（含简单文本路径）
    SUSPENDED = "suspended"    # 等待玩家回答 pending_interaction
    FROZEN    = "frozen"       # 关键段失败，管线冻结

@dataclass
class PendingInteraction:
    kind: str              # "weapon_offer" | "standoff" | "clarify"
    question: str          # 玩家可见问题文本
    interaction_id: str    # resolver 路由键

@dataclass
class EndingInfo:
    name: str
    narrative: str
    game_over: bool = True

@dataclass
class TurnDiagnostics:                       # 低频/调试数据统一入口
    combat_entry: CombatEntryCheck | None = None
    time_agent: dict | None = None
    enrich_raw: dict | None = None
    pre_parse: PreParseResult | None = None

@dataclass
class TurnResult:
    status: TurnStatus
    brief: NarratorBrief | None = None       # COMPLETED 时必有
    text: str = ""                           # SUSPENDED→question；FROZEN→提示；简单路径文本
    pending_interaction: PendingInteraction | None = None
    combat_init: CombatInit | None = None
    ending: EndingInfo | None = None
    npc_events: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    frozen_message: str = ""
    diagnostics: TurnDiagnostics = field(default_factory=TurnDiagnostics)
```

现有 7 个返回路径的映射：

| 现有路径 | 新形态 |
|---------|--------|
| 正常走完（8-key dict） | `COMPLETED` + brief(NarratorBrief) + 其余字段 |
| 武器 offer 应答 | 过渡期返回 `COMPLETED`+text（后续迁往 resolver） |
| 武器 offer 提问 / standoff 提问 | `SUSPENDED` + PendingInteraction(kind=..., question=...) |
| pre-parse ambiguous 反问 | `SUSPENDED` + PendingInteraction(kind="clarify") |
| NPC 纯对话 / 快捷路径错误 | `COMPLETED` + text（brief=None） |
| 递归上限确定性兜底 | `COMPLETED` + brief |
| TurnFrozenError | `FROZEN` + frozen_message |

契约不变量（`__post_init__` 轻量断言）：
- SUSPENDED 必须有 pending_interaction
- brief=None 时 text 必须非空

### 2. 外层契约（`run_turn` 返回，玩家面）

```python
@dataclass
class PlayerTurnResult:
    status: TurnStatus                        # 与内层共用枚举
    brief: str = ""
    narrative: str = ""
    pending_interaction: PendingInteraction | None = None
    player_snapshot: PlayerFacingSnapshot | None = None
    skill_results: list[dict] = field(default_factory=list)
    combat: dict | None = None                # 调用方战斗结算后回填（现有模式保留）
    combat_init: CombatInit | None = None
    ending: EndingInfo | None = None
    game_over: bool = False
    timestamp: str = ""
    diagnostics: dict = field(default_factory=dict)   # time_agent / npc_events / npcs_visible
```

现有 14 键的映射：

| 现有键 | 去向 |
|--------|------|
| brief / narrative | 保留（text 路径时 narrative=text） |
| player_snapshot / skill_results / combat / combat_init / ending / game_over / timestamp | 保留 |
| **full** | 删除（无消费者） |
| **scene_update** | 删除（已在 run_turn 内部 apply 到 world） |
| **standoff_prompt** | 删除 → pending_interaction |
| time_agent / npc_events / npcs_visible | 收进 diagnostics |
| game_frozen / frozen_message | status=FROZEN + text |

路由层说明：前端 router 自行附加的 `narrative_html`、`turn_dynamic_text` 属于呈现层适配，不进契约；router 拿到 PlayerTurnResult 后照常附加。

### 3. NarratorBrief 变更与 enrich 流（B1）

现状：enrich 产出 `results`（合并叙事）→ 覆写第一个成功 outcome 的 message → narrator 输入混杂。

新流：facts 与 presentation 分离——

```
enrich.results ──────────────→ Curator.assemble(..., enriched_summary)
outcomes（原文不动）─────────→ NarratorBrief.action_outcomes   ← 事实
                                NarratorBrief.enriched_summary  ← 呈现（新字段）
```

| 位置 | 变更 |
|------|------|
| `messages.py` NarratorBrief | 新增 `enriched_summary: str = ""` |
| `curator.py` | `assemble()` 增加第 4 参 `enriched_summary=""`，透传到 brief |
| `keeper.py` Step 3.5 | 删除覆写块（`o.message = results`），`results` 存本地变量传给 curate |
| `keeper.py` complete_combat_turn | 同样去覆写，enrich 结果进 brief.enriched_summary |
| `prompts.py` narrator prompt | brief 有 enriched_summary 时以其为叙事主素材，outcomes 作补充事实 |
| `run_turn` display_brief | `brief.enriched_summary or "\n".join(o.message ...)` |
| 前端 fallback 渲染 | 同样优先 enriched_summary |

降级行为：enrich 失败/降级 → `enriched_summary=""` → 展示路径回退 outcomes 拼接，与现状等价。

附带收益：outcome.message 不再被覆写后，post-enrich 结局 fallback 扫描变为纯防御性，实施时评估是否简化。

### 4. 生产端改造（5 处）

| 位置 | 变更 |
|------|------|
| `keeper.process_turn` | 7 个返回点 → TurnResult（§1 映射表） |
| `keeper.complete_combat_turn` | 返回 `TurnResult(COMPLETED, brief=..., diagnostics.enrich_raw=...)` |
| `game_loop.run_turn` | 消费 TurnResult → 产出 PlayerTurnResult；**新增应答分发**：玩家输入到达时若存在 pending interaction，按 `interaction_id` 分发到现有处理器（`"standoff"`→`continue_standoff`、`"weapon_offer"`→process_turn 现有 offer 拦截、`"clarify"`→pre_parse 跨回合上下文），无匹配则走正常回合 |
| `game_loop.continue_standoff` | 返回 TurnResult（可能带 combat_init 或下一组 SUSPENDED） |
| `keeper.resolve_standoff` | 保持内部形状，由 continue_standoff 包装进契约 |

### 5. 消费端改造（9 处）

| 消费端 | 改动量 | 说明 |
|--------|--------|------|
| `frontend/routers/game.py` | 中 | `turn.get(key)` → 属性访问；SUSPENDED 转发 pending_interaction；FROZEN 走 status 判定；战斗结束读 complete_combat_turn 返回的 `.brief` |
| `run_game.py` | 中 | 主循环键访问 → 属性；SUSPENDED 打印 question 继续循环 |
| `src/llm_player.py` | 小 | time_agent/npc_events/npcs_visible 改从 diagnostics 读 |
| `tests/test_harness_parallel.py` | 小 | standoff 检测改 `status==SUSPENDED and kind=="standoff"` |
| `tests/test_p0_pipeline_fixes.py` | 小 | `result.get("combat_init")` → `result.combat_init` 等 |
| `tests/test_escalation_real.py` | 小 | process_turn 结果访问方式 |
| `tests/game_loop_harness.py` | 小 | run_turn 结果访问 |
| `src/audit_player_log.py` | 评估 | 主要读日志文件，预计无需改（实施时验证） |
| `prompts.py` narrator | 小 | 读 brief.enriched_summary（§3） |

### 6. 错误处理

- **FROZEN**：`status=FROZEN` + `text=frozen_message`；外层映射为 brief/narrative=冻结提示；前端现有 `game_frozen` 处理改判 status
- **挂起应答无匹配**：玩家输入与 pending 无关时落入正常回合（现状行为保留）
- **enrich 降级**：`enriched_summary=""` → 展示层回退 outcomes 拼接
- **契约不变量违反**：`__post_init__` 断言失败即抛错，生产方写错立即暴露

### 7. 测试策略

1. **契约单测**：7 个返回路径各一例，验证 status + 不变量（复用 test_p0_pipeline_fixes 的 world/mock 基建）
2. **迁移回归**：现有全套测试绿（test_turn_monitor 已知遗留失败除外）
3. **集成冒烟**：llm_player mock 模式跑 3 回合验证端到端

## 非目标（本计划不做）

- 统一 resolver 注册表 / 中断机制重构（后续计划）
- 存读档序列化边界修复（敌人库/NPC profiles/time_condition，用户拍板排最后）
- process_turn 五阶段拆分（C1，本契约落地后变成机械提取）
- 战斗完成契约统一 CLI/前端（B5，后续计划）
- PreParse 真并行化（C3）

## 成功标准

- process_turn 所有返回路径产出合法 TurnResult，`__post_init__` 不变量全覆盖
- run_turn 产出 PlayerTurnResult，14 键旧 dict 完全移除
- 前端/CLI/llm_player/harness 全部改为属性访问，无 `.get("standoff_prompt")` 等旧键残留
- standoff 在前端首次生产可达（SUSPENDED → 问答 UI → continue_standoff）
- 现有测试套件全绿（已知遗留失败除外）
