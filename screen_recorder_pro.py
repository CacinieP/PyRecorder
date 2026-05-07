"""
Windows Screen Recorder Pro
Screen recording with audio and webcam overlay support
"""

import sys
import cv2
import numpy as np
from mss import mss
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSpinBox, QFileDialog, QComboBox, QGroupBox,
    QMessageBox, QProgressBar, QCheckBox, QDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QImage, QPixmap
from datetime import datetime
import threading
import pyaudio
import wave
import os
from moviepy import VideoFileClip, AudioFileClip


class AudioRecorder:
    """Handle audio recording"""

    def __init__(self, output_path, sample_rate=44100, channels=2, chunk=1024):
        self.output_path = output_path
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk = chunk
        self.frames = []
        self.is_recording = False
        self.audio = pyaudio.PyAudio()

    def start(self):
        """Start audio recording"""
        self.frames = []
        self.is_recording = True

        try:
            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk,
                stream_callback=self._callback
            )
            self.stream.start_stream()
        except Exception as e:
            print(f"Audio recording error: {e}")
            self.is_recording = False

    def _callback(self, in_data, frame_count, time_info, status):
        """Audio stream callback"""
        if self.is_recording:
            self.frames.append(in_data)
        return (None, pyaudio.paContinue)

    def stop(self):
        """Stop audio recording and save"""
        self.is_recording = False

        if hasattr(self, 'stream'):
            self.stream.stop_stream()
            self.stream.close()

        self.audio.terminate()

        # Save audio file
        if self.frames:
            try:
                wf = wave.open(self.output_path, 'wb')
                wf.setnchannels(self.channels)
                wf.setsampwidth(self.audio.get_sample_size(pyaudio.paInt16))
                wf.setframerate(self.sample_rate)
                wf.writeframes(b''.join(self.frames))
                wf.close()
                return True
            except Exception as e:
                print(f"Error saving audio: {e}")
        return False


