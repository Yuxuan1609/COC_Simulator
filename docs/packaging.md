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
--hidden-import docx
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
  --add-data "data/investigator;investigator" ^
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
  --hidden-import docx ^
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

## PyInstaller 运行时路径

`frontend/_paths.py` 统一管理 dev / PyInstaller / Nuitka 三种模式的路径解析：

```python
# frontend/_paths.py
_exe_dir = Path(sys.executable).parent
IS_FROZEN = getattr(sys, 'frozen', False) or _exe_dir.name.endswith('.dist')

if IS_FROZEN:
    _bundle = Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS') else _exe_dir
    PROJECT_ROOT = _bundle                    # _internal/ 或 .dist/
    FRONTEND_DIR = _bundle / "frontend"       # _internal/frontend/ 或 .dist/frontend/
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    FRONTEND_DIR = PROJECT_ROOT / "frontend"
```

所有 6 个路由器文件（`frontend/routers/*.py`）通过 `from frontend._paths import PROJECT_ROOT, FRONTEND_DIR` 统一导入，不再各自用 `Path(__file__)` 计算路径。

### 打包器检测差异

| 打包器 | `sys.frozen` | `sys._MEIPASS` | `__compiled__` | 检测方式 |
|--------|:--:|:--:|:--:|------|
| PyInstaller | ✓ | ✓ | ✗ | `sys.frozen` |
| Nuitka 4.1.2 | ✗ | ✗ | ✗ | `sys.executable.parent` 以 `.dist` 结尾 |

## Nuitka 打包

### 环境要求

- **Nuitka** ≥ 4.1（当前 4.1.2）
- **Python** 3.14（实验性支持，推荐 3.13）
- **Visual Studio** 2022/2026 + **Desktop C++ 工作负载**
- **MSVC** cl.exe ≥ 14.5
- **Windows SDK** 10.0.26100+（`D:\Windows Kits\10\`）

### 构建命令

```powershell
# VS 编码修复（非英语 VS 必需）
$env:CL = "/utf-8"

python -m nuitka --standalone --windows-console-mode=disable `
  --msvc=14.5 --output-dir=dist_nuitka `
  --include-data-dir=frontend/templates=frontend/templates `
  --include-data-dir=frontend/static=frontend/static `
  --include-data-dir=data=data `
  --include-data-files=src/config_llm.template.py=src/config_llm.template.py `
  --include-data-files=src/config_llm.py=src/config_llm.py `
  --include-package=pythonnet --include-package=clr `
  --include-package-data=pythonnet `
  --include-package-data=clr_loader `
  --no-deployment-flag=excluded-module-usage `
  --assume-yes-for-downloads `
  frontend/server.py
```

输出在 `dist_nuitka/server.dist/server.exe`。

### Nuitka 注意点

1. **Nuitka 4.1.2 不设置 `sys.frozen`、`sys._MEIPASS`、`__compiled__`**。项目通过 `sys.executable.parent` 以 `.dist` 结尾来识别 Nuitka 模式（见 `frontend/_paths.py`）
2. **非英语 Visual Studio** 需要 `$env:CL = "/utf-8"` 否则 C4819 编码错误
3. **`--include-data-dir=src=src` 无效**：Nuitka 排除 `.py` 文件，需用 `--include-data-files` 逐个添加
4. **`--no-deployment-flag=excluded-module-usage`**：避免 webview 平台模块被排除
5. **Python 3.14 为实验性支持**，可能出现未预期的兼容性问题
6. **首次构建需下载 Dependency Walker**（`--assume-yes-for-downloads`）
7. `_paths.py` 由 Nuitka 编译为 C 代码，无需作为数据文件包含
8. **pywebview 平台子模块由 Nuitka pywebview 插件自动处理**，无需手动 `--include-module`。手动指定反而会因与插件决策冲突导致 `FATAL: Conflict between user and plugin decision` 错误
9. **pythonnet 运行时 DLL 需显式包含数据**：`--include-package=pythonnet` 只包含 Python 模块，不包含 `.dll` 等非 Python 数据文件。必须加 `--include-package-data=pythonnet` 才会把 `runtime/System.*.dll` 打包进去。同理 `clr_loader` 需要 `--include-package-data=clr_loader`

### 与 PyInstaller 输出对比

| 项目 | PyInstaller | Nuitka |
|------|------------|--------|
| 输出结构 | `dist/TRPG助手/TRPG助手.exe` + `_internal/` | `dist_nuitka/server.dist/server.exe` |
| exe 大小 | ~14 MB (stub) | ~46 MB (compiled) |
| 总大小 | ~157 MB | ~156 MB |
| 启动速度 | 解包 .pyc（慢） | 原生 C（快） |
| `src/` 数据 | 通过 `--add-data` 完整包含 | 仅 `config_llm.*` 通过 `--include-data-files`

已集成 `pywebview` 嵌入原生窗口：

- `frontend/server.py` 使用 `webview.create_window()` + `webview.start()`
- 打包命令已包含 `--hidden-import webview`
- 优点：无地址栏/刷新按钮、干净的原生窗口体验

## 已知问题

- `frontend/static/assets/` 素材文件约 50MB（含视频），可考虑单独提供"素材包"
- `frontend/static/fonts/` 当前为空目录，如需要捆绑字体请自行放入
- Windows Defender 可能拦截 `--onedir` 模式，用户需手动加白名单（误报率低于 `--onefile`）
