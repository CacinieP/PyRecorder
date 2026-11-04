"""The PyRecorder main window: one Start button, one file out.

Lifecycle (ported from the legacy macOS edition, which validated it on real
hardware): idle → preparing → probing (background device probes) → recording
→ stopping (ffmpeg finalises the MP4 trailer) → idle. The GUI thread never
blocks on devices or ffmpeg: probes run in PreRecordProbe, ffmpeg completion
is polled by a 50ms timer, and all diagnostic pipes are drained by
ProcessOutputReader.
"""
import os
import subprocess
import sys
import time
from datetime import datetime

from PyQt6.QtCore import QTimer, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog,
                             QGroupBox, QHBoxLayout, QLabel, QMainWindow,
                             QMessageBox, QPushButton, QSizePolicy, QSpinBox,
                             QVBoxLayout, QWidget)

from pyrecorder import __version__
from pyrecorder.camera import (CameraPipeFeed, clamp_pip, pipe_camera_size,
                               probe_camera)
from pyrecorder.channels import open_channel
from pyrecorder.command import (CameraInput, ExtraAudioInput, NativeScreenInput,
                                PipeScreenInput, build_command)
from pyrecorder.ffmpeg_exe import (ProcessOutputReader, find_ffmpeg,
                                    install_hint, popen_ffmpeg,
                                    request_graceful_stop)
from pyrecorder.mp4check import recording_succeeded
from pyrecorder.pacing import pick_camera_fps
from pyrecorder.screenfeed import ScreenPipeFeed, even_size
from pyrecorder.ui.bubble import PipPreviewWindow
from pyrecorder.ui.live import LivePreviewThread, LivePreviewWindow
from pyrecorder.ui.region import RegionSelector

CAMERA_INDEX = 0   # v1 uses the first camera (ADR-0003 notes the rationale)

GO_STYLE = ("QPushButton { background-color: #4CAF50; color: white;"
            " font-size: 14px; font-weight: bold; border-radius: 6px; }"
            " QPushButton:hover { background-color: #45a049; }")
STOP_STYLE = ("QPushButton { background-color: #f44336; color: white;"
              " font-size: 14px; font-weight: bold; border-radius: 6px; }"
              " QPushButton:hover { background-color: #da190b; }")


class DeviceListThread(QThread):
    """Enumerate audio inputs (and the screen) without freezing the window."""
    done = pyqtSignal(dict)

    def __init__(self, backend):
        super().__init__()
        self.backend = backend

    def run(self):
        devices = []
        try:
            devices = self.backend.list_audio_inputs()
        except Exception:
            devices = []
        screen_ok, screen_hint = (False, "")
        try:
            screen_ok, screen_hint = self.backend.check_screen()
        except Exception as exc:
            screen_hint = str(exc)
        self.done.emit({"devices": devices, "screen_ok": screen_ok,
                        "screen_hint": screen_hint})


class PreRecordProbe(QThread):
    """Probe screen/camera/mic off the GUI thread (~1.5-4s altogether)."""
    done = pyqtSignal(dict)

    def __init__(self, backend, want_camera, want_mic, mic_device_id):
        super().__init__()
        self.backend = backend
        self.want_camera = want_camera
        self.want_mic = want_mic
        self.mic_device_id = mic_device_id

    def run(self):
        screen_ok, screen_hint = (True, "")
        try:
            screen_ok, screen_hint = self.backend.check_screen()
        except Exception as exc:
            screen_ok, screen_hint = False, str(exc)
        camera = None
        if not self.isInterruptionRequested() and self.want_camera and screen_ok:
            try:
                camera = probe_camera(CAMERA_INDEX, self.backend.id)
            except Exception:
                camera = None
        mic_ok = False
        if not self.isInterruptionRequested() and self.want_mic and screen_ok:
            try:
                mic_ok = bool(self.backend.probe_audio(self.mic_device_id))
            except Exception:
                mic_ok = False
        if not self.isInterruptionRequested():
            self.done.emit({"screen_ok": screen_ok, "screen_hint": screen_hint,
                            "camera": camera, "mic_ok": mic_ok})


