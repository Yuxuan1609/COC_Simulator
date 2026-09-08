"""
LLM 后端配置模板。
复制为 config_llm.py 并填入你自己的配置。
config_llm.py 不会被 Git 跟踪。
"""

# ═══════════════════════════════════════════════════════════════
# API 连接
# ═══════════════════════════════════════════════════════════════

LLM_BASE_URL = "https://ark.cn-beijing.volces.com/api/coding/v3"
"""主 API 端点。默认火山方舟（Ark）OpenAI 兼容网关。"""

LLM_API_KEY_ENV = "ARK_API_KEY"
"""主 API Key 环境变量名。从 .env 或系统环境读取。"""

LLM_API_KEY = ""
"""可选：直接写在本文件的主 Key（空则只用环境变量）。config_llm.py 不入库。"""


# ═══════════════════════════════════════════════════════════════
# 模型选择
# ═══════════════════════════════════════════════════════════════

LLM_DEFAULT_MODEL = "deepseek-v4-flash"
"""主模型：用于 Keeper Parse、Narrator、Author 等核心调用。"""

LLM_FLASH_MODEL = "deepseek-v4-flash"
"""轻量模型：用于 CombatEntry、TimeAgent、Enrich、Standoff 等高频调用。"""

LLM_STRIP_THINKING_PARAMS = True
"""主端是否剥离 extra_body.thinking / reasoning_effort（Ark 不支持 DeepSeek thinking 扩展）。"""


# ═══════════════════════════════════════════════════════════════
# 生成参数默认值
# ═══════════════════════════════════════════════════════════════

LLM_THINKING_ENABLED = True
"""是否启用思考模式（deepseek reasoning）。"""

LLM_REASONING_EFFORT = "high"
"""推理强度："low" / "medium" / "high" / "max"。"""

LLM_TEMPERATURE_JSON = 0.3
"""JSON 模式（结构化判定）默认温度。"""

LLM_TEMPERATURE_TEXT = 0.7
"""文本模式（叙事生成）默认温度。"""

LLM_MAX_TOKENS_JSON = 162840
"""JSON 模式默认 max_tokens。"""

LLM_MAX_TOKENS_TEXT = 20000
"""文本模式默认 max_tokens。"""


# ═══════════════════════════════════════════════════════════════
# 各调用点的 reasoning_effort 覆盖
# ═══════════════════════════════════════════════════════════════

RE_KEEPER_PARSE = "max"
RE_NARRATOR = "max"
RE_COMBAT_ENTRY = "low"
RE_TIME_AGENT = None           # None = 使用 LLM_REASONING_EFFORT 默认值
RE_AUTHOR = "max"
RE_INTENT_DETECTOR = "low"
RE_ENRICH = None
RE_STANDOFF = None
RE_MEMORY_COMPRESS = None
RE_COMBAT_NARRATIVE = "low"
RE_SUPPLEMENT_NARRATIVE = "max"
RE_SUPPLEMENT_ENTITIES = "max"
RE_SUPPLEMENT_L1 = "max"
RE_SUPPLEMENT_L3 = "max"


# ═══════════════════════════════════════════════════════════════
# Fallback provider（主端 402 账单不足时切换；api_key 为空则禁用）
# ═══════════════════════════════════════════════════════════════

LLM_FALLBACK_PROVIDER = {
    "base_url": "https://api.deepseek.com",
    "api_key": "",
    "api_key_env": "DEEPSEEK_API_KEY",
    "default_model": "deepseek-v4-flash-vision-exp",
    "flash_model": "deepseek-v4-flash-vision-exp",
    "strip_thinking": False,
}
