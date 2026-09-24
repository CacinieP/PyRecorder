"""Recording state transitions without opening screen, camera, or microphone."""
import io
import json
import os
import shutil
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtGui import QCloseEvent

import screen_recorder_mac as mac

RECORDING_SUCCEEDED = mac.recording_succeeded


class Process:
    def __init__(self, returncode=None):
        self.returncode = returncode
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO()
        self.stderr = io.BytesIO()
        self.terminated = 0
        self.killed = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated += 1

    def kill(self):
        self.killed += 1

    def wait(self, *args, **kwargs):
        raise AssertionError("the GUI must not wait for ffmpeg synchronously")


class Worker:
    def __init__(self):
        self.running = True
        self.stopped = False

    def isRunning(self):
        return self.running

    def stop(self):
        self.stopped = True

    def wait(self, *args):
        raise AssertionError("the GUI must not join a running worker")


@pytest.fixture
def subject(qapp, monkeypatch):
    monkeypatch.setattr(mac.ScreenRecorderMac, "probe_devices", lambda self: None)
    dialogs = []
    for kind in ("critical", "information", "warning"):
        monkeypatch.setattr(mac.QMessageBox, kind,
                            lambda *args, _kind=kind: dialogs.append((_kind, args[2])))
    rec = mac.ScreenRecorderMac()
    rec.dialogs = dialogs
    rec.output_path = "unused.mp4"
    rec.start_time = time.time()
    monkeypatch.setattr(mac, "recording_succeeded", lambda code, path: code in (0, 255))
    yield rec
    rec.proc = None
    rec.cam_feed = rec.live_thread = rec.stderr_reader = None
    rec.lifecycle_timer.stop()
    rec.elapsed_timer.stop()
    rec.close()


def test_repeated_stop_is_idempotent_and_keeps_the_gui_responsive(subject):
    proc = subject.proc = Process()
    subject.stop_recording()
    subject.stop_recording()
    subject._finalize()
    assert proc.terminated == 1
    assert proc.killed == 0
    assert subject.proc is proc
    assert not subject.record_btn.isEnabled()
    assert subject.lifecycle_timer.isActive()
    assert subject.dialogs == []


def test_stop_escalates_only_after_deadline_and_only_once(subject, monkeypatch):
    proc = subject.proc = Process()
    now = [100.0]
    monkeypatch.setattr(mac.time, "monotonic", lambda: now[0])
    subject.stop_recording()
    now[0] += 14
    subject._poll_lifecycle()
    assert proc.killed == 0
    now[0] += 2
    subject._poll_lifecycle()
    subject._poll_lifecycle()
    assert proc.terminated == 1
    assert proc.killed == 1


def test_stale_finalize_cannot_stop_a_new_session(subject):
    proc = subject.proc = Process()
    subject._session = 2
    subject._finalize(session=1)
    assert subject.proc is proc
    assert proc.terminated == 0
    assert subject.dialogs == []


def test_unexpected_exit_is_reported_once_and_releases_streams(subject):
    proc = subject.proc = Process(returncode=1)
    subject._state = "recording"
    subject._poll_lifecycle()
    subject._poll_lifecycle()
    assert subject.proc is None
    assert subject._state == "idle"
    assert subject.record_btn.isEnabled()
    assert [kind for kind, _ in subject.dialogs] == ["critical"]
    assert proc.stdin.closed and proc.stdout.closed and proc.stderr.closed


def test_finalize_retains_workers_until_they_finish(subject):
    proc = subject.proc = Process(returncode=255)
    worker = subject.cam_feed = Worker()
    reader = SimpleNamespace(is_alive=lambda: True, tail_text=lambda: "diagnostic")
    subject.stderr_reader = reader
    subject._finalize()
    assert worker.stopped
    assert subject.proc is proc and subject.cam_feed is worker
    assert not proc.stderr.closed
    assert subject.dialogs == []
    worker.running = False
    subject._finalize()
    assert subject.proc is proc, "the stderr reader must also finish before cleanup"
    reader.is_alive = lambda: False
    subject._finalize()
    subject._finalize()
    assert subject.proc is None
    assert [kind for kind, _ in subject.dialogs] == ["information"]


