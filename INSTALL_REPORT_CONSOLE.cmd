@echo off
setlocal
set "PROJECT_ROOT=%~dp0"
set "INSTALL_SCRIPT=%PROJECT_ROOT%scripts\install_report_console_shortcuts.ps1"
if not exist "%INSTALL_SCRIPT%" (
  echo ERROR: Extract the complete ZIP before installing shortcuts.
  pause
  exit /b 2
)
cd /d "%PROJECT_ROOT%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_SCRIPT%"
set "INSTALL_EXIT=%ERRORLEVEL%"
if not "%INSTALL_EXIT%"=="0" pause
exit /b %INSTALL_EXIT%
