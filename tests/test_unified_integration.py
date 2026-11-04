"""End-to-end integration: the real pipeline against a real ffmpeg process.

No devices or permissions needed: the feeders run with synthetic sources
(a fake mss and a fake camera), but everything else is production code —
build_command, both pipe feeders, pacing under the GIL, SIGTERM stop,
moov-based success check. This is the exact runtime path Windows and Linux
take (ADR-0002), executed here against whatever real ffmpeg is installed.
"""
import subprocess
import time

import pytest

pytest.importorskip("PyQt6", reason="pyrecorder imports PyQt6 at module level")

from pyrecorder import mp4check  # noqa: E402
from pyrecorder.camera import CameraPipeFeed  # noqa: E402
from pyrecorder.channels import open_channel  # noqa: E402
from pyrecorder.command import CameraInput, PipeScreenInput, build_command  # noqa: E402
from pyrecorder.ffmpeg_exe import ProcessOutputReader, find_ffmpeg  # noqa: E402
from pyrecorder.screenfeed import ScreenPipeFeed  # noqa: E402

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="needs a real ffmpeg")

SCREEN_SIZE = (640, 360)
CAMERA_SIZE = (320, 180)
FPS = 15
SECONDS = 3.0


class FakeShot:
    def __init__(self, size, tick):
        self.bgra = bytes([tick % 256]) * (size[0] * size[1] * 4)


class FakeMss:
    def __init__(self):
        self.grabs = 0

    def grab(self, monitor):
        self.grabs += 1
        return FakeShot(SCREEN_SIZE, self.grabs)

    def close(self):
        pass


class FakeCamera:
    """Delivers frames at ~FPS with the declared geometry."""

    def __init__(self):
        import numpy as np
        self.frame = np.zeros((CAMERA_SIZE[1], CAMERA_SIZE[0], 3), np.uint8)
        self.opened = True

    def isOpened(self):
        return self.opened

    def read(self):
        time.sleep(1.0 / FPS)
        self.frame[:, :] = (self.frame[0, 0, 0].astype(int) + 1) % 256
        return True, self.frame

    def release(self):
        self.opened = False


def test_real_ffmpeg_pipeline_screen_plus_camera(qapp, tmp_path):
    ffmpeg = find_ffmpeg()
    output = str(tmp_path / "integration.mp4")

    # production channel flavor for this platform (pipes on POSIX, loopback
    # TCP on Windows where pass_fds does not exist)
    screen_channel = open_channel()
    cam_channel = open_channel()

    cmd, extra = build_command(
        ffmpeg, output, FPS,
        screen=PipeScreenInput(screen_channel.input_arg(), SCREEN_SIZE),
        camera=CameraInput(cam_channel.input_arg(), FPS, CAMERA_SIZE),
        pip=(160, 20, 20), layout="pip",
        encoder_main=["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28"])
    pass_fds = tuple(fd for fd in (screen_channel.pass_fd(), cam_channel.pass_fd())
                     if fd is not None)
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, pass_fds=pass_fds)
    stderr_reader = ProcessOutputReader(proc.stderr)
    stderr_reader.start()
    screen_channel.after_spawn()
    cam_channel.after_spawn()

    screen_feed = ScreenPipeFeed((0, 0, *SCREEN_SIZE), None, FPS,
                                 size=SCREEN_SIZE, mss_factory=FakeMss,
                                 sink_factory=screen_channel.connect)
    cam_feed = CameraPipeFeed(0, "darwin", None, FPS, size=CAMERA_SIZE,
                              opener=lambda idx: FakeCamera(),
                              sink_factory=cam_channel.connect)
    screen_feed.start()
    cam_feed.start()

    time.sleep(SECONDS)
    proc.terminate()               # production stop path: one SIGTERM
    rc = proc.wait(timeout=15)
    screen_feed.stop()
    cam_feed.stop()
    screen_feed.wait(4000)
    cam_feed.wait(4000)
    stderr_reader.join(2)

    assert rc in (0, 255), f"ffmpeg exit {rc}: {stderr_reader.tail_text(500)}"
    assert mp4check.recording_succeeded(rc, output)

    probe = subprocess.run(
        [ffmpeg.replace("ffmpeg", "ffprobe"), "-v", "error",
         "-show_entries", "stream=codec_type,codec_name,width,height",
         "-show_entries", "format=duration", "-of", "default=nw=1", output],
        capture_output=True, text=True)
    assert probe.returncode == 0, probe.stderr
    details = probe.stdout
    assert "codec_name=h264" in details
    assert f"width={SCREEN_SIZE[0]}" in details and f"height={SCREEN_SIZE[1]}" in details
    duration = float([line for line in details.splitlines()
                      if line.startswith("duration=")][0].split("=")[1])
    # the session includes ffmpeg startup; the file must cover most of it
    assert SECONDS * 0.75 <= duration <= SECONDS * 1.5, \
        f"duration {duration}s drifted from the {SECONDS}s session"
    assert extra == []
