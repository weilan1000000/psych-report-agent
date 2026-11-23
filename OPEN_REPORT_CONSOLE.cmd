@echo off
setlocal
set "PROJECT_ROOT=%~dp0"
if not exist "%PROJECT_ROOT%report_app\launcher.py" (
  echo ERROR: Extract the complete ZIP before opening the report console.
  pause
  exit /b 2
)
cd /d "%PROJECT_ROOT%"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
  if errorlevel 1 (
    echo.
    echo ERROR: The local Python environment is invalid or belongs to another computer.
    echo Run SETUP_FIRST_TIME.cmd to repair it automatically.
    pause
    exit /b 3
  )
  ".venv\Scripts\python.exe" -m report_app.launcher
) else (
  echo.
  echo ERROR: The local Python environment has not been installed.
  echo Run SETUP_FIRST_TIME.cmd first.
  pause
  exit /b 3
)
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" pause
exit /b %APP_EXIT%
