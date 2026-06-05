@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found.
    echo [ERROR] Please run setup_venv.ps1 first.
    pause
    exit /b 1
)

echo ========================================
echo Generate local HTTPS self-signed cert
echo ========================================
echo.
echo [INFO] Extra SAN entries can be added as arguments.
echo [INFO] Example: generate_https_cert.bat 192.168.1.20 interview.local
echo.

set EXTRA_SAN=
:loop
if "%~1"=="" goto run
set EXTRA_SAN=%EXTRA_SAN% --san "%~1"
shift
goto loop

:run
"%~dp0venv\Scripts\python.exe" "%~dp0scripts\generate_self_signed_cert.py" %EXTRA_SAN%

echo.
echo [INFO] Done. If another computer still sees a certificate warning,
echo [INFO] import certs\server.crt into that computer's Trusted Root Certification Authorities.
pause
