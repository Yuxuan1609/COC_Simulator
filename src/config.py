"""
集中化配置 —— 不包含 API 密钥等敏感信息。
所有硬编码的开关、阈值、魔法数字统一从此读取。
"""

# ═══════════════════════════════════════════════════════════════
# 子系统开关
# ═══════════════════════════════════════════════════════════════

WR0_ENABLED = False
"""创作者豁免（World Rule 0）。开启后 Author 不受世界规则约束。"""

OFFLINE_INJECTION_ENABLED = True
"""模组构建时离线预填充武器/敌人。"""

RUNTIME_INJECTION_ENABLED = True
"""游戏运行时动态注入武器/敌人（/inject 命令）。"""

JUDGMENT_TIER2_ENABLED = True
"""LLM 增强技能判定（Tier 2）。关闭后仅用确定性 D100 判定。"""

SHOW_NON_TRIGGERABLE = True
"""Keeper Parse prompt 是否展示未满足条件的实体。"""

AT_WORLD_ENABLED = True
"""管线是否生成 AT_WORLD 世界初始化自动触发。"""

INJECT_L3_WR0 = True
"""管线是否向 L3 的 world_rules 注入 WR0 条目。"""


# ═══════════════════════════════════════════════════════════════
# 游戏循环阈值
# ═══════════════════════════════════════════════════════════════

MAX_ESCALATION_DEPTH = 3
"""Author Patch/StructuralEdit 递归深度上限。"""

INTENT_COOLDOWN_WINDOW = 3
"""IntentDetector 相同意图去重窗口（回合数）。"""

COMMS_INTERVAL_MINUTES = 15
"""TimePressure 通信间隔（游戏内分钟数）。"""

NPC_MEMORY_CAP = 20
"""NPC 对话记忆条数上限。"""


# ═══════════════════════════════════════════════════════════════
# 管线参数
# ═══════════════════════════════════════════════════════════════

PIPELINE_MAX_RETRIES = 3
"""管线 LLM 调用最大重试次数。"""


# ═══════════════════════════════════════════════════════════════
# Agent 系统提示词覆盖（可选）
# ═══════════════════════════════════════════════════════════════
# 留空字符串则使用 agent 内置默认值。
# 提供非空字符串则完全替换对应 agent 的 system prompt。

AGENT_SYSTEM_PROMPTS = {
    "keeper_parse": "",
    "keeper_enrich": "",
    "narrator": "",
    "combat_entry": "",
    "time_agent": "",
    "author": "",
    "author_time_pressure": "",
    "intent_detector": "",
    "npc_dialogue": "",
    "trait_enhance": "",
    "failure_penalty": "",
    "memory_compress": "",
}
