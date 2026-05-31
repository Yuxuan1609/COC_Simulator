@echo off
REM Nuitka standalone build for TRPG助手
REM
REM 前置条件:
REM   - Visual Studio 2022/2026 + Desktop C++ 工作负载
REM   - MSVC cl.exe >= 14.5
REM   - Windows SDK 10.0.26100+

set "CL=/utf-8"

python -m nuitka --standalone --windows-console-mode=disable ^
  --msvc=14.5 --output-dir=dist_nuitka ^
  --include-data-dir=frontend/templates=frontend/templates ^
  --include-data-dir=frontend/static=frontend/static ^
  --include-data-dir=data=data ^
  --include-data-files=src/config_llm.template.py=src/config_llm.template.py ^
  --include-data-files=src/config_llm.py=src/config_llm.py ^
  --include-package=pythonnet --include-package=clr ^
  --include-package-data=pythonnet ^
  --include-package-data=clr_loader ^
  --no-deployment-flag=excluded-module-usage ^
  --assume-yes-for-downloads ^
  frontend/server.py

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ==== Build OK ====
    echo Output: dist_nuitka\server.dist\server.exe
) else (
    echo.
    echo ==== Build FAILED (exit code %ERRORLEVEL%) ====
)
