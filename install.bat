@echo off
REM Double-click this to install mouse2pad (no need to know PowerShell).
REM It just runs install.ps1 with the execution policy relaxed for this run only.
echo Installing bedrock-mouse2pad...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
echo.
pause
