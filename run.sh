#!/usr/bin/env bash
# One-click launcher for macOS / Linux. Re-runs setup if .venv is missing.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ] && [ ! -x ".venv/Scripts/python.exe" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt
fi

if [ -x ".venv/Scripts/python.exe" ]; then
    PY=".venv/Scripts/python.exe"
else
    PY=".venv/bin/python"
fi

export PYTHONPATH="$(pwd)/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m audio_splitter
