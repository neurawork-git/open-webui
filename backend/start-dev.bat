@echo off
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set CORS_ALLOW_ORIGIN=http://localhost:5173;http://localhost:8080

cd /d "%~dp0"

echo Starting Open WebUI backend on http://localhost:8080
echo Press Ctrl+C to stop

call venv\Scripts\activate.bat
python -m uvicorn open_webui.main:app --port 8080 --host 0.0.0.0 --reload
