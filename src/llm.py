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
) -> dict | str:
    """
    统一 DeepSeek 调用入口。
    json_mode=True  → 返回解析后的 dict（用于结构化判定）
    json_mode=False → 返回原始文本（用于叙事生成/压缩）
    model: 模型名称，None 时默认 "deepseek-v4-pro"
    thinking: 是否启用思考模式，None 时默认 True
    reasoning_effort: 推理强度 ("low"/"medium"/"high")，None 时默认 "high"
    """
    _model = model if model is not None else "deepseek-v4-pro"
    _reasoning_effort = reasoning_effort if reasoning_effort is not None else "high"
    _thinking = thinking if thinking is not None else True

    if json_mode:
        default_system = system if model is not None else "你是一个严格的规则判定助手，仅按给定条件输出 JSON。"
        response = client.chat.completions.create(
            model=_model,
            messages=[
                {"role": "system", "content": system or default_system},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=162840,
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
        except json.JSONDecodeError:
            content_text = _extract_json(raw)
            try:
                result = json.loads(content_text)
                _log_response(json.dumps(result, ensure_ascii=False, indent=2))
                return result
            except json.JSONDecodeError:
                print(f"[JSON解析失败] 原始返回内容:\n{raw[:2000]}")
                raise
    else:
        default_system =  system if model is not None else "你是一个专业的TRPG主持人（KP）。"
        response = client.chat.completions.create(
            model=_model,
            messages=[
                {"role": "system", "content": system or default_system},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=20000,
            reasoning_effort=_reasoning_effort,
            extra_body={"thinking": {"type": "enabled" if _thinking else "disabled"}}
        )
        result = response.choices[0].message.content.strip()
        _log_response(result)
        return result