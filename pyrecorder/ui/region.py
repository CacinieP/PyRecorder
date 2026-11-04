"""Full-screen translucent overlay for dragging a capture region.

Emits `(capture_region, logical_region)`:

- ``logical_region`` — (x, y, w, h) in global logical points, useful for
  mapping the camera bubble relative to the capture origin on every platform.
- ``capture_region`` — what the recorder should capture: logical points on
  macOS (avfoundation captures points; ffmpeg's crop filter applies the
  scale) or physical desktop pixels on Windows/Linux (the mss feeder grabs
  exactly this rect). The backend decides via ``region_coords_kind()``.
"""
from PyQt6.QtCore import QPointF, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class RegionSelector(QWidget):
    region_selected = pyqtSignal(tuple, tuple)

    def __init__(self, backend):
        screen = QGuiApplication.primaryScreen()
        geo = screen.geometry()
        super().__init__(None, Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.backend = backend
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
            self.start_pos = self._global(event)
            self.end_pos = self.start_pos
            self.update()

    def mouseMoveEvent(self, event):
        if self.start_pos:
            self.end_pos = self._global(event)
            self.update()

    def mouseReleaseEvent(self, event):
        if self.start_pos and self.end_pos:
            x1, x2 = sorted((self.start_pos.x(), self.end_pos.x()))
            y1, y2 = sorted((self.start_pos.y(), self.end_pos.y()))
            w, h = x2 - x1, y2 - y1
            self.close()
            if w > 10 and h > 10:
                self._emit(x1, y1, w, h)
        else:
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def _global(self, event):
        pos = event.globalPosition().toPoint()
        # clamp inside the overlay: on multi-screen setups with different
        # origins a quick drag past the edge would otherwise select negative
        # sizes relative to this screen
        geo = self.geometry()
        return QPointF(
            min(max(pos.x(), geo.x()), geo.x() + geo.width()),
            min(max(pos.y(), geo.y()), geo.y() + geo.height())).toPoint()

    def _emit(self, x1, y1, w, h):
        logical = (x1, y1, w, h)
        if self.backend.region_coords_kind() == "logical":
            capture = logical
        else:
            origin = self.backend.region_origin_physical(self)
            ox, oy = self.geometry().x(), self.geometry().y()
            rel = (x1 - ox, y1 - oy, w, h)
            capture = self.backend.region_to_physical(
                rel, origin, self.devicePixelRatioF())
        self.region_selected.emit(tuple(capture), logical)
