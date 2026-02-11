"""
Windows Screen Recorder
A simple screen recording application with GUI
"""

import sys
import cv2
import numpy as np
from mss import mss
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSpinBox, QFileDialog, QComboBox, QGroupBox,
    QMessageBox, QProgressBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QIcon
import threading
from datetime import datetime


class RecordingThread(QThread):
    """Thread for handling screen recording"""
    progress = pyqtSignal(int)
    finished = pyqtSignal()

    def __init__(self, output_path, fps, codec, region=None):
        super().__init__()
        self.output_path = output_path
        self.fps = fps
        self.codec = codec
        self.region = region
        self.is_running = True
        self.recording = True
        self.frame_count = 0

    def run(self):
        """Main recording loop"""
        try:
            # Setup screen capture
            sct = mss()

            # Define capture region
            if self.region:
                monitor = {"top": self.region[1], "left": self.region[0],
                          "width": self.region[2], "height": self.region[3]}
            else:
                monitor = sct.monitors[1]  # Primary monitor

            # Get screen dimensions
            width = monitor["width"]
            height = monitor["height"]

            # Setup video writer
            fourcc = cv2.VideoWriter_fourcc(*self.codec)
            out = cv2.VideoWriter(self.output_path, fourcc, self.fps, (width, height))

            self.frame_count = 0
            last_time = datetime.now()

            while self.is_running:
                # Capture screen
                screenshot = sct.grab(monitor)

                # Convert to numpy array
                img = np.array(screenshot)

                # Convert RGB to BGR for OpenCV
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

                # Write frame
                out.write(img)
                self.frame_count += 1

                # Emit progress every second
                current_time = datetime.now()
                if (current_time - last_time).seconds >= 1:
                    self.progress.emit(self.frame_count)
                    last_time = current_time

                # Control frame rate
                cv2.waitKey(int(1000 / self.fps))

            # Release resources
            out.release()
            self.progress.emit(self.frame_count)

        except Exception as e:
            print(f"Recording error: {e}")

        self.finished.emit()

    def stop(self):
        """Stop recording"""
        self.is_running = False
        self.wait()


class RegionSelector(QWidget):
    """Widget for selecting recording region"""
    region_selected = pyqtSignal(tuple)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                           Qt.WindowType.WindowStaysOnTopHint |
                           Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background-color: rgba(0, 120, 215, 50);")
        self.setWindowTitle("Select Region")

        self.start_pos = None
        self.current_pos = None
        self.selecting = False

        self.setFixedSize(200, 100)
        self.label = QLabel("Drag to select region\nPress ESC to cancel")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("color: white; font-weight: bold; background: rgba(0,0,0,150); padding: 10px;")

        layout = QVBoxLayout()
        layout.addWidget(self.label)
        self.setLayout(layout)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selecting = True
            self.start_pos = event.pos()
            self.label.hide()

    def mouseMoveEvent(self, event):
        if self.selecting and self.start_pos:
            self.current_pos = event.pos()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.selecting:
            self.selecting = False
            if self.start_pos and self.current_pos:
                x = min(self.start_pos.x(), self.current_pos.x())
                y = min(self.start_pos.y(), self.current_pos.y())
                w = abs(self.current_pos.x() - self.start_pos.x())
                h = abs(self.current_pos.y() - self.start_pos.y())

                if w > 10 and h > 10:
                    self.region_selected.emit((x, y, w, h))

            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()


