@echo off
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set CORS_ALLOW_ORIGIN=http://localhost:5173;http://localhost:8080
cd /d "%~dp0"
venv\Scripts\python.exe -m uvicorn open_webui.main:app --port 8080 --host 0.0.0.0 --reload
