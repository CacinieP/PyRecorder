"""Probes must not freeze the GUI, and the camera must keep its own geometry.

Before: start_recording() ran _camera_probe() (~0.7-1s) and
probe_audio_device() (~0.4s) inline, freezing the window on every Start; and
CameraPipeFeed resized every frame to 1920x1080, stretching a 4:3 camera.
"""
import os
import sys
import threading
import time

import numpy as np
import pytest

pytest.importorskip("PyQt6", reason="screen_recorder_mac imports PyQt6 at module level")
pytest.importorskip("cv2", reason="the camera path needs OpenCV")

from PyQt6.QtCore import QCoreApplication  # noqa: E402

import screen_recorder_mac as mac  # noqa: E402

MAIN_THREAD = threading.current_thread()
REAL_FFMPEG = mac.shutil.which("ffmpeg")


def _collect(thread, timeout=8.0):
    """Start a PreRecordProbe and return the dict it emitted."""
    got = {}
    thread.done.connect(got.update)
    thread.start()
    assert thread.wait(int(timeout * 1000)), "probe thread did not finish"
    deadline = time.time() + 2
    while not got and time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    return got


# --------------------------------------------------------------------------
# probe_camera(): one probe, both facts ffmpeg needs for a rawvideo pipe
# --------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "darwin", reason="needs a real AVFoundation camera")
def test_probe_camera_reports_none_for_an_invalid_index():
    assert mac.probe_camera(99) is None


@pytest.mark.skipif(sys.platform != "darwin", reason="needs a real AVFoundation camera")
def test_probe_camera_reports_a_rate_and_the_native_frame_size():
    info = mac.probe_camera(0, window=0.4)
    assert info is not None, "camera 0 should open on this machine"
    assert info["fps"] and info["fps"] > 5
    w, h = info["size"]
    assert w > 0 and h > 0


def test_probe_camera_swallows_a_broken_backend(monkeypatch):
    def boom(idx, *a, **k):
        raise RuntimeError("no cv2 backend")
    monkeypatch.setattr(mac, "_open_camera", boom)
    assert mac.probe_camera(0) is None


# --------------------------------------------------------------------------
# PreRecordProbe: the blocking work happens off the GUI thread
# --------------------------------------------------------------------------

def test_pre_record_probe_does_not_run_on_the_gui_thread():
    seen = {}

    def fake_camera(idx):
        seen["camera"] = threading.current_thread()
        return {"fps": 28.0, "size": (1920, 1080)}

    def fake_mic(idx):
        seen["mic"] = threading.current_thread()
        return True

    got = _collect(mac.PreRecordProbe(0, 0, True, True,
                                      camera_prober=fake_camera, mic_prober=fake_mic))
    assert seen["camera"] is not MAIN_THREAD
    assert seen["mic"] is not MAIN_THREAD
    assert got["camera"] == {"fps": 28.0, "size": (1920, 1080)}
    assert got["mic_ok"] is True


def test_pre_record_probe_skips_devices_the_user_disabled():
    calls = []
    got = _collect(mac.PreRecordProbe(0, 0, False, False,
                                      camera_prober=lambda i: calls.append("camera"),
                                      mic_prober=lambda i: calls.append("mic")))
    assert calls == [], "disabled devices must not be probed at all"
    assert got == {"camera": None, "mic_ok": False}


def test_pre_record_probe_reports_a_dead_camera_as_none():
    got = _collect(mac.PreRecordProbe(0, 0, True, False,
                                      camera_prober=lambda i: None,
                                      mic_prober=lambda i: True))
    assert got["camera"] is None
    assert got["mic_ok"] is False        # not requested -> not probed


def test_pre_record_probe_reports_an_unopenable_microphone():
    got = _collect(mac.PreRecordProbe(None, 3, False, True,
                                      camera_prober=lambda i: {"fps": 30, "size": (1, 1)},
                                      mic_prober=lambda i: False))
    assert got["mic_ok"] is False


# --------------------------------------------------------------------------
# letterbox(): undistorted preview for cameras that are not 16:9
# --------------------------------------------------------------------------

def test_letterbox_pads_a_4_3_frame_to_the_exact_canvas():
    out = mac.letterbox(np.full((960, 1280, 3), 255, np.uint8), 640, 360)
    assert out.shape == (360, 640, 3)
    assert (out[:, :80, :] == 0).all(), "left pillar box must be black"
    assert (out[:, -80:, :] == 0).all(), "right pillar box must be black"
    assert (out[:, 80:560, :] == 255).all(), "the 4:3 image must fill the middle undistorted"


def test_letterbox_leaves_a_matching_frame_full_bleed():
    out = mac.letterbox(np.full((360, 640, 3), 200, np.uint8), 640, 360)
    assert out.shape == (360, 640, 3)
    assert out.min() == 200 and out.max() == 200


def test_letterbox_pads_a_wide_frame_top_and_bottom():
    out = mac.letterbox(np.full((400, 1600, 3), 255, np.uint8), 640, 360)
    assert out.shape == (360, 640, 3)
    assert out[0, 320, 0] == 0, "top bar must be black"
    assert out[180, 320, 0] == 255


def test_letterbox_pads_a_tall_frame_left_and_right():
    out = mac.letterbox(np.full((1280, 720, 3), 255, np.uint8), 640, 360)
    assert out.shape == (360, 640, 3)
    assert out[180, 0, 0] == 0 and out[180, 320, 0] == 255


# --------------------------------------------------------------------------
# the probed geometry must reach ffmpeg and the pipe writer
# --------------------------------------------------------------------------

