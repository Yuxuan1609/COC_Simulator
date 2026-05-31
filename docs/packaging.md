# 打包分析文档

> 日期：2026-05-31（更新）

## 启动入口

**主入口**：`frontend/server.py`

```python
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)
    webview.create_window("TRPG 调查员助手", url, ...)
    webview.start()
```

- FastAPI + Jinja2 + HTMX 全栈 Web 应用
- 双击启动 → pywebview 嵌入原生窗口 → 玩家在浏览器中游玩
- `run_game.py` 是 CLI 纯文本入口，不面向普通玩家

## 需要打包的目录

| 路径 | 内容 | 必需 |
|------|------|------|
| `src/` | 所有 Python 源码（game engine、管线、监控） | ✓ |
| `frontend/templates/` | Jinja2 HTML 模板 | ✓ |
| `frontend/static/css/` | tailwind-built.css | ✓ |
| `frontend/static/js/` | assets.js 背景轮播 | ✓ |
| `frontend/static/fonts/` | 捆绑字体（当前为空，预留） | — |
| `frontend/static/assets/` | 页面背景图片/视频素材 | ✓ |
| `frontend/static/uploads/` | 车卡头像上传目录 | 运行时创建 |
| `data/library/core/` | weapons.json / enemies.json / bosses.json 等 | ✓ |
| `data/modules/` | 模组 L1/L2/L3 JSON（可选，用户可自行放置） | 打包空目录 |
| `data/occupations.json` | 职业数据 | ✓ |
| `data/skill_checks.json` | 技能列表 | ✓ |
| `data/stress_profile.json` | 压力配置 | ✓ |
| `data/autosave/` | 自动存档输出 | 运行时创建 |

## 不需要打包的目录

| 路径 | 说明 |
|------|------|
| `素材/` | 原始素材库，已筛选到 `frontend/static/assets/` |
| `tests/` | 测试代码 |
| `notebooks/` | Jupyter 开发笔记 |
| `docs/` | 设计文档 |
| `logs/` | 运行时日志，运行后创建 |
| `.git/` `.idea/` `.vscode/` `.claude/` `.superpowers/` | 开发工具配置 |

## Hidden Import

以下包通过 `importlib` 或字符串动态导入，PyInstaller 无法自动检测：

```
--hidden-import fastapi
--hidden-import uvicorn
--hidden-import jinja2
--hidden-import openai
--hidden-import websockets
--hidden-import python-docx
--hidden-import PyPDF2
--hidden-import webview
--hidden-import uvicorn.loops.auto
--hidden-import uvicorn.protocols.http.auto
```

## 打包命令

```bash
pyinstaller --onedir --noconsole --name "TRPG助手" ^
  --add-data "frontend/templates;frontend/templates" ^
  --add-data "frontend/static;frontend/static" ^
  --add-data "data/library;data/library" ^
  --add-data "data/modules;data/modules" ^
  --add-data "data/templates;data/templates" ^
  --add-data "data/occupations.json;data" ^
  --add-data "data/skill_checks.json;data" ^
  --add-data "data/stress_profile.json;data" ^
  --add-data "data/saves;data/saves" ^
  --add-data "src;src" ^
  --hidden-import fastapi ^
  --hidden-import uvicorn ^
  --hidden-import jinja2 ^
  --hidden-import openai ^
  --hidden-import websockets ^
  --hidden-import python-docx ^
  --hidden-import PyPDF2 ^
  --hidden-import webview ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols.http.auto ^
  frontend/server.py
```

> **注意**：`--add-data` 不包含 `data/modules/supplements/`（运行时产物，不随分发）。  
> `data/debug/`、`data/output/`、`data/autosave/` 等运行时目录也不在打包范围内。

分发时用户拿到 `dist/TRPG助手/` 文件夹，双击 `TRPG助手.exe` 即可。

## 启动后行为

1. 自动创建 `src/config_llm.py`（从模板，若不存在）
2. 启动 uvicorn 127.0.0.1:8080
3. pywebview 弹出原生窗口（1280×800），加载 `http://localhost:8080/`
4. 用户在启动页配置 API Key → 开始游戏

## pywebview 集成（已实现）

已集成 `pywebview` 嵌入原生窗口：

- `frontend/server.py` 使用 `webview.create_window()` + `webview.start()`
- 打包命令已包含 `--hidden-import webview`
- 优点：无地址栏/刷新按钮、干净的原生窗口体验

## 已知问题

- `frontend/static/assets/` 素材文件约 50MB（含视频），可考虑单独提供"素材包"
- `frontend/static/fonts/` 当前为空目录，如需要捆绑字体请自行放入
- Windows Defender 可能拦截 `--onedir` 模式，用户需手动加白名单（误报率低于 `--onefile`）
