@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_dev.ps1" %*
exit /b %ERRORLEVEL%
