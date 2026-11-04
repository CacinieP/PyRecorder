"""Camera capture: OpenCV everywhere, piped into ffmpeg as raw BGR.

ffmpeg's own camera demuxers misbehave (frozen frames on some macOS devices),
so the camera is always captured through OpenCV's platform backend and pushed
into the recording process through a rawvideo pipe (ADR-0003).
"""
import time

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage

from pyrecorder.channels import FdSink
from pyrecorder.pacing import estimate_fps, frames_due

# The preview bubble letterboxes onto this size; most modern cams deliver
# 1080p, and requesting that (then scaling in software) is more reliable than
# asking the device for a smaller mode, which some reject with an I/O error.
PREVIEW_W, PREVIEW_H = 640, 360
CAMERA_CAPTURE_SIZE = (1920, 1080)

_OPENCV_BACKEND = {
    "darwin": "CAP_AVFOUNDATION",
    "win32": "CAP_DSHOW",
    "linux": "CAP_V4L2",
}


def _backend_flag(platform_id):
    import cv2
    name = _OPENCV_BACKEND.get(platform_id)
    return getattr(cv2, name, 0) if name else 0


def open_camera(idx, platform_id):
    """Open `idx` via the platform's OpenCV backend and ask for 1080p.

    The device decides what it actually delivers, so callers must read the real
    frame size instead of assuming the request was honoured.
    """
    import cv2
    cap = cv2.VideoCapture(idx, _backend_flag(platform_id))
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_CAPTURE_SIZE[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_CAPTURE_SIZE[1])
    return cap


def probe_camera(camera_idx, platform_id, window=0.7):
    """Measure a camera: {"fps": float|None, "size": (w, h)} or None if unusable.

    Both facts are needed because the recorder feeds ffmpeg through a rawvideo
    pipe, which carries neither timestamps nor format probing: the declared rate
    becomes the camera clock, and the declared geometry decides whether a 4:3
    camera gets stretched into 16:9. Blocks for ~`window` seconds, so call it
    from a worker thread.
    """
    cap = None
    try:
        cap = open_camera(camera_idx, platform_id)
        if cap is None or not cap.isOpened():
            return None
        seen = []

        def read():
            ok, frame = cap.read()
            if ok and not seen:
                seen.append((int(frame.shape[1]), int(frame.shape[0])))
            return ok

        fps = estimate_fps(read, window=window)
        if not seen:
            return None
        return {"fps": fps, "size": seen[0]}
    except Exception:
        return None
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass


def letterbox(frame, w, h):
    """Resize `frame` into exactly (w, h) without distorting it.

    Used for the preview bubble, whose window is locked to 16:9 while the camera
    may not be — resizing to fill used to squeeze 4:3 into 16:9.
    """
    import cv2
    import numpy as np
    fh, fw = frame.shape[:2]
    s = min(w / fw, h / fh)
    nw, nh = max(1, int(round(fw * s))), max(1, int(round(fh * s)))
    small = cv2.resize(frame, (nw, nh))
    out = np.zeros((h, w, 3), np.uint8)
    y0, x0 = (h - nh) // 2, (w - nw) // 2
    out[y0:y0 + nh, x0:x0 + nw] = small[:, :, :3] if small.ndim == 3 else small
    return out


def clamp_pip(pip, cap_w, cap_h, aspect=9 / 16):
    """(w, x, y) kept fully inside the capture area.

    `aspect` is the camera's height/width, so a 4:3 camera (taller than the
    16:9 the bubble window shows) still lands entirely inside the frame.
    """
    w, x, y = pip
    h = int(w * aspect)
    x = max(0, min(x, cap_w - w))
    y = max(0, min(y, cap_h - h))
    return w, x, y


def pipe_camera_size(native, layout, separate, pip_w):
    """The frame size to push through the camera pipe.

    Raw BGR at 1920x1080 is 6.2MB per frame (~112MB/s at 18fps), which a Python
    feeder cannot sustain while the GUI and the preview reader contend for the
    GIL: measured 13.2 delivered fps against 18.7 declared, and a 6s session
    came out 1.67s long. So only send full resolution when something needs it —
    the separate camera file, or a speaker layout compositing at 1080 high.
    """
    w, h = int(native[0]), int(native[1])
    if separate or layout != "pip":
        return (w, h)
    target_w = int(pip_w) & ~1              # even, matches scale=W:-2
    if target_w < 2 or target_w >= w:
        return (w, h)
    target_h = max(2, int(round(h * target_w / w)) & ~1)
    return (target_w, target_h)


