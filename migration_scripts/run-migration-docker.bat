@echo off
echo ========================================
echo   Open WebUI Migration (Docker Version)
echo ========================================
echo.

REM Check if webui.db exists
if not exist "webui.db" (
    echo [ERROR] webui.db not found in current folder!
    echo Please copy webui.db to: %~dp0
    pause
    exit /b 1
)

echo Source: webui.db
echo Target: PostgreSQL at 10.10.135.12
echo.

set /p confirm="Continue? (y/n): "
if /i not "%confirm%"=="y" (
    echo Cancelled.
    exit /b 0
)

echo.
echo [INFO] Running migration in Docker container...
echo.

docker run --rm ^
    -v "%~dp0:/data" ^
    -w /data ^
    -e SQLITE_PATH=/data/webui.db ^
    -e PG_HOST=10.10.135.12 ^
    -e PG_PORT=5432 ^
    -e PG_USER=dbadmin ^
    -e PG_PASSWORD=Blinked6-Defiling ^
    -e PG_DATABASE=openwebui ^
    python:3.11-slim ^
    bash -c "pip install -q psycopg2-binary && python /data/migrate_sqlite_to_postgres.py"

echo.
if errorlevel 1 (
    echo [WARN] Migration completed with errors.
) else (
    echo [OK] Migration completed!
)

pause
