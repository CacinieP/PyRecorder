"""Basic edition regressions using fake screens and real Qt event delivery."""
import sys
import threading
import time
import types
from pathlib import Path

import cv2
import numpy as np
import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QTimer

import screen_recorder as basic
import screen_recorder_pro as pro


def spin_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.005)
    assert predicate(), "the basic recorder did not finish in time"


@pytest.fixture
def screen(monkeypatch):
    class Screen:
        monitors = [None, {"left": 0, "top": 0, "width": 32, "height": 24}]
        closed = False
        grabs = 0

        def grab(self, monitor):
            self.grabs += 1
            return np.tile(np.array([0, 0, 255, 255], dtype=np.uint8), (24, 32, 1))

        def close(self):
            self.closed = True

    instance = Screen()
    monkeypatch.setitem(sys.modules, "mss", types.SimpleNamespace(mss=lambda: instance))
    return instance


@pytest.fixture
def window(qapp, monkeypatch, tmp_path):
    dialogs = []
    monkeypatch.setattr(basic.QMessageBox, "information",
                        lambda *args: dialogs.append(("saved", args[-1])))
    monkeypatch.setattr(basic.QMessageBox, "critical",
                        lambda *args: dialogs.append(("failed", args[-1])))
    instance = basic.ScreenRecorder()
    instance.output_folder = str(tmp_path)
    instance.dialogs = dialogs
    instance.show()
    yield instance
    if instance.recording_thread and instance.recording_thread.isRunning():
        instance.recording_thread.stop()
        assert instance.recording_thread.wait(5000)
    qapp.processEvents()
    instance.close()
    instance.deleteLater()
    QCoreApplication.sendPostedEvents(instance, QEvent.Type.DeferredDelete)


def test_basic_reports_unavailable_encoder_without_claiming_saved(window, screen, monkeypatch):
    class ClosedWriter:
        def isOpened(self):
            return False

        def release(self):
            pass

    monkeypatch.setattr(pro.cv2, "VideoWriter", lambda *args: ClosedWriter())
    window.start_recording()
    spin_until(lambda: not window._recording_active)
    assert [kind for kind, _ in window.dialogs] == ["failed"]
    assert "Cannot open video writer" in window.dialogs[0][1]
    assert not Path(window.current_output_path).exists()
    assert screen.closed and screen.grabs == 0


def test_basic_preserves_bgra_color_and_publishes_only_after_release(screen, monkeypatch, tmp_path):
    output = tmp_path / "basic.mp4"
    worker = basic.RecordingThread(str(output), 30, "mp4v")
    frames, releases = [], []

    class Writer:
        def __init__(self, path, *args):
            self.path = Path(path)
            self.path.write_bytes(b"header")

        def isOpened(self):
            return True

        def write(self, frame):
            frames.append(frame.copy())
            worker.stop()

        def release(self):
            assert not output.exists()
            releases.append(True)

    monkeypatch.setattr(pro.cv2, "VideoWriter", Writer)
    worker.start()
    assert worker.wait(5000)
    assert worker.output_saved and output.exists()
    assert frames[0][0, 0].tolist() == [0, 0, 255]
    assert releases == [True] and screen.closed


def test_basic_selector_survives_until_cancel_and_can_reopen(window):
    window.select_region()
    selector = window.region_selector
    assert selector is not None and selector.isVisible()
    window.select_region()
    assert window.region_selector is selector
    selector.close()
    QCoreApplication.sendPostedEvents(selector, QEvent.Type.DeferredDelete)
    assert window.region_selector is None
    window.select_region()
    assert window.region_selector is not None
    window.region_selector.region_selected.emit((10, 20, 200, 100))
    assert window.region == (10, 20, 200, 100)
    window.full_screen_btn.click()
    assert window.region is None
    assert window.region_label.text() == "Full Screen"


def test_basic_close_keeps_event_loop_alive_until_real_mp4_is_finalized(
        window, screen, monkeypatch):
    real_writer = cv2.VideoWriter
    releasing = threading.Event()
    allow_release = threading.Event()

    class SlowFinalize:
        def __init__(self, *args):
            self.writer = real_writer(*args)

        def isOpened(self):
            return self.writer.isOpened()

        def write(self, frame):
            self.writer.write(frame)

        def release(self):
            releasing.set()
            assert allow_release.wait(5)
            self.writer.release()

    monkeypatch.setattr(pro.cv2, "VideoWriter", SlowFinalize)
    try:
        window.start_recording()
        spin_until(lambda: window.recording_thread.frame_count >= 2)
        worker = window.recording_thread
        window.close()
        assert window.isVisible() and window._closing
        assert not window.record_btn.isEnabled()
        window.start_recording()
        assert window.recording_thread is worker
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        spin_until(lambda: releasing.is_set() and bool(ticks))
        assert worker.isRunning() and not worker.output_saved
        assert not Path(window.current_output_path).exists()
        allow_release.set()
        spin_until(lambda: not window._recording_active and not window.isVisible())
        assert worker.output_saved and screen.closed
        assert window.dialogs == []
        video = cv2.VideoCapture(window.current_output_path)
        try:
            ok, frame = video.read()
            assert ok and frame is not None
            assert video.get(cv2.CAP_PROP_FRAME_COUNT) >= 2
        finally:
            video.release()
    finally:
        allow_release.set()
