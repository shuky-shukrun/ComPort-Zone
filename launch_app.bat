@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch_app.ps1" %*
exit /b %ERRORLEVEL%
