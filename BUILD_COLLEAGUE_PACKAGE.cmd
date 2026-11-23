@echo off
cd /d "%~dp0"
title Psych Report Agent - Build Colleague Package
powershell -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build_colleague_package.ps1"
if errorlevel 1 (
  echo.
  echo Package build failed.
  pause
  exit /b 1
)
pause
