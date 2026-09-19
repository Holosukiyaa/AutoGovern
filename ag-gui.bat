@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
if "%~1"=="" (
  python -B -m ag gui
) else (
  python -B -m ag gui "%~1"
)
if errorlevel 1 pause
endlocal
