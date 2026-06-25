@echo off
setlocal
REM ImmoManager Pro - safe Windows 11 starter.
REM Pass arguments through to scripts\start_windows.ps1, for example:
REM   start.bat -Port 9000 -Seed

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_windows.ps1" %*
exit /b %errorlevel%
