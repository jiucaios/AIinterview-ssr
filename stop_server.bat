@echo off
chcp 65001 >nul
title AI Interview System - Stop Backend Server

echo ========================================
echo AI Interview System - Stopping Backend
echo ========================================
echo.

set "port=8000"
set "found=0"

echo [INFO] Looking for Django server process on port %port%...
echo.

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :%port% ^| findstr LISTENING') do (
    set "pid=%%a"
    set "found=1"
    echo [INFO] Found Django server process: PID=%%a
    echo [INFO] Terminating process...
    taskkill /F /PID %%a
    if %errorlevel% equ 0 (
        echo [INFO] Successfully terminated process %%a
    ) else (
        echo [ERROR] Failed to terminate process %%a
    )
)

if %found% equ 0 (
    echo [WARN] No Django server found running on port %port%
)

echo.
echo [INFO] Operation completed
pause