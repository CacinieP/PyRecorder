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


def pytest_addoption(parser):
    parser.addoption(
        "--run-hardware", action="store_true", default=False,
        help="run tests that access real camera and audio devices",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "hardware: requires real devices (enable with --run-hardware)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-hardware"):
        return
    skip_hardware = pytest.mark.skip(reason="requires --run-hardware")
    for item in items:
        if item.get_closest_marker("hardware"):
            item.add_marker(skip_hardware)


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
def recorder(qapp, monkeypatch):
    """An offscreen recorder without automatic access to real devices."""
    from PyQt6.QtCore import QCoreApplication, QEvent
    import screen_recorder_mac as mac

    monkeypatch.setattr(mac.ScreenRecorderMac, "probe_devices", lambda self: None)
    rec = mac.ScreenRecorderMac()
    rec.proc = None
    try:
        yield rec
    finally:
        rec.proc = None
        rec.elapsed_timer.stop()
        rec.close()
        rec.deleteLater()
        # Destroy the receiver now, before monkeypatches are undone or later
        # tests process events and deliver its pending singleShot callbacks.
        QCoreApplication.sendPostedEvents(rec, QEvent.Type.DeferredDelete)
