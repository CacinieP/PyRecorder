"""Tests for screen_recorder_pro.py (Windows-only at runtime, but the module and
its recording helpers must be importable/testable anywhere).

Verified against moviepy 2.1.2 (2026-09-18): `set_audio`/`subclip`/`verbose=`
no longer exist, so the merge has to use `with_audio`/`subclipped`.
"""
import importlib
import os
import shutil
import subprocess
import sys
import types
import wave

import pytest

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _import_pro():
    import screen_recorder_pro
    return importlib.reload(screen_recorder_pro)


class _FakeStream:
    def __init__(self, callback):
        self.callback = callback
        self.started = self.stopped = self.closed = False

    def start_stream(self):
        self.started = True

    def stop_stream(self):
        self.stopped = True

    def close(self):
        self.closed = True


class _FakePyAudio:
    def __init__(self):
        self.terminated = False
        self.stream = None

    def get_sample_size(self, fmt):
        return 2

    def open(self, **kw):
        self.stream = _FakeStream(kw.get("stream_callback"))
        return self.stream

    def terminate(self):
        self.terminated = True


def _fake_pyaudio():
    mod = types.ModuleType("pyaudio")
    mod.paInt16 = 8
    mod.paContinue = 0
    mod.PyAudio = _FakePyAudio
    return mod


def test_module_is_importable_off_windows():
    # Fails today: `ctypes.windll.user32` runs at import time, and pyaudio/mss
    # are imported eagerly, so nothing in this file can be tested on macOS/Linux.
    _import_pro()


def test_audio_recorder_streams_to_disk_instead_of_ram(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "pyaudio", _fake_pyaudio())
    pro = _import_pro()
    path = str(tmp_path / "audio.wav")
    rec = pro.AudioRecorder(path, sample_rate=8000, channels=1, chunk=2)
    rec.start()

    chunk = b"\x01\x02\x03\x04"          # 2 frames, 1 channel, 16 bit
    mid = None
    for i in range(10):
        rec._callback(chunk, 2, None, 0)
        if i == 4:
            mid = os.path.getsize(path)

    assert mid is not None and mid > 44, "frames must reach the disk while recording"
    assert not getattr(rec, "frames", None), "audio must not be buffered in RAM"
    assert rec.stop() is True

    with wave.open(path, "rb") as w:
        assert w.getnframes() == 20
        assert w.getframerate() == 8000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2


def test_audio_recorder_stop_returns_false_when_nothing_was_recorded(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "pyaudio", _fake_pyaudio())
    pro = _import_pro()
    rec = pro.AudioRecorder(str(tmp_path / "empty.wav"))
    rec.start()
    assert rec.stop() is False


@pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="needs ffmpeg/ffprobe to build fixtures")
def test_merge_audio_video_produces_a_playable_file_with_audio(tmp_path):
    pro = _import_pro()
    video, audio, out = (tmp_path / n for n in ("v.mp4", "a.wav", "o.mp4"))
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc2=size=320x240:rate=30:duration=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=1",
                    "-ar", "44100", "-ac", "2", str(audio)], check=True)

    pro.merge_audio_video(str(video), str(audio), str(out))

    assert out.stat().st_size > 0
    probe = subprocess.run([FFPROBE, "-v", "error",
                            "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                            str(out)], capture_output=True, text=True)
    assert "video" in probe.stdout and "audio" in probe.stdout


@pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="needs ffmpeg/ffprobe to build fixtures")
def test_merge_trims_audio_that_is_longer_than_the_video(tmp_path):
    # This is the code path that calls subclip()/subclipped().
    pro = _import_pro()
    video, audio, out = (tmp_path / n for n in ("v.mp4", "a.wav", "o.mp4"))
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc2=size=320x240:rate=30:duration=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=3",
                    "-ar", "44100", "-ac", "2", str(audio)], check=True)

    pro.merge_audio_video(str(video), str(audio), str(out))

    dur = subprocess.run([FFPROBE, "-v", "error",
                          "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(out)], capture_output=True, text=True).stdout.strip()
    assert 0.8 <= float(dur) <= 1.5, f"expected the 1s video length, got {dur}"
