@echo off
setlocal

REM Fetch missing H1 bars into backend cache, then exit.

set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE="

REM Prefer repo .venv python (same as other apps)
set "VENV_PY=%SCRIPT_DIR%..\..\.venv\Scripts\python.exe"
if exist "%VENV_PY%" set "PYTHON_EXE=%VENV_PY%"
if "%PYTHON_EXE%"=="" set "PYTHON_EXE=python"

set "FETCH_SCRIPT=%SCRIPT_DIR%fetch_flow_mt5.py"
if not exist "%FETCH_SCRIPT%" (
  echo [ERROR] Script not found: %FETCH_SCRIPT%
  exit /b 1
)

set "DAYS=30"
if not "%~1"=="" set "DAYS=%~1"

echo [INFO] Prefetching MT5 H1 cache for last %DAYS% day(s)...
"%PYTHON_EXE%" "%FETCH_SCRIPT%" --days %DAYS%
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo [ERROR] Prefetch failed (exit=%RC%).
  echo.
  echo [INFO] fetch_flow_mt5 finished with exit=%RC%.
)
exit /b %RC%

