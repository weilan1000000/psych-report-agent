@echo off
setlocal
set "PROJECT_ROOT=%~dp0"
set "STOP_SCRIPT=%PROJECT_ROOT%scripts\stop_report_app.ps1"
if not exist "%STOP_SCRIPT%" (
  echo ERROR: The complete extracted project folder was not found.
  pause
  exit /b 2
)
cd /d "%PROJECT_ROOT%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%STOP_SCRIPT%"
set "STOP_EXIT=%ERRORLEVEL%"
if not "%STOP_EXIT%"=="0" pause
exit /b %STOP_EXIT%
