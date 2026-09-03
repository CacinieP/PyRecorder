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


def list_av_devices():
    """Return (screen_index, camera_index, mic_index) from avfoundation."""
    try:
        proc = subprocess.run(
            [FFMPEG, "-hide_banner", "-f", "avfoundation", "-list_devices",
             "true", "-i", ""],
            capture_output=True, text=True, timeout=20,
        )
    except Exception:
        return None, None, None

    screen = camera = mic = None
    section = "video"
    for line in proc.stderr.splitlines():
        if "AVFoundation video devices" in line:
            section = "video"
            continue
        if "AVFoundation audio devices" in line:
            section = "audio"
            continue
        m = re.search(r"\[(\d+)\]\s+(.+)$", line.strip())
        if not m:
            continue
        idx, name = int(m.group(1)), m.group(2)
        if "Capture screen" in name and screen is None:
            screen = idx
        elif section == "video" and camera is None and "Capture screen" not in name:
            camera = idx
        elif section == "audio" and mic is None:
            mic = idx
    return screen, camera, mic


PREVIEW_W, PREVIEW_H = 640, 360
# this device (and most modern cams) only delivers 1080p; request that and
# scale down in the filter — forcing smaller sizes fails with I/O error
CAMERA_CAPTURE_SIZE = "1920x1080"


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
        import cv2
        cap = cv2.VideoCapture(self.camera_idx, cv2.CAP_AVFOUNDATION)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        return cap

    def stop(self):
        self._stop = True

    def run(self):
        import cv2
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
                small = cv2.resize(frame, (PREVIEW_W, PREVIEW_H))
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
        self.thread.stop()
        self.thread.wait(3000)
        super().closeEvent(event)

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
                  camera_pipe_fd=None):
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

    # split screen input if it is needed both composited and as its own file
    scr_stream = base
    if separate:
        filters.append(f"{base}split=2[scrA][scrB]")
        scr_stream, base = "[scrA]", "[scrB]"

    if region:
        x, y, w, h = region
        x, y = int(x * screen_scale), int(y * screen_scale)
        w, h = int(w * screen_scale), int(h * screen_scale)
        filters.append(f"{base}crop={w}:{h}:{x}:{y}[base]")
        base = "[base]"

    cam_stream = None
    if camera_enabled and camera_idx is not None and camera_pipe_fd is not None:
        cmd += [
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-video_size", CAMERA_CAPTURE_SIZE,
            "-framerate", str(fps),
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
        prev_w = 480
        filters.append(f"{base}split=2[rec][pv];[pv]scale={prev_w}:-2[prev]")
        base = "[rec]"

    if filters:
        cmd += ["-filter_complex", ";".join(filters)]

    cmd += ["-map", base]

    if audio_stream:
        cmd += ["-map", audio_stream, "-c:a", "aac", "-b:a", "128k"]
    cmd += ["-c:v", "h264_videotoolbox", "-b:v", "8M", "-pix_fmt", "yuv420p",
            output_path]

    # separate files (no re-filtering, hardware encoded)
    if separate and scr_stream:
        cmd += ["-map", scr_stream, "-c:v", "h264_videotoolbox", "-b:v", "8M",
                "-pix_fmt", "yuv420p",
                output_path.replace(".mp4", "_screen.mp4")]
        extra_files.append(output_path.replace(".mp4", "_screen.mp4"))
    if separate and cam_stream:
        cmd += ["-map", cam_stream, "-c:v", "h264_videotoolbox", "-b:v", "2M",
                "-pix_fmt", "yuv420p",
                output_path.replace(".mp4", "_camera.mp4")]
        extra_files.append(output_path.replace(".mp4", "_camera.mp4"))

    if preview:
        cmd += ["-map", "[prev]", "-f", "rawvideo", "-pix_fmt", "rgb24",
                "pipe:1"]
    return cmd, extra_files


class CameraPipeFeed(QThread):
    """Capture the camera with OpenCV and write raw BGR frames into the pipe
    that ffmpeg reads as its second input. Closing the pipe signals EOF."""
    failed = pyqtSignal(str)

    def __init__(self, camera_idx, write_fd, fps):
        super().__init__()
        self.camera_idx = camera_idx
        self.write_fd = write_fd
        self.fps = fps
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        import cv2
        import time
        try:
            cap = cv2.VideoCapture(self.camera_idx, cv2.CAP_AVFOUNDATION)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            if not cap.isOpened():
                self.failed.emit("Camera opened by recorder failed.")
                return
            target = (1920, 1080)
            n = 0
            while not self._stop:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.05)
                    continue
                if frame.shape[1] != target[0] or frame.shape[0] != target[1]:
                    frame = cv2.resize(frame, target)
                try:
                    os.write(self.write_fd, frame.tobytes())
                except OSError:
                    break  # reader gone — recording stopped
            cap.release()
        finally:
            try:
                os.close(self.write_fd)  # EOF for ffmpeg
            except OSError:
                pass


