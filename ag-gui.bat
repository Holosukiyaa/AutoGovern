@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY (
  where py >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
  echo 找不到运行环境，请先安装解释器并加入系统路径。
  pause
  exit /b 1
)
if "%~1"=="" (
  %PY% -B -m ag gui
) else (
  %PY% -B -m ag gui "%~1"
)
if errorlevel 1 pause
endlocal
