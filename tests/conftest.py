"""Shared pytest setup: make the repo root importable and stay headless."""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Tests must not need a window server (CI runs headless).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


import pytest  # noqa: E402


@pytest.fixture()
def recorder():
    """A real ScreenRecorderMac instance (offscreen) with no recording running."""
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication
    import screen_recorder_mac as mac

    global _APP
    _APP = QApplication.instance() or QApplication([])
    rec = mac.ScreenRecorderMac()
    rec.proc = None
    yield rec
    rec.proc = None
