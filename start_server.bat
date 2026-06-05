@echo off
chcp 65001 >nul
title AI Interview System - HTTPS Backend Server

echo ========================================
echo AI Interview System - Starting HTTPS Backend
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

if not exist "certs\server.crt" (
    echo [WARN] certs\server.crt not found. Generating self-signed certificate...
    "venv\Scripts\python.exe" "scripts\generate_self_signed_cert.py"
)

if not exist "certs\server.key" (
    echo [ERROR] certs\server.key not found.
    echo [ERROR] Please run generate_https_cert.bat.
    pause
    exit /b 1
)

echo [INFO] Starting Django ASGI server with HTTPS and WebSocket support...
echo [INFO] AI text model: qwen3.5-omni-plus
echo [INFO] AI realtime model: qwen3.5-omni-plus-realtime
echo [INFO] Realtime voice: Sunnybobi
echo [INFO] Server bind: https://0.0.0.0:8000
echo [INFO] LAN clients should use: https://YOUR_LAN_IP:8000
echo [INFO] HR page: https://YOUR_LAN_IP:8000/api/ai-interview/hr/
echo [INFO] WebSocket endpoint: wss://YOUR_LAN_IP:8000/ws/voice-interview/
echo.
echo [INFO] For microphone access on other computers:
echo [INFO] 1. Open the HTTPS URL.
echo [INFO] 2. If the browser warns about the certificate, trust/import certs\server.crt.
echo [INFO] 3. Allow microphone permission when prompted.
echo.
echo Press Ctrl+C to stop server
echo.

venv\Scripts\python.exe -m daphne -e ssl:8000:privateKey=certs/server.key:certKey=certs/server.crt:interface=0.0.0.0 config.asgi:application

echo.
echo [INFO] Server stopped
pause
