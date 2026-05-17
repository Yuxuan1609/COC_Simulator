"""
TRPG UI 显示模块 —— HTML/CSS 样式与 IPython.display 输出函数。

从 notebook_simplified.ipynb 拆分，不包含游戏逻辑。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scenario_core import ScenarioWorld

from IPython.display import HTML, display, clear_output


# ═══════════════════════════════════════════════════════════════
#  样式常量
# ═══════════════════════════════════════════════════════════════

STYLE = """
<style>
  .trpg-root { font-family: 'Noto Serif SC', 'SimSun', 'Songti SC', serif; line-height: 1.8; }
  .trpg-narrative {
    background: linear-gradient(180deg, #1c1410 0%, #16110e 100%);
    border-left: 3px solid #6b3a2a;
    padding: 18px 22px; margin: 10px 0; border-radius: 0 6px 6px 0;
    color: #d4c5a0; font-size: 14px;
    box-shadow: 0 2px 8px rgba(0,0,0,.3);
  }
  .trpg-narrative::before { content: \"◆ KP 叙述 ◆\"; display: block;
    color: #8b5a3c; font-size: 10px; letter-spacing: 3px; margin-bottom: 8px;
    border-bottom: 1px solid #3a2218; padding-bottom: 6px; }
  .trpg-scene {
    background: #12161a; border: 1px solid #2a3640; border-radius: 6px;
    padding: 16px 20px; margin: 10px 0; color: #bcc8d0;
  }
  .trpg-scene .location { color: #7a9eb3; font-weight: bold; font-size: 15px;
    border-bottom: 1px solid #1e2d38; padding-bottom: 8px; margin-bottom: 10px; }
  .trpg-scene .section-title { color: #5a8090; font-size: 11px; letter-spacing: 2px;
    margin: 10px 0 4px 0; }
  .trpg-scene .item { color: #8aa4b0; margin: 3px 0 3px 8px; }
  .trpg-system {
    background: #111; border: 1px solid #333; border-radius: 4px;
    padding: 8px 14px; margin: 4px 0; color: #777; font-size: 12px;
  }
  .trpg-system.warn {
    border-color: #5a3a1a; color: #c9a060; background: #1a1410;
  }
  .trpg-system.event {
    border-color: #6b2020; color: #c97070; background: #1a1010;
  }
  .trpg-prompt {
    color: #888; font-size: 12px; margin-top: 8px;
  }
  .trpg-debug {
    background: #0a0a0a; border: 1px dashed #333; border-radius: 4px;
    padding: 10px 14px; margin: 4px 0; color: #555; font-size: 11px;
    font-family: 'Consolas', 'Courier New', monospace; white-space: pre-wrap;
  }
  .trpg-input-area {
    margin: 16px 0 4px 0; padding: 12px 16px;
    border: 1px solid #2a2a2a; border-left: 3px solid #4a6a7a;
    border-radius: 0 4px 4px 0;
    background: #0e1114;
  }
  .trpg-input-area .turn-badge {
    display: inline-block; background: #1e2d38; color: #6a8a9a;
    font-size: 10px; padding: 2px 8px; border-radius: 3px;
    margin-right: 10px; letter-spacing: 1px;
  }
  .trpg-input-area .location-tag {
    display: inline-block; color: #7a9eb3; font-size: 11px;
  }
  .trpg-input-area .prompt-text {
    display: block; color: #8aa0b0; font-size: 14px; margin-top: 8px;
    font-weight: bold;
  }
  .trpg-turn-sep {
    border: none; border-top: 1px solid #1a1a1a;
    margin: 20px 0 10px 0; padding: 0;
  }
</style>
"""


# ═══════════════════════════════════════════════════════════════
#  内部工具
# ═══════════════════════════════════════════════════════════════

def _html(content: str, klass: str = "") -> str:
    """生成一次性的 HTML 块"""
    wrapper = f'<div class="trpg-root">{STYLE}<div class="{klass}">{content}</div></div>'
    return wrapper


def _esc(text: str) -> str:
    """HTML 转义"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ═══════════════════════════════════════════════════════════════
#  输出函数
# ═══════════════════════════════════════════════════════════════

def display_narrative(text: str):
    """KP 叙述 —— 深色暖调卡片"""
    display(HTML(_html(_esc(text), "trpg-narrative")))


def display_split_result(brief: str, narrative: str):
    """拆分显示：简要结果 + 沉浸式叙事"""
    # 简要结果 —— 紧凑系统消息
    display(HTML(_html(
        f'<span style="color:#8aa0b0;">{_esc(brief)}</span>',
        "trpg-system"
    )))
    # 沉浸式叙事 —— 深色暖调卡片
    display(HTML(_html(_esc(narrative), "trpg-narrative")))


def display_scene(text: str):
    """场景摘要 —— 冷调蓝色面板（从文本自动解析）"""
    lines = text.split("\n")
    html_lines = ['<div class="trpg-scene">']
    for line in lines:
        line = _esc(line)
        if line.startswith("══════") and line.endswith("══════"):
            name = line.strip("═ ")
            html_lines.append(f'<div class="location">{name}</div>')
        elif line.startswith("═══") and line.endswith("═══"):
            html_lines.append(f'<div class="section-title">{line.strip("═ ")}</div>')
        elif line.startswith("  "):
            html_lines.append(f'<div class="item">{line}</div>')
        elif line.strip():
            html_lines.append(f'<div class="item">{line}</div>')
        else:
            html_lines.append('<br>')
    html_lines.append('</div>')
    display(HTML(_html("\n".join(html_lines), "")))


def display_system(text: str, level: str = "info"):
    """系统消息。level: info / warn / event"""
    cls = f"trpg-system {level}" if level != "info" else "trpg-system"
    display(HTML(_html(_esc(text), cls)))


def display_debug(text: str):
    """调试信息 —— 暗色代码块"""
    display(HTML(_html(_esc(text), "trpg-debug")))


# ═══════════════════════════════════════════════════════════════
#  输入区域
# ═══════════════════════════════════════════════════════════════

def display_input_area(turn: int, location: str):
    """在 input() 前显示美化的输入区域"""
    html = (
        f'<hr class="trpg-turn-sep">'
        f'<div class="trpg-input-area">'
        f'<span class="turn-badge">TURN {turn}</span>'
        f'<span class="location-tag">{_esc(location)}</span>'
        f'<span class="prompt-text">▸ 请输入你的行动：</span>'
        f'</div>'
    )
    display(HTML(_html(html, "")))


# ═══════════════════════════════════════════════════════════════
#  场景摘要 → HTML
# ═══════════════════════════════════════════════════════════════

def render_scene_to_html(world: ScenarioWorld) -> str:
    """将当前场景转为美观的 HTML 面板"""
    node = world._current_node()
    if not node:
        return "未知地点"

    parts = [f'<div class="trpg-scene">']
    parts.append(f'<div class="location">{world.current_location}</div>')
    parts.append(f'<p style="color:#bcc8d0;margin:6px 0;">{_esc(node.description)}</p>')

    exits = world.get_possible_exits()
    parts.append('<div class="section-title">可移动方向</div>')
    if exits:
        for e in exits:
            parts.append(f'<div class="item">→ <b>{_esc(e.target)}</b>：{_esc(e.method)}</div>')
    else:
        parts.append('<div class="item">（无路可走）</div>')

    interactions = world.get_available_interactions()
    done = world.completed_interactions.get(world.current_location, set())
    available = [i for i in interactions if i.name not in done]
    completed = [i for i in interactions if i.name in done]

    parts.append('<div class="section-title">可执行动作</div>')
    if available:
        for i, inter in enumerate(available, 1):
            parts.append(
                f'<div class="item">{i}. <b>[{_esc(inter.type)}] {_esc(inter.name)}</b>'
                f'<br><span style="color:#667a88;font-size:11px;">{_esc(inter.trigger)}</span></div>'
            )
    else:
        parts.append('<div class="item">（无新增可执行动作）</div>')
    if completed:
        parts.append(
            f'<div class="item" style="color:#556;margin-top:6px;">'
            f'已完成：{_esc(", ".join(completed))}</div>'
        )

    active = world.get_active_event_effects()
    if active:
        parts.append('<div class="section-title">已触发事件</div>')
        for name, impact in active:
            parts.append(
                f'<div class="item">◆ <b style="color:#c97070;">{_esc(name)}</b>'
                f'<br><span style="color:#776;font-size:11px;">{_esc(impact[:120])}...</span></div>'
            )

    parts.append('</div>')
    return "\n".join(parts)
