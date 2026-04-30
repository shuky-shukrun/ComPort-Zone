@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_tests.ps1" %*
exit /b %ERRORLEVEL%
