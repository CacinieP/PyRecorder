"""
macOS Screen Recorder (ffmpeg backend)
Screen recording with simultaneous webcam (PiP) and microphone, encoded in
hardware (h264_videotoolbox) — one ffmpeg process, no post-merge step.
Requires: brew install ffmpeg, plus Screen Recording / Camera / Microphone
permission for the app (or terminal) running this script.
"""

import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime

from process_output import ProcessOutputReader

from PyQt6.QtCore import QEvent, QRect, QThread, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton, QSizePolicy, QSpinBox,
    QSizeGrip, QVBoxLayout, QWidget,
)

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def ffmpeg_available():
    return shutil.which("ffmpeg") is not None or os.path.exists(FFMPEG)


def parse_av_device_lists(text):
    """Parse avfoundation `-list_devices` output into (screens, cameras, mics).

    Each is a list of (index, name) in the order ffmpeg reported them, so the UI
    can offer every audio input (e.g. BlackHole for system audio) instead of
    silently hard-coding the first one.
    """
    screens, cameras, mics = [], [], []
    section = "video"
    for line in (text or "").splitlines():
        if "AVFoundation video devices" in line:
            section = "video"
            continue
        if "AVFoundation audio devices" in line:
            section = "audio"
            continue
        m = re.search(r"\[(\d+)\]\s+(.+)$", line.strip())
        if not m:
            continue
        idx, name = int(m.group(1)), m.group(2).strip()
        if section == "audio":
            mics.append((idx, name))
        elif "Capture screen" in name:
            screens.append((idx, name))
        else:
            cameras.append((idx, name))
    return screens, cameras, mics


def _first(devices):
    return devices[0][0] if devices else None


def parse_av_devices(text):
    """(screen_index, camera_index, mic_index) — the first of each class."""
    screens, cameras, mics = parse_av_device_lists(text)
    return _first(screens), _first(cameras), _first(mics)


def list_all_av_devices():
    """(screens, cameras, mics) as lists of (index, name) from avfoundation."""
    try:
        proc = subprocess.run(
            [FFMPEG, "-hide_banner", "-f", "avfoundation", "-list_devices",
             "true", "-i", ""],
            capture_output=True, text=True, timeout=20,
        )
    except Exception:
        return [], [], []
    return parse_av_device_lists(proc.stderr)


def list_av_devices():
    """Return (screen_index, camera_index, mic_index) from avfoundation."""
    screens, cameras, mics = list_all_av_devices()
    return _first(screens), _first(cameras), _first(mics)