def test_closing_during_probe_cancels_start_and_waits_without_blocking(subject):
    entered, release = threading.Event(), threading.Event()
    mic_calls = []

    def camera_probe(index):
        entered.set()
        assert release.wait(2)
        return {"fps": 30, "size": (640, 480)}

    subject._state = "probing"
    subject._pending = {"cam_wanted": True}
    probe = subject.probe_thread = mac.PreRecordProbe(
        0, 0, True, True, camera_prober=camera_probe,
        mic_prober=lambda index: mic_calls.append(index))
    results = []
    probe.done.connect(results.append)
    probe.done.connect(subject._on_probes_done)
    subject.show()
    probe.start()
    try:
        assert entered.wait(1)
        event = QCloseEvent()
        subject.closeEvent(event)
        assert not event.isAccepted()
        assert subject._pending is None
        assert probe.isInterruptionRequested()
        assert subject.isVisible()
    finally:
        release.set()
        assert probe.wait(2000)
    QCoreApplication.processEvents()
    subject._poll_lifecycle()
    assert results == []
    assert mic_calls == []
    assert subject.proc is None
    assert not subject.isVisible()


def test_late_probe_result_after_close_cannot_start_recording(subject, monkeypatch):
    def unexpected_launch(*args, **kwargs):
        pytest.fail("a closed recorder must not launch ffmpeg")

    monkeypatch.setattr(mac.subprocess, "Popen", unexpected_launch)
    subject._closing = True
    subject._pending = None
    subject._on_probes_done({"camera": None, "mic_ok": False})
    assert subject.proc is None


def test_closing_while_recording_finishes_file_before_closing(subject):
    subject.show()
    proc = subject.proc = Process()
    subject._state = "recording"
    event = QCloseEvent()
    subject.closeEvent(event)
    assert not event.isAccepted()
    assert proc.terminated == 1
    assert subject.isVisible()
    subject.closeEvent(QCloseEvent())
    assert proc.terminated == 1
    proc.returncode = 255
    subject._poll_lifecycle()
    assert subject.proc is None
    assert not subject.isVisible()
    assert subject.dialogs == [], "successful close needs no second confirmation"


def test_stop_when_idle_does_not_schedule_a_failure_dialog(subject):
    subject.stop_recording()
    subject._poll_lifecycle()
    assert subject.dialogs == []
    assert not subject.lifecycle_timer.isActive()


def test_probe_waits_for_camera_preview_to_release_its_device(subject, monkeypatch):
    started = []

    class Probe:
        done = SimpleNamespace(connect=lambda callback: None)

        def __init__(self, *args):
            pass

        def start(self):
            started.append(True)

        def isRunning(self):
            return False

    monkeypatch.setattr(mac, "PreRecordProbe", Probe)
    worker = Worker()
    window = SimpleNamespace(thread=worker, close=lambda: None)
    subject._retired_pip_windows.append(window)
    subject._state = "preparing"
    subject._pending = {"cam_wanted": True, "mic_wanted": False, "mic_idx": None}
    subject._poll_lifecycle()
    assert started == []
    worker.running = False
    subject._poll_lifecycle()
    assert started == [True]
    assert subject._state == "probing"


def test_preview_cannot_reopen_until_previous_camera_worker_finishes(subject, monkeypatch):
    opened = []

    class Preview:
        def __init__(self, *args):
            self.thread = Worker()
            opened.append(self)

        def move(self, *args):
            pass

        def show(self):
            pass

        def close(self):
            self.thread.stop()

    monkeypatch.setattr(mac, "PipPreviewWindow", Preview)
    subject.camera_idx = 0
    subject.preview_btn.setChecked(True)
    assert len(opened) == 1
    subject.preview_btn.setChecked(False)
    assert opened[0].thread.stopped
    assert not subject.preview_btn.isEnabled()
    subject.preview_btn.setChecked(True)  # programmatic toggle bypasses disabled UI
    subject.toggle_pip_preview(True)      # direct calls must be guarded as well
    subject._set_controls(True)
    assert len(opened) == 1
    assert not subject.preview_btn.isChecked()
    assert not subject.preview_btn.isEnabled()
    opened[0].thread.running = False
    subject._poll_lifecycle()
    assert subject.preview_btn.isEnabled()
    subject.preview_btn.setChecked(True)
    subject.toggle_pip_preview(True)
    assert len(opened) == 2, "the retired camera released its device; opening is safe"
    opened[1].thread.running = False
    subject.preview_btn.setChecked(False)
    subject._poll_lifecycle()