class WebcamPreviewDialog(QDialog):
    """Dialog showing live webcam preview"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Webcam Preview")
        self.setMinimumSize(480, 360)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        layout = QVBoxLayout(self)
        self.video_label = QLabel("Initializing webcam...")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: black; color: white;")
        layout.addWidget(self.video_label)

        hint = QLabel("Close this window to stop preview")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        self.cap = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)

    def showEvent(self, event):
        super().showEvent(event)
        self.cap = cv2.VideoCapture(0)
        if self.cap.isOpened():
            self.timer.start(33)  # ~30fps
        else:
            self.video_label.setText("Cannot open webcam.\nCheck if camera is connected.")
            if self.cap:
                self.cap.release()
                self.cap = None

    def update_frame(self):
        if self.cap and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = frame.shape
                bytes_per_line = ch * w
                qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                pixmap = QPixmap.fromImage(qimg).scaled(
                    self.video_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.video_label.setPixmap(pixmap)

    def closeEvent(self, event):
        self.timer.stop()
        if self.cap:
            self.cap.release()
            self.cap = None
        super().closeEvent(event)


class RecordingThread(QThread):
    """Thread for handling screen recording"""
    progress = pyqtSignal(int)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, output_path, fps, codec, region=None, record_audio=False,
                 audio_path=None, webcam_enabled=False, webcam_position="bottom-right",
                 webcam_size=240):
        super().__init__()
        self.output_path = output_path
        self.fps = fps
        self.codec = codec
        self.region = region
        self.record_audio = record_audio
        self.audio_path = audio_path
        self.webcam_enabled = webcam_enabled
        self.webcam_position = webcam_position
        self.webcam_size = webcam_size
        self.is_running = True
        self.frame_count = 0
        self.audio_recorder = None

    def _overlay_webcam(self, frame, cam_frame, width, height):
        """Overlay webcam frame onto screen frame at specified position"""
        cam_h, cam_w = cam_frame.shape[:2]
        margin = 10

        if self.webcam_position == "bottom-right":
            y1 = height - cam_h - margin
            x1 = width - cam_w - margin
        elif self.webcam_position == "bottom-left":
            y1 = height - cam_h - margin
            x1 = margin
        elif self.webcam_position == "top-left":
            y1 = margin
            x1 = margin
        else:  # top-right
            y1 = margin
            x1 = width - cam_w - margin

        y2 = y1 + cam_h
        x2 = x1 + cam_w

        # Bounds check
        if y1 >= 0 and x1 >= 0 and y2 <= height and x2 <= width:
            frame[y1:y2, x1:x2] = cam_frame

    def run(self):
        """Main recording loop"""
        cap = None
        try:
            # Start audio recording if enabled
            if self.record_audio and self.audio_path:
                self.audio_recorder = AudioRecorder(self.audio_path)
                self.audio_recorder.start()

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
            temp_video_path = self.output_path.replace('.mp4', '_temp.mp4')
            out = cv2.VideoWriter(temp_video_path, fourcc, self.fps, (width, height))

            # Setup webcam if enabled
            if self.webcam_enabled:
                cap = cv2.VideoCapture(0)
                if not cap.isOpened():
                    cap = None

            self.frame_count = 0
            last_time = datetime.now()

            while self.is_running:
                # Capture screen
                screenshot = sct.grab(monitor)

                # Convert to numpy array
                img = np.array(screenshot)

                # Convert RGB to BGR for OpenCV
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

                # Overlay webcam frame if enabled
                if cap is not None and cap.isOpened():
                    ret, cam_frame = cap.read()
                    if ret:
                        cam_h, cam_w = cam_frame.shape[:2]
                        target_w = self.webcam_size
                        target_h = int(target_w * cam_h / cam_w)
                        cam_frame = cv2.resize(cam_frame, (target_w, target_h))
                        self._overlay_webcam(img, cam_frame, width, height)

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
            if cap is not None:
                cap.release()
            self.progress.emit(self.frame_count)

            # Stop audio recording
            audio_success = False
            if self.audio_recorder:
                audio_success = self.audio_recorder.stop()

            # Merge audio and video if audio was recorded
            if self.record_audio and audio_success and os.path.exists(self.audio_path):
                self.progress.emit(self.frame_count)
                try:
                    video_clip = VideoFileClip(temp_video_path)
                    audio_clip = AudioFileClip(self.audio_path)

                    # Trim audio to match video duration
                    video_duration = video_clip.duration
                    if audio_clip.duration > video_duration:
                        audio_clip = audio_clip.subclip(0, video_duration)

                    final_clip = video_clip.set_audio(audio_clip)
                    final_clip.write_videofile(
                        self.output_path,
                        codec='libx264',
                        audio_codec='aac',
                        verbose=False,
                        logger=None
                    )

                    # Clean up temp files
                    video_clip.close()
                    audio_clip.close()
                    os.remove(temp_video_path)
                    os.remove(self.audio_path)

                except Exception as e:
                    self.error.emit(f"Failed to merge audio/video: {e}")
                    # If merge fails, keep video only
                    if os.path.exists(temp_video_path):
                        os.rename(temp_video_path, self.output_path)
            else:
                # No audio or audio failed, just rename temp file
                if os.path.exists(temp_video_path):
                    os.rename(temp_video_path, self.output_path)

        except Exception as e:
            if cap is not None:
                cap.release()
            self.error.emit(f"Recording error: {e}")

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


class ScreenRecorderPro(QMainWindow):
    """Main application window - Pro version with audio and webcam"""

    def __init__(self):
        super().__init__()
        self.recording_thread = None
        self.output_folder = ""
        self.audio_path = ""
        self.region = None
        self.start_time = None

        self.init_ui()

    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("PyRecorder Pro")
        self.setMinimumSize(520, 580)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Title
        title_label = QLabel("PyRecorder Pro - Teaching Screen Recorder")
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

        # Audio recording
        audio_layout = QHBoxLayout()
        self.audio_checkbox = QCheckBox("Record Audio (Microphone)")
        self.audio_checkbox.setChecked(False)
        audio_layout.addWidget(self.audio_checkbox)
        audio_layout.addStretch()
        settings_layout.addLayout(audio_layout)

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
        self.codec_combo.addItems(["mp4v", "XVID", "MJPG"])
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

        # Webcam settings group
        webcam_group = QGroupBox("Webcam Overlay")
        webcam_layout = QVBoxLayout()

        # Enable webcam
        webcam_enable_layout = QHBoxLayout()
        self.webcam_checkbox = QCheckBox("Enable Webcam Overlay")
        self.webcam_checkbox.setChecked(False)
        webcam_enable_layout.addWidget(self.webcam_checkbox)
        webcam_enable_layout.addStretch()
        webcam_layout.addLayout(webcam_enable_layout)

        # Webcam position
        pos_layout = QHBoxLayout()
        pos_layout.addWidget(QLabel("Position:"))
        self.webcam_pos_combo = QComboBox()
        self.webcam_pos_combo.addItems([
            "Bottom-Right", "Bottom-Left", "Top-Left", "Top-Right"
        ])
        pos_layout.addWidget(self.webcam_pos_combo)
        pos_layout.addStretch()
        webcam_layout.addLayout(pos_layout)

        # Webcam size
        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel("Overlay Size (width):"))
        self.webcam_size_spinbox = QSpinBox()
        self.webcam_size_spinbox.setRange(100, 640)
        self.webcam_size_spinbox.setValue(240)
        self.webcam_size_spinbox.setSingleStep(20)
        size_layout.addWidget(self.webcam_size_spinbox)
        size_layout.addWidget(QLabel("px"))
        size_layout.addStretch()
        webcam_layout.addLayout(size_layout)

        # Preview button
        preview_btn_layout = QHBoxLayout()
        self.preview_btn = QPushButton("Preview Webcam")
        self.preview_btn.clicked.connect(self.preview_webcam)
        preview_btn_layout.addWidget(self.preview_btn)
        preview_btn_layout.addStretch()
        webcam_layout.addLayout(preview_btn_layout)

        webcam_group.setLayout(webcam_layout)
        main_layout.addWidget(webcam_group)

        # Status
        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout()

        self.status_label = QLabel("Ready to record")
        status_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setMaximum(0)
        self.progress_bar.setMinimum(0)
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

    def preview_webcam(self):
        """Open webcam preview dialog"""
        dialog = WebcamPreviewDialog(self)
        dialog.exec()

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
        record_audio = self.audio_checkbox.isChecked()
        webcam_enabled = self.webcam_checkbox.isChecked()
        webcam_position = self.webcam_pos_combo.currentText().lower().replace("-", "-")
        webcam_size = self.webcam_size_spinbox.value()

        # Setup audio path
        if record_audio:
            base_path = os.path.splitext(output_path)[0]
            self.audio_path = f"{base_path}_audio.wav"
        else:
            self.audio_path = None

        # Build status text
        status_parts = []
        if record_audio:
            status_parts.append("audio")
        if webcam_enabled:
            status_parts.append("webcam")
        status_suffix = f" ({' + '.join(status_parts)})" if status_parts else ""

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
        self.status_label.setText(f"Recording...{status_suffix}")
        self.progress_bar.setMaximum(0)
        self.progress_bar.setMinimum(0)

        # Disable settings during recording
        self.fps_spinbox.setEnabled(False)
        self.codec_combo.setEnabled(False)
        self.audio_checkbox.setEnabled(False)
        self.webcam_checkbox.setEnabled(False)
        self.webcam_pos_combo.setEnabled(False)
        self.webcam_size_spinbox.setEnabled(False)

        # Start recording thread
        self.recording_thread = RecordingThread(
            output_path,
            fps,
            codec,
            self.region,
            record_audio,
            self.audio_path,
            webcam_enabled,
            webcam_position,
            webcam_size
        )
        self.recording_thread.progress.connect(self.update_progress)
        self.recording_thread.finished.connect(self.recording_finished)
        self.recording_thread.error.connect(self.recording_error)
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

        # Re-enable settings
        self.fps_spinbox.setEnabled(True)
        self.codec_combo.setEnabled(True)
        self.audio_checkbox.setEnabled(True)
        self.webcam_checkbox.setEnabled(True)
        self.webcam_pos_combo.setEnabled(True)
        self.webcam_size_spinbox.setEnabled(True)

        if self.start_time:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            self.status_label.setText(f"Saved! Duration: {elapsed:.1f}s")

            QMessageBox.information(
                self,
                "PyRecorder - Recording Complete",
                f"Recording saved to:\n{self.current_output_path}\n\n"
                f"Total frames: {self.frame_count_label.text().split(': ')[1]}\n"
                f"Duration: {elapsed:.1f} seconds"
            )

    def recording_error(self, error_msg):
        """Handle recording error"""
        QMessageBox.critical(
            self,
            "PyRecorder - Error",
            f"An error occurred during recording:\n{error_msg}"
        )


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    recorder = ScreenRecorderPro()
    recorder.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
