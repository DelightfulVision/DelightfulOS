@echo off
REM Start the DelightfulOS server (Windows)
cd /d "%~dp0"

if not exist .env (
    echo ERROR: .env not found. Copy .env.example to .env and fill in your keys.
    echo   copy .env.example .env
    exit /b 1
)

if not exist .venv (
    echo Setting up virtual environment...
    uv venv
    uv pip install -e ".[dev]"
    uv pip install -e "%~dp0.."
)

.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 %*
