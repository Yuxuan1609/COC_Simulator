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
        default_system = "你是一个严格的规则判定助手，仅按给定条件输出 JSON。"
        response = client.chat.completions.create(
            model=_model,
            messages=[
                {"role": "system", "content": system or default_system},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=16284,
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
        default_system = "你是一个专业的TRPG主持人（KP）。"
        response = client.chat.completions.create(
            model=_model,
            messages=[
                {"role": "system", "content": system or default_system},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=2000,
            reasoning_effort=_reasoning_effort,
            extra_body={"thinking": {"type": "enabled" if _thinking else "disabled"}}
        )
        result = response.choices[0].message.content.strip()
        _log_response(result)
        return result


def call_deepseek_json(prompt: str) -> dict:
    """调用 DeepSeek 进行结构化判定，返回解析后的 dict。"""
    response = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[
            {"role": "system", "content": "你是一个严格的规则判定助手，仅按给定条件输出 JSON。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
        max_tokens=162840,
        reasoning_effort="high",
        extra_body={"thinking": {"type": "enabled"}}
    )

    content = response.choices[0].message.content.strip()
    content = _extract_json(content)

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        print(f"[JSON解析失败] 原始返回内容:\n{content[:2000]}")
        raise


def call_deepseek_write(prompt: str) -> dict:
    """调用 DeepSeek 进行创作性输出，返回解析后的 dict。"""
    response = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[
            {"role": "system", "content": "你是一个优秀的跑团模组创作者，按给定条件输出 JSON。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.9,
        max_tokens=162840,
        reasoning_effort="high",
        extra_body={"thinking": {"type": "enabled"}}
    )

    content = response.choices[0].message.content.strip()
    content = _extract_json(content)

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        print(f"[JSON解析失败] 原始返回内容:\n{content[:2000]}")
        raise


def call_deepseek_summarize(
    content: str,
    max_chars: int = 2000,
    focus: str = "",
    output_path: str = "summary.txt",
) -> str:
    """
    调用 DeepSeek 对长文本进行缩写和概述，提炼核心信息。
    """
    focus_hint = ""
    if focus:
        focus_hint = f"\n请侧重保留与「{focus}」相关的信息，其他内容可大幅精简。"

    prompt = f"""原文：
\"\"\"
{content}
\"\"\" 请对原文文本进行浓缩式概述。要求：

1. 对原文的故事脉络和背景进行概述性描述
2. 删除重复描述、冗余修饰和旁枝末节
3. 语言精炼，用最少的字数传达最完整的信息
4. 输出概述的目标长度：不超过 {max_chars} 字
5. 保持原文的语气基调（如恐怖、悬疑等）
6. 输出文本用于帮助kp/游戏管理者 指导整体游戏进行
7. 直接输出概述文本，不要包含任何解释、评价或 markdown 标记{focus_hint}

"""

    response = client.chat.completions.create(
        model="deepseek-v4-pro",
        messages=[
            {"role": "system", "content": "你是一个专业的模组写作者，擅长将长文浓缩为故事概述。仅输出概述结果，不附加任何额外说明。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=16284,
        reasoning_effort="high",
        extra_body={"thinking": {"type": "enabled"}}
    )

    summary = response.choices[0].message.content.strip()

    print(f"[概述完成] 原文 {len(content)} 字 -> 概述 {len(summary)} 字 "
          f"(压缩比 {len(summary)/max(len(content),1)*100:.1f}%)")

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(summary)
        print(f"已保存概述至: {output_path}")

    return summary
