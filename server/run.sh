#!/bin/bash
# Start the DelightfulOS server
# Usage: ./run.sh [--reload]
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$SCRIPT_DIR"

# Check .env exists
if [ ! -f .env ]; then
    echo "ERROR: .env not found. Copy .env.example to .env and fill in your keys."
    echo "  cp .env.example .env"
    exit 1
fi

# Check venv exists
if [ ! -d .venv ]; then
    echo "Setting up virtual environment..."
    uv venv
    uv pip install -e ".[dev]"
    uv pip install -e "$PROJECT_ROOT"
fi

EXTRA_ARGS=""
if [ "$1" = "--reload" ]; then
    EXTRA_ARGS="--reload --reload-dir . --reload-dir ../delightfulos"
fi

.venv/Scripts/python -m uvicorn app.main:app \
    --host 0.0.0.0 --port 8000 $EXTRA_ARGS