class RecorderWindow(QMainWindow):
    def __init__(self, backend):
        super().__init__()
        self.backend = backend
        self.proc = None
        self._stop_requested = False
        self._stop_started = None
        self._kill_requested = False
        self._signaled_ffmpeg = False
        self._session = 0
        self._state = "idle"
        self._closing = False
        self._pending = None
        self._recording_error = None
        self.device_thread = None
        self.probe_thread = None
        self.stderr_reader = None
        self._retired_pip_windows = []
        self.output_path = ""
        self.region = None          # platform capture form (logical pts on mac)
        self.region_logical = None  # global logical points, for bubble mapping
        self._capture_rect = None   # physical (x, y, w, h) for mss platforms
        self.pip_window = None
        self.live_thread = None
        self.live_window = None
        self.cam_feed = None
        self.screen_feed = None
        self.extra_files = []
        self.save_folder = backend.default_output_folder()
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.timeout.connect(self.update_elapsed)
        self.lifecycle_timer = QTimer(self)
        self.lifecycle_timer.setInterval(50)
        self.lifecycle_timer.timeout.connect(self._poll_lifecycle)
        self.start_time = 0.0
        self.init_ui()
        QTimer.singleShot(100, self.refresh_devices)

    # ---- UI ------------------------------------------------------------

    def init_ui(self):
        self.setWindowTitle(f"PyRecorder {__version__}")
        self.setMinimumWidth(460)
        self.resize(480, min(780, int(QGuiApplication.primaryScreen()
                                      .availableGeometry().height() * 0.85)))

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        title = QLabel("屏幕 + 人脸 + 声音 → 一个 MP4")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Output
        out_group = QGroupBox("Output")
        out_layout = QHBoxLayout()
        self.path_label = QLabel(self.save_folder)
        self.path_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                      QSizePolicy.Policy.Preferred)
        browse = QPushButton("Choose...")
        browse.clicked.connect(self.browse_folder)
        out_layout.addWidget(self.path_label, 1)
        out_layout.addWidget(browse)
        out_group.setLayout(out_layout)
        layout.addWidget(out_group)

        # Capture area
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

        # Camera
        cam_group = QGroupBox("Camera (Picture-in-Picture)")
        cam_layout = QVBoxLayout()
        cam_top_row = QHBoxLayout()
        self.cam_checkbox = QCheckBox("Record camera overlay")
        self.cam_checkbox.setChecked(True)
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
        size_row.addWidget(QLabel("px  (drag the bubble to move)"))
        size_row.addStretch()
        cam_layout.addLayout(size_row)
        cam_group.setLayout(cam_layout)
        layout.addWidget(cam_group)

        # Audio + options
        opt_group = QGroupBox("Audio & Quality")
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
        opt_stack.addLayout(opt_layout)

        # Every audio input the platform can see — on macOS that includes
        # virtual devices (BlackHole) for system-audio recording.
        mic_row = QHBoxLayout()
        mic_row.addWidget(QLabel("Audio input:"))
        self.mic_combo = QComboBox()
        self.mic_combo.setSizePolicy(QSizePolicy.Policy.Expanding,
                                     QSizePolicy.Policy.Preferred)
        mic_row.addWidget(self.mic_combo, 1)
        opt_stack.addLayout(mic_row)

        self.separate_checkbox = QCheckBox("Also save separate screen & camera files")
        opt_stack.addWidget(self.separate_checkbox)
        opt_group.setLayout(opt_stack)
        layout.addWidget(opt_group)

        # Status
        self.status_label = QLabel("Detecting devices…")
        layout.addWidget(self.status_label)

        self.record_btn = QPushButton("Start Recording")
        self.record_btn.setMinimumHeight(44)
        self.record_btn.setStyleSheet(GO_STYLE)
        self.record_btn.clicked.connect(self.toggle_recording)
        layout.addWidget(self.record_btn)

        layout.addStretch()

    # ---- devices ---------------------------------------------------------

    def refresh_devices(self):
        if self._closing or self._state != "idle" or self.device_thread:
            return
        if find_ffmpeg() is None:
            self.status_label.setText("ffmpeg missing")
            QMessageBox.warning(
                self, "ffmpeg not found",
                "ffmpeg is required but not installed.\n\n"
                f"Install it with:\n    {install_hint()}\n\n"
                "Then restart PyRecorder.")
            return
        self.status_label.setText("Detecting devices…")
        thread = DeviceListThread(self.backend)
        self.device_thread = thread
        thread.done.connect(self._on_devices_listed)
        # The worker may still be finishing when its result is delivered;
        # destroy it only from its own finished signal.
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._device_thread_finished)
        thread.start()

    def _device_thread_finished(self):
        self.device_thread = None

    def _on_devices_listed(self, result):
        if self._closing or self._state != "idle":
            return
        self._populate_mic_combo(result.get("devices", []))
        parts = ["screen OK" if result.get("screen_ok") else "screen NOT found"]
        parts.append("mic OK" if self.mic_combo.count() else "no mic")
        self.status_label.setText("Devices: " + ", ".join(parts))

    def _populate_mic_combo(self, devices):
        previous = self.mic_combo.currentData()
        self.mic_combo.blockSignals(True)
        self.mic_combo.clear()
        for device in devices:
            self.mic_combo.addItem(device.label, device.id)
        if previous is not None:
            at = self.mic_combo.findData(previous)
            if at >= 0:
                self.mic_combo.setCurrentIndex(at)
        self.mic_combo.blockSignals(False)

    def selected_mic(self):
        """(wanted, device_id) — device_id None when nothing is selected."""
        if not self.mic_checkbox.isChecked() or self.mic_combo.count() == 0:
            return False, None
        return True, self.mic_combo.currentData()

    # ---- actions -----------------------------------------------------------

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Save Folder",
                                                  self.save_folder)
        if folder:
            self.save_folder = folder
            self.path_label.setText(folder)

    def select_region(self):
        if self._state != "idle" or self._closing:
            return
        self.selector = RegionSelector(self.backend)
        self.selector.region_selected.connect(self.on_region_selected)
        self.selector.show()

    def on_region_selected(self, capture_region, logical_region):
        self.region = capture_region
        self.region_logical = logical_region
        self.region_label.setText(
            f"Region: {capture_region[2]} x {capture_region[3]}")

    def clear_region(self):
        self.region = None
        self.region_logical = None
        self.region_label.setText("Full Screen")

    # ---- camera preview bubble ------------------------------------------------

    def toggle_pip_preview(self, checked):
        if not checked:
            self._close_pip_bubble()
            return
        if self._closing or self._state != "idle" or self._retired_pip_windows:
            self.preview_btn.setChecked(False)
            return
        if self.pip_window is not None:
            return
        screen = QGuiApplication.primaryScreen().geometry()
        w = self.cam_size.value()
        self.pip_window = PipPreviewWindow(CAMERA_INDEX, self.backend.id, w)
        self.pip_window.move(screen.x() + screen.width() - w - 40,
                             screen.y() + screen.height() - int(w * 9 / 16) - 60)
        self.pip_window.show()
        # size spinbox only sets the *initial* size; ignore while bubble exists
        self.cam_size.setEnabled(False)

    def _close_pip_bubble(self):
        if self.pip_window:
            window = self.pip_window
            self.pip_window = None
            window.close()
            self._retired_pip_windows.append(window)
            self.lifecycle_timer.start()
            self.preview_btn.setEnabled(False)
            self.preview_btn.setChecked(False)
        self.cam_size.setEnabled(True)

    # ---- recording ----------------------------------------------------------

    def toggle_recording(self):
        if self.proc is not None:
            self.stop_recording()
        elif self._state == "idle" and not self._closing:
            self.start_recording()

    def start_recording(self):
        if self._closing or self._state != "idle" or self.proc is not None:
            return
        ffmpeg = find_ffmpeg()
        if ffmpeg is None:
            QMessageBox.warning(self, "ffmpeg not found",
                                f"Install ffmpeg first:\n    {install_hint()}")
            return

        os.makedirs(self.save_folder, exist_ok=True)
        self.output_path = os.path.join(
            self.save_folder, f"recording_{datetime.now():%Y%m%d_%H%M%S}.mp4")

        screen = QGuiApplication.primaryScreen()
        scale = screen.devicePixelRatio() or 1.0
        geo = screen.geometry()

        logical = self.region_logical if self.region_logical else \
            (geo.x(), geo.y(), geo.width(), geo.height())

        cam_wanted = self.cam_checkbox.isChecked()
        mic_wanted, mic_device = self.selected_mic()

        if self.backend.screen_capture_kind() == "native":
            cap_w, cap_h = int(logical[2] * scale), int(logical[3] * scale)
        else:
            if self.region is not None:
                rx, ry, rw, rh = self.region
            else:
                rx, ry = round(geo.x() * scale), round(geo.y() * scale)
                rw, rh = geo.width() * scale, geo.height() * scale
            rw, rh = even_size(rw, rh)
            self._capture_rect = (rx, ry, rw, rh)
            cap_w, cap_h = rw, rh

        # PiP rect: prefer the preview bubble's on-screen geometry, otherwise
        # the bottom-right corner at the default size. Clamping waits for the
        # probe because it needs the camera's real aspect ratio.
        if self.pip_window and self.pip_window.isVisible():
            pip = self.pip_window.pip_rect((logical[0], logical[1]), scale)
        else:
            margin = int(24 * scale)
            w = int(self.cam_size.value() * scale)
            pip = (w, cap_w - w - margin, cap_h - int(w * 9 / 16) - margin)

        # the bubble has to release the camera before the recorder opens it
        self._close_pip_bubble()

        self._pending = {
            "ffmpeg": ffmpeg, "scale": scale, "logical": logical,
            "mic_device": mic_device, "cam_wanted": cam_wanted,
            "mic_wanted": mic_wanted, "pip": pip, "cap_w": cap_w, "cap_h": cap_h,
            "fps": self.fps_spin.value(),
            "layout": ("pip", "speaker-right", "speaker-left")[
                self.layout_combo.currentIndex()],
            "separate": self.separate_checkbox.isChecked(),
        }
        self._session += 1
        self._recording_error = None
        self._state = "preparing"
        self._set_controls(False)
        self.record_btn.setEnabled(False)
        self.status_label.setText("Preparing devices…")
        self.lifecycle_timer.start()

    def _launch_pending_probe(self):
        if self._closing or self._pending is None or self._state != "preparing":
            return
        if self._retired_pip_windows:
            return  # the preview must release the camera before probing it
        if self.probe_thread is not None and self.probe_thread.isRunning():
            return
        p = self._pending
        self.probe_thread = PreRecordProbe(
            self.backend, p["cam_wanted"], p["mic_wanted"], p["mic_device"])
        session = self._session
        self.probe_thread.done.connect(
            lambda result: self._on_probes_done(result, session))
        self._state = "probing"
        self.probe_thread.start()

    def _abort_start(self, message=None, detail=None):
        """Return to the idle state after a start that did not get going."""
        if message:
            QMessageBox.critical(self, "PyRecorder", message)
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
        if not result.get("screen_ok"):
            self._abort_start(
                "Screen capture is not available.\n\n" + result.get("screen_hint", ""))
            return

        cam = result.get("camera")
        cam_on = bool(p["cam_wanted"]) and cam is not None
        mic_on = bool(p["mic_wanted"]) and bool(result.get("mic_ok"))

        if p["mic_wanted"] and not mic_on:
            QMessageBox.warning(
                self, "PyRecorder",
                "Microphone is unavailable — recording video only.\n\n"
                + self.backend.permission_hint())
        if p["cam_wanted"] and not cam_on:
            QMessageBox.warning(
                self, "PyRecorder",
                "Camera is unavailable — recording screen"
                + (" + microphone" if mic_on else "") + " only.")
        if self._closing or (session is not None and session != self._session):
            return  # a warning dialog may have processed a close event

        cam_fps = cam_size = None
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

        channels = []
        camera = screen_input = mic_input = None
        try:
            if cam_on:
                cam_channel = open_channel()
                channels.append(cam_channel)
                camera = CameraInput(cam_channel.input_arg(), cam_fps or p["fps"],
                                     cam_size)

            if self.backend.screen_capture_kind() == "native":
                mic_arg = p["mic_device"] if mic_on else None
                screen_input = NativeScreenInput(
                    self.backend.native_screen_args(p["fps"], mic_arg),
                    audio_stream="0:a" if mic_on else None)
            else:
                screen_channel = open_channel()
                channels.append(screen_channel)
                screen_input = PipeScreenInput(
                    screen_channel.input_arg(),
                    (self._capture_rect[2], self._capture_rect[3]))
                if mic_on:
                    mic_input = ExtraAudioInput(
                        self.backend.audio_input_args(p["mic_device"]),
                        self.backend.audio_stream_label())

            cmd, self.extra_files = build_command(
                p["ffmpeg"], self.output_path, p["fps"],
                screen=screen_input, mic=mic_input, camera=camera,
                region=self.region if self.backend.screen_capture_kind() == "native" else None,
                screen_scale=p["scale"], pip=pip, layout=p["layout"],
                separate=p["separate"], preview=True,
                capture_size=(p["cap_w"], p["cap_h"]),
                encoder_main=self.backend.encoder_args("main"),
                encoder_camera=self.backend.encoder_args("camera"))
            # POSIX channels hand their read end to the child; Windows
            # channels carry no fds (ffmpeg connects over loopback TCP).
            pass_fds = [fd for fd in (ch.pass_fd() for ch in channels)
                        if fd is not None]
            self.proc = popen_ffmpeg(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, pass_fds=tuple(pass_fds))
        except Exception as e:
            for channel in channels:
                channel.discard()
            QMessageBox.critical(self, "PyRecorder", f"Failed to start ffmpeg:\n{e}")
            self._abort_start()
            return

        self.stderr_reader = ProcessOutputReader(self.proc.stderr)
        self.stderr_reader.start()

        for channel in channels:
            channel.after_spawn()   # drop the parent's copy of any read end

        self.cam_feed = None
        if camera is not None:
            self.cam_feed = CameraPipeFeed(
                CAMERA_INDEX, self.backend.id, None,
                camera.fps, size=tuple(camera.size),
                sink_factory=cam_channel.connect)
            self.cam_feed.failed.connect(
                lambda message, session=self._session:
                self._on_camera_feed_failed(message, session))
            self.cam_feed.start()

        self.screen_feed = None
        if self.backend.screen_capture_kind() != "native":
            self.screen_feed = ScreenPipeFeed(
                self._capture_rect, None, p["fps"],
                size=(screen_input.size[0], screen_input.size[1]),
                sink_factory=screen_channel.connect)
            self.screen_feed.failed.connect(
                lambda message, session=self._session:
                self._on_screen_feed_failed(message, session))
            self.screen_feed.start()

        self.live_thread = LivePreviewThread(self.proc)
        self.live_window = LivePreviewWindow()
        self.live_thread.frame.connect(self.live_window.on_frame)
        self.live_thread.start()
        self.live_window.show()

        self.record_btn.setEnabled(True)
        self._state = "recording"
        self.record_btn.setText("Stop Recording")
        self.record_btn.setStyleSheet(STOP_STYLE)
        self.start_time = time.time()
        self.elapsed_timer.start(500)

    def _on_camera_feed_failed(self, message, session):
        if session != self._session or self.proc is None:
            return
        self._recording_error = message
        self.stop_recording()
        self.status_label.setText("Camera failed — stopping…")

    def _on_screen_feed_failed(self, message, session):
        if session != self._session or self.proc is None:
            return
        self._recording_error = message
        self.stop_recording()
        self.status_label.setText("Screen capture failed — stopping…")

    def stop_recording(self):
        """Stop feeders first (EOF), then escalate to a signal only if needed.

        Closing every rawvideo input lets ffmpeg drain its filter graph and
        write the MP4 trailer by itself — verified against real ffmpeg on both
        channel flavors, and the only stop primitive that works on Windows
        (TerminateProcess never flushes). Native inputs (avfoundation) cannot
        EOF, so those get SIGTERM/CTRL_BREAK straight away; hard kill stays
        the last-resort escalation.
        """
        if self.proc is None or self._stop_requested:
            return
        self._stop_requested = True
        self._state = "stopping"
        self._stop_started = time.monotonic()
        self._kill_requested = False
        self._signaled_ffmpeg = False
        self.record_btn.setEnabled(False)
        self.status_label.setText("Stopping…")
        for worker in (self.cam_feed, self.screen_feed):
            if worker is not None:
                worker.stop()               # EOF on every pipe input
        if self.backend.screen_capture_kind() == "native":
            self._signal_ffmpeg()           # native inputs never EOF
        self.lifecycle_timer.start()

    def _signal_ffmpeg(self):
        if self._signaled_ffmpeg or self.proc is None or self.proc.poll() is not None:
            return
        self._signaled_ffmpeg = True
        request_graceful_stop(self.proc)

    def _poll_lifecycle(self):
        """Observe process/thread completion without blocking the GUI."""
        for window in list(self._retired_pip_windows):
            if not window.thread.isRunning():
                window.close()
                self._retired_pip_windows.remove(window)
        if not self._retired_pip_windows and self._state == "idle" and not self._closing:
            self.preview_btn.setEnabled(True)
        if self._state == "preparing":
            self._launch_pending_probe()
        proc = self.proc
        if proc is not None:
            if proc.poll() is not None:
                self._finalize(self._session)
            elif self._stop_requested:
                # pipe platforms: give EOF a few seconds to finalise before
                # signalling; then a few more before the hard kill
                age = time.monotonic() - self._stop_started
                if age >= 5:
                    self._signal_ffmpeg()
                if age >= 15 and not self._kill_requested:
                    self._kill_requested = True
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
        if self._closing:
            self._finish_close()
        elif (self.proc is None and self._state == "idle"
              and not self._retired_pip_windows
              and not (self.device_thread and self.device_thread.isRunning())
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
        if self.screen_feed:
            self.screen_feed.stop()
        if self.live_thread:
            self.live_thread.stop()
        workers = (self.cam_feed, self.screen_feed, self.live_thread)
        if (any(worker and worker.isRunning() for worker in workers)
                or (self.stderr_reader and self.stderr_reader.is_alive())):
            return  # retain every worker until it actually finishes

        err_tail = self.stderr_reader.tail_text() if self.stderr_reader else ""
        recording_error = self._recording_error or getattr(
            self.cam_feed, "failure_reason", None) or getattr(
            self.screen_feed, "failure_reason", None)
        self._recording_error = None
        self.stderr_reader = None
        self.cam_feed = None
        self.screen_feed = None
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
        succeeded = recording_succeeded(code, output_path)
        if recording_error:
            self.status_label.setText("Stopped: capture failed")
            message = "Recording stopped because a capture device failed.\n\n" + recording_error
            if succeeded:
                files = "\n".join([output_path] + extra_files)
                message += "\n\nSaved partial recording:\n" + files
                QMessageBox.warning(self, "PyRecorder", message)
            else:
                message += "\n\nThe recording could not be finalized."
                if err_tail:
                    message += "\n\nffmpeg output:\n" + err_tail
                QMessageBox.critical(self, "PyRecorder", message)
        elif not succeeded:
            self.status_label.setText("Failed")
            QMessageBox.critical(
                self, "PyRecorder",
                "Recording failed.\n\n"
                + self.backend.permission_hint()
                + (f"\n\nffmpeg output:\n{err_tail}" if err_tail else ""))
        else:
            files = "\n".join([output_path] + extra_files)
            self.status_label.setText(f"Saved: {output_path} ({secs:.1f}s)")
            if not self._closing:
                QMessageBox.information(self, "PyRecorder", f"Recording saved:\n{files}")

    def update_elapsed(self):
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
            # Stay alive until ffmpeg, the feeders and every probe/enumeration
            # worker has finished (a blocked device enumeration can outlive a
            # fixed wait; destroying its QThread would abort the process).
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
                or bool(self.probe_thread and self.probe_thread.isRunning())
                or bool(self.device_thread and self.device_thread.isRunning()))

    def _finish_close(self):
        if not self._shutdown_pending():
            self.close()

    def _set_controls(self, enabled):
        self.cam_checkbox.setEnabled(enabled)
        self.preview_btn.setEnabled(enabled and self._state == "idle"
                                    and not self._closing and not self._retired_pip_windows)
        self.layout_combo.setEnabled(enabled)
        self.separate_checkbox.setEnabled(enabled)
        self.mic_checkbox.setEnabled(enabled)
        self.mic_combo.setEnabled(enabled)
        self.fps_spin.setEnabled(enabled)
        self.region_btn.setEnabled(enabled)
        self.clear_region_btn.setEnabled(enabled)


def run_app(backend=None):
    """Create the application (used by the console script and __main__)."""
    if backend is None:
        from pyrecorder.platforms import backend_for
        backend = backend_for()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    window = RecorderWindow(backend)
    window.show()
    return app, window