class CameraFrameThread(QThread):
    """Live camera preview for the floating bubble — the same platform capture
    path the recorder uses."""
    frame = pyqtSignal(object)
    failed = pyqtSignal(str)

    MAX_BAD_READS = 30

    def __init__(self, camera_idx, platform_id):
        super().__init__()
        self.camera_idx = camera_idx
        self.platform_id = platform_id
        self.cap = None
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        attempt = 0
        while not self._stop:
            try:
                self.cap = open_camera(self.camera_idx, self.platform_id)
            except Exception as e:
                self.failed.emit(str(e))
                return
            if not self.cap.isOpened():
                attempt += 1
                if attempt > 3:
                    self.failed.emit("Cannot open camera (check permission "
                                     "or other apps using it).")
                    return
                time.sleep(0.5)
                continue
            attempt = 0
            bad = 0
            while not self._stop:
                ret, frame = self.cap.read()  # blocks until next device frame
                if not ret:
                    bad += 1
                    if bad > self.MAX_BAD_READS:
                        break
                    time.sleep(0.1)
                    continue
                bad = 0
                small = letterbox(frame, PREVIEW_W, PREVIEW_H)
                img = QImage(small.tobytes(), PREVIEW_W, PREVIEW_H,
                             PREVIEW_W * 3,
                             QImage.Format.Format_BGR888).copy()
                self.frame.emit(img)
            self.cap.release()
            if self._stop:
                return
            self.failed.emit("Camera stream stalled — reconnecting…")
            time.sleep(0.5)
        return


class CameraPipeFeed(QThread):
    """Capture the camera with OpenCV and write raw BGR frames into the stream
    that ffmpeg reads as an input. Closing the stream signals EOF."""
    failed = pyqtSignal(str)
    MAX_BAD_READS = 30
    RETRY_DELAY = 0.1

    def __init__(self, camera_idx, platform_id, write_fd, fps, size=None,
                 opener=None, sink_factory=None):
        super().__init__()
        self.camera_idx = camera_idx
        self.platform_id = platform_id
        self.fps = fps
        # geometry the pipe promised ffmpeg; frames are resized to match it
        self.size = tuple(size) if size else CAMERA_CAPTURE_SIZE
        self._opener = opener or (lambda idx: open_camera(idx, platform_id))
        # `write_fd` keeps the historical (test-facing) signature; production
        # passes a channel sink_factory (pipes on POSIX, TCP on Windows).
        self._sink_factory = sink_factory or (lambda: FdSink(write_fd))
        self._stop = False
        self.failure_reason = None

    def stop(self):
        self._stop = True

    def _fail(self, message):
        # Keep the reason even if process completion is observed before the
        # queued signal reaches the GUI.
        self.failure_reason = message
        self.failed.emit(message)

    def run(self):
        import cv2
        cap = None
        sink = None
        try:
            cap = self._opener(self.camera_idx)
            if cap is None or not cap.isOpened():
                if not self._stop:
                    self._fail("Camera opened by recorder failed.")
                return
            sink = self._sink_factory()
            target = self.size
            # ffmpeg timestamps this pipe from the declared framerate alone, so
            # write on exactly that clock (duplicating when the device is slow).
            interval = 1.0 / (self.fps or 30)
            next_due = time.monotonic()
            last = None
            bad_reads = 0
            while not self._stop:
                ret, frame = cap.read()
                if self._stop:
                    return
                if ret:
                    bad_reads = 0
                    if frame.shape[1] != target[0] or frame.shape[0] != target[1]:
                        frame = cv2.resize(frame, target)
                    last = frame
                else:
                    bad_reads += 1
                    if bad_reads >= self.MAX_BAD_READS:
                        self._fail("Camera stopped delivering frames.")
                        return
                    # A disconnected device may fail immediately. Back off,
                    # retaining the last frame only during this short retry.
                    time.sleep(self.RETRY_DELAY)
                if last is None:
                    continue
                due, next_due = frames_due(next_due, time.monotonic(), interval)
                if not due:
                    continue
                payload = last.tobytes()
                for _ in range(due):
                    if self._stop or not sink.write(payload):
                        return  # reader gone — recording stopped
        except Exception as exc:
            if not self._stop:
                self._fail(str(exc))
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
            if sink is not None:
                sink.close()  # EOF for ffmpeg
