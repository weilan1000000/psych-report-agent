@echo off
setlocal
set "PROJECT_ROOT=%~dp0"
set "SETUP_SCRIPT=%PROJECT_ROOT%scripts\setup_first_time.ps1"
title Psych Report Agent - First-Time Setup

if not exist "%SETUP_SCRIPT%" (
  echo.
  echo ERROR: The complete project folder was not found.
  echo.
  echo Do not run SETUP_FIRST_TIME.cmd inside the ZIP preview window.
  echo Right-click the ZIP file, choose "Extract All", open the extracted folder,
  echo and then run SETUP_FIRST_TIME.cmd again.
  echo.
  pause
  exit /b 2
)

cd /d "%PROJECT_ROOT%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SETUP_SCRIPT%" -SkipLaunch %*
set "SETUP_EXIT=%ERRORLEVEL%"
if not "%SETUP_EXIT%"=="0" (
  echo.
  echo Setup failed. See output\setup\setup.log for details.
  echo Press any key to open the setup log.
  pause >nul
  if exist "%PROJECT_ROOT%output\setup\setup.log" (
    start "" notepad.exe "%PROJECT_ROOT%output\setup\setup.log"
  )
  exit /b %SETUP_EXIT%
)
echo.
echo ================================================
echo Setup completed successfully.
echo Press any key to open Psych Report Console now.
echo ================================================
pause >nul
call "%PROJECT_ROOT%OPEN_REPORT_CONSOLE.cmd"
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" (
  echo.
  echo Setup succeeded, but the report console could not be opened.
  echo Double-click OPEN_REPORT_CONSOLE.cmd and send the displayed error if needed.
  pause
)
exit /b %APP_EXIT%