def _read_exactly(fd, n, timeout=10.0):
    buf = b""
    deadline = time.time() + timeout
    while len(buf) < n and time.time() < deadline:
        chunk = os.read(fd, n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def _cmd(**kw):
    args = dict(output_path="/tmp/out/rec.mp4", fps=30, screen_idx=1, mic_idx=0,
                camera_idx=0, mic_enabled=False, camera_enabled=True,
                pip=(320, 10, 10), screen_scale=2.0, preview=False,
                camera_pipe_fd=7)
    args.update(kw)
    return mac.build_command(**args)[0]


def test_build_command_declares_the_probed_camera_size():
    cmd = _cmd(camera_size=(1280, 960), camera_fps=28.0)
    j = cmd.index("pipe:7")
    assert cmd[j - 5:j - 3] == ["-video_size", "1280x960"]


def test_build_command_defaults_to_the_1080p_pipe_size():
    cmd = _cmd()
    j = cmd.index("pipe:7")
    assert cmd[j - 5:j - 3] == ["-video_size", "1920x1080"]


class FakeCap:
    """Stands in for cv2.VideoCapture, delivering frames of a fixed size."""

    def __init__(self, w, h, pattern=None):
        self.w, self.h = w, h
        self.frame = (pattern if pattern is not None
                      else (np.arange(w * h * 3, dtype=np.uint8) % 251).reshape(h, w, 3))
        self.released = False
        self._left = 500

    def isOpened(self):
        return True

    def set(self, *a):
        return True

    def read(self):
        if self._left <= 0:
            time.sleep(0.01)
            return False, None
        self._left -= 1
        return True, self.frame

    def release(self):
        self.released = True


def test_camera_feed_writes_the_probed_size_without_stretching():
    cap = FakeCap(1280, 960)
    r, w = os.pipe()
    feed = mac.CameraPipeFeed(0, w, 30, size=(1280, 960), opener=lambda idx: cap)
    feed.start()
    need = 1280 * 960 * 3
    got = _read_exactly(r, need)
    feed.stop()
    feed.wait(5000)
    os.close(r)
    assert len(got) == need
    assert got == cap.frame.tobytes(), "frame must pass through unresized"


def test_camera_feed_resizes_when_the_device_ignores_the_request():
    cap = FakeCap(1920, 1080)                      # device delivers 16:9...
    r, w = os.pipe()
    feed = mac.CameraPipeFeed(0, w, 30, size=(1280, 720), opener=lambda idx: cap)
    feed.start()
    need = 1280 * 720 * 3
    got = _read_exactly(r, need)
    feed.stop()
    feed.wait(5000)
    os.close(r)
    assert len(got) == need                         # ...but the pipe promised 1280x720


# --------------------------------------------------------------------------
# PiP placement must use the camera's real aspect, not a hard-coded 16:9
# --------------------------------------------------------------------------

def test_clamp_pip_keeps_a_tall_pip_inside_the_frame():
    # 4:3 camera at 400px wide -> 300px tall; y must leave room for all of it
    w, x, y = mac.clamp_pip((400, 1200, 900), cap_w=1920, cap_h=1080, aspect=3 / 4)
    assert (w, x, y) == (400, 1200, 780)


def test_clamp_pip_keeps_the_default_16_9_behaviour():
    w, x, y = mac.clamp_pip((320, 5000, 5000), cap_w=1920, cap_h=1080)
    assert (w, x, y) == (320, 1600, 900)


def test_clamp_pip_never_returns_negative_offsets():
    _, x, y = mac.clamp_pip((4000, -50, -50), cap_w=1920, cap_h=1080, aspect=3 / 4)
    assert x == 0 and y == 0


# --------------------------------------------------------------------------
# the pipe payload must be small enough for a Python feeder to sustain, and a
# short stall must catch up instead of dropping time
# --------------------------------------------------------------------------

def test_frames_due_bursts_to_catch_up_after_a_one_second_stall():
    # Resyncing here is what shortened recordings: the camera timeline fell
    # behind the screen timeline and the overlay stopped advancing.
    n, nxt = mac.frames_due(next_due=0.0, now=1.0, interval=1 / 30)
    assert n == 31
    assert nxt == pytest.approx(31 / 30)


def test_frames_due_still_resyncs_after_a_very_long_stall():
    n, _ = mac.frames_due(next_due=0.0, now=30.0, interval=1 / 30)
    assert n == 1, "a 30s backlog must not flood the pipe with 900 copies"


def test_pipe_camera_size_sends_full_resolution_when_a_file_needs_it():
    assert mac.pipe_camera_size((1920, 1080), "pip", True, 640) == (1920, 1080)
    assert mac.pipe_camera_size((1920, 1080), "speaker-right", False, 640) == (1920, 1080)
    assert mac.pipe_camera_size((1920, 1080), "speaker-left", False, 640) == (1920, 1080)


def test_pipe_camera_size_shrinks_to_the_pip_for_a_corner_overlay():
    # 1920x1080 BGR is 6.2MB per frame; a 640px PiP needs 0.9MB. Measured: the
    # feeder only sustained 13.2 of 18.7 declared fps at full size, which made a
    # 6s session come out 1.67s long.
    assert mac.pipe_camera_size((1920, 1080), "pip", False, 640) == (640, 360)
    assert mac.pipe_camera_size((1280, 960), "pip", False, 400) == (400, 300)


def test_pipe_camera_size_never_upscales_and_always_returns_even_numbers():
    assert mac.pipe_camera_size((640, 480), "pip", False, 1920) == (640, 480)
    assert mac.pipe_camera_size((1920, 1080), "pip", False, 333) == (332, 186)


def test_pipe_camera_size_keeps_a_4_3_camera_undistorted():
    w, h = mac.pipe_camera_size((1280, 960), "pip", False, 500)
    assert abs(h / w - 0.75) < 0.01
