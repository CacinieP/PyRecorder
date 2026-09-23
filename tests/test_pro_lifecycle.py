"""Exercise the Windows capture lifecycle without accessing real devices."""
from datetime import datetime
from pathlib import Path
import sys
import types

import numpy as np
import pytest


@pytest.fixture
def capture(monkeypatch, tmp_path):
    import screen_recorder_pro as pro

    class Screen:
        monitors = [None, {"top": 0, "left": 0, "width": 2, "height": 2}]
        closed = False
        grabs = 0
        failure = None

        def grab(self, monitor):
            self.grabs += 1
            if self.failure:
                raise self.failure
            # A red MSS pixel, in BGRA order.
            return np.tile(np.array([0, 0, 255, 255], dtype=np.uint8), (2, 2, 1))

        def close(self):
            self.closed = True

    class Writer:
        opened = True
        released = False
        release_failure = None
        path = None

        def __init__(self):
            self.frames = []

        def open(self, path, *args):
            self.path = Path(path)
            if self.opened:
                self.path.write_bytes(b"video header")
            return self

        def isOpened(self):
            return self.opened

        def write(self, frame):
            self.frames.append(frame.copy())
            with self.path.open("ab") as file:
                file.write(b"frame")

        def release(self):
            self.released = True
            if self.release_failure:
                raise self.release_failure

    class Camera:
        released = False
        opened = True

        def isOpened(self):
            return self.opened

        def read(self):
            return False, None

        def release(self):
            self.released = True

    class Audio:
        started = False
        stops = 0
        success = True

        def start(self):
            self.started = True
            audio_path.write_bytes(b"wav data")

        def stop(self):
            self.stops += 1
            return self.started and self.success

    screen, writer, camera, audio = Screen(), Writer(), Camera(), Audio()
    output = tmp_path / "recording.mp4"
    audio_path = tmp_path / "recording_audio.wav"
    worker = pro.RecordingThread(str(output), 30, "mp4v", record_audio=True,
                                 audio_path=str(audio_path), webcam_enabled=True)
    errors, finished = [], []
    worker.error.connect(errors.append)
    worker.finished.connect(lambda: finished.append(True))
    monkeypatch.setitem(sys.modules, "mss", types.SimpleNamespace(mss=lambda: screen))
    monkeypatch.setattr(pro.cv2, "VideoWriter", writer.open)
    monkeypatch.setattr(pro.cv2, "VideoCapture", lambda *args: camera)
    monkeypatch.setattr(pro, "AudioRecorder", lambda *args: audio)
    monkeypatch.setattr(pro.cv2, "waitKey", lambda *args: setattr(worker, "is_running", False))
    monkeypatch.setattr(worker, "_emit_preview", lambda *args: None)
    monkeypatch.setattr(pro, "merge_audio_video",
                        lambda video, sound, out: Path(out).write_bytes(b"merged video"))
    return types.SimpleNamespace(
        pro=pro, worker=worker, screen=screen, writer=writer, camera=camera,
        audio=audio, output=output, audio_path=audio_path,
        temp=tmp_path / "recording_temp.mp4", merged=tmp_path / "recording_merged.mp4",
        errors=errors, finished=finished,
    )


def test_capture_preserves_red_channel_and_releases_devices(capture):
    c = capture
    c.worker.run()

    assert c.writer.frames[0][0, 0].tolist() == [0, 0, 255]
    assert c.output.read_bytes() == b"merged video"
    assert c.worker.output_saved
    assert c.screen.closed and c.writer.released and c.camera.released
    assert c.audio.stops == 1
    assert not c.temp.exists() and not c.audio_path.exists() and not c.merged.exists()
    assert c.errors == [] and c.finished == [True]


def test_real_qthread_emits_finished_once(capture, qapp):
    c = capture
    c.worker.start()
    assert c.worker.wait(5000)
    qapp.processEvents()
    assert c.worker.output_saved and c.finished == [True]


def test_video_only_recording_does_not_open_microphone(capture):
    c = capture
    c.worker.record_audio = False
    c.worker.run()

    assert c.worker.output_saved and c.output.read_bytes() == b"video headerframe"
    assert not c.audio.started and not c.temp.exists()
    assert c.errors == []


def test_unavailable_writer_fails_before_opening_camera_or_microphone(capture):
    c = capture
    c.writer.opened = False
    c.worker.run()

    assert "Cannot open video writer" in c.errors[0]
    assert c.screen.closed and c.writer.released
    assert c.screen.grabs == 0 and not c.audio.started
    assert not c.worker.output_saved and not c.output.exists()
    assert c.finished == [True]


