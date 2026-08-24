"""
通用工具：文件解析 + Token 估算。
"""

import os
import random
import re


# ── 文件解析 ──

def parser(file_path: str) -> str:
    """解析 Word (.docx) 或 PDF (.pdf) 文件，返回提取的纯文本。"""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")

    ext = os.path.splitext(file_path)[1].lower()

    if ext == '.docx':
        return _parse_docx(file_path)
    elif ext == '.doc':
        raise ValueError(
            "不支持旧版 .doc 格式，请用 Word 将文件另存为 .docx 后再试"
        )
    elif ext == '.pdf':
        return _parse_pdf(file_path)
    else:
        raise ValueError(f"不支持的文件格式: {ext}，仅支持 .docx 和 .pdf")


def _parse_docx(file_path: str) -> str:
    """解析 .docx 文件"""
    try:
        from docx import Document
    except ImportError:
        raise ImportError("请安装 python-docx: pip install python-docx")

    doc = Document(file_path)
    return "\n".join(para.text for para in doc.paragraphs)


def _parse_pdf(file_path: str) -> str:
    """解析 .pdf 文件，兼容 PyPDF2 新旧版本"""
    try:
        import PyPDF2
    except ImportError:
        raise ImportError("请安装 PyPDF2: pip install PyPDF2")

    PdfReader = getattr(PyPDF2, 'PdfReader', None) or getattr(PyPDF2, 'PdfFileReader', None)
    if PdfReader is None:
        raise ImportError("PyPDF2 版本过旧，请升级: pip install --upgrade PyPDF2")

    text_parts = []
    with open(file_path, 'rb') as f:
        reader = PdfReader(f)
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)

    if not text_parts:
        raise ValueError("PDF 未提取到文本，可能是扫描件或图片型 PDF")

    return "\n".join(text_parts)


# ── Token 估算 ──

def estimate_tokens(text: str) -> int:
    """
    粗略估算文本的 token 数量。
    中文字符约 1.5 token/字，英文/数字约 0.25 token/字符。
    """
    chinese_chars = len(re.findall(r'[一-鿿　-〿＀-￯]', text))
    other_chars = len(text) - chinese_chars
    return int(chinese_chars * 1.5 + other_chars * 0.25)


def estimate_and_truncate_context(
    content: str,
    extra_prompt_chars: int = 0,
    max_tokens: int = 300000,
    safety_margin: float = 0.95,
) -> str:
    """
    预估上下文 token 数，若超过 max_tokens 则截断 content 至限制内。

    参数:
        content: 主要内容文本
        extra_prompt_chars: prompt 模板中除 content 外的固定文本字符数
        max_tokens: token 上限（默认 300000）
        safety_margin: 安全余量系数
    """
    total_estimated = estimate_tokens(content) + estimate_tokens("x" * extra_prompt_chars)

    print(f"[Token 预估] content: {estimate_tokens(content):,} tokens")
    if extra_prompt_chars:
        print(f"[Token 预估] extra_prompt: {estimate_tokens('x' * extra_prompt_chars):,} tokens")
    print(f"[Token 预估] 合计: {total_estimated:,} tokens (上限: {max_tokens:,})")

    if total_estimated <= max_tokens:
        print("[Token 预估] 无需截断，直接使用原文")
        return content

    extra_tokens = estimate_tokens("x" * extra_prompt_chars)
    available_tokens = int(max_tokens * safety_margin) - extra_tokens

    if available_tokens <= 0:
        raise ValueError(f"extra_prompt 已占用 {extra_tokens:,} tokens，content 无可用空间")

    target_chars = int(available_tokens / 1.2)
    truncated = content[:target_chars]

    last_break = max(truncated.rfind("\n\n"), truncated.rfind("。"), truncated.rfind("\n"))
    if last_break > target_chars * 0.7:
        truncated = content[:last_break + 1]

    print(f"[Token 预估] 截断: {len(content):,} -> {len(truncated):,} chars "
          f"(估算 {estimate_tokens(truncated):,} tokens)")

    return truncated


