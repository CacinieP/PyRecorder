#!/bin/bash
# PyRecorder for macOS launcher (double-click in Finder)
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null 2>&1 && [ ! -x /opt/homebrew/bin/ffmpeg ]; then
    echo "ffmpeg not found. Install it with:  brew install ffmpeg"
    exit 1
fi

if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements-mac.txt

exec python3 screen_recorder_mac.py
