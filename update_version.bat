@echo off
setlocal

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\update_version.ps1" %*

if errorlevel 1 (
    echo.
    echo Version update failed.
    pause
    exit /b 1
)