def probe_audio_device(mic_idx, ffmpeg=None, timeout=10):
    """True when ffmpeg can actually open this audio input device.

    Appearing in the device list is not enough: with Microphone permission
    denied (or the device busy) avfoundation fails to open it, and because audio
    shares the recording command the *whole* capture would die. Probing first
    lets the recorder degrade to video-only with a warning. Costs ~0.4s; an
    invalid index exits 251 with "Invalid audio device index".
    """
    if mic_idx is None:
        return False
    ff = ffmpeg or FFMPEG
    try:
        proc = subprocess.run(
            [ff, "-hide_banner", "-loglevel", "error", "-f", "avfoundation",
             "-i", f":{mic_idx}", "-t", "0.2", "-f", "null", "-"],
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception:
        return False
    return proc.returncode == 0


def frames_due(next_due, now, interval, max_catchup=2.0):
    """(copies_to_write, new_next_due) for a writer pacing to `interval`.

    The camera pipe carries no timestamps — ffmpeg derives them from the
    declared framerate — so the writer must honour that rate exactly or the
    camera timeline drifts behind the screen timeline and, because `overlay`
    waits for both inputs, the recording ends up shorter than the session.
    Falling behind is therefore paid back by duplicating frames; only a stall
    longer than `max_catchup` resyncs, to avoid flooding the pipe.
    """
    if now < next_due:
        return 0, next_due
    backlog = now - next_due
    if backlog > max_catchup:
        return 1, now + interval
    n = int(backlog // interval) + 1
    return n, next_due + n * interval


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


PREVIEW_W, PREVIEW_H = 640, 360
# this device (and most modern cams) only delivers 1080p; request that and
# scale down in the filter — forcing smaller sizes fails with I/O error
CAMERA_CAPTURE_SIZE = "1920x1080"
# The live-preview stream is letterboxed onto this fixed canvas so the reader
# never has to guess the geometry (it used to, and got Speaker modes wrong).
LIVE_PREVIEW_W, LIVE_PREVIEW_H = 480, 270

GO_STYLE = ("QPushButton { background-color: #4CAF50; color: white;"
            " font-size: 14px; font-weight: bold; border-radius: 6px; }"
            " QPushButton:hover { background-color: #45a049; }")
STOP_STYLE = ("QPushButton { background-color: #f44336; color: white;"
              " font-size: 14px; font-weight: bold; border-radius: 6px; }"
              " QPushButton:hover { background-color: #da190b; }")


def _open_camera(idx):
    """Open `idx` through OpenCV's AVFoundation backend and ask for 1080p.

    The device decides what it actually delivers, so callers must read the real
    frame size instead of assuming the request was honoured.
    """
    import cv2
    cap = cv2.VideoCapture(idx, cv2.CAP_AVFOUNDATION)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    return cap


def probe_camera(camera_idx, window=0.7):
    """Measure a camera: {"fps": float|None, "size": (w, h)} or None if unusable.

    Both facts are needed because the recorder feeds ffmpeg through a rawvideo
    pipe, which carries neither timestamps nor format probing: the declared rate
    becomes the camera clock, and the declared geometry decides whether a 4:3
    camera gets stretched into 16:9. Blocks for ~`window` seconds, so call it
    from a worker thread.
    """
    cap = None
    try:
        cap = _open_camera(camera_idx)
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


class PreRecordProbe(QThread):
    """Run the blocking device probes off the GUI thread.

    start_recording() used to do them inline: ~0.7–1s for the camera plus ~0.4s
    for the microphone froze the window on every Start.
    """
    done = pyqtSignal(dict)

    def __init__(self, camera_idx, mic_idx, want_camera, want_mic,
                 camera_prober=probe_camera, mic_prober=probe_audio_device):
        super().__init__()
        self.camera_idx = camera_idx
        self.mic_idx = mic_idx
        self.want_camera = want_camera
        self.want_mic = want_mic
        self._camera_prober = camera_prober
        self._mic_prober = mic_prober

    def run(self):
        camera = None
        if not self.isInterruptionRequested() and self.want_camera and self.camera_idx is not None:
            try:
                camera = self._camera_prober(self.camera_idx)
            except Exception:
                camera = None
        mic_ok = False
        if not self.isInterruptionRequested() and self.want_mic and self.mic_idx is not None:
            try:
                mic_ok = bool(self._mic_prober(self.mic_idx))
            except Exception:
                mic_ok = False
        if not self.isInterruptionRequested():
            self.done.emit({"camera": camera, "mic_ok": mic_ok})


class CameraFrameThread(QThread):
    """Live camera preview via OpenCV's AVFoundation backend — the same
    AVCaptureSession path QuickTime uses. ffmpeg's avfoundation demuxer
    delivers a frozen stream on some devices; OpenCV does not."""
    frame = pyqtSignal(object)
    failed = pyqtSignal(str)

    MAX_BAD_READS = 30

    def __init__(self, camera_idx):
        super().__init__()
        self.camera_idx = camera_idx
        self.cap = None
        self._stop = False

    def _open(self):
        return _open_camera(self.camera_idx)

    def stop(self):
        self._stop = True

    def run(self):
        import time
        attempt = 0
        while not self._stop:
            try:
                self.cap = self._open()
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

class PipPreviewWindow(QWidget):
    """Floating camera bubble: draggable anywhere, resizable (16:9 locked).

    Its geometry on screen IS the PiP position/size used when recording
    (converted to device pixels relative to the capture region)."""
    geometry_changed = pyqtSignal()
    MIN_W, MAX_W = 120, 800

    def __init__(self, camera_idx, initial_width):
        super().__init__(None, Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.camera_idx = camera_idx
        self._drag_offset = None
        self._fixed_aspect = 9 / 16  # h/w — camera delivers 16:9 at 1080p
        self._resizing = False

        self.video_label = QLabel("Starting camera…")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet(
            "background-color: rgba(20,20,20,230); color:#aaa;"
            "border: 2px solid #00aeff; border-radius: 12px;"
            "font-size: 12px;")

        grip = QSizeGrip(self)
        grip.setFixedSize(20, 20)
        grip.installEventFilter(self)

        # corner buttons keep the 16:9 ratio no matter how the user zooms
        btn_style = ("QPushButton { background: rgba(40,40,40,200); color:#fff;"
                     " border-radius: 9px; font-weight: bold; }"
                     "QPushButton:hover { background: rgba(0,174,255,220); }")
        minus = QPushButton("−", self)
        minus.setFixedSize(18, 18)
        minus.setStyleSheet(btn_style)
        minus.clicked.connect(lambda: self.zoom(4 / 5))
        plus = QPushButton("+", self)
        plus.setFixedSize(18, 18)
        plus.setStyleSheet(btn_style)
        plus.clicked.connect(lambda: self.zoom(5 / 4))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.video_label)

        self.minus_btn, self.plus_btn = minus, plus
        self._reposition_overlays(grip)

        w = max(self.MIN_W, min(self.MAX_W, initial_width))
        self.resize(w, round(w * self._fixed_aspect))

        self.thread = CameraFrameThread(camera_idx)
        self.thread.frame.connect(self.on_frame)
        self.thread.failed.connect(self.on_failed)
        self.thread.finished.connect(self._finish_close)
        self._closing = False
        self.thread.start()

    def _reposition_overlays(self, grip=None):
        grip = grip or self.findChild(QSizeGrip)
        if grip:
            grip.move(self.width() - 20, self.height() - 20)
            grip.raise_()
        self.plus_btn.move(self.width() - 46, 8)
        self.minus_btn.move(self.width() - 24, 8)
        for b in (self.plus_btn, self.minus_btn):
            b.raise_()

    def zoom(self, factor):
        w = int(self.width() * factor)
        w = max(self.MIN_W, min(self.MAX_W, w))
        # keep the top-right corner roughly stationary (buttons live there)
        dx = self.width() - w
        self.resize(w, round(w * self._fixed_aspect))
        self.move(self.x() + dx, self.y())
        self.geometry_changed.emit()

    def eventFilter(self, obj, event):
        # grip drag: anchored to the press position, so the width is always
        # start_width + cursor_delta — no feedback from the window's own size
        if obj is not None and isinstance(obj, QSizeGrip):
            if event.type() == QEvent.Type.MouseButtonPress:
                self._resizing = True
                self._resize_start_w = self.width()
                self._resize_start_gx = event.globalPosition().toPoint().x()
                return True
            if self._resizing and event.type() == QEvent.Type.MouseMove:
                dx = event.globalPosition().toPoint().x() - self._resize_start_gx
                w = max(self.MIN_W, min(self.MAX_W, self._resize_start_w + dx))
                self.resize(w, round(w * self._fixed_aspect))
                self._reposition_overlays()
                self.geometry_changed.emit()
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._resizing = False
                self.geometry_changed.emit()
                return True
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # fix the video area so the pixmap never drives the window size
        self.video_label.setFixedSize(self.width(), self.height())
        self._reposition_overlays()

    def on_frame(self, img):
        target_w = max(2, self.width() - 4)
        target_h = max(2, round(target_w * self._fixed_aspect) - 4)
        pm = QPixmap.fromImage(img).scaled(
            target_w, target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.video_label.setPixmap(pm)

    def on_failed(self, msg):
        self.video_label.setText("Camera unavailable\n" + msg)

    # drag by pressing anywhere on the video area
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self.frameGeometry().topLeft())

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and not self._resizing:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            self.geometry_changed.emit()

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        self.geometry_changed.emit()

    def closeEvent(self, event):
        self._closing = True
        self.thread.stop()
        if self.thread.isRunning():
            event.ignore()
            return
        super().closeEvent(event)

    def _finish_close(self):
        if self._closing:
            self.close()

    def pip_rect(self, capture_origin_logical, scale):
        """(w, x, y) in device pixels relative to the capture origin."""
        g = self.geometry()
        w = int(g.width() * scale)
        x = int((g.x() - capture_origin_logical[0]) * scale)
        y = int((g.y() - capture_origin_logical[1]) * scale)
        return w, x, y


def build_command(output_path, fps, screen_idx, mic_idx, camera_idx,
                  mic_enabled, camera_enabled, pip, region=None,
                  screen_scale=1.0, layout="pip", separate=False, preview=False,
                  camera_pipe_fd=None, camera_fps=None, camera_size=None):
    """Assemble the ffmpeg command.

    region: (x, y, w, h) logical points, or None for full screen.
    pip: (w, x, y) camera overlay width/position in OUTPUT device pixels,
         relative to the capture origin (layout="pip" only).
    layout: "pip" (corner overlay) | "speaker-right" | "speaker-left"
            (Tencent-Meeting presenter style: screen + speaker panel side by
            side, composited at 1080p height).
    separate: also write screen-only and camera-only files next to output.
    preview: also output a downscaled composited rawvideo stream on stdout.
    camera_pipe_fd: child fd that raw BGR camera frames arrive on. The frames
         are captured by OpenCV (AVFoundation), because ffmpeg's own
         avfoundation camera demuxer delivers a frozen stream on some devices.
    camera_fps: the camera's *measured* delivery rate. The pipe input carries
        no timestamps of its own, so whatever is declared here becomes the
        camera clock; declaring the GUI fps while the device is slower makes
        ffmpeg duplicate frames and the whole timeline run slow.

    Returns (cmd, extra_files)."""
    extra_files = []
    if mic_enabled and mic_idx is not None:
        video_in = f"{screen_idx}:{mic_idx}"
    else:
        video_in = f"{screen_idx}:none" if mic_idx is not None else str(screen_idx)

    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "warning", "-y",
        "-f", "avfoundation", "-framerate", str(fps),
        "-capture_cursor", "1", "-capture_mouse_clicks", "1",
        "-i", video_in,
    ]
    audio_stream = "0:a" if mic_enabled and mic_idx is not None else None

    filters = []
    base = "[0:v]"

    # crop first, so the screen-only file holds what was actually recorded
    if region:
        x, y, w, h = region
        x, y = int(x * screen_scale), int(y * screen_scale)
        w, h = int(w * screen_scale), int(h * screen_scale)
        filters.append(f"{base}crop={w}:{h}:{x}:{y}[crp]")
        base = "[crp]"

    # split the (already cropped) screen if it is also wanted as its own file
    scr_stream = base
    if separate:
        filters.append(f"{base}split=2[scrA][scrB]")
        scr_stream, base = "[scrA]", "[scrB]"

    cam_stream = None
    if camera_enabled and camera_idx is not None and camera_pipe_fd is not None:
        if camera_size:
            size_str = f"{int(camera_size[0])}x{int(camera_size[1])}"
        else:
            size_str = CAMERA_CAPTURE_SIZE
        cmd += [
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-video_size", size_str,
            "-framerate", str(round(camera_fps or fps, 3)),
            "-i", f"pipe:{camera_pipe_fd}",
        ]
        cam_in = "[1:v]"
        if separate:
            filters.append(f"{cam_in}split=2[camA][camB]")
            cam_stream, cam_in = "[camA]", "[camB]"

        if layout == "pip":
            pip_w, pip_x, pip_y = int(pip[0]), int(pip[1]), int(pip[2])
            filters.append(f"{cam_in}scale={pip_w}:-2[cam]")
            filters.append(f"{base}[cam]overlay={pip_x}:{pip_y}[out]")
        else:
            # presenter mode: equalize heights at 1080, stack horizontally
            if layout == "speaker-right":
                filters.append(
                    f"{cam_in}scale=-2:1080[spk];"
                    f"{base}scale=-2:1080[scrS];"
                    f"[scrS][spk]hstack=inputs=2[out]")
            else:
                filters.append(
                    f"{cam_in}scale=-2:1080[spk];"
                    f"{base}scale=-2:1080[scrS];"
                    f"[spk][scrS]hstack=inputs=2[out]")
        base = "[out]"

    if preview:
        filters.append(
            f"{base}split=2[rec][pv];"
            f"[pv]scale={LIVE_PREVIEW_W}:{LIVE_PREVIEW_H}:"
            f"force_original_aspect_ratio=decrease,"
            f"pad={LIVE_PREVIEW_W}:{LIVE_PREVIEW_H}:(ow-iw)/2:(oh-ih)/2[prev]")
        base = "[rec]"

    if filters:
        cmd += ["-filter_complex", ";".join(filters)]

    cmd += ["-map", base]

    if audio_stream:
        cmd += ["-map", audio_stream, "-c:a", "aac", "-b:a", "128k"]
    # `-r` on every output: the avfoundation screen input reports a bogus
    # "1000k tbr", and any output inheriting it (the rawvideo preview above all)
    # makes ffmpeg duplicate frames without bound.
    cmd += ["-c:v", "h264_videotoolbox", "-b:v", "8M", "-pix_fmt", "yuv420p",
            "-r", str(fps), output_path]

    # separate files (no re-filtering, hardware encoded)
    if separate and scr_stream:
        cmd += ["-map", scr_stream, "-c:v", "h264_videotoolbox", "-b:v", "8M",
                "-pix_fmt", "yuv420p", "-r", str(fps),
                output_path.replace(".mp4", "_screen.mp4")]
        extra_files.append(output_path.replace(".mp4", "_screen.mp4"))
    if separate and cam_stream:
        cmd += ["-map", cam_stream, "-c:v", "h264_videotoolbox", "-b:v", "2M",
                "-pix_fmt", "yuv420p", "-r", str(fps),
                output_path.replace(".mp4", "_camera.mp4")]
        extra_files.append(output_path.replace(".mp4", "_camera.mp4"))

    if preview:
        cmd += ["-map", "[prev]", "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-r", str(fps), "pipe:1"]
    return cmd, extra_files


class CameraPipeFeed(QThread):
    """Capture the camera with OpenCV and write raw BGR frames into the pipe
    that ffmpeg reads as its second input. Closing the pipe signals EOF."""
    failed = pyqtSignal(str)

    def __init__(self, camera_idx, write_fd, fps, size=None, opener=None):
        super().__init__()
        self.camera_idx = camera_idx
        self.write_fd = write_fd
        self.fps = fps
        # geometry the pipe promised ffmpeg; frames are resized to match it
        self.size = tuple(size) if size else (1920, 1080)
        self._opener = opener or _open_camera
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        import cv2
        cap = None
        try:
            cap = self._opener(self.camera_idx)
            if cap is None or not cap.isOpened():
                self.failed.emit("Camera opened by recorder failed.")
                return
            target = self.size
            # ffmpeg timestamps this pipe from the declared framerate alone, so
            # write on exactly that clock (duplicating when the device is slow).
            interval = 1.0 / (self.fps or 30)
            next_due = time.monotonic()
            last = None
            while not self._stop:
                ret, frame = cap.read()
                if ret:
                    if frame.shape[1] != target[0] or frame.shape[0] != target[1]:
                        frame = cv2.resize(frame, target)
                    last = frame
                if last is None:
                    continue
                due, next_due = frames_due(next_due, time.monotonic(), interval)
                if not due:
                    continue
                payload = last.tobytes()
                for _ in range(due):
                    try:
                        remaining = memoryview(payload)
                        while remaining and not self._stop:
                            written = os.write(self.write_fd, remaining)
                            if written <= 0:
                                return
                            remaining = remaining[written:]
                    except OSError:
                        return  # reader gone — recording stopped
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
            try:
                os.close(self.write_fd)  # EOF for ffmpeg
            except OSError:
                pass


def preview_dims(region=None, screen_geo=None, scale=1.0, layout="pip"):
    """(w, h) of the rawvideo preview stream.

    build_command() letterboxes the preview onto a fixed canvas, so the size no
    longer depends on the capture region, the pixel ratio or the layout. The
    parameters are kept for call-site compatibility.
    """
    return LIVE_PREVIEW_W, LIVE_PREVIEW_H


def estimate_fps(read_frame, window=1.0, clock=time.monotonic):
    """Measure a capture device's real delivery rate in frames/second.

    read_frame() must return True when it delivered a frame. The first frame is
    treated as warm-up (device start latency) and excluded. Returns None when
    the device delivers too few frames to trust.
    """
    t0 = clock()
    elapsed = 0.0
    frames = 0
    warmed = False
    while True:
        got = read_frame()
        now = clock()
        if got:
            if warmed:
                frames += 1
            else:
                warmed = True
                t0 = now
        elapsed = now - t0
        if elapsed >= window:
            break
        if not warmed and elapsed >= window * 3:
            break   # device never produced a frame
    if frames < 2 or elapsed <= 0:
        return None
    return frames / elapsed


def pick_camera_fps(measured, fallback, lo=5.0, hi=60.0):
    """Clamp a measured camera rate into a usable range, else use the fallback."""
    if not measured:
        return float(fallback)
    return float(min(hi, max(lo, measured)))


def _mp4_has_moov(path, tail_bytes=4 * 1024 * 1024):
    """True when the mp4 trailer (moov atom) was written.

    ffmpeg writes moov last. A recording interrupted before the muxer finished
    leaves plenty of mdat bytes behind but no moov, so the file has a plausible
    size yet will not play and ffprobe reports no duration.
    """
    try:
        size = os.path.getsize(path)
        if size == 0:
            return False
        with open(path, "rb") as f:
            f.seek(max(0, size - tail_bytes))
            return b"moov" in f.read()
    except OSError:
        return False


def recording_succeeded(returncode, output_path):
    """A recording is good when ffmpeg exited cleanly *and* left a playable file.

    ffmpeg exits 0 after 'q' and 255 after SIGTERM; a negative code means it was
    killed and never finalised the container. The moov check catches the case
    where the exit code looks fine but the trailer is missing.
    """
    if returncode not in (0, 255):
        return False
    return _mp4_has_moov(output_path)


class LivePreviewThread(QThread):
    """Read composited rawvideo frames piped from the recording process."""
    frame = pyqtSignal(object)

    def __init__(self, proc, w, h):
        super().__init__()
        self.proc = proc
        self.w, self.h = w, h
        self._stop = False

    def run(self):
        n = self.w * self.h * 3
        while not self._stop:
            data = self.proc.stdout.read(n)
            if len(data) < n:
                break
            self.frame.emit(QImage(data, self.w, self.h, self.w * 3,
                                   QImage.Format.Format_RGB888).copy())

    def stop(self):
        self._stop = True


class LivePreviewWindow(QWidget):
    """Always-on-top live preview of the composited output (screen + PiP)."""

    def __init__(self, w, h):
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool)
        self.setWindowTitle("Live Preview — what is being recorded")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.label = QLabel()
        self.label.setMinimumSize(w, h)
        self.label.setStyleSheet("background-color: #111; border-radius: 6px;")
        self.label.setScaledContents(True)
        layout.addWidget(self.label)

    def on_frame(self, img):
        self.label.setPixmap(QPixmap.fromImage(img))

    def closeEvent(self, event):
        event.accept()


