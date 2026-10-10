@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 goto baddir
if not "%~1"=="" (
  cd /d "%~1"
  if errorlevel 1 goto baddir
)
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
set "CFG="
for /f "delims=" %%P in ('%PY% -B -m ag config') do set "CFG=%%P"
if not defined CFG (
  echo 没有得到配置文件路径。
  pause
  exit /b 1
)
start "" notepad "%CFG%"
goto :eof
:baddir
echo 进不了这个目录。
pause
exit /b 1
