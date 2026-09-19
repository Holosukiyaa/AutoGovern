@echo off
setlocal
set "HERE=%~dp0"
set "PYTHONPATH=%HERE%src"
if "%~1"=="" (
  python -B -m ag gui "%HERE%."
) else (
  python -m ag gui "%~1"
)
endlocal
