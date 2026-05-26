@echo off
chcp 65001 >nul
title AI Interview System - Backend Server

echo ========================================
echo AI Interview System - Starting Backend
echo ========================================
echo.

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found!
    echo [ERROR] Please run setup_venv.ps1 first
    pause
    exit /b 1
)

if not exist ".env" (
    echo [WARN] .env file not found, using default config
) else (
    echo [INFO] Loaded .env configuration file
)

echo [INFO] Starting Django ASGI server with WebSocket support...
echo [INFO] Server address: http://localhost:8000
echo [INFO] Test page: http://localhost:8000/api/ai-interview/test/
echo [INFO] WebSocket endpoint: ws://localhost:8000/ws/voice-interview/
echo.
echo Press Ctrl+C to stop server
echo.

venv\Scripts\python.exe -m daphne -b 0.0.0.0 -p 8000 config.asgi:application

echo.
echo [INFO] Server stopped
pause