"""Tests for the stop/finalize path of the macOS recorder.

`q` on stdin is ignored by ffmpeg whenever a pipe input is open (verified
2026-09-18), and writing the *str* "q" to a binary pipe raises TypeError. The
recorder must therefore stop ffmpeg with a signal.
"""
import time

import pytest

pytest.importorskip("PyQt6", reason="screen_recorder_mac imports PyQt6 at module level")

from PyQt6.QtWidgets import QApplication  # noqa: E402

import screen_recorder_mac as mac  # noqa: E402


class FakeStdin:
    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        pass


class FakeProc:
    """Stands in for the ffmpeg subprocess."""

    def __init__(self, alive=True):
        self.alive = alive
        self.stdin = FakeStdin()
        self.stdout = None
        self.stderr = None
        self.returncode = None
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self):
        return None if self.alive else 0

    def terminate(self):
        self.terminate_calls += 1

    def kill(self):
        self.kill_calls += 1

    def wait(self, timeout=None):
        self.alive = False
        self.returncode = 255
        return 255


_APP = None          # keep a reference so PyQt does not collect the app object


@pytest.fixture()
def recorder():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    rec = mac.ScreenRecorderMac()
    rec.proc = None
    yield rec
    rec.proc = None


def test_stop_recording_signals_ffmpeg_and_never_touches_stdin(recorder):
    proc = FakeProc(alive=True)
    recorder.proc = proc

    mac.ScreenRecorderMac.stop_recording(recorder)

    assert proc.stdin.writes == [], "must not send 'q': ffmpeg ignores it with a pipe input"
    assert proc.terminate_calls == 1


def test_stop_recording_is_a_no_op_when_nothing_is_running(recorder):
    recorder.proc = None
    mac.ScreenRecorderMac.stop_recording(recorder)      # must not raise
    recorder.proc = FakeProc(alive=False)
    mac.ScreenRecorderMac.stop_recording(recorder)      # already exited
    assert recorder.proc.terminate_calls == 0


class _DialogSpy:
    """Stands in for QMessageBox so _finalize() cannot block the test run."""

    def __init__(self):
        self.shown = []

    def _record(self, kind):
        def show(parent, title, text, *a, **k):
            self.shown.append((kind, text))
        return staticmethod(show)

    def install(self, monkeypatch, module):
        for kind in ("information", "critical", "warning"):
            monkeypatch.setattr(module.QMessageBox, kind,
                                lambda *a, _k=kind, **k: self.shown.append((_k, a[2] if len(a) > 2 else "")))
        return self


def test_finalize_does_not_signal_ffmpeg_a_second_time(recorder, monkeypatch, tmp_path):
    # A second SIGTERM lands while ffmpeg is still flushing the muxer and costs
    # the moov atom: the mp4 keeps its size but no longer plays (verified 2026-09-18).
    spy = _DialogSpy().install(monkeypatch, mac)
    proc = FakeProc(alive=True)
    recorder.proc = proc
    recorder.output_path = str(tmp_path / "rec.mp4")
    recorder.extra_files = []
    recorder.live_thread = None
    recorder.cam_feed = None
    recorder.start_time = time.time()

    mac.ScreenRecorderMac.stop_recording(recorder)     # user pressed Stop
    assert proc.terminate_calls == 1
    mac.ScreenRecorderMac._finalize(recorder)          # 300ms timer fires

    assert proc.terminate_calls == 1, "must not re-signal a stop already requested"
    assert proc.kill_calls == 0
    assert spy.shown, "user must still get a dialog"


def test_stop_recording_reports_that_it_is_stopping(recorder):
    recorder.proc = FakeProc(alive=True)
    mac.ScreenRecorderMac.stop_recording(recorder)
    assert "Stopping" in recorder.status_label.text()
