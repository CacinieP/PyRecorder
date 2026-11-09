"""Always-on-top live preview of the composited output (screen + bubble).

ffmpeg writes a letterboxed 480x270 rgb24 stream on stdout; this reader turns
it into QImages. The fixed canvas means the geometry never has to be guessed
(a previous version derived it and got Speaker layouts wrong).
"""
from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from pyrecorder.command import LIVE_PREVIEW_W, LIVE_PREVIEW_H


class LivePreviewThread(QThread):
    """Read composited rawvideo frames piped from the recording process."""
    frame = pyqtSignal(object)

    def __init__(self, proc, w=LIVE_PREVIEW_W, h=LIVE_PREVIEW_H):
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
    def __init__(self, w=LIVE_PREVIEW_W, h=LIVE_PREVIEW_H):
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
