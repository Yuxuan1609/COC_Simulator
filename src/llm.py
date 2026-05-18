"""
LLM 调用封装：DeepSeek API 客户端与结构化/创作/概述调用。
"""

import os
import json
import re
from openai import OpenAI

# 从项目根目录 .env 文件加载环境变量
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
_env_path = os.path.normpath(_env_path)
if os.path.exists(_env_path):
    with open(_env_path, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                _key = _key.strip()
                _val = _val.strip().strip('"').strip("'")
                if _key and _key not in os.environ:
                    os.environ[_key] = _val

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY", ""),
    base_url="https://api.deepseek.com"
)

# ── 响应日志 ──

_log_file: str | None = None


def set_llm_log_file(path: str):
    """设置 LLM 响应日志文件路径。设置后 call_deepseek 会将响应写入该文件。"""
    global _log_file
    _log_file = path


def _log_response(content: str):
    """将 LLM 响应写入日志文件（如已配置）"""
    if not _log_file:
        return
    with open(_log_file, 'a', encoding='utf-8') as f:
        f.write("\n--- Response ---\n")
        f.write(content)
        f.write("\n\n")


def _extract_json(content: str) -> str:
    """从 LLM 返回内容中提取 JSON 字符串。"""
    # 尝试从 markdown 代码块中提取
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", content, re.DOTALL)
    if match:
        content = match.group(1).strip()

    # 尝试定位 JSON 的起始/结束花括号
    if not (content.startswith("{") or content.startswith("[")):
        start = content.find("{")
        if start == -1:
            start = content.find("[")
        if start != -1:
            content = content[start:]
            depth = 0
            end = -1
            for i, ch in enumerate(content):
                if ch in "{[":
                    depth += 1
                elif ch in "}]":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end != -1:
                content = content[:end]

    return content


def call_deepseek(
    prompt: str, *,
    json_mode: bool = True,
    system: str = None,
    model: str | None = None,
    thinking: bool | None = None,
    reasoning_effort: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    max_retries: int = 3,
    fallback_schema: dict | None = None,
) -> dict | str:
    """
    统一 DeepSeek 调用入口。
    json_mode=True  → 返回解析后的 dict（用于结构化判定）
    json_mode=False → 返回原始文本（用于叙事生成/压缩）
    model: 模型名称，None 时默认 "deepseek-v4-pro"
    thinking: 是否启用思考模式，None 时默认 True
    reasoning_effort: 推理强度 ("low"/"medium"/"high")，None 时默认 "high"
    temperature: 温度参数，None 时 json_mode 默认 0.3，非 json_mode 默认 0.7
    max_tokens: 最大输出 token 数，None 时 json_mode 默认 162840，非 json_mode 默认 20000
    max_retries: JSON 解析失败时最大重试次数（默认 3）
    fallback_schema: 全部重试失败后，按此 dict 的 key 构造返回（空值填充）
    """
    _model = model if model is not None else "deepseek-v4-pro"
    _reasoning_effort = reasoning_effort if reasoning_effort is not None else "high"
    _thinking = thinking if thinking is not None else True

    if json_mode:
        _temperature = temperature if temperature is not None else 0.3
        _max_tokens = max_tokens if max_tokens is not None else 162840
        default_system = system or "你是一个严格的规则判定助手，仅按给定条件输出 JSON。"

        last_error = None
        for attempt in range(1, max_retries + 1):
            response = client.chat.completions.create(
                model=_model,
                messages=[
                    {"role": "system", "content": default_system},
                    {"role": "user", "content": prompt}
                ],
                temperature=_temperature,
                max_tokens=_max_tokens,
                reasoning_effort=_reasoning_effort,
                extra_body={"thinking": {"type": "enabled" if _thinking else "disabled"}}
            )
            raw = response.choices[0].message.content.strip()
            if raw.startswith("```json"):
                raw = raw[7:-3].strip()
            elif raw.startswith("```"):
                raw = raw[3:-3].strip()
            try:
                result = json.loads(raw)
                _log_response(json.dumps(result, ensure_ascii=False, indent=2))
                return result
            except json.JSONDecodeError as e:
                last_error = e
                content_text = _extract_json(raw)
                try:
                    result = json.loads(content_text)
                    _log_response(json.dumps(result, ensure_ascii=False, indent=2))
                    return result
                except json.JSONDecodeError:
                    if attempt < max_retries:
                        print(f"[JSON解析失败] 第{attempt}/{max_retries}次重试...")
                        _temperature = max(0.0, _temperature - 0.1)
                    else:
                        print(f"[JSON解析失败] {max_retries}次重试均失败\n  原始返回:\n{raw[:500]}")

        if fallback_schema is not None:
            print(f"[JSON Fallback] 使用 fallback schema 兜底")
            fallback = {k: (v() if callable(v) else v) for k, v in fallback_schema.items()}
            _log_response(json.dumps(fallback, ensure_ascii=False, indent=2))
            return fallback

        raise last_error or RuntimeError("JSON解析失败且无 fallback")
    else:
        _temperature = temperature if temperature is not None else 0.7
        _max_tokens = max_tokens if max_tokens is not None else 20000
        default_system = system or "你是一个专业的TRPG主持人（KP）。"
        response = client.chat.completions.create(
            model=_model,
            messages=[
                {"role": "system", "content": default_system},
                {"role": "user", "content": prompt}
            ],
            temperature=_temperature,
            max_tokens=_max_tokens,
            reasoning_effort=_reasoning_effort,
            extra_body={"thinking": {"type": "enabled" if _thinking else "disabled"}}
        )
        result = response.choices[0].message.content.strip()
        _log_response(result)
        return result


