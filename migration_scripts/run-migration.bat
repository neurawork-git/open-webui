@echo off
setlocal enabledelayedexpansion

echo ========================================
echo   Open WebUI SQLite to PostgreSQL Migration
echo ========================================
echo.

REM Check if webui.db exists in current folder
if not exist "webui.db" (
    echo [ERROR] webui.db not found in current folder!
    echo.
    echo Please copy webui.db to this folder:
    echo   %~dp0
    echo.
    pause
    exit /b 1
)

echo Source: webui.db (in this folder)
echo Target: PostgreSQL at 10.10.135.12
echo.
echo [INFO] Checking Python installation...

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH!
    echo.
    echo Please install Python 3.8+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

REM Display Python version
for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [OK] Found %PYVER%

REM Check if virtual environment exists, create if not
if not exist "venv" (
    echo.
    echo [INFO] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment!
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
)

REM Activate virtual environment
echo [INFO] Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo [INFO] Installing dependencies...
pip install -q -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies!
    pause
    exit /b 1
)
echo [OK] Dependencies installed

echo.
echo ========================================
echo   Ready to migrate!
echo ========================================
echo.
echo This will:
echo   1. Connect to the SQLite database (webui.db)
echo   2. Connect to PostgreSQL at 10.10.135.12
echo   3. Truncate existing data in PostgreSQL tables
echo   4. Copy all data with type conversions
echo   5. Skip: document_chunk, alembic_version, migratehistory
echo.
echo WARNING: This will OVERWRITE existing data in PostgreSQL!
echo.
set /p confirm="Continue? (y/n): "
if /i not "%confirm%"=="y" (
    echo Migration cancelled.
    pause
    exit /b 0
)

echo.
echo [INFO] Starting migration...
echo.

REM Run the migration script
python migrate_sqlite_to_postgres.py

echo.
if errorlevel 1 (
    echo [WARN] Migration completed with errors. Check output above.
) else (
    echo [OK] Migration completed successfully!
)

echo.
pause
