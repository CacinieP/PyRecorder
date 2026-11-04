"""Tests for the mss screen feeder: pacing, passthrough, EOF on stop."""
import os
import threading
import time

import pytest

pytest.importorskip("PyQt6", reason="pyrecorder imports PyQt6 at module level")

from pyrecorder.screenfeed import ScreenPipeFeed, even_size  # noqa: E402


def test_even_size_rounds_down():
    assert even_size(1921, 1081) == (1920, 1080)
    assert even_size(1920, 1080) == (1920, 1080)


class FakeShot:
    def __init__(self, size, counter):
        self.bgra = bytes([counter % 256]) * (size[0] * size[1] * 4)


class FakeMss:
    """Delivers one frame per grab call, counting them."""

    def __init__(self, size):
        self.size = size
        self.grabs = 0

    def grab(self, monitor):
        self.grabs += 1
        return FakeShot(self.size, self.grabs)

    def close(self):
        pass


def run_feed_seconds(feed, read_fd, seconds, frame_bytes):
    """Run `feed` for ~`seconds` while draining its pipe.

    Returns (frames_written, saw_eof, payload). The reader owns `read_fd` and
    closes it at EOF; the feed closes its write end when it stops, which is
    the EOF signal ffmpeg relies on.
    """
    chunks = []
    saw_eof = threading.Event()

    def reader():
        while True:
            data = os.read(read_fd, 1 << 16)
            if not data:
                saw_eof.set()
                os.close(read_fd)
                return
            chunks.append(data)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    feed.start()
    time.sleep(seconds)
    feed.stop()
    assert feed.wait(4000), "feed thread did not stop"
    thread.join(2)
    total = b"".join(chunks)
    return len(total) // frame_bytes, saw_eof.is_set(), total


def test_feed_paces_to_declared_framerate_and_signals_eof(qapp):
    size = (64, 48)
    r, w = os.pipe()
    fake = FakeMss(size)
    feed = ScreenPipeFeed((0, 0, size[0], size[1]), w, fps=10, size=size,
                          mss_factory=lambda: fake)
    frames, saw_eof, payload = run_feed_seconds(feed, r, 0.55, size[0] * size[1] * 4)
    assert 3 <= frames <= 8            # ~10fps for 0.55s, with pacing slack
    assert saw_eof                      # the feed closed the pipe (EOF for ffmpeg)
    assert payload[:1] == b"\x01"       # first grabbed frame went through first
    assert fake.grabs >= 2


def test_feed_reports_size_mismatch_as_failure(qapp):
    size = (64, 48)
    r, w = os.pipe()

    class BadMss(FakeMss):
        def grab(self, monitor):
            return FakeShot((32, 48), 1)   # wrong size

    failures = []
    feed = ScreenPipeFeed((0, 0, size[0], size[1]), w, fps=5, size=size,
                          mss_factory=lambda: BadMss(size))
    feed.failed.connect(failures.append)
    frames, saw_eof, _ = run_feed_seconds(feed, r, 0.4, size[0] * size[1] * 4)
    qapp.processEvents()      # queued cross-thread signal delivery
    assert failures and "unexpected frame size" in failures[0]
    assert saw_eof


def test_feed_survives_transient_grab_errors(qapp):
    size = (64, 48)
    r, w = os.pipe()

    class FlakyMss(FakeMss):
        def grab(self, monitor):
            self.grabs += 1
            if self.grabs in (2, 3):
                raise OSError("transient")
            return FakeShot(self.size, self.grabs)

    failures = []
    feed = ScreenPipeFeed((0, 0, size[0], size[1]), w, fps=10, size=size,
                          mss_factory=lambda: FlakyMss(size))
    feed.failed.connect(failures.append)
    frames, saw_eof, _ = run_feed_seconds(feed, r, 0.5, size[0] * size[1] * 4)
    assert not failures
    assert frames >= 2 and saw_eof
