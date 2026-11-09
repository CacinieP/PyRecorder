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
from pyrecorder.ffmpeg_exe import (ProcessOutputReader, find_ffmpeg,  # noqa: E402
                                    request_graceful_stop)
from pyrecorder.screenfeed import ScreenPipeFeed  # noqa: E402

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="needs a real ffmpeg")

SCREEN_SIZE = (640, 360)
CAMERA_SIZE = (320, 180)
FPS = 15
SECONDS = 3.0


class FakeShot:
    def __init__(self, size, tick):
        self.bgra = bytes([tick % 256]) * (size[0] * size[1] * 4)


class DeliverySpan:
    """Wall-clock window a feeder actually delivered over (first→last write).

    Duration assertions must compare against this measured window, not the
    nominal sleep: on a loaded CI runner the ffmpeg child can take most of a
    second to bind its TCP listeners, which shortens the fed window through
    no fault of the pacing code (a fixed floor flaked exactly this way on
    the Windows leg).
    """

    def __init__(self, channel):
        self.channel = channel
        self.first = None
        self.last = None

    def sink_factory(self):
        def make():
            return _SpanSink(self.channel.connect(), self)
        return make

    def window(self):
        if self.first is None or self.last is None:
            return 0.0
        return self.last - self.first


class _SpanSink:
    """Sink wrapper that timestamps every frame handed to ffmpeg."""

    def __init__(self, sink, span):
        self._sink = sink
        self._span = span

    def write(self, payload):
        now = time.monotonic()
        if self._span.first is None:
            self._span.first = now
        self._span.last = now
        return self._sink.write(payload)

    def close(self):
        self._sink.close()


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

    screen_span = DeliverySpan(screen_channel)
    cam_span = DeliverySpan(cam_channel)
    screen_feed = ScreenPipeFeed((0, 0, *SCREEN_SIZE), None, FPS,
                                 size=SCREEN_SIZE, mss_factory=FakeMss,
                                 sink_factory=screen_span.sink_factory())
    cam_feed = CameraPipeFeed(0, "darwin", None, FPS, size=CAMERA_SIZE,
                              opener=lambda idx: FakeCamera(),
                              sink_factory=cam_span.sink_factory())
    screen_feed.start()
    cam_feed.start()

    time.sleep(SECONDS)
    # production stop path: EOF every feeder first — ffmpeg finalises and
    # exits on its own (the only stop that flushes the MP4 trailer on every
    # platform); escalate to a signal, then a kill, only if it hangs.
    screen_feed.stop()
    cam_feed.stop()
    screen_feed.wait(4000)
    cam_feed.wait(4000)
    try:
        rc = proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        request_graceful_stop(proc)
        try:
            rc = proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = proc.wait(timeout=5)
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
    # The file must cover the wall-clock window the screen feeder actually
    # delivered (timestamped at the channel sink) — the overlay ends when the
    # main input ends. The nominal sleep is not the right reference: ffmpeg's
    # listener-binding delay on a loaded runner shrinks the fed window.
    window = screen_span.window()
    assert abs(duration - window) <= 1.0, \
        f"duration {duration:.2f}s vs fed window {window:.2f}s"
    # and the fed window itself must not have collapsed (the legacy bug this
    # guards: a 6s session came out as a 1.67s file)
    assert window >= SECONDS * 0.5, \
        f"fed window {window:.2f}s collapsed from the {SECONDS}s session"
    assert extra == []


def test_real_ffmpeg_minimal_filterless_command(qapp, tmp_path):
    """Screen only, no camera/preview/separate: no filter_complex is built,
    so this guards the plain `-map 0:v` path against real ffmpeg (label
    syntax like '[0:v]' would be rejected outside a filter graph)."""
    ffmpeg = find_ffmpeg()
    output = str(tmp_path / "minimal.mp4")
    channel = open_channel()
    cmd, _ = build_command(
        ffmpeg, output, FPS,
        screen=PipeScreenInput(channel.input_arg(), SCREEN_SIZE),
        encoder_main=["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28"])
    assert "-filter_complex" not in cmd
    pass_fds = tuple(fd for fd in (channel.pass_fd(),) if fd is not None)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, pass_fds=pass_fds)
    reader = ProcessOutputReader(proc.stderr)
    reader.start()
    channel.after_spawn()
    feed = ScreenPipeFeed((0, 0, *SCREEN_SIZE), None, FPS, size=SCREEN_SIZE,
                          mss_factory=FakeMss, sink_factory=channel.connect)
    feed.start()
    time.sleep(1.5)
    feed.stop()
    feed.wait(4000)
    try:
        rc = proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        request_graceful_stop(proc)
        rc = proc.wait(timeout=8)
    reader.join(2)
    assert rc in (0, 255), f"ffmpeg exit {rc}: {reader.tail_text(500)}"
    assert mp4check.recording_succeeded(rc, output)
