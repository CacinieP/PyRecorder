"""Shared pytest setup: make the repo root importable and stay headless."""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Tests must not need a window server (CI runs headless).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


import pytest  # noqa: E402

_APP = None


@pytest.fixture(autouse=True, scope="session")
def qapp():
    """A QApplication for the whole session.

    Queued signal/slot delivery (QThread -> main thread) needs an event
    dispatcher to exist, so any test that runs a QThread needs this even if it
    never builds a widget.
    """
    global _APP
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    return _APP


@pytest.fixture()
def recorder(qapp):
    """A real ScreenRecorderMac instance (offscreen) with no recording running."""
    import screen_recorder_mac as mac

    rec = mac.ScreenRecorderMac()
    rec.proc = None
    yield rec
    rec.proc = None
