@echo off
setlocal
set "HERE=%~dp0"
set "PYTHONPATH=%HERE%src"
python -B -m ag gui "%HERE%..\CartridgeFlow"
endlocal
