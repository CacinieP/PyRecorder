#!/bin/bash
# PyRecorder launcher for macOS (double-click in Finder).
# Creates a project venv on first run; the [ffmpeg-binary] extra ships a
# private ffmpeg so no Homebrew setup is needed.
set -euo pipefail
cd "$(dirname "$0")"

# PyRecorder needs Python 3.11+ (pyproject: requires-python). macOS's system
# python3 is 3.9 — catch it here before pip turns it into a confusing
# Requires-Python error inside venv creation.
if ! command -v python3 >/dev/null 2>&1 || \
   ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "PyRecorder needs Python 3.11+; 'python3' on PATH: $(python3 -V 2>&1 || echo 'not found')."
    echo "Install Python 3.11+ (python.org installer, or: brew install python) and rerun."
    exit 1
fi

if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
.venv/bin/python -m pip install -q -e ".[ffmpeg-binary]"

exec .venv/bin/python -m pyrecorder
