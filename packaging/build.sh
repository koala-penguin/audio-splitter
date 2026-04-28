#!/usr/bin/env bash
# Build a single-file binary with PyInstaller.
# macOS  -> dist/AudioSplitter and dist/AudioSplitter.app
# Linux  -> dist/AudioSplitter
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x ".venv/bin/python" ]; then
    echo "[build] Creating venv..."
    python3 -m venv .venv
fi

PY=".venv/bin/python"
"$PY" -m pip install --upgrade pip --quiet
"$PY" -m pip install -r requirements.txt --quiet
"$PY" -m pip install "pyinstaller>=6.0" --quiet

rm -rf build dist
"$PY" -m PyInstaller packaging/audio_splitter.spec --noconfirm

echo
echo "[build] Done. See dist/"
ls -lh dist/ || true
