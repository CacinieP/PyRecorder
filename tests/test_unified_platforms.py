"""Tests for the platform backends: device-list parsing and input args.

ffmpeg outputs are real captures (fixtures), because the parsers exist
precisely to survive ffmpeg's format quirks.
"""
import subprocess

import pytest

pytest.importorskip("PyQt6", reason="backends import PyQt6 transitively")

from pyrecorder.platforms.linux import LinuxBackend, parse_pactl_sources  # noqa: E402
from pyrecorder.platforms.macos import MacosBackend, parse_av_device_lists  # noqa: E402
from pyrecorder.platforms.windows import (WindowsBackend,  # noqa: E402
                                           parse_dshow_device_lists)

# --------------------------------------------------------------------------
# macOS avfoundation (real ffmpeg 8.1.2 output, captured 2026-09-18)
# --------------------------------------------------------------------------

AVFOUNDATION_LIST = """\
[AVFoundation indev @ 0x9b9014140] AVFoundation video devices:
[AVFoundation indev @ 0x9b9014140] [0] MacBook Neo\u76f8\u673a
[AVFoundation indev @ 0x9b9014140] [1] Capture screen 0
[AVFoundation indev @ 0x9b9014140] AVFoundation audio devices:
[AVFoundation indev @ 0x9b9014140] [0] MacBook Neo\u9ea6\u514b\u98ce
[in#0 @ 0x9b9014000] Error opening input: Input/output error
Error opening input file .
"""


def test_mac_parse_separates_screens_cameras_mics():
    screens, cameras, mics = parse_av_device_lists(AVFOUNDATION_LIST)
    assert screens == [(1, "Capture screen 0")]
    assert cameras == [(0, "MacBook Neo相机")]
    assert mics == [(0, "MacBook Neo麦克风")]


def test_mac_screen_index_and_audio_devices(monkeypatch):
    backend = MacosBackend()
    monkeypatch.setattr(backend, "list_all_av_devices",
                        lambda: parse_av_device_lists(AVFOUNDATION_LIST))
    assert backend.refresh_screen_index() == 1
    devices = backend.list_audio_inputs()
    assert devices[0].id == "0" and "麦克风" in devices[0].label


def test_mac_native_screen_args_embed_mic_or_none(monkeypatch):
    backend = MacosBackend()
    monkeypatch.setattr(backend, "refresh_screen_index", lambda: 2)
    monkeypatch.setattr(backend, "_screen_index", 2, raising=False)
    args = backend.native_screen_args(30, "5")
    assert args[args.index("-i") + 1] == "2:5"
    args = backend.native_screen_args(30, None)
    assert args[args.index("-i") + 1] == "2:none"
    assert "-capture_cursor" in args


def test_mac_audio_rides_screen_input(monkeypatch):
    backend = MacosBackend()
    calls = []

    def fake_run(args, timeout=10):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    from pyrecorder import ffmpeg_exe
    monkeypatch.setattr(ffmpeg_exe, "run_tool", fake_run)
    assert backend.audio_input_args("0") is None
    assert backend.audio_stream_label() == "0:a"
    assert backend.probe_audio("0") is True
    assert any(":0" in str(a) for a in calls[0])


def test_mac_probe_rejects_bad_index(monkeypatch):
    backend = MacosBackend()
    monkeypatch.setattr("pyrecorder.ffmpeg_exe.run_tool", lambda *a, **k: None)
    assert backend.probe_audio(None) is False
    assert backend.probe_audio("notanumber") is False


# --------------------------------------------------------------------------
# Windows dshow
# --------------------------------------------------------------------------

DSHOW_LIST = """\
[dshow @ 0x2]  "Integrated Webcam" (video)
[dshow @ 0x2]    Alternative name "@device_pnp_\\\\?\\usb#vid_1bcf&pid_28c4#..."
[dshow @ 0x2]  "Microphone (Realtek(R) Audio)" (audio)
[dshow @ 0x2]    Alternative name "@device_cm_{33D9A762-90C8-11D0-BD43-00A0C911CE86}\\wave_{...}"
[dshow @ 0x2]  "Microphone Array (Intel Smart Sound)" (audio)
"""


def test_dshow_parse_separates_video_and_audio():
    cameras, mics = parse_dshow_device_lists(DSHOW_LIST)
    assert cameras == ["Integrated Webcam"]
    assert mics == ["Microphone (Realtek(R) Audio)",
                    "Microphone Array (Intel Smart Sound)"]


def test_windows_audio_input_args_quote_the_name():
    backend = WindowsBackend()
    args = backend.audio_input_args("Microphone (Realtek(R) Audio)")
    assert args[:3] == ["-f", "dshow", "-i"]
    assert args[3] == 'audio="Microphone (Realtek(R) Audio)"'
    assert backend.audio_stream_label() == "1:a"


def test_windows_probe_uses_same_quoting(monkeypatch):
    backend = WindowsBackend()
    seen = []

    def fake_run(args, timeout=10):
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("pyrecorder.ffmpeg_exe.run_tool", fake_run)
    assert backend.probe_audio("Mic X") is True
    assert 'audio="Mic X"' in seen[0]


# --------------------------------------------------------------------------
# Linux pulse
# --------------------------------------------------------------------------

PACTL_LIST = (
    "alsa_input.pci-0000_00_1f.3.analog-stereo\tBuilt-in Audio Analog Stereo\tmodule-alsa-card.c\t\n"
    "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor\tMonitor of Built-in Audio Analog Stereo\tmodule-alsa-card.c\t\n"
)


def test_pulse_parse_keeps_monitors_for_system_audio():
    devices = parse_pactl_sources(PACTL_LIST)
    assert devices[0].id == "alsa_input.pci-0000_00_1f.3.analog-stereo"
    assert devices[1].id.endswith(".monitor")


def test_linux_falls_back_to_default_without_pactl(monkeypatch):
    backend = LinuxBackend()
    monkeypatch.setattr("shutil.which", lambda name: None)
    devices = backend.list_audio_inputs()
    assert [d.id for d in devices] == ["default"]


def test_linux_audio_input_args():
    backend = LinuxBackend()
    assert backend.audio_input_args("default") == ["-f", "pulse", "-i", "default"]


def test_linux_wayland_without_x11_is_rejected(monkeypatch):
    backend = LinuxBackend()
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.delenv("DISPLAY", raising=False)
    ok, hint = backend.check_screen()
    assert not ok and "Wayland" in hint


def test_linux_x11_accepted_when_mss_reports_monitors(monkeypatch):
    backend = LinuxBackend()
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")

    class FakeMss:
        monitors = [{"left": 0, "top": 0, "width": 1920, "height": 1080}]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import types
    fake_mss_mod = types.ModuleType("mss")
    fake_mss_mod.mss = lambda: FakeMss()
    monkeypatch.setitem(__import__("sys").modules, "mss", fake_mss_mod)
    ok, hint = backend.check_screen()
    assert ok


# --------------------------------------------------------------------------
# backend selection
# --------------------------------------------------------------------------

def test_backend_for_each_platform():
    from pyrecorder.platforms import backend_for
    assert backend_for("darwin").id == "darwin"
    assert backend_for("win32").id == "win32"
    assert backend_for("linux").id == "linux"
    assert backend_for("weird").id == "linux"    # POSIX default


def test_encoder_defaults_differ_by_platform():
    from pyrecorder.platforms import backend_for
    mac = backend_for("darwin").encoder_args("main")
    win = backend_for("win32").encoder_args("main")
    assert "h264_videotoolbox" in mac and "libx264" in win