class RegionSelector(QWidget):
    """Full-screen translucent overlay for dragging a capture region."""
    region_selected = pyqtSignal(tuple)

    def __init__(self):
        screen = QGuiApplication.primaryScreen()
        geo = screen.geometry()
        super().__init__(None, Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setGeometry(geo)
        self.setMouseTracking(True)
        self.start_pos = None
        self.end_pos = None
        self.setCursor(Qt.CursorShape.CrossCursor)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 60))
        if self.start_pos and self.end_pos:
            rect = self._rect()
            p.setPen(QPen(QColor(0, 174, 255), 2))
            p.setBrush(QColor(0, 174, 255, 50))
            p.drawRect(rect)
            p.setPen(QColor(255, 255, 255))
            p.drawText(rect.adjusted(0, -24, 0, 0),
                       Qt.AlignmentFlag.AlignCenter,
                       f"{rect.width()} x {rect.height()}")
        p.end()

    def _rect(self):
        x1, x2 = sorted((self.start_pos.x(), self.end_pos.x()))
        y1, y2 = sorted((self.start_pos.y(), self.end_pos.y()))
        ox, oy = self.geometry().x(), self.geometry().y()
        return QRect(x1 - ox, y1 - oy, x2 - x1, y2 - y1)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_pos = event.globalPosition().toPoint()
            self.end_pos = self.start_pos
            self.update()

    def mouseMoveEvent(self, event):
        if self.start_pos:
            self.end_pos = event.globalPosition().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if self.start_pos and self.end_pos:
            x1, x2 = sorted((self.start_pos.x(), self.end_pos.x()))
            y1, y2 = sorted((self.start_pos.y(), self.end_pos.y()))
            w, h = x2 - x1, y2 - y1
            self.close()
            if w > 10 and h > 10:
                self.region_selected.emit((x1, y1, w, h))
        else:
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()


