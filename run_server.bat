@echo off
cd /d "%~dp0"
"%~dp0venv\Scripts\python.exe" -m daphne -b 0.0.0.0 -p 8000 config.asgi:application