def test_invalid_region_closes_screen_before_any_recording(capture):
    c = capture
    c.worker.region = (0, 0, 0, 2)
    c.worker.run()

    assert "Invalid capture area" in c.errors[0]
    assert c.screen.closed and not c.audio.started and c.writer.path is None
    assert not c.worker.output_saved and c.finished == [True]


def test_capture_failure_releases_all_devices_and_preserves_intermediates(capture):
    c = capture
    c.screen.failure = RuntimeError("screen disconnected")
    c.worker.run()

    assert "screen disconnected" in c.errors[0]
    assert c.screen.closed and c.writer.released and c.camera.released
    assert c.audio.stops == 1
    assert c.temp.exists() and c.audio_path.exists()
    assert not c.worker.output_saved and not c.output.exists()
    assert c.finished == [True]


def test_one_cleanup_failure_does_not_leak_other_devices(capture):
    c = capture
    c.writer.release_failure = RuntimeError("writer close failed")
    c.worker.run()

    assert "writer close failed" in c.errors[0]
    assert c.screen.closed and c.camera.released and c.audio.stops == 1
    assert not c.worker.output_saved and not c.output.exists()


def test_merge_failure_keeps_sources_and_does_not_publish_partial_output(capture, monkeypatch):
    c = capture

    def failed_merge(video, audio, output):
        Path(output).write_bytes(b"partial mp4")
        raise RuntimeError("encoder failed")

    monkeypatch.setattr(c.pro, "merge_audio_video", failed_merge)
    c.worker.run()

    assert "encoder failed" in c.errors[0]
    assert c.merged.read_bytes() == b"partial mp4"
    assert c.temp.exists() and c.audio_path.exists()
    assert not c.worker.output_saved and not c.output.exists()
    assert c.finished == [True]


def test_missing_microphone_audio_does_not_silently_save_video(capture):
    c = capture
    c.audio.success = False
    c.worker.run()

    assert "Microphone audio was not recorded" in c.errors[0]
    assert c.temp.exists() and c.audio_path.exists()
    assert c.audio.stops == 1 and c.screen.closed and c.writer.released
    assert not c.worker.output_saved and not c.output.exists()


def test_stop_before_first_frame_is_not_reported_as_saved(capture):
    c = capture
    c.worker.is_running = False
    c.worker.run()

    assert "before any video frames" in c.errors[0]
    assert c.screen.closed and c.writer.released and c.camera.released
    assert c.audio.stops == 1
    assert not c.worker.output_saved and not c.output.exists()


@pytest.mark.parametrize("filename", ["output", "temp", "audio_path", "merged"])
def test_existing_recording_or_recovery_file_is_not_overwritten(capture, filename):
    c = capture
    path = getattr(c, filename)
    path.write_bytes(b"previous recording")
    c.worker.run()

    assert "already exists" in c.errors[0]
    assert path.read_bytes() == b"previous recording"
    assert not c.audio.started and c.screen.grabs == 0
    assert not c.worker.output_saved


def test_unopened_webcam_is_released(capture):
    c = capture
    c.camera.opened = False
    c.worker.run()
    assert c.camera.released and c.worker.output_saved


def test_invalid_audio_during_merge_closes_video_reader(monkeypatch):
    import screen_recorder_pro as pro

    closed = []
    video = types.SimpleNamespace(close=lambda: closed.append(True))

    def unreadable_audio(path):
        raise ValueError("invalid wav")

    monkeypatch.setitem(sys.modules, "moviepy", types.SimpleNamespace(
        VideoFileClip=lambda path: video, AudioFileClip=unreadable_audio))
    with pytest.raises(ValueError, match="invalid wav"):
        pro.merge_audio_video("video.mp4", "audio.wav", "output.mp4")
    assert closed == [True]


def test_failure_does_not_show_saved_dialog(monkeypatch, qapp):
    import screen_recorder_pro as pro

    monkeypatch.setattr(pro, "get_visible_windows", lambda: [])
    saved_dialogs = []
    monkeypatch.setattr(pro.QMessageBox, "information", lambda *args: saved_dialogs.append(args))
    window = pro.ScreenRecorderPro()
    window.recording_thread = types.SimpleNamespace(output_saved=False)
    window.start_time = datetime.now()
    window.recording_finished()

    assert saved_dialogs == []
    assert "failed" in window.status_label.text().lower()
    assert window.record_btn.isEnabled() and window.fps_spinbox.isEnabled()
    assert window.start_time is None
    window.close()
