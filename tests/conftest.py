"""Shared pytest setup: make the repo root importable and stay headless."""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Tests must not need a window server (CI runs headless).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