# ── 掷骰 ──

def roll_dice(num: int, sides: int) -> int:
    """投 num 个 sides 面骰子求和"""
    if sides < 2:
        raise ValueError(f"sides must be >= 2, got {sides}")
    if num < 0:
        raise ValueError(f"num must be >= 0, got {num}")
    import random
    return sum(random.randint(1, sides) for _ in range(num))


def roll_formula(formula: str) -> int:
    """解析 NdM+K 骰式并掷骰；不匹配返回 0。judge/combat 的 heal 原子共用。"""
    m = re.match(r"^(\d*)D(\d+)([+-]\d+)?$", str(formula).strip().upper())
    if not m:
        return 0
    n = int(m.group(1) or 1)
    d = int(m.group(2))
    bonus = int(m.group(3) or 0)
    return sum(random.randint(1, d) for _ in range(n)) + bonus


def roll_d6(num: int) -> int:
    """投 num 个 6 面骰子求和"""
    return roll_dice(num, 6)


# ── 技能体系配置 ──

_SKILL_CONFIG_CACHE: dict | None = None


def load_skill_config(path: str | None = None) -> dict:
    """加载技能体系配置（技能/属性/legacy_map/attr_aliases/pseudo_skills），缓存。"""
    global _SKILL_CONFIG_CACHE
    if _SKILL_CONFIG_CACHE is None or path is not None:
        import json
        if path is None:
            path = os.path.join(os.path.dirname(__file__), "..", "data", "skill_config.json")
            path = os.path.normpath(path)
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if path is None:
            _SKILL_CONFIG_CACHE = cfg
        return cfg
    return _SKILL_CONFIG_CACHE


def normalize_skill_name(name: str) -> tuple[str, str]:
    """技能名归一单点。返回 (kind, value)：
    ("skill", 新技能名) / ("attr", 属性英文名) / ("pseudo", "DODGE") /
    ("ignore", 原名)（已废弃如母语） / ("unknown", 原名)（未识别）。
    顺序：新表精确 → legacy_map → 去括号重试 → 属性别名 → 伪技能 → unknown。
    """
    cfg = load_skill_config()
    name = (name or "").strip()
    if not name:
        return ("unknown", name)
    new_names = {s["name"] for s in cfg["skills"]}
    legacy = cfg.get("legacy_map", {})

    aliases = cfg.get("attr_aliases", {})
    pseudo = cfg.get("pseudo_skills", {})

    def _lookup(n: str) -> tuple[str, str] | None:
        if n in new_names:
            return ("skill", n)
        if n in legacy:
            mapped = legacy[n]
            return ("ignore", n) if mapped is None else ("skill", mapped)
        if n in aliases:
            return ("attr", aliases[n])
        if n in pseudo:
            return ("pseudo", pseudo[n])
        return None

    hit = _lookup(name)
    if hit:
        return hit
    stripped = re.sub(r"[（(][^)）]*[)）]", "", name).strip()
    if stripped != name:
        hit = _lookup(stripped)
        if hit:
            return hit
    return ("unknown", name)


# ── 技能检定定义加载 ──

def load_skill_checks(path: str | None = None) -> list:
    """加载技能检定定义表，返回列表 [{name, ...}, ...]。
    U9：默认数据源切换为 skill_config.json 的 skills 列表（兼容旧形状）。"""
    import json
    if path is None:
        return [dict(s) for s in load_skill_config()["skills"]]
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


_COC_SKILL_NAMES_CACHE: list[str] | None = None


def get_coc_skill_names() -> list[str]:
    """获取新 20 项技能名列表（缓存，从 data/skill_config.json 读取）。"""
    global _COC_SKILL_NAMES_CACHE
    if _COC_SKILL_NAMES_CACHE is None:
        _COC_SKILL_NAMES_CACHE = [s["name"] for s in load_skill_config()["skills"]]
    return _COC_SKILL_NAMES_CACHE
