"""Offscreen GUI lifecycle tests for the unified recorder window.

Devices, ffmpeg and feeds are faked; what is under test is the window's state
machine: device listing, degradation dialogs, command launch per platform,
finalize back to idle.
"""
import io

import pytest
from PyQt6.QtCore import QThread, Qt
from PyQt6.QtTest import QTest

pytest.importorskip("PyQt6", reason="pyrecorder.ui imports PyQt6 at module level")

from pyrecorder.platforms.base import AudioDevice, Backend  # noqa: E402
from pyrecorder.ui import main_window as mw  # noqa: E402


class FakeListThread(QThread):
    done = mw.pyqtSignal(dict)

    def __init__(self, backend):
        super().__init__()
        self.backend = backend

    def run(self):
        self.done.emit({"devices": self.backend.devices,
                        "screen_ok": True, "screen_hint": ""})


class FakeProbe(QThread):
    done = mw.pyqtSignal(dict)

    def __init__(self, backend, want_camera, want_mic, mic_device_id):
        super().__init__()
        self.result = backend.probe_result

    def run(self):
        self.done.emit(dict(self.result))


class FakeFeed(QThread):
    failed = mw.pyqtSignal(str)

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.failure_reason = None

    def run(self):
        pass  # a real feed loops; QThread's default run() would exec() forever

    def stop(self):
        pass


class FakePopenModule:
    commands = []

    class Popen:
        def __init__(self, cmd, **kwargs):
            FakePopenModule.commands.append(cmd)
            self.returncode = 255          # "ffmpeg exited" for the poll timer
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO()

        def poll(self):
            return self.returncode

        def terminate(self):
            pass

        def kill(self):
            pass


class FakeBackend(Backend):
    def __init__(self, kind="native", devices=None, probe=None):
        super().__init__()
        self.id = "darwin" if kind == "native" else "linux"
        self.kind = kind
        self.devices = devices if devices is not None else \
            [AudioDevice("0", "Fake Mic")]
        self.probe_result = probe or {"screen_ok": True, "screen_hint": "",
                                      "camera": None, "mic_ok": False}

    def list_audio_inputs(self):
        return self.devices

    def check_screen(self):
        return True, ""

    def screen_capture_kind(self):
        return self.kind

    def native_screen_args(self, fps, mic_device_id=None):
        return ["-f", "avfoundation", "-framerate", str(fps),
                "-i", f"7:{mic_device_id or 'none'}"]

    def audio_input_args(self, device_id):
        return ["-f", "pulse", "-i", str(device_id)]


@pytest.fixture()
def dialogs(monkeypatch):
    shown = []
    for name in ("warning", "critical", "information"):
        monkeypatch.setattr(
            mw.QMessageBox, name,
            staticmethod(lambda *a, _n=name, _s=shown: _s.append(_n)))
    return shown


@pytest.fixture()
def window(qapp, monkeypatch, dialogs):
    FakePopenModule.commands = []
    monkeypatch.setattr(mw, "find_ffmpeg", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(mw, "DeviceListThread", FakeListThread)
    monkeypatch.setattr(mw, "PreRecordProbe", FakeProbe)
    monkeypatch.setattr(mw, "CameraPipeFeed", FakeFeed)
    monkeypatch.setattr(mw, "ScreenPipeFeed", FakeFeed)
    monkeypatch.setattr(mw.subprocess, "Popen", FakePopenModule.Popen)

    def make(backend):
        win = mw.RecorderWindow(backend)
        win.save_folder = "/tmp/pyrecorder-test"
        return win

    yield make
    for win in mw.QApplication.topLevelWidgets():
        if isinstance(win, mw.RecorderWindow):
            win._closing = True
            win._pending = None
            if win.device_thread and win.device_thread.isRunning():
                win.device_thread.wait(2000)
            if win.probe_thread and win.probe_thread.isRunning():
                win.probe_thread.wait(2000)
            win.elapsed_timer.stop()
            win.lifecycle_timer.stop()
            win.deleteLater()
    pump(0)


def pump(ms=400):
    QTest.qWait(ms)


def test_devices_listed_into_combo(window):
    win = window(FakeBackend())
    pump(400)   # 100ms singleShot → refresh_devices → worker → queued signal
    assert win.mic_combo.count() == 1
    assert "screen OK" in win.status_label.text()
    assert win.mic_combo.itemData(0) == "0"


def test_full_mac_lifecycle_degrades_mic_and_finishes(window, dialogs):
    backend = FakeBackend(kind="native")
    win = window(backend)
    pump(100)
    win.mic_checkbox.setChecked(True)
    win.start_recording()
    assert win._state == "preparing"
    pump(600)   # probe (instant) → launch → ffmpeg "exits" → finalize

    assert win._state == "idle"
    assert len(FakePopenModule.commands) == 1
    cmd = FakePopenModule.commands[0]
    assert cmd[cmd.index("-i") + 1] == "7:none"    # mic degraded away
    assert "warning" in dialogs                     # degradation warned the user
    win.close()


def test_pipe_platform_command_uses_screen_and_audio_pipes(window):
    backend = FakeBackend(kind="mss_pipe",
                          probe={"screen_ok": True, "screen_hint": "",
                                 "camera": None, "mic_ok": True})
    win = window(backend)
    pump(400)   # let the (faked) device list fill the mic combo first
    win.start_recording()
    pump(600)

    assert len(FakePopenModule.commands) == 1
    cmd = FakePopenModule.commands[0]
    inputs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-i"]
    assert inputs[0].startswith("pipe:")       # mss screen
    assert inputs[1] == "0"                    # pulse "default" style input
    assert "bgra" in cmd and "libx264" in cmd
    assert win._state == "idle"
    win.close()


def test_start_aborts_when_screen_unavailable(window):
    backend = FakeBackend(kind="native",
                          probe={"screen_ok": False, "screen_hint": "nope",
                                 "camera": None, "mic_ok": False})
    win = window(backend)
    pump(100)
    win.start_recording()
    pump(300)
    assert win._state == "idle"
    assert FakePopenModule.commands == []      # never launched ffmpeg
    win.close()


def test_missing_ffmpeg_blocks_start(window, monkeypatch):
    win = window(FakeBackend())
    pump(100)
    monkeypatch.setattr(mw, "find_ffmpeg", lambda: None)
    win.start_recording()
    pump(100)
    assert win._state == "idle" and FakePopenModule.commands == []
    win.close()


def test_region_selection_updates_labels(window, monkeypatch):
    win = window(FakeBackend(kind="mss_pipe"))
    pump(100)
    win.on_region_selected((0, 0, 1280, 720), (100, 200, 1280, 720))
    assert "1280" in win.region_label.text()
    win.clear_region()
    assert win.region is None and win.region_label.text() == "Full Screen"
    win.close()