class ScreenRecorderMac(QMainWindow):
    def __init__(self):
        super().__init__()
        self.proc = None
        self._stop_requested = False
        self._stop_started = None
        self._kill_requested = False
        self._session = 0
        self._state = "idle"
        self._closing = False
        self._pending = None
        self.probe_thread = None
        self.stderr_reader = None
        self._retired_pip_windows = []
        self.output_path = ""
        self.region = None
        self.screen_idx = self.camera_idx = self.mic_idx = None
        self.pip_window = None
        self.live_thread = None
        self.live_window = None
        self.cam_feed = None
        self.extra_files = []
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.timeout.connect(self.update_elapsed)
        self.lifecycle_timer = QTimer(self)
        self.lifecycle_timer.setInterval(50)
        self.lifecycle_timer.timeout.connect(self._poll_lifecycle)
        self.start_time = 0.0
        self.init_ui()
        QTimer.singleShot(100, self.probe_devices)

    def init_ui(self):
        self.setWindowTitle("PyRecorder for macOS")
        self.setMinimumWidth(430)
        self.resize(460, min(760, int(QGuiApplication.primaryScreen()
                                      .availableGeometry().height() * 0.85)))

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        title = QLabel("PyRecorder for macOS")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Output
        out_group = QGroupBox("Output")
        out_layout = QHBoxLayout()
        self.path_label = QLabel("Default: ~/Movies")
        self.path_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                      QSizePolicy.Policy.Preferred)
        browse = QPushButton("Choose...")
        browse.clicked.connect(self.browse_folder)
        out_layout.addWidget(self.path_label, 1)
        out_layout.addWidget(browse)
        out_group.setLayout(out_layout)
        layout.addWidget(out_group)

        # Capture
        cap_group = QGroupBox("Capture Area")
        cap_layout = QHBoxLayout()
        self.region_label = QLabel("Full Screen")
        self.region_btn = QPushButton("Select Region")
        self.region_btn.clicked.connect(self.select_region)
        self.clear_region_btn = QPushButton("Clear")
        self.clear_region_btn.clicked.connect(self.clear_region)
        cap_layout.addWidget(self.region_label, 1)
        cap_layout.addWidget(self.region_btn)
        cap_layout.addWidget(self.clear_region_btn)
        cap_group.setLayout(cap_layout)
        layout.addWidget(cap_group)

        # Webcam
        cam_group = QGroupBox("Camera (Picture-in-Picture)")
        cam_layout = QVBoxLayout()
        cam_top_row = QHBoxLayout()
        self.cam_checkbox = QCheckBox("Record camera overlay")
        cam_top_row.addWidget(self.cam_checkbox)
        self.preview_btn = QPushButton("Preview & Position")
        self.preview_btn.setCheckable(True)
        self.preview_btn.toggled.connect(self.toggle_pip_preview)
        cam_top_row.addStretch()
        cam_top_row.addWidget(self.preview_btn)
        cam_layout.addLayout(cam_top_row)

        layout_row = QHBoxLayout()
        layout_row.addWidget(QLabel("Layout:"))
        self.layout_combo = QComboBox()
        self.layout_combo.addItems([
            "Corner PiP (draggable bubble)",
            "Speaker Right (presenter mode)",
            "Speaker Left (presenter mode)",
        ])
        layout_row.addWidget(self.layout_combo, 1)
        cam_layout.addLayout(layout_row)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Default size:"))
        self.cam_size = QSpinBox()
        self.cam_size.setRange(120, 640)
        self.cam_size.setValue(320)
        self.cam_size.setSingleStep(40)
        size_row.addWidget(self.cam_size)
        size_row.addWidget(QLabel("px  (drag the bubble to move, "
                                  "corner grip to resize)"))
        size_row.addStretch()
        cam_layout.addLayout(size_row)
        cam_group.setLayout(cam_layout)
        layout.addWidget(cam_group)

        # Options
        opt_group = QGroupBox("Options")
        opt_stack = QVBoxLayout()
        opt_layout = QHBoxLayout()
        self.mic_checkbox = QCheckBox("Microphone")
        self.mic_checkbox.setChecked(True)
        opt_layout.addWidget(self.mic_checkbox)
        opt_layout.addWidget(QLabel("FPS:"))
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(10, 60)
        self.fps_spin.setValue(30)
        opt_layout.addWidget(self.fps_spin)
        opt_layout.addStretch()
        self.separate_checkbox = QCheckBox("Also save separate screen & camera files")
        opt_layout.addWidget(self.separate_checkbox)
        opt_stack.addLayout(opt_layout)

        # Every audio input ffmpeg can see, so a virtual device (BlackHole) can
        # be chosen for system audio instead of only the first microphone.
        mic_row = QHBoxLayout()
        mic_row.addWidget(QLabel("Audio input:"))
        self.mic_combo = QComboBox()
        self.mic_combo.setSizePolicy(QSizePolicy.Policy.Expanding,
                                     QSizePolicy.Policy.Preferred)
        mic_row.addWidget(self.mic_combo, 1)
        opt_stack.addLayout(mic_row)

        opt_group.setLayout(opt_stack)
        layout.addWidget(opt_group)

        # Status
        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)

        self.record_btn = QPushButton("Start Recording")
        self.record_btn.setMinimumHeight(44)
        self.record_btn.setStyleSheet(GO_STYLE)
        self.record_btn.clicked.connect(self.toggle_recording)
        layout.addWidget(self.record_btn)

        layout.addStretch()

    # ---- devices & permissions ----

    def probe_devices(self):
        if self._closing or self._state != "idle":
            return
        if not ffmpeg_available():
            QMessageBox.warning(
                self, "ffmpeg not found",
                "ffmpeg is required but not installed.\n\n"
                "Install it with Homebrew:\n    brew install ffmpeg\n\n"
                "Then restart PyRecorder.")
            self.status_label.setText("ffmpeg missing")
            return
        screens, cameras, mics = list_all_av_devices()
        self.screen_idx = _first(screens)
        self.camera_idx = _first(cameras)
        self.mic_idx = _first(mics)
        self._populate_mic_combo(mics)
        parts = []
        parts.append("screen OK" if self.screen_idx is not None else "screen NOT found")
        parts.append("camera OK" if self.camera_idx is not None else "no camera")
        parts.append("mic OK" if self.mic_idx is not None else "no mic")
        self.status_label.setText("Devices: " + ", ".join(parts))

    def _populate_mic_combo(self, devices):
        """Fill the audio-input chooser, keeping the current pick if it survives."""
        previous = self.mic_combo.currentData()
        self.mic_combo.blockSignals(True)
        self.mic_combo.clear()
        for idx, name in devices:
            self.mic_combo.addItem(f"{name}  [{idx}]", idx)
        if previous is not None:
            at = self.mic_combo.findData(previous)
            if at >= 0:
                self.mic_combo.setCurrentIndex(at)
        self.mic_combo.blockSignals(False)

    def selected_mic_index(self):
        """avfoundation index of the chosen audio input, or None when there is
        no device / no chooser yet."""
        if self.mic_combo.count() == 0:
            return None
        data = self.mic_combo.currentData()
        return self.mic_idx if data is None else data

    # ---- actions ----

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Save Folder",
                                                  os.path.expanduser("~/Movies"))
        if folder:
            self.save_folder = folder
            self.path_label.setText(folder)

    def select_region(self):
        self.selector = RegionSelector()
        self.selector.region_selected.connect(self.on_region_selected)
        self.selector.show()

    def on_region_selected(self, region):
        self.region = region
        self.region_label.setText(f"Region: {region[2]} x {region[3]}")

    def clear_region(self):
        self.region = None
        self.region_label.setText("Full Screen")

    # ---- camera preview bubble ----

    def toggle_pip_preview(self, checked):
        if not checked:
            self._close_pip_bubble()
            return
        if self.camera_idx is None:
            self.probe_devices()
            if self.camera_idx is None:
                QMessageBox.warning(self, "PyRecorder",
                                    "No camera device found.")
                self.preview_btn.setChecked(False)
                return
        screen = QGuiApplication.primaryScreen().geometry()
        w = self.cam_size.value()
        self.pip_window = PipPreviewWindow(self.camera_idx, w)
        self.pip_window.move(screen.x() + screen.width() - w - 40,
                             screen.y() + screen.height() - int(w * 9 / 16) - 60)
        self.pip_window.show()
        # size spinbox only sets the *initial* size; ignore while bubble exists
        self.cam_size.setEnabled(False)

    # ---- recording ----

    def toggle_recording(self):
        if self.proc is not None:
            self.stop_recording()
        elif self._state == "idle" and not self._closing:
            self.start_recording()

    def start_recording(self):
        if self._closing or self._state != "idle" or self.proc is not None:
            return
        if not ffmpeg_available():
            self.probe_devices()
            if not ffmpeg_available():
                return
        if self.screen_idx is None:
            self.probe_devices()
            if self.screen_idx is None:
                QMessageBox.critical(
                    self, "PyRecorder",
                    "No screen capture device found.\n\n"
                    "Grant Screen Recording permission:\n"
                    "System Settings → Privacy & Security → Screen Recording,\n"
                    "enable your terminal/app, then restart it and PyRecorder.")
                return

        folder = getattr(self, "save_folder", None) or os.path.expanduser("~/Movies")
        os.makedirs(folder, exist_ok=True)
        self.output_path = os.path.join(
            folder, f"recording_{datetime.now():%Y%m%d_%H%M%S}.mp4")

        screen = QGuiApplication.primaryScreen()
        scale = screen.devicePixelRatio() or 1.0
        screen_geo = screen.geometry()

        cam_wanted = self.cam_checkbox.isChecked() and self.camera_idx is not None
        mic_idx = self.selected_mic_index()
        mic_wanted = self.mic_checkbox.isChecked() and mic_idx is not None

        # PiP rect: prefer the preview bubble's on-screen geometry, otherwise the
        # bottom-right corner at the default size. Clamping waits for the probe
        # because it needs the camera's real aspect ratio.
        cap_w = int((self.region[2] if self.region else screen_geo.width()) * scale)
        cap_h = int((self.region[3] if self.region else screen_geo.height()) * scale)
        if self.pip_window and self.pip_window.isVisible():
            origin = (screen_geo.x() + (self.region[0] if self.region else 0),
                      screen_geo.y() + (self.region[1] if self.region else 0))
            pip = self.pip_window.pip_rect(origin, scale)
        else:
            margin = int(24 * scale)
            w = int(self.cam_size.value() * scale)
            pip = (w, cap_w - w - margin, cap_h - int(w * 9 / 16) - margin)

        # the bubble has to release the camera before the recorder opens it
        self._close_pip_bubble()

        # The device probes block for ~1s altogether (camera ~0.7s, microphone
        # ~0.4s), so they run in a worker thread instead of freezing the window.
        self._pending = {
            "scale": scale, "screen_geo": screen_geo, "mic_idx": mic_idx,
            "cam_wanted": cam_wanted, "mic_wanted": mic_wanted,
            "pip": pip, "cap_w": cap_w, "cap_h": cap_h,
            "fps": self.fps_spin.value(),
            "layout": ("pip", "speaker-right", "speaker-left")[
                self.layout_combo.currentIndex()],
            "separate": self.separate_checkbox.isChecked(),
        }
        self._session += 1
        self._state = "preparing"
        self._set_controls(False)
        self.record_btn.setEnabled(False)
        self.status_label.setText("Preparing devices…")
        self.lifecycle_timer.start()
        self._launch_pending_probe()

    def _launch_pending_probe(self):
        if self._closing or self._pending is None or self._state != "preparing":
            return
        if self._retired_pip_windows:
            return  # the preview must release the camera before probing it
        if self.probe_thread is not None and self.probe_thread.isRunning():
            return
        p = self._pending
        self.probe_thread = PreRecordProbe(
            self.camera_idx if p["cam_wanted"] else None,
            p["mic_idx"] if p["mic_wanted"] else None,
            p["cam_wanted"], p["mic_wanted"])
        session = self._session
        self.probe_thread.done.connect(lambda result: self._on_probes_done(result, session))
        self._state = "probing"
        self.probe_thread.start()

    def _close_pip_bubble(self):
        if self.pip_window:
            window = self.pip_window
            self.pip_window = None
            window.close()
            self._retired_pip_windows.append(window)
            self.lifecycle_timer.start()
            self.preview_btn.setChecked(False)
        self.cam_size.setEnabled(True)

    def _abort_start(self):
        """Return to the idle state after a start that did not get going."""
        self._pending = None
        self._state = "idle"
        self._set_controls(True)
        self.record_btn.setEnabled(True)
        self.record_btn.setText("Start Recording")
        self.record_btn.setStyleSheet(GO_STYLE)

    def _on_probes_done(self, result, session=None):
        """Second half of Start: the blocking device probes have finished."""
        if (self._closing or self._pending is None
                or (session is not None and session != self._session)):
            return
        p, self._pending = self._pending, None
        cam = result.get("camera")
        cam_on = bool(p["cam_wanted"]) and cam is not None
        mic_on = bool(p["mic_wanted"]) and bool(result.get("mic_ok"))

        if p["mic_wanted"] and not mic_on:
            QMessageBox.warning(
                self, "PyRecorder",
                "Microphone is unavailable — recording video only.\n\n"
                "Grant access in System Settings → Privacy & Security → "
                "Microphone, or pick another Audio input, then start again.")
        if p["cam_wanted"] and not cam_on:
            QMessageBox.warning(
                self, "PyRecorder",
                "Camera is unavailable — recording screen"
                + (" + microphone" if mic_on else "") + " only.")
        if self._closing or (session is not None and session != self._session):
            return  # a warning dialog may have processed a close event

        cam_fps = cam_size = None
        native = None
        aspect = 9 / 16
        if cam_on:
            # never declare more than the output rate: the composite is CFR at
            # the GUI fps, so a higher camera clock only buys extra copies
            cam_fps = pick_camera_fps(cam.get("fps"), p["fps"], hi=float(p["fps"]))
            native = tuple(cam["size"])
            aspect = native[1] / native[0]
        pip = clamp_pip(p["pip"], p["cap_w"], p["cap_h"], aspect)
        if cam_on:
            cam_size = pipe_camera_size(native, p["layout"], p["separate"], pip[0])

        cam_pipe_fd = None
        if cam_on:
            r, w = os.pipe()
            os.set_inheritable(r, True)
            cam_pipe_fd = r
            self._cam_pipe_write_fd = w

        cmd, self.extra_files = build_command(
            self.output_path, p["fps"],
            self.screen_idx, p["mic_idx"], self.camera_idx,
            mic_on, cam_on, pip,
            region=self.region, screen_scale=p["scale"], layout=p["layout"],
            separate=p["separate"], preview=True,
            camera_pipe_fd=cam_pipe_fd, camera_fps=cam_fps, camera_size=cam_size)

        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE,
                                         pass_fds=(cam_pipe_fd,) if cam_pipe_fd is not None else ())
        except Exception as e:
            if cam_pipe_fd is not None:
                os.close(cam_pipe_fd)
                os.close(self._cam_pipe_write_fd)
            QMessageBox.critical(self, "PyRecorder", f"Failed to start ffmpeg:\n{e}")
            self._abort_start()
            return

        self.stderr_reader = ProcessOutputReader(self.proc.stderr)
        self.stderr_reader.start()

        # the child inherited its own copy of the read end; drop ours
        if cam_pipe_fd is not None:
            try:
                os.close(cam_pipe_fd)
            except OSError:
                pass

        # OpenCV feeds the camera frames into ffmpeg's pipe
        self.cam_feed = None
        if cam_pipe_fd is not None:
            self.cam_feed = CameraPipeFeed(self.camera_idx, self._cam_pipe_write_fd,
                                           cam_fps or p["fps"], size=cam_size)
            self.cam_feed.failed.connect(
                lambda m: self.status_label.setText("Camera feed: " + m))
            self.cam_feed.start()

        # live preview of the composited output (screen + camera)
        pw, ph = preview_dims(self.region, p["screen_geo"], p["scale"], p["layout"])
        self.live_thread = LivePreviewThread(self.proc, pw, ph)
        self.live_window = LivePreviewWindow(pw, ph)
        self.live_thread.frame.connect(self.live_window.on_frame)
        self.live_thread.start()
        self.live_window.show()

        self.record_btn.setEnabled(True)
        self._state = "recording"
        self.record_btn.setText("Stop Recording")
        self.record_btn.setStyleSheet(STOP_STYLE)
        self.start_time = time.time()
        self.elapsed_timer.start(500)

    def stop_recording(self):
        """Signal ffmpeg once, then let the event loop wait for its trailer."""
        if self.proc is None or self._stop_requested:
            return
        self._stop_requested = True
        self._state = "stopping"
        self._stop_started = time.monotonic()
        self._kill_requested = False
        self.record_btn.setEnabled(False)
        self.status_label.setText("Stopping…")
        if self.proc.poll() is None:
            try:
                self.proc.terminate()
            except ProcessLookupError:
                pass  # ffmpeg exited between poll() and the signal
        self.lifecycle_timer.start()

    def _poll_lifecycle(self):
        """Observe process/thread completion without blocking the GUI."""
        for window in list(self._retired_pip_windows):
            if not window.thread.isRunning():
                window.close()
                self._retired_pip_windows.remove(window)
        if self._state == "preparing":
            self._launch_pending_probe()
        proc = self.proc
        if proc is not None:
            if proc.poll() is not None:
                self._finalize(self._session)
            elif (self._stop_requested and not self._kill_requested
                  and time.monotonic() - self._stop_started >= 15):
                self._kill_requested = True
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        if self._closing:
            self._finish_close()
        elif (self.proc is None and self._state == "idle"
              and not self._retired_pip_windows
              and not (self.probe_thread and self.probe_thread.isRunning())):
            self.lifecycle_timer.stop()

    def _finalize(self, session=None):
        """Finalize only this session, after ffmpeg and all readers have exited."""
        if session is not None and session != self._session:
            return
        proc = self.proc
        if proc is None:
            return
        if proc.poll() is None:
            self.stop_recording()
            return
        self._state = "finalizing"
        self.record_btn.setEnabled(False)
        self.elapsed_timer.stop()
        if self.cam_feed:
            self.cam_feed.stop()
        if self.live_thread:
            self.live_thread.stop()
        if (any(worker and worker.isRunning() for worker in (self.cam_feed, self.live_thread))
                or (self.stderr_reader and self.stderr_reader.is_alive())):
            return  # retain every worker until it actually finishes

        err_tail = self.stderr_reader.tail_text() if self.stderr_reader else ""
        self.stderr_reader = None
        self.cam_feed = None
        self.live_thread = None
        if self.live_window:
            self.live_window.close()
            self.live_window = None
        for name in ("stdin", "stdout", "stderr"):
            stream = getattr(proc, name, None)
            if stream:
                try:
                    stream.close()
                except (AttributeError, OSError):
                    pass
        code = proc.returncode
        output_path, extra_files = self.output_path, list(self.extra_files)
        secs = time.time() - self.start_time
        # Clear state before displaying a dialog (which runs a nested event
        # loop). Timer callbacks must not finalize the same process twice.
        self.proc = None
        self._stop_requested = False
        self._stop_started = None
        self._state = "idle"
        self.record_btn.setText("Start Recording")
        self.record_btn.setStyleSheet(GO_STYLE)
        self.record_btn.setEnabled(True)
        self._set_controls(True)
        if not recording_succeeded(code, output_path):
            self.status_label.setText("Failed")
            QMessageBox.critical(
                self, "PyRecorder",
                "Recording failed.\n\nIf the video is black or empty, grant "
                "permissions (Screen Recording / Camera / Microphone) in "
                "System Settings → Privacy & Security, then restart this app."
                + (f"\n\nffmpeg output:\n{err_tail}" if err_tail else ""))
        else:
            files = "\n".join([output_path] + extra_files)
            self.status_label.setText(f"Saved: {output_path} ({secs:.1f}s)")
            if not self._closing:
                QMessageBox.information(self, "PyRecorder", f"Recording saved:\n{files}")

    def update_elapsed(self):
        import time
        if self.proc and self.proc.poll() is None and not self._stop_requested:
            self.status_label.setText(
                f"Recording… {time.time() - self.start_time:.0f}s")

    def closeEvent(self, event):
        self._closing = True
        self._pending = None
        if self.probe_thread and self.probe_thread.isRunning():
            self.probe_thread.requestInterruption()
        self._close_pip_bubble()
        if self.proc is not None:
            self.stop_recording()
        if self._shutdown_pending():
            event.ignore()
            self.record_btn.setEnabled(False)
            self._set_controls(False)
            self.status_label.setText("Closing…")
            self.lifecycle_timer.start()
            return
        self.lifecycle_timer.stop()
        self.elapsed_timer.stop()
        event.accept()

    def _shutdown_pending(self):
        return (self.proc is not None or bool(self._retired_pip_windows)
                or bool(self.probe_thread and self.probe_thread.isRunning()))

    def _finish_close(self):
        if not self._shutdown_pending():
            self.close()

    def _set_controls(self, enabled):
        self.cam_checkbox.setEnabled(enabled)
        self.preview_btn.setEnabled(enabled)
        self.layout_combo.setEnabled(enabled)
        self.separate_checkbox.setEnabled(enabled)
        self.mic_checkbox.setEnabled(enabled)
        self.mic_combo.setEnabled(enabled)
        self.fps_spin.setEnabled(enabled)
        self.region_btn.setEnabled(enabled)
        self.clear_region_btn.setEnabled(enabled)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    recorder = ScreenRecorderMac()
    recorder.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