@pytest.mark.parametrize("state,closing", [("recording", False), ("idle", True)])
def test_retired_preview_drain_does_not_enable_preview_during_recording_or_close(
        subject, monkeypatch, state, closing):
    worker = Worker()
    worker.running = False
    subject._retired_pip_windows.append(SimpleNamespace(thread=worker, close=lambda: None))
    subject.preview_btn.setEnabled(False)
    subject._state, subject._closing = state, closing
    subject._poll_lifecycle()
    assert not subject.preview_btn.isEnabled()
    subject.camera_idx = 0
    monkeypatch.setattr(mac, "PipPreviewWindow", lambda *args: pytest.fail("camera opened"))
    subject.toggle_pip_preview(True)
    assert subject.pip_window is None


def test_camera_feed_retries_short_writes_and_releases_capture(monkeypatch):
    pytest.importorskip("cv2")
    payload = b"abcdefghijkl"
    frame = SimpleNamespace(shape=(2, 2, 3), tobytes=lambda: payload)
    released, closed, chunks = [], [], []
    cap = SimpleNamespace(isOpened=lambda: True, read=lambda: (True, frame),
                          release=lambda: released.append(True))
    feed = mac.CameraPipeFeed(0, 987654, 30, size=(2, 2), opener=lambda index: cap)

    def short_write(fd, data):
        assert fd == 987654
        chunks.append(bytes(data[:3]))
        if sum(map(len, chunks)) == len(payload):
            feed.stop()
        return 3

    monkeypatch.setattr(mac.os, "write", short_write)
    monkeypatch.setattr(mac.os, "close", closed.append)
    feed.run()
    assert b"".join(chunks) == payload
    assert released == [True]
    assert closed == [987654]


def test_camera_feed_releases_capture_when_ffmpeg_closes_pipe(monkeypatch):
    pytest.importorskip("cv2")
    frame = SimpleNamespace(shape=(2, 2, 3), tobytes=lambda: b"x" * 12)
    released, closed = [], []
    cap = SimpleNamespace(isOpened=lambda: True, read=lambda: (True, frame),
                          release=lambda: released.append(True))
    feed = mac.CameraPipeFeed(0, 987654, 30, size=(2, 2), opener=lambda index: cap)

    def broken_pipe(*args):
        raise BrokenPipeError()

    monkeypatch.setattr(mac.os, "write", broken_pipe)
    monkeypatch.setattr(mac.os, "close", closed.append)
    feed.run()
    assert released == [True]
    assert closed == [987654]


@pytest.mark.parametrize("has_first_frame", [False, True])
def test_camera_feed_stops_and_reports_persistent_read_failure(monkeypatch, has_first_frame):
    pytest.importorskip("cv2")
    frame = SimpleNamespace(shape=(2, 2, 3), tobytes=lambda: b"x" * 12)
    reads, sleeps, failures, released, closed = [], [], [], [], []
    now = [0.0]
    monkeypatch.setattr(mac.time, "monotonic", lambda: now[0])

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    def read():
        reads.append(True)
        # Fail rather than hang if the retry limit regresses.
        assert len(reads) <= feed.MAX_BAD_READS + int(has_first_frame)
        if has_first_frame and len(reads) == 1:
            return True, frame
        return False, None

    cap = SimpleNamespace(isOpened=lambda: True, read=read,
                          release=lambda: released.append(True))
    feed = mac.CameraPipeFeed(0, 987654, 30, size=(2, 2), opener=lambda index: cap)
    feed.failed.connect(failures.append)
    monkeypatch.setattr(mac.time, "sleep", sleep)
    monkeypatch.setattr(mac.os, "write", lambda fd, data: len(data))
    monkeypatch.setattr(mac.os, "close", closed.append)
    feed.run()

    assert len(reads) == feed.MAX_BAD_READS + int(has_first_frame)
    assert sleeps == [feed.RETRY_DELAY] * (feed.MAX_BAD_READS - 1)
    assert failures == ["Camera stopped delivering frames."]
    assert feed.failure_reason == failures[0]
    assert released == [True] and closed == [987654]