class ScreenRecorder(QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()
        self.recording_thread = None
        self.output_folder = ""
        self.region = None
        self.start_time = None

        self.init_ui()

    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("PyRecorder")
        self.setMinimumSize(500, 400)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Title
        title_label = QLabel("PyRecorder - Screen Recorder")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        main_layout.addWidget(title_label)

        # Output settings group
        output_group = QGroupBox("Output Settings")
        output_layout = QVBoxLayout()

        # File path
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("Save Location:"))
        self.path_label = QLabel("Not selected")
        path_layout.addWidget(self.path_label)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_file)
        path_layout.addWidget(browse_btn)
        output_layout.addLayout(path_layout)

        output_group.setLayout(output_layout)
        main_layout.addWidget(output_group)

        # Recording settings group
        settings_group = QGroupBox("Recording Settings")
        settings_layout = QVBoxLayout()

        # FPS setting
        fps_layout = QHBoxLayout()
        fps_layout.addWidget(QLabel("Frame Rate (FPS):"))
        self.fps_spinbox = QSpinBox()
        self.fps_spinbox.setRange(10, 60)
        self.fps_spinbox.setValue(30)
        fps_layout.addWidget(self.fps_spinbox)
        fps_layout.addStretch()
        settings_layout.addLayout(fps_layout)

        # Codec setting
        codec_layout = QHBoxLayout()
        codec_layout.addWidget(QLabel("Video Codec:"))
        self.codec_combo = QComboBox()
        self.codec_combo.addItems(["mp4v", "XVID", "H264", "MJPG"])
        self.codec_combo.setCurrentText("mp4v")
        codec_layout.addWidget(self.codec_combo)
        codec_layout.addStretch()
        settings_layout.addLayout(codec_layout)

        # Region setting
        region_layout = QHBoxLayout()
        region_layout.addWidget(QLabel("Recording Area:"))
        self.region_label = QLabel("Full Screen")
        region_layout.addWidget(self.region_label)
        region_btn = QPushButton("Select Region")
        region_btn.clicked.connect(self.select_region)
        region_layout.addWidget(region_btn)
        settings_layout.addLayout(region_layout)

        settings_group.setLayout(settings_layout)
        main_layout.addWidget(settings_group)

        # Status
        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout()

        self.status_label = QLabel("Ready to record")
        status_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximum(0)
        status_layout.addWidget(self.progress_bar)

        self.frame_count_label = QLabel("Frames: 0")
        status_layout.addWidget(self.frame_count_label)

        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)

        # Control buttons
        button_layout = QHBoxLayout()

        self.record_btn = QPushButton("Start Recording")
        self.record_btn.setMinimumHeight(50)
        self.record_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 14px;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        self.record_btn.clicked.connect(self.toggle_recording)
        button_layout.addWidget(self.record_btn)

        main_layout.addLayout(button_layout)
        main_layout.addStretch()

    def browse_file(self):
        """Open folder dialog to select save location"""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Select Save Folder",
            ""
        )

        if folder_path:
            self.output_folder = folder_path
            self.path_label.setText(folder_path)

    def select_region(self):
        """Open region selector"""
        self.region = None
        self.region_label.setText("Full Screen")

        selector = RegionSelector()
        selector.region_selected.connect(self.on_region_selected)
        selector.showFullScreen()

    def on_region_selected(self, region):
        """Handle region selection"""
        self.region = region
        self.region_label.setText(f"Custom: {region[2]}x{region[3]}")

    def toggle_recording(self):
        """Start or stop recording"""
        if self.recording_thread and self.recording_thread.isRunning():
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        """Start screen recording"""
        # Validate output folder
        if not self.output_folder:
            self.browse_file()
            if not self.output_folder:
                return

        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = f"{self.output_folder}/recording_{timestamp}.mp4"
        self.current_output_path = output_path

        # Get settings
        fps = self.fps_spinbox.value()
        codec = self.codec_combo.currentText()

        # Update UI
        self.record_btn.setText("Stop Recording")
        self.record_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                font-size: 14px;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)
        self.status_label.setText("Recording...")
        self.progress_bar.setMaximum(0)
        self.progress_bar.setMinimum(0)

        # Start recording thread
        self.recording_thread = RecordingThread(
            output_path,
            fps,
            codec,
            self.region
        )
        self.recording_thread.progress.connect(self.update_progress)
        self.recording_thread.finished.connect(self.recording_finished)
        self.recording_thread.start()

        self.start_time = datetime.now()

    def stop_recording(self):
        """Stop screen recording"""
        if self.recording_thread:
            self.status_label.setText("Stopping...")
            self.recording_thread.stop()

    def update_progress(self, frame_count):
        """Update recording progress"""
        self.frame_count_label.setText(f"Frames: {frame_count}")

        if self.start_time:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            self.status_label.setText(f"Recording... ({elapsed:.0f}s)")

    def recording_finished(self):
        """Handle recording completion"""
        self.record_btn.setText("Start Recording")
        self.record_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-size: 14px;
                font-weight: bold;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)

        if self.start_time:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            self.status_label.setText(f"Saved! Duration: {elapsed:.1f}s")

        QMessageBox.information(
            self,
            "PyRecorder - Recording Complete",
            f"Recording saved to:\n{self.current_output_path}\n\n"
            f"Total frames: {self.frame_count_label.text().split(': ')[1]}"
        )


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    recorder = ScreenRecorder()
    recorder.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