def preview_dims(region, screen_geo, scale, prev_w=480):
    """(w, h) of the rawvideo preview stream — must match scale=W:-2."""
    cap_w = (region[2] if region else screen_geo.width()) * scale
    cap_h = (region[3] if region else screen_geo.height()) * scale
    return prev_w, max(2, int(round(cap_h * prev_w / cap_w / 2)) * 2)


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
        opt_group.setLayout(opt_layout)
        layout.addWidget(opt_group)

        # Status
        self.status_label = QLabel("Ready")
        layout.addWidget(self.status_label)

        self.record_btn = QPushButton("Start Recording")
        self.record_btn.setMinimumHeight(44)
        self.record_btn.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white;
                          font-size: 14px; font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #45a049; }
        """)
        self.record_btn.clicked.connect(self.toggle_recording)
        layout.addWidget(self.record_btn)

        layout.addStretch()

    # ---- devices & permissions ----

    def probe_devices(self):
        if not ffmpeg_available():
            QMessageBox.warning(
                self, "ffmpeg not found",
                "ffmpeg is required but not installed.\n\n"
                "Install it with Homebrew:\n    brew install ffmpeg\n\n"
                "Then restart PyRecorder.")
            self.status_label.setText("ffmpeg missing")
            return
        self.screen_idx, self.camera_idx, self.mic_idx = list_av_devices()
        parts = []
        parts.append("screen OK" if self.screen_idx is not None else "screen NOT found")
        parts.append("camera OK" if self.camera_idx is not None else "no camera")
        parts.append("mic OK" if self.mic_idx is not None else "no mic")
        self.status_label.setText("Devices: " + ", ".join(parts))

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
            if self.pip_window:
                self.pip_window.close()
                self.pip_window = None
            self.cam_size.setEnabled(True)
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
        if self.proc and self.proc.poll() is None:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
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

        cam_on = self.cam_checkbox.isChecked() and self.camera_idx is not None
        mic_on = self.mic_checkbox.isChecked() and self.mic_idx is not None

        # PiP rect: prefer the preview bubble's on-screen geometry; otherwise
        # default to bottom-right corner at the default size.
        screen_geo = screen.geometry()
        if self.region:
            origin_x, origin_y = screen_geo.x() + self.region[0], \
                screen_geo.y() + self.region[1]
        else:
            origin_x, origin_y = screen_geo.x(), screen_geo.y()
        if self.pip_window and self.pip_window.isVisible():
            pip = self.pip_window.pip_rect((origin_x, origin_y), scale)
            pip_w, pip_x, pip_y = pip
            # clamp inside the capture area
            cap_w = int((self.region[2] if self.region
                         else screen_geo.width()) * scale)
            cap_h = int((self.region[3] if self.region
                         else screen_geo.height()) * scale)
            pip_x = max(0, min(pip_x, cap_w - pip_w))
            pip_y = max(0, min(pip_y, cap_h - int(pip_w * 9 / 16)))
            pip = (pip_w, pip_x, pip_y)
        else:
            margin = int(24 * scale)
            w = int(self.cam_size.value() * scale)
            cap_w = int((self.region[2] if self.region
                         else screen_geo.width()) * scale)
            cap_h = int((self.region[3] if self.region
                         else screen_geo.height()) * scale)
            pip = (w, cap_w - w - margin, cap_h - int(w * 9 / 16) - margin)

        # camera must be released by the preview before recording opens it
        if self.pip_window:
            self.pip_window.close()
            self.pip_window = None
            self.preview_btn.setChecked(False)
            self.cam_size.setEnabled(True)

        # probe the camera via OpenCV; degrade to screen-only if unavailable
        cam_pipe_fd = None
        if cam_on:
            if self._camera_probe():
                r, w = os.pipe()
                os.set_inheritable(r, True)
                cam_pipe_fd = r
                self._cam_pipe_write_fd = w
            else:
                QMessageBox.warning(
                    self, "PyRecorder",
                    "Camera is unavailable — recording screen"
                    + (" + microphone" if mic_on else "") + " only.")
                cam_on = False

        cmd, self.extra_files = build_command(
            self.output_path, self.fps_spin.value(),
            self.screen_idx, self.mic_idx, self.camera_idx,
            mic_on, cam_on, pip,
            region=self.region, screen_scale=scale,
            layout=("pip", "speaker-right", "speaker-left")[
                self.layout_combo.currentIndex()],
            separate=self.separate_checkbox.isChecked(),
            preview=True, camera_pipe_fd=cam_pipe_fd)

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
            return

        # OpenCV feeds the camera frames into ffmpeg's pipe
        self.cam_feed = None
        if cam_pipe_fd is not None:
            self.cam_feed = CameraPipeFeed(self.camera_idx, self._cam_pipe_write_fd,
                                           self.fps_spin.value())
            self.cam_feed.failed.connect(
                lambda m: self.status_label.setText("Camera feed: " + m))
            self.cam_feed.start()

        # live preview of the composited output (screen + camera)
        pw, ph = preview_dims(self.region, screen_geo, scale)
        self.live_thread = LivePreviewThread(self.proc, pw, ph)
        self.live_window = LivePreviewWindow(pw, ph)
        self.live_thread.frame.connect(self.live_window.on_frame)
        self.live_thread.start()
        self.live_window.show()

        self.record_btn.setText("Stop Recording")
        self.record_btn.setStyleSheet("""
            QPushButton { background-color: #f44336; color: white;
                          font-size: 14px; font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #da190b; }
        """)
        self._set_controls(False)
        import time
        self.start_time = time.time()
        self.elapsed_timer.start(500)

    def _camera_probe(self):
        """Quick OpenCV open + one frame, so a broken camera degrades to a
        screen-only recording instead of failing the whole command."""
        try:
            import cv2
            cap = cv2.VideoCapture(self.camera_idx, cv2.CAP_AVFOUNDATION)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            ok = False
            for _ in range(10):
                if cap.isOpened() and cap.read()[0]:
                    ok = True
                    break
                time.sleep(0.1)
            cap.release()
            return ok
        except Exception:
            return False

    def stop_recording(self):
        if self.proc and self.proc.poll() is None:
            self.status_label.setText("Stopping…")
            try:
                self.proc.stdin.write("q")
                self.proc.stdin.flush()
            except Exception:
                self.proc.terminate()
        # wait for ffmpeg to finalize the file
        QTimer.singleShot(300, self._finalize)

    def _finalize(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()
        self.elapsed_timer.stop()
        if getattr(self, "cam_feed", None):
            self.cam_feed.stop()
            self.cam_feed.wait(3000)
            self.cam_feed = None
        if self.live_thread:
            self.live_thread.stop()
            self.live_thread = None
        if self.live_window:
            self.live_window.close()
            self.live_window = None
        self.record_btn.setText("Start Recording")
        self.record_btn.setStyleSheet("""
            QPushButton { background-color: #4CAF50; color: white;
                          font-size: 14px; font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #45a049; }
        """)
        self._set_controls(True)

        err_tail = ""
        if self.proc and self.proc.stderr:
            err_tail = self.proc.stderr.read()[-800:]
        code = self.proc.returncode if self.proc else -1
        if code not in (0, 255) or not os.path.exists(self.output_path):
            QMessageBox.critical(
                self, "PyRecorder",
                "Recording failed.\n\nIf the video is black or empty, grant "
                "permissions (Screen Recording / Camera / Microphone) in "
                "System Settings → Privacy & Security, then restart this app."
                + (f"\n\nffmpeg output:\n{err_tail}" if err_tail else ""))
            self.status_label.setText("Failed")
        else:
            import time
            secs = time.time() - self.start_time
            files = "\n".join([self.output_path] + self.extra_files)
            self.status_label.setText(f"Saved: {self.output_path} ({secs:.1f}s)")
            QMessageBox.information(self, "PyRecorder",
                                    f"Recording saved:\n{files}")
        self.proc = None

    def update_elapsed(self):
        import time
        if self.proc and self.proc.poll() is None:
            self.status_label.setText(
                f"Recording… {time.time() - self.start_time:.0f}s")

    def _set_controls(self, enabled):
        self.cam_checkbox.setEnabled(enabled)
        self.preview_btn.setEnabled(enabled)
        self.layout_combo.setEnabled(enabled)
        self.separate_checkbox.setEnabled(enabled)
        self.mic_checkbox.setEnabled(enabled)
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