def test_camera_feed_recovers_after_transient_read_failures(monkeypatch):
    pytest.importorskip("cv2")
    frame = SimpleNamespace(shape=(2, 2, 3), tobytes=lambda: b"x" * 12)
    results = iter([False, False, True, False, False, True])
    failures, released, closed = [], [], []
    now, good_reads = [0.0], [0]

    def read():
        success = next(results)
        if success:
            good_reads[0] += 1
            now[0] += 1 / 30  # successful capture also advances the device clock
        return success, frame if success else None

    def write(fd, data):
        if good_reads[0] == 2:
            feed.stop()
        return len(data)

    cap = SimpleNamespace(isOpened=lambda: True, read=read,
                          release=lambda: released.append(True))
    feed = mac.CameraPipeFeed(0, 987654, 30, size=(2, 2), opener=lambda index: cap)
    feed.MAX_BAD_READS = 3
    feed.failed.connect(failures.append)
    monkeypatch.setattr(mac.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(mac.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(mac.os, "write", write)
    monkeypatch.setattr(mac.os, "close", closed.append)
    feed.run()
    assert good_reads[0] == 2 and failures == []
    assert feed.failure_reason is None
    assert released == [True] and closed == [987654]


def test_camera_failure_stops_recording_and_reports_partial_output_once(subject):
    proc = subject.proc = Process()
    subject._state = "recording"
    subject._on_camera_feed_failed("Camera disconnected", subject._session)
    subject._on_camera_feed_failed("Camera disconnected", subject._session)
    subject.update_elapsed()
    assert proc.terminated == 1
    assert subject._state == "stopping"
    assert "Camera failed" in subject.status_label.text()
    proc.returncode = 255
    subject._poll_lifecycle()
    subject._poll_lifecycle()
    assert subject.proc is None
    assert len(subject.dialogs) == 1
    kind, message = subject.dialogs[0]
    assert kind == "warning"
    assert "Camera disconnected" in message
    assert "partial recording" in message and subject.output_path in message
    assert "camera failed" in subject.status_label.text()


def test_finalize_keeps_camera_failure_even_before_queued_signal_delivery(subject):
    subject.proc = Process(returncode=1)
    subject.cam_feed = Worker()
    subject.cam_feed.running = False
    subject.cam_feed.failure_reason = "Camera stopped delivering frames."
    subject._finalize()
    assert subject.dialogs == [("critical", "Recording stopped because the camera failed.\n\n"
                                "Camera stopped delivering frames.\n\n"
                                "The recording could not be finalized.")]


def test_old_camera_failure_cannot_stop_another_session(subject):
    proc = subject.proc = Process()
    subject._session = 2
    subject._on_camera_feed_failed("Old camera failure", session=1)
    assert proc.terminated == 0
    assert subject._recording_error is None
    assert subject.dialogs == []


def _spin_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert predicate(), "the asynchronous lifecycle did not finish in time"


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="requires ffmpeg and ffprobe, without capture devices")
@pytest.mark.skipif(os.name != "posix",
                    reason="macOS stop uses POSIX SIGTERM; Windows terminate force-kills ffmpeg")
def test_real_ffmpeg_stop_finalizes_mp4_and_releases_all_workers(subject, monkeypatch, tmp_path):
    monkeypatch.setattr(mac, "recording_succeeded", RECORDING_SUCCEEDED)
    monkeypatch.setattr(mac, "ffmpeg_available", lambda: True)

    def synthetic_command(output_path, *args, **kwargs):
        return ([shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "warning", "-y",
                 "-re", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10",
                 "-filter_complex", "[0:v]split[rec][pv];[pv]scale=480:270[prev]",
                 "-map", "[rec]", "-c:v", "libx264", "-pix_fmt", "yuv420p", output_path,
                 "-map", "[prev]", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], [])

    monkeypatch.setattr(mac, "build_command", synthetic_command)
    subject.screen_idx = 1
    subject.cam_checkbox.setChecked(False)
    subject.mic_checkbox.setChecked(False)
    subject.save_folder = str(tmp_path)
    subject.start_recording()
    _spin_until(lambda: subject.proc is not None)
    proc = subject.proc
    reader, preview = subject.stderr_reader, subject.live_thread
    frames = []
    preview.frame.connect(lambda image: frames.append(image.size()))
    try:
        _spin_until(lambda: len(frames) >= 5)
        subject.stop_recording()
        subject.stop_recording()
        _spin_until(lambda: subject.proc is None)
        assert proc.returncode in (0, 255)
        assert [kind for kind, _ in subject.dialogs] == ["information"]
        assert not reader.is_alive() and not preview.isRunning()
        assert proc.stdin.closed and proc.stdout.closed and proc.stderr.closed
        assert subject.record_btn.isEnabled()
        probe = subprocess.run(
            [shutil.which("ffprobe"), "-v", "error", "-show_entries", "format=duration",
             "-of", "json", subject.output_path], capture_output=True, text=True,
            timeout=5, check=True)
        assert float(json.loads(probe.stdout)["format"]["duration"]) > 0
    finally:
        if proc.poll() is None:
            proc.kill()
        if subject.proc is not None:
            _spin_until(lambda: subject.proc is None)
