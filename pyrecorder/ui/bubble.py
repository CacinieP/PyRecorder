"""Floating camera bubble: draggable anywhere, resizable (16:9 locked).

Its geometry on screen IS the PiP position/size used when recording
(converted to device pixels relative to the capture region) — what the
teacher positions is exactly what the video shows.
"""
from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import (QLabel, QPushButton, QSizeGrip, QVBoxLayout,
                             QWidget)

from pyrecorder.camera import CameraFrameThread


class PipPreviewWindow(QWidget):
    geometry_changed = pyqtSignal()
    MIN_W, MAX_W = 120, 800

    def __init__(self, camera_idx, platform_id, initial_width):
        super().__init__(None, Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.camera_idx = camera_idx
        self.platform_id = platform_id
        self._drag_offset = None
        self._fixed_aspect = 9 / 16  # h/w — most cams deliver 16:9 at 1080p
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

        self.thread = CameraFrameThread(camera_idx, platform_id)
        self.thread.frame.connect(self.on_frame)
        self.thread.failed.connect(self.on_failed)
        # a machine without a camera must not leave a dead bubble on screen
        self.thread.unavailable.connect(self._on_unavailable)
        self.thread.finished.connect(self._finish_close)
        self._closing = False
        self.thread.start()

    def _on_unavailable(self, message):
        self.video_label.setText("Camera unavailable\n" + message)
        self._closing = True
        self.thread.stop()
        if not self.thread.isRunning():
            self.close()

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
        from PyQt6.QtGui import QPixmap
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
