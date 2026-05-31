@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

cd /d "%~dp0.."

echo ============================================
echo  TRPG助手 打包脚本
echo ============================================
echo.

REM ---- 检查 pyinstaller ----
python -c "import PyInstaller" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 未找到 PyInstaller，请先安装：pip install pyinstaller
    pause
    exit /b 1
)

REM ---- 检查必要模块 ----
echo [检查] 验证依赖模块...
python -c "import fastapi, uvicorn, jinja2, openai, websockets, webview, docx, PyPDF2" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 缺少必要的 Python 模块。
    pause
    exit /b 1
)
echo [检查] 所有依赖模块已就绪。
echo.

REM ---- 清理旧构建 ----
echo [清理] 删除旧的 build/dist 目录...
if exist "dist\TRPG助手" rmdir /s /q "dist\TRPG助手"
if exist "build\TRPG助手" rmdir /s /q "build\TRPG助手"
if exist "TRPG助手.spec" del /q "TRPG助手.spec"

REM ---- 运行 PyInstaller ----
echo [打包] 正在运行 PyInstaller（可能需要几分钟）...
echo.

python -m PyInstaller --onedir --noconsole --name "TRPG助手" --add-data "frontend/templates;frontend/templates" --add-data "frontend/static;frontend/static" --add-data "data/library;data/library" --add-data "data/modules;data/modules" --add-data "data/templates;data/templates" --add-data "data/occupations.json;data" --add-data "data/skill_checks.json;data" --add-data "data/stress_profile.json;data" --add-data "data/saves;data/saves" --add-data "src;src" --hidden-import fastapi --hidden-import uvicorn --hidden-import jinja2 --hidden-import openai --hidden-import websockets --hidden-import docx --hidden-import PyPDF2 --hidden-import webview --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto frontend/server.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [错误] PyInstaller 打包失败。
    pause
    exit /b 1
)

echo.
echo ============================================
echo  打包完成！
echo ============================================
echo.
echo 输出目录：%CD%\dist\TRPG助手\
echo.
echo 启动方式：双击 dist\TRPG助手\TRPG助手.exe
echo.
echo 注意：
echo - 打包后首次启动可能被 Windows Defender 拦截
echo - 如遇杀软误报，请添加白名单
echo - data\modules\supplements\ 已排除在打包外
echo.
pause
