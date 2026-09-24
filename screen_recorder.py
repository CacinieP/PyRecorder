"""
Windows Screen Recorder
A simple screen recording application with GUI
"""

import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSpinBox, QFileDialog, QComboBox, QGroupBox,
    QMessageBox, QProgressBar
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from datetime import datetime


from screen_recorder_pro import RecordingThread as ProRecordingThread, RegionSelector


class RecordingThread(ProRecordingThread):
    """Use the same capture, timing and recovery guarantees as the Pro edition."""

    def _emit_preview(self, img, width, height):
        # The basic edition has no preview panel.
        pass


class ScreenRecorder(QMainWindow):
    """Main application window"""

    def __init__(self):
        super().__init__()
        self.recording_thread = None
        self.output_folder = ""
        self.region = None
        self.start_time = None
        self.region_selector = None
        self._recording_active = False
        self._stopping = False
        self._closing = False
        self._error_message = None

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
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self.browse_file)
        path_layout.addWidget(self.browse_btn)
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
        self.region_btn = QPushButton("Select Region")
        self.region_btn.clicked.connect(self.select_region)
        region_layout.addWidget(self.region_btn)
        self.full_screen_btn = QPushButton("Full Screen")
        self.full_screen_btn.clicked.connect(self.clear_region)
        region_layout.addWidget(self.full_screen_btn)
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
        if self._recording_active or self._closing:
            return
        if self.region_selector is not None:
            self.region_selector.raise_()
            return
        selector = RegionSelector()
        self.region_selector = selector
        selector.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        selector.destroyed.connect(lambda: self._clear_region_selector(selector))
        selector.region_selected.connect(self.on_region_selected)
        selector.showFullScreen()

    def _clear_region_selector(self, selector):
        if self.region_selector is selector:
            self.region_selector = None

    def on_region_selected(self, region):
        """Handle region selection"""
        self.region = region
        self.region_label.setText(f"Custom: {region[2]}x{region[3]}")

    def clear_region(self):
        if self._recording_active or self._closing:
            return
        if self.region_selector is not None:
            self.region_selector.close()
        self.region = None
        self.region_label.setText("Full Screen")

    def toggle_recording(self):
        """Start or stop recording"""
        if self._recording_active:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        """Start screen recording"""
        if self._recording_active or self._closing:
            return
        # Validate output folder
        if not self.output_folder:
            self.browse_file()
            if not self.output_folder:
                return

        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
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

        if self.region_selector is not None:
            self.region_selector.close()
        self._recording_active = True
        self._stopping = False
        self._error_message = None
        self._set_controls_enabled(False)
        self.frame_count_label.setText("Frames: 0")
        self.start_time = datetime.now()

        # Start recording thread
        self.recording_thread = RecordingThread(
            output_path,
            fps,
            codec,
            self.region
        )
        self.recording_thread.progress.connect(self.update_progress)
        self.recording_thread.finished.connect(self.recording_finished)
        self.recording_thread.error.connect(self.recording_error)
        self.recording_thread.start()

    def stop_recording(self):
        """Stop screen recording"""
        if self._recording_active and not self._stopping:
            self._stopping = True
            self.record_btn.setEnabled(False)
            self.status_label.setText("Closing..." if self._closing else "Stopping...")
            self.recording_thread.stop()

    def update_progress(self, frame_count):
        """Update recording progress"""
        self.frame_count_label.setText(f"Frames: {frame_count}")

        if self.start_time and not self._stopping:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            self.status_label.setText(f"Recording... ({elapsed:.0f}s)")

    def recording_finished(self):
        """Publish the result only after the worker has finished cleanup."""
        if not self._recording_active:
            return
        if self.recording_thread.isRunning():
            QTimer.singleShot(10, self.recording_finished)
            return
        self._recording_active = False
        self._stopping = False
        self._set_controls_enabled(True)
        self.record_btn.setEnabled(True)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
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

        self.start_time = None
        if not self.recording_thread.output_saved:
            self._closing = False
            self.status_label.setText("Recording failed. Captured files were kept for recovery.")
            QMessageBox.critical(
                self, "PyRecorder - Recording Failed",
                self._error_message or "Recording could not be saved. Check the output folder.")
            return

        duration = self.recording_thread.frame_count / self.recording_thread.fps
        self.status_label.setText(f"Saved! Duration: {duration:.1f}s")
        if self._closing:
            self.close()
            return
        QMessageBox.information(
            self, "PyRecorder - Recording Complete",
            f"Recording saved to:\n{self.current_output_path}\n\n"
            f"Total frames: {self.recording_thread.frame_count}")

    def recording_error(self, message):
        # A worker error arrives before its finished signal. Keep the window
        # alive until cleanup is done, then show a single terminal result.
        self._error_message = message

    def _set_controls_enabled(self, enabled):
        for control in (self.fps_spinbox, self.codec_combo,
                        self.browse_btn, self.region_btn, self.full_screen_btn):
            control.setEnabled(enabled)

    def closeEvent(self, event):
        if self.region_selector is not None:
            self.region_selector.close()
        if self._recording_active:
            self._closing = True
            self.stop_recording()
            event.ignore()
            return
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    recorder = ScreenRecorder()
    recorder.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
