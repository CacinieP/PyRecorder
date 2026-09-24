"""Exercise Windows GUI ownership and shutdown without opening devices."""
import threading
import time
import weakref
import sys
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QTimer


def spin_until(qapp, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.001)
    assert predicate()


@pytest.fixture
def gui(monkeypatch, tmp_path, qapp):
    import screen_recorder_pro as pro
    monkeypatch.setattr(pro, 'get_visible_windows', lambda: [])
    errors, successes, workers = [], [], []
    monkeypatch.setattr(pro.QMessageBox, 'critical', lambda *args: errors.append(args))
    monkeypatch.setattr(pro.QMessageBox, 'information', lambda *args: successes.append(args))

    class Worker(pro.RecordingThread):
        fail = False

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.finishing = threading.Event()
            self.release_merge = threading.Event()
            self.stops = 0
            workers.append(self)

        def run(self):
            self._stop_event.wait(3)
            if self.fail:
                self.error.emit('synthetic disk failure; source files preserved')
            self.finishing.set()
            self.release_merge.wait(3)
            self.output_saved = not self.fail
            self.capture_duration = 1.0

        def stop(self):
            self.stops += 1
            super().stop()

    monkeypatch.setattr(pro, 'RecordingThread', Worker)
    window = pro.ScreenRecorderPro()
    window.output_folder = str(tmp_path)
    window.show()
    yield SimpleNamespace(window=window, workers=workers, errors=errors,
                          successes=successes, worker_type=Worker, pro=pro)
    for worker in workers:
        worker.stop()
        worker.release_merge.set()
        assert worker.wait(3000)
    qapp.processEvents()
    window.close()
    qapp.processEvents()


def test_stop_and_close_wait_asynchronously_for_finalization(gui, qapp):
    window = gui.window
    window.start_recording()
    worker = window.recording_thread
    started = time.monotonic()
    window.stop_recording()
    assert time.monotonic() - started < 0.1
    spin_until(qapp, worker.finishing.is_set)
    window.stop_recording()
    window.toggle_recording()
    window.start_recording()
    assert len(gui.workers) == 1 and worker.stops == 1
    assert not window.record_btn.isEnabled()

    window.close()
    window.close()
    assert window.isVisible() and window._close_pending
    assert worker.stops == 1
    ticks = []
    QTimer.singleShot(0, lambda: ticks.append(True))
    spin_until(qapp, lambda: bool(ticks))
    assert worker.isRunning()  # GUI events are serviced during merge.
    worker.release_merge.set()
    spin_until(qapp, lambda: not window.isVisible())
    assert not worker.isRunning() and worker.output_saved
    assert gui.successes == []  # Closing does not produce a saved dialog.


def test_error_dialog_waits_for_worker_cleanup_before_closing(gui, qapp):
    gui.worker_type.fail = True
    window = gui.window
    window.start_recording()
    worker = window.recording_thread
    window.close()
    spin_until(qapp, worker.finishing.is_set)
    qapp.processEvents()
    assert gui.errors == [] and window.isVisible()
    worker.release_merge.set()
    spin_until(qapp, lambda: not window.isVisible())
    assert len(gui.errors) == 1 and gui.successes == []


def test_region_selector_survives_return_and_is_released_after_cancel(gui, qapp):
    window = gui.window
    window.capture_mode_combo.setCurrentText('Custom Region')
    window.select_region()
    selector = window.region_selector
    ref = weakref.ref(selector)
    assert selector.isVisible()
    window.select_region()
    assert window.region_selector is selector
    selector.close()
    assert window.region_selector is None
    del selector
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert ref() is None
    window.select_region()
    assert window.region_selector is not None
    window.close()
    assert window.region_selector is None


def test_physical_selection_uses_local_dpi_and_native_monitor_origin(gui):
    # A secondary monitor's native origin must not be multiplied by its DPR.
    assert gui.pro.physical_region((10, 20, 100, 80), (-1920, 200), 1.5) == (
        -1905, 230, 150, 120)


def test_window_crop_is_intersection_in_screen_pixels(gui):
    worker = gui.worker_type('unused.mp4', 30, 'mp4v',
                             region=(350, 250, 100, 100),
                             window_rect=(300, 200, 800, 600))
    assert worker._capture_monitor(None) == {
        'left': 350, 'top': 250, 'width': 100, 'height': 100}
    worker.region = (250, 150, 100, 100)
    assert worker._capture_monitor(None) == {
        'left': 300, 'top': 200, 'width': 50, 'height': 50}


def test_closing_during_synthetic_capture_finalizes_a_playable_mp4(monkeypatch, tmp_path, qapp):
    import cv2
    import numpy as np
    import screen_recorder_pro as pro

    class Screen:
        monitors = [None, {'left': 0, 'top': 0, 'width': 160, 'height': 120}]
        closed = False

        def grab(self, monitor):
            return np.full((120, 160, 4), [0, 0, 255, 255], dtype=np.uint8)

        def close(self):
            self.closed = True

    screen = Screen()
    monkeypatch.setitem(sys.modules, 'mss', SimpleNamespace(mss=lambda: screen))
    monkeypatch.setattr(pro, 'get_visible_windows', lambda: [])
    dialogs = []
    monkeypatch.setattr(pro.QMessageBox, 'critical', lambda *args: dialogs.append(args))
    monkeypatch.setattr(pro.QMessageBox, 'information', lambda *args: dialogs.append(args))
    window = pro.ScreenRecorderPro()
    window.output_folder = str(tmp_path)
    window.show()
    window.start_recording()
    worker = window.recording_thread
    try:
        spin_until(qapp, lambda: worker.frame_count >= 3 or not worker.isRunning())
        assert worker.frame_count >= 3, dialogs
        window.close()
        spin_until(qapp, lambda: not window.isVisible())
        assert not worker.isRunning() and worker.output_saved and screen.closed
        assert dialogs == []
        reader = cv2.VideoCapture(window.current_output_path)
        try:
            assert reader.isOpened()
            ok, frame = reader.read()
            assert ok and frame.shape[:2] == (120, 160)
            assert frame[0, 0, 2] > 200 and frame[0, 0, 0] < 20
            duration = reader.get(cv2.CAP_PROP_FRAME_COUNT) / reader.get(cv2.CAP_PROP_FPS)
            assert abs(duration - worker.capture_duration) <= 1 / worker.fps + 0.001
        finally:
            reader.release()
    finally:
        worker.stop()
        assert worker.wait(3000)
        qapp.processEvents()
        window.close()
