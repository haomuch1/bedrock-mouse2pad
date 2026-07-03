@echo off
REM Double-click this to remove mouse2pad.
echo Uninstalling bedrock-mouse2pad...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0uninstall.ps1"
echo.
pause
