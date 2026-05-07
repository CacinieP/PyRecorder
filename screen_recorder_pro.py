"""
Windows Screen Recorder Pro
Screen recording with audio, webcam overlay, and window capture support
"""

import sys
import cv2
import numpy as np
from mss import mss
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSpinBox, QFileDialog, QComboBox, QGroupBox,
    QMessageBox, QProgressBar, QCheckBox, QDialog, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QImage, QPixmap
from datetime import datetime
import threading
import pyaudio
import wave
import os
from moviepy import VideoFileClip, AudioFileClip
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32


def get_visible_windows():
    """Enumerate all visible windows with titles using Win32 API"""
    windows = []

    def enum_callback(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                if title:
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    w = rect.right - rect.left
                    h = rect.bottom - rect.top
                    if w > 50 and h > 50:
                        windows.append({
                            'title': title,
                            'hwnd': hwnd,
                            'rect': (rect.left, rect.top, w, h)
                        })
        return True

    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(enum_callback)
    user32.EnumWindows(callback, 0)
    return windows


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
        if self.is_recording:
            self.frames.append(in_data)
        return (None, pyaudio.paContinue)

    def stop(self):
        self.is_recording = False
        if hasattr(self, 'stream'):
            self.stream.stop_stream()
            self.stream.close()
        self.audio.terminate()
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
            self.timer.start(33)
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
                qimg = QImage(frame.data, w, h, ch * w, QImage.Format.Format_RGB888)
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
    preview_frame = pyqtSignal(object)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, output_path, fps, codec, region=None, record_audio=False,
                 audio_path=None, webcam_enabled=False, webcam_position="bottom-right",
                 webcam_size=240, window_hwnd=None, window_rect=None):
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
        self.window_hwnd = window_hwnd
        self.window_rect = window_rect
        self.is_running = True
        self.frame_count = 0
        self.audio_recorder = None

    def _overlay_webcam(self, frame, cam_frame, width, height):
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
        else:
            y1 = margin
            x1 = width - cam_w - margin

        y2 = y1 + cam_h
        x2 = x1 + cam_w
        if y1 >= 0 and x1 >= 0 and y2 <= height and x2 <= width:
            frame[y1:y2, x1:x2] = cam_frame

    def _emit_preview(self, img, width, height):
        scale = min(480 / width, 360 / height, 1.0)
        if scale < 1.0:
            preview = cv2.resize(img, None, fx=scale, fy=scale)
        else:
            preview = img
        preview_rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)
        h, w, ch = preview_rgb.shape
        qimg = QImage(preview_rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
        self.preview_frame.emit(qimg)

    def run(self):
        cap = None
        try:
            if self.record_audio and self.audio_path:
                self.audio_recorder = AudioRecorder(self.audio_path)
                self.audio_recorder.start()

            sct = mss()

            # Determine capture monitor
            if self.window_rect:
                # Window capture mode
                wx, wy, ww, wh = self.window_rect
                if self.region:
                    # Sub-region within window (relative coords)
                    monitor = {
                        "top": wy + self.region[1],
                        "left": wx + self.region[0],
                        "width": min(self.region[2], ww - self.region[0]),
                        "height": min(self.region[3], wh - self.region[1])
                    }
                else:
                    monitor = {"top": wy, "left": wx, "width": ww, "height": wh}
            elif self.region:
                monitor = {"top": self.region[1], "left": self.region[0],
                          "width": self.region[2], "height": self.region[3]}
            else:
                monitor = sct.monitors[1]

            width = monitor["width"]
            height = monitor["height"]

            if width <= 0 or height <= 0:
                self.error.emit("Invalid capture area (zero size)")
                self.finished.emit()
                return

            fourcc = cv2.VideoWriter_fourcc(*self.codec)
            temp_video_path = self.output_path.replace('.mp4', '_temp.mp4')
            out = cv2.VideoWriter(temp_video_path, fourcc, self.fps, (width, height))

            if self.webcam_enabled:
                cap = cv2.VideoCapture(0)
                if not cap.isOpened():
                    cap = None

            self.frame_count = 0
            last_time = datetime.now()
            preview_interval = max(1, self.fps // 5)

            while self.is_running:
                screenshot = sct.grab(monitor)
                img = np.array(screenshot)
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

                if cap is not None and cap.isOpened():
                    ret, cam_frame = cap.read()
                    if ret:
                        cam_h, cam_w = cam_frame.shape[:2]
                        target_w = self.webcam_size
                        target_h = int(target_w * cam_h / cam_w)
                        cam_frame = cv2.resize(cam_frame, (target_w, target_h))
                        self._overlay_webcam(img, cam_frame, width, height)

                out.write(img)
                self.frame_count += 1

                current_time = datetime.now()
                if (current_time - last_time).seconds >= 1:
                    self.progress.emit(self.frame_count)
                    last_time = current_time

                if self.frame_count % preview_interval == 0:
                    self._emit_preview(img, width, height)

                cv2.waitKey(int(1000 / self.fps))

            out.release()
            if cap is not None:
                cap.release()

            # Final preview
            self._emit_preview(img, width, height)
            self.progress.emit(self.frame_count)

            audio_success = False
            if self.audio_recorder:
                audio_success = self.audio_recorder.stop()

            if self.record_audio and audio_success and os.path.exists(self.audio_path):
                try:
                    video_clip = VideoFileClip(temp_video_path)
                    audio_clip = AudioFileClip(self.audio_path)

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

                    video_clip.close()
                    audio_clip.close()
                    os.remove(temp_video_path)
                    os.remove(self.audio_path)
                except Exception as e:
                    self.error.emit(f"Failed to merge audio/video: {e}")
                    if os.path.exists(temp_video_path):
                        os.rename(temp_video_path, self.output_path)
            else:
                if os.path.exists(temp_video_path):
                    os.rename(temp_video_path, self.output_path)

        except Exception as e:
            if cap is not None:
                cap.release()
            self.error.emit(f"Recording error: {e}")

        self.finished.emit()

    def stop(self):
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
    """Main application window - Pro version with audio, webcam, and window capture"""

    def __init__(self):
        super().__init__()
        self.recording_thread = None
        self.output_folder = ""
        self.audio_path = ""
        self.region = None
        self.start_time = None
        self.current_output_path = ""
        self._selected_window_rect = None

        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("PyRecorder Pro")
        self.setMinimumSize(960, 660)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(10)

        # ===== Left panel: settings =====
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setFixedWidth(420)

        title_label = QLabel("PyRecorder Pro")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        left_layout.addWidget(title_label)

        # --- Output Settings ---
        output_group = QGroupBox("Output Settings")
        output_layout = QVBoxLayout()
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("Save:"))
        self.path_label = QLabel("Not selected")
        self.path_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        path_layout.addWidget(self.path_label)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_file)
        path_layout.addWidget(browse_btn)
        output_layout.addLayout(path_layout)
        output_group.setLayout(output_layout)
        left_layout.addWidget(output_group)

        # --- Recording Settings ---
        settings_group = QGroupBox("Recording Settings")
        settings_layout = QVBoxLayout()

        # Capture mode
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Capture:"))
        self.capture_mode_combo = QComboBox()
        self.capture_mode_combo.addItems(["Full Screen", "Custom Region", "Window Capture"])
        self.capture_mode_combo.currentIndexChanged.connect(self.on_capture_mode_changed)
        mode_layout.addWidget(self.capture_mode_combo)
        settings_layout.addLayout(mode_layout)

        # Window selector (shown for Window Capture)
        window_layout = QHBoxLayout()
        window_layout.addWidget(QLabel("Window:"))
        self.window_combo = QComboBox()
        self.window_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        window_layout.addWidget(self.window_combo)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_windows)
        window_layout.addWidget(refresh_btn)
        self.window_row = QWidget()
        wl = QVBoxLayout(self.window_row)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addLayout(window_layout)
        self.window_row.hide()
        settings_layout.addWidget(self.window_row)

        # Region info row
        region_layout = QHBoxLayout()
        region_layout.addWidget(QLabel("Area:"))
        self.region_label = QLabel("Full Screen")
        self.region_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        region_layout.addWidget(self.region_label)
        self.region_btn = QPushButton("Select Region")
        self.region_btn.clicked.connect(self.select_region)
        region_layout.addWidget(self.region_btn)
        settings_layout.addLayout(region_layout)

        # Audio
        audio_layout = QHBoxLayout()
        self.audio_checkbox = QCheckBox("Record Audio (Microphone)")
        audio_layout.addWidget(self.audio_checkbox)
        audio_layout.addStretch()
        settings_layout.addLayout(audio_layout)

        # FPS
        fps_layout = QHBoxLayout()
        fps_layout.addWidget(QLabel("FPS:"))
        self.fps_spinbox = QSpinBox()
        self.fps_spinbox.setRange(10, 60)
        self.fps_spinbox.setValue(30)
        fps_layout.addWidget(self.fps_spinbox)
        fps_layout.addStretch()
        settings_layout.addLayout(fps_layout)

        # Codec
        codec_layout = QHBoxLayout()
        codec_layout.addWidget(QLabel("Codec:"))
        self.codec_combo = QComboBox()
        self.codec_combo.addItems(["mp4v", "XVID", "MJPG"])
        codec_layout.addWidget(self.codec_combo)
        codec_layout.addStretch()
        settings_layout.addLayout(codec_layout)

        settings_group.setLayout(settings_layout)
        left_layout.addWidget(settings_group)

        # --- Webcam Overlay ---
        webcam_group = QGroupBox("Webcam Overlay")
        webcam_layout = QVBoxLayout()

        enable_layout = QHBoxLayout()
        self.webcam_checkbox = QCheckBox("Enable Webcam Overlay")
        enable_layout.addWidget(self.webcam_checkbox)
        enable_layout.addStretch()
        webcam_layout.addLayout(enable_layout)

        pos_layout = QHBoxLayout()
        pos_layout.addWidget(QLabel("Position:"))
        self.webcam_pos_combo = QComboBox()
        self.webcam_pos_combo.addItems(["Bottom-Right", "Bottom-Left", "Top-Left", "Top-Right"])
        pos_layout.addWidget(self.webcam_pos_combo)
        pos_layout.addStretch()
        webcam_layout.addLayout(pos_layout)

        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel("Size:"))
        self.webcam_size_spinbox = QSpinBox()
        self.webcam_size_spinbox.setRange(100, 640)
        self.webcam_size_spinbox.setValue(240)
        self.webcam_size_spinbox.setSingleStep(20)
        size_layout.addWidget(self.webcam_size_spinbox)
        size_layout.addWidget(QLabel("px"))
        size_layout.addStretch()
        webcam_layout.addLayout(size_layout)

        preview_btn_layout = QHBoxLayout()
        preview_btn = QPushButton("Preview Webcam")
        preview_btn.clicked.connect(self.preview_webcam)
        preview_btn_layout.addWidget(preview_btn)
        preview_btn_layout.addStretch()
        webcam_layout.addLayout(preview_btn_layout)

        webcam_group.setLayout(webcam_layout)
        left_layout.addWidget(webcam_group)

        # --- Status ---
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
        left_layout.addWidget(status_group)

        # Record button
        self.record_btn = QPushButton("Start Recording")
        self.record_btn.setMinimumHeight(45)
        self.record_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50; color: white;
                font-size: 14px; font-weight: bold; border-radius: 5px;
            }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #cccccc; }
        """)
        self.record_btn.clicked.connect(self.toggle_recording)
        left_layout.addWidget(self.record_btn)

        left_layout.addStretch()

        # ===== Right panel: live preview =====
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        preview_title = QLabel("Live Preview")
        preview_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_font = QFont()
        preview_font.setPointSize(12)
        preview_font.setBold(True)
        preview_title.setFont(preview_font)
        right_layout.addWidget(preview_title)

        self.preview_label = QLabel("Preview will appear\nwhen recording starts")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(480, 360)
        self.preview_label.setStyleSheet(
            "background-color: #1a1a2e; color: #888; "
            "border: 2px solid #333; border-radius: 8px; "
            "font-size: 14px;"
        )
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_layout.addWidget(self.preview_label, 1)

        right_layout.addStretch()

        # Assemble
        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel, 1)

        # Initial state
        self.on_capture_mode_changed(0)
        self.refresh_windows()

    # ---- Capture mode ----

    def on_capture_mode_changed(self, index):
        mode = self.capture_mode_combo.currentText()
        self.region = None
        self._selected_window_rect = None

        if mode == "Full Screen":
            self.window_row.hide()
            self.region_btn.hide()
            self.region_label.setText("Full Screen")
        elif mode == "Custom Region":
            self.window_row.hide()
            self.region_btn.show()
            self.region_label.setText("Click 'Select Region'")
        elif mode == "Window Capture":
            self.window_row.show()
            self.region_btn.show()
            self.region_label.setText("Select window above, or crop region")

    def refresh_windows(self):
        self.window_combo.clear()
        windows = get_visible_windows()
        for w in windows:
            # Truncate long titles for display
            title = w['title']
            if len(title) > 60:
                title = title[:57] + "..."
            self.window_combo.addItem(title, w['hwnd'])
        if self.window_combo.count() == 0:
            self.window_combo.addItem("(No windows found)", None)

    def _get_selected_window_rect(self):
        hwnd = self.window_combo.currentData()
        if hwnd is None:
            return None
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w > 0 and h > 0:
            return (rect.left, rect.top, w, h)
        return None

    # ---- Actions ----

    def browse_file(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Select Save Folder", "")
        if folder_path:
            self.output_folder = folder_path
            self.path_label.setText(folder_path)

    def select_region(self):
        self.region = None
        mode = self.capture_mode_combo.currentText()
        if mode == "Full Screen":
            self.region_label.setText("Full Screen")
            return
        selector = RegionSelector()
        selector.region_selected.connect(self.on_region_selected)
        selector.showFullScreen()

    def on_region_selected(self, region):
        mode = self.capture_mode_combo.currentText()
        self.region = region
        self.region_label.setText(f"Region: {region[2]}x{region[3]}")

    def preview_webcam(self):
        dialog = WebcamPreviewDialog(self)
        dialog.exec()

    # ---- Recording ----

    def toggle_recording(self):
        if self.recording_thread and self.recording_thread.isRunning():
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        if not self.output_folder:
            self.browse_file()
            if not self.output_folder:
                return

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = f"{self.output_folder}/recording_{timestamp}.mp4"
        self.current_output_path = output_path

        fps = self.fps_spinbox.value()
        codec = self.codec_combo.currentText()
        record_audio = self.audio_checkbox.isChecked()
        webcam_enabled = self.webcam_checkbox.isChecked()
        webcam_position = self.webcam_pos_combo.currentText().lower().replace(" ", "-")
        webcam_size = self.webcam_size_spinbox.value()

        # Determine capture parameters based on mode
        mode = self.capture_mode_combo.currentText()
        window_rect = None
        region = None

        if mode == "Custom Region":
            if self.region is None:
                QMessageBox.warning(self, "PyRecorder", "Please select a region first.")
                return
            region = self.region
        elif mode == "Window Capture":
            window_rect = self._get_selected_window_rect()
            if window_rect is None:
                QMessageBox.warning(self, "PyRecorder", "Please select a window first.")
                return
            if self.region:
                region = self.region

        if record_audio:
            base_path = os.path.splitext(output_path)[0]
            self.audio_path = f"{base_path}_audio.wav"
        else:
            self.audio_path = None

        status_parts = []
        if record_audio:
            status_parts.append("audio")
        if webcam_enabled:
            status_parts.append("webcam")
        if mode == "Window Capture":
            status_parts.append("window")
        elif mode == "Custom Region":
            status_parts.append("region")
        status_suffix = f" ({' + '.join(status_parts)})" if status_parts else ""

        self.record_btn.setText("Stop Recording")
        self.record_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336; color: white;
                font-size: 14px; font-weight: bold; border-radius: 5px;
            }
            QPushButton:hover { background-color: #da190b; }
        """)
        self.status_label.setText(f"Recording...{status_suffix}")
        self.progress_bar.setMaximum(0)
        self.progress_bar.setMinimum(0)
        self.preview_label.setText("Starting...")

        self._set_controls_enabled(False)

        self.recording_thread = RecordingThread(
            output_path, fps, codec, region, record_audio, self.audio_path,
            webcam_enabled, webcam_position, webcam_size,
            window_hwnd=None, window_rect=window_rect
        )
        self.recording_thread.progress.connect(self.update_progress)
        self.recording_thread.preview_frame.connect(self.update_preview)
        self.recording_thread.finished.connect(self.recording_finished)
        self.recording_thread.error.connect(self.recording_error)
        self.recording_thread.start()

        self.start_time = datetime.now()

    def stop_recording(self):
        if self.recording_thread:
            self.status_label.setText("Stopping...")
            self.recording_thread.stop()

    def update_progress(self, frame_count):
        self.frame_count_label.setText(f"Frames: {frame_count}")
        if self.start_time:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            self.status_label.setText(f"Recording... ({elapsed:.0f}s)")

    def update_preview(self, qimg):
        pixmap = QPixmap.fromImage(qimg).scaled(
            self.preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.preview_label.setPixmap(pixmap)

    def recording_finished(self):
        self.record_btn.setText("Start Recording")
        self.record_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50; color: white;
                font-size: 14px; font-weight: bold; border-radius: 5px;
            }
            QPushButton:hover { background-color: #45a049; }
        """)
        self._set_controls_enabled(True)

        if self.start_time:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            self.status_label.setText(f"Saved! Duration: {elapsed:.1f}s")

            QMessageBox.information(
                self, "PyRecorder - Recording Complete",
                f"Recording saved to:\n{self.current_output_path}\n\n"
                f"Total frames: {self.frame_count_label.text().split(': ')[1]}\n"
                f"Duration: {elapsed:.1f} seconds"
            )

        self.preview_label.setText("Recording saved.\nStart a new recording to preview.")

    def recording_error(self, error_msg):
        QMessageBox.critical(self, "PyRecorder - Error", f"Recording error:\n{error_msg}")

    def _set_controls_enabled(self, enabled):
        self.fps_spinbox.setEnabled(enabled)
        self.codec_combo.setEnabled(enabled)
        self.audio_checkbox.setEnabled(enabled)
        self.webcam_checkbox.setEnabled(enabled)
        self.webcam_pos_combo.setEnabled(enabled)
        self.webcam_size_spinbox.setEnabled(enabled)
        self.capture_mode_combo.setEnabled(enabled)
        self.window_combo.setEnabled(enabled)
        self.region_btn.setEnabled(enabled)


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    recorder = ScreenRecorderPro()
    recorder.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