def evaluate_trait_enhancement(
    inv_desc: str,
    inv_appearance: str,
    skill_name: str,
    skill_detail: str,
    current_tier: str,
    entity_name: str,
    graded_tiers: dict | None = None,
    search_context: bool = False,
) -> dict:
    """规则增强 sub-agent：基于调查员特质修正技能检定结果。

    返回 {"tier": str, "detail_override": str | None, "reason": str}
    - tier: 修正后的等级(failure/regular/hard/extreme)，可能不变
    - detail_override: 若 LLM 给出新的结果描述则使用，否则 None
    - reason: 修正理由简述
    """
    tier_order = ["failure", "regular", "hard", "extreme"]
    current_idx = tier_order.index(current_tier) if current_tier in tier_order else 1

    graded_text = ""
    if graded_tiers:
        for t, text in graded_tiers.items():
            graded_text += f"  {t}: {text}\n"

    prompt = f"""你是 TRPG 规则辅助裁判。根据调查员的特质，判断是否需要修正本次技能检定结果。

【调查员】
  描述：{inv_desc or '（无）'}
  外貌：{inv_appearance or '（无）'}

【当前检定】
  实体：{entity_name}
  技能：{skill_name}
  原始结果：{skill_detail}
  当前等级：{current_tier}（failure < regular < hard < extreme）
  检定上下文：{'搜索侦查' if search_context else '实体交互'}

【分级结果参考】
{graded_text or '（无分级结果）'}

请判断：调查员的特质描述是否暗示此技能应有优势（或劣势）？
仅在特质明确相关时修正。例如：
- "观察力极其优秀" → 侦查可提升一级
- "胆小如鼠" → 涉及勇气的检定可降一级
- 无关特质则不修正

返回 JSON：
{{
  "tier": "{current_tier}",
  "detail_override": null,
  "reason": "修正或不修正的理由"
}}

规则：
- tier 只能是 failure / regular / hard / extreme 之一
- 只能升或降一级，不能跨级
- 若无需修正，tier 保持原值，reason 说明原因
- detail_override 仅在确实需要新的结果描述时填写，否则填 null
- 优先修正有明确指向的描述，不要过度解读
- 直接输出 JSON
"""
    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {"role": "system", "content": "你是一个TRPG规则辅助裁判。仅输出JSON。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
        max_tokens=500,
        extra_body={"thinking": {"type": "disabled"}},
    )
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```json"):
        raw = raw[7:-3].strip()
    elif raw.startswith("```"):
        raw = raw[3:-3].strip()
    try:
        result = json.loads(raw)
        # Validate tier
        if result.get("tier") not in tier_order:
            result["tier"] = current_tier
        # Prevent more than 1 tier shift
        new_idx = tier_order.index(result["tier"])
        if abs(new_idx - current_idx) > 1:
            result["tier"] = tier_order[current_idx + (1 if new_idx > current_idx else -1)]
        return result
    except json.JSONDecodeError:
        return {"tier": current_tier, "detail_override": None,
                "reason": "JSON解析失败，保持原结果"}