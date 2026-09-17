@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%~dp0src
set "PY=python"
where python >nul 2>&1 || set "PY=py -3"
if "%~1"=="" (
  %PY% -m ag gui
) else (
  %PY% -m ag gui "%~1"
)
