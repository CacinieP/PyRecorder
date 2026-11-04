"""Screen feeder: grab with mss, push raw BGRA frames into the ffmpeg pipe.

This replaces the legacy Windows path (mss -> BGRA->BGR -> OpenCV VideoWriter
-> MoviePy merge) with a straight bytes pump: mss's BGRA buffer is exactly
what ffmpeg's `rawvideo, pix_fmt bgra` input expects, so no per-frame numpy
conversion happens in Python (ADR-0002).

Like the camera pipe, this pipe carries no timestamps: the feeder paces to
the declared framerate (duplicating on slow grabs, resyncing after a stall)
or the recording timeline drifts.
"""
import time

from PyQt6.QtCore import QThread, pyqtSignal

from pyrecorder.channels import FdSink
from pyrecorder.pacing import frames_due


def even_size(width, height):
    """Round a capture rect down to even dimensions (yuv420p requirement)."""
    return (int(width) & ~1), (int(height) & ~1)


class ScreenPipeFeed(QThread):
    failed = pyqtSignal(str)

    def __init__(self, rect, write_fd, fps, size=None, mss_factory=None,
                 sink_factory=None):
        super().__init__()
        self.rect = tuple(rect)          # (left, top, w, h) physical px, even
        self.fps = fps
        self.size = tuple(size) if size else even_size(rect[2], rect[3])
        self._mss_factory = mss_factory
        # `write_fd` keeps the historical (test-facing) signature; a channel
        # sink_factory is what production uses (pipes on POSIX, TCP on Windows).
        self._sink_factory = sink_factory or (lambda: FdSink(write_fd))
        self._stop = False
        self.failure_reason = None

    def stop(self):
        self._stop = True

    def _fail(self, message):
        self.failure_reason = message
        self.failed.emit(message)

    def run(self):
        sct = None
        sink = None
        try:
            try:
                if self._mss_factory is not None:
                    sct = self._mss_factory()
                else:
                    import mss
                    sct = mss.mss()
            except Exception as exc:
                self._fail(f"Screen capture could not start: {exc}")
                return
            sink = self._sink_factory()
            monitor = {"left": self.rect[0], "top": self.rect[1],
                       "width": self.size[0], "height": self.size[1]}
            interval = 1.0 / (self.fps or 30)
            next_due = time.monotonic()
            bad_grabs = 0
            while not self._stop:
                try:
                    shot = sct.grab(monitor)
                    payload = shot.bgra
                except Exception as exc:
                    bad_grabs += 1
                    if bad_grabs >= 10:
                        self._fail(f"Screen capture stopped delivering frames: {exc}")
                        return
                    time.sleep(0.05)
                    continue
                bad_grabs = 0
                if len(payload) != self.size[0] * self.size[1] * 4:
                    self._fail("Screen capture returned an unexpected frame size.")
                    return
                due, next_due = frames_due(next_due, time.monotonic(), interval)
                if not due:
                    continue
                for _ in range(due):
                    if self._stop or not sink.write(payload):
                        return  # reader gone — recording stopped
        except Exception as exc:
            if not self._stop:
                self._fail(str(exc))
        finally:
            if sct is not None:
                try:
                    sct.close()
                except Exception:
                    pass
            if sink is not None:
                sink.close()  # EOF for ffmpeg
