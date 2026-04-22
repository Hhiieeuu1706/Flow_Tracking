@echo off
setlocal

set "PYTHON_EXE=e:\Trade folder\Trading_analyze\.venv\Scripts\python.exe"
set "APP_PATH=e:\Trade folder\Trading_analyze\flow_tracking\backend\app.py"
set "LOG_DIR=e:\Trade folder\Trading_analyze\flow_tracking\data"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "PREFETCH_LOG=%LOG_DIR%\prefetch_start.log"
set "FRONTEND_DIR=e:\Trade folder\Trading_analyze\flow_tracking\frontend"
set "PREFETCH_DAYS=360"
set "PREFETCH_CONFIRM=0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -and ($_.CommandLine -match 'flow_tracking[\\/]+backend[\\/]+app\\.py') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; Start-Sleep -Milliseconds 700" >nul 2>&1

REM Build frontend so backend serves latest UI code from dist/
echo [INFO] Building frontend...
pushd "%FRONTEND_DIR%"
call npm run build
if %ERRORLEVEL% NEQ 0 (
  echo [WARN] Frontend build failed; continuing with existing dist.
)
popd

REM ICMarkets MT5 terminal (ensure MT5 terminal is running before starting backend)
REM ICMarkets data path: C:\Users\PC\AppData\Roaming\MetaQuotes\Terminal\010E047102812FC0C18890992854220E
echo [INFO] Make sure ICMarkets MT5 terminal is running...
echo [INFO] ICMarkets MT5 terminal path: C:\Program Files\MetaTrader 5 IC Markets Global\terminal64.exe

REM Wait a bit for MT5 to start
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 5" >nul 2>&1

REM Prefetch missing H1 cache (partial range) before opening web
echo [INFO] Running prefetch (%PREFETCH_DAYS% days)...
echo [INFO] Prefetch log: %PREFETCH_LOG%
if "%PREFETCH_CONFIRM%"=="1" (
  set "NO_PAUSE="
) else (
  set "NO_PAUSE=1"
)
call "%~dp0backend\fetch_flow_mt5.bat" %PREFETCH_DAYS% >> "%PREFETCH_LOG%" 2>&1
set "NO_PAUSE="
if %ERRORLEVEL% NEQ 0 (
  echo [WARN] Prefetch failed; starting server anyway.
  echo [WARN] See prefetch log: %PREFETCH_LOG%
)
if %ERRORLEVEL% EQU 0 (
  echo [INFO] Prefetch completed.
)

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Python not found: %PYTHON_EXE%
  exit /b 1
)

echo [INFO] Starting backend with: %PYTHON_EXE%
start "" http://127.0.0.1:5057
echo [INFO] Backend logs will continue in this window. Press Ctrl+C to stop.
"%PYTHON_EXE%" -u "%APP_PATH%"
set "RC=%ERRORLEVEL%"
echo.
echo [INFO] Backend exited with code %RC%.
echo Press any key to close...
pause >nul

