
@echo off
chcp 65001 >nul
title COC 调查员创建

echo.
echo   ═══════════════════════════════════════
echo     COC 7th 调查员创建 — 车卡模拟器
echo   ═══════════════════════════════════════
echo.

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   [错误] 未找到 Python，请先安装 Python 3.10+
    echo   https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

:: 检查依赖（首次运行时提醒）
python -c "import openai" >nul 2>&1
if %errorlevel% neq 0 (
    echo   [提示] 检测到缺失依赖，正在安装...
    pip install openai python-docx pypdf
    if %errorlevel% neq 0 (
        echo   [错误] 依赖安装失败，请手动运行: pip install openai python-docx pypdf
        pause
        exit /b 1
    )
    echo   [完成] 依赖安装成功
    echo.
)

:: 检查 .env 文件
if not exist ".env" (
    echo   [警告] 未找到 .env 文件，请确保已配置 DEEPSEEK_API_KEY
    echo   在项目根目录创建 .env 文件，内容为:
    echo     DEEPSEEK_API_KEY=你的API密钥
    echo.
)

:: 启动
echo   正在启动...
echo.
python frontend\server.py

:: 如果异常退出
if %errorlevel% neq 0 (
    echo.
    echo   [错误] 服务器启动失败
    pause
)
