#!/bin/bash
# PyRecorder launcher for macOS (double-click in Finder).
# Creates a project venv on first run; the [ffmpeg-binary] extra ships a
# private ffmpeg so no Homebrew setup is needed.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
.venv/bin/python -m pip install -q -e ".[ffmpeg-binary]"

exec .venv/bin/python -m pyrecorder
