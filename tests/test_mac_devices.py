"""Audio device handling: listing every device, probing that it can actually be
opened, and letting the user pick one (BlackHole for system audio).

Before this, the recorder hard-coded the first audio device in the avfoundation
list and only checked that it *existed* — with Microphone permission denied,
ffmpeg failed to open it and the whole recording died instead of degrading to
video-only.
"""
import stat
import sys

import pytest

pytest.importorskip("PyQt6", reason="screen_recorder_mac imports PyQt6 at module level")

import screen_recorder_mac as mac  # noqa: E402

REAL_FFMPEG = mac.shutil.which("ffmpeg")

FFMPEG_8_1_2 = """\
[AVFoundation indev @ 0x9b9014140] AVFoundation video devices:
[AVFoundation indev @ 0x9b9014140] [0] MacBook Neo\u76f8\u673a
[AVFoundation indev @ 0x9b9014140] [1] Capture screen 0
[AVFoundation indev @ 0x9b9014140] AVFoundation audio devices:
[AVFoundation indev @ 0x9b9014140] [0] MacBook Neo\u9ea6\u514b\u98ce
"""

TWO_SCREENS_AND_BLACKHOLE = """\
[AVFoundation indev @ 0x1] AVFoundation video devices:
[AVFoundation indev @ 0x1] [0] FaceTime HD Camera
[AVFoundation indev @ 0x1] [1] Capture screen 0
[AVFoundation indev @ 0x1] [2] Capture screen 1
[AVFoundation indev @ 0x1] AVFoundation audio devices:
[AVFoundation indev @ 0x1] [0] BlackHole 2ch
[AVFoundation indev @ 0x1] [1] Built-in Microphone
[AVFoundation indev @ 0x1] [2] Zoom Audio Device
"""


# --------------------------------------------------------------------------
# listing every device (not just the first of each class)
# --------------------------------------------------------------------------

def test_lists_every_audio_device_in_ffmpeg_order():
    _, _, mics = mac.parse_av_device_lists(TWO_SCREENS_AND_BLACKHOLE)
    assert mics == [(0, "BlackHole 2ch"),
                    (1, "Built-in Microphone"),
                    (2, "Zoom Audio Device")]


def test_lists_screens_and_cameras_separately():
    screens, cameras, _ = mac.parse_av_device_lists(TWO_SCREENS_AND_BLACKHOLE)
    assert screens == [(1, "Capture screen 0"), (2, "Capture screen 1")]
    assert cameras == [(0, "FaceTime HD Camera")]


def test_lists_are_empty_for_garbage_input():
    assert mac.parse_av_device_lists("") == ([], [], [])
    assert mac.parse_av_device_lists("no devices here") == ([], [], [])


def test_first_of_each_class_still_drives_parse_av_devices():
    # parse_av_devices() keeps its old contract: the first of each class.
    assert mac.parse_av_devices(TWO_SCREENS_AND_BLACKHOLE) == (1, 0, 0)
    assert mac.parse_av_devices("") == (None, None, None)


# --------------------------------------------------------------------------
# probing that the device can actually be opened
# --------------------------------------------------------------------------

def _stub_ffmpeg(tmp_path, name, script):
    path = tmp_path / name
    path.write_text(script)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


def test_probe_needs_a_device_index():
    assert mac.probe_audio_device(None) is False


def test_probe_reports_false_when_ffmpeg_cannot_run():
    assert mac.probe_audio_device(0, ffmpeg="/nonexistent/ffmpeg") is False


def test_probe_follows_the_ffmpeg_exit_code(tmp_path):
    ok = _stub_ffmpeg(tmp_path, "ffmpeg-ok", "#!/bin/sh\nexit 0\n")
    bad = _stub_ffmpeg(tmp_path, "ffmpeg-bad", "#!/bin/sh\nexit 251\n")
    assert mac.probe_audio_device(0, ffmpeg=ok) is True
    assert mac.probe_audio_device(0, ffmpeg=bad) is False


def test_probe_opens_exactly_the_selected_audio_device(tmp_path):
    log = tmp_path / "args.txt"
    spy = _stub_ffmpeg(tmp_path, "ffmpeg-spy",
                       f'#!/bin/sh\necho "$@" > "{log}"\nexit 0\n')
    assert mac.probe_audio_device(3, ffmpeg=spy) is True
    args = log.read_text().split()
    assert "avfoundation" in args
    assert ":3" in args, f"must request audio device 3 only, got {args}"
    assert "-i" in args


@pytest.mark.hardware
@pytest.mark.skipif(sys.platform != "darwin" or not REAL_FFMPEG,
                    reason="needs real avfoundation devices")
def test_probe_rejects_an_invalid_device_index_on_a_real_machine():
    # Measured 2026-09-18: ffmpeg exits 251 with "Invalid audio device index".
    assert mac.probe_audio_device(99) is False


# --------------------------------------------------------------------------
# the UI chooser
# --------------------------------------------------------------------------

def test_mic_combo_lists_devices_and_exposes_the_selected_index(recorder):
    mac.ScreenRecorderMac._populate_mic_combo(
        recorder, [(0, "BlackHole 2ch"), (1, "Built-in Microphone")])

    assert recorder.mic_combo.count() == 2
    assert recorder.mic_combo.itemData(0) == 0
    assert "BlackHole 2ch" in recorder.mic_combo.itemText(0)
    assert recorder.selected_mic_index() == 0

    recorder.mic_combo.setCurrentIndex(1)
    assert recorder.selected_mic_index() == 1


def test_mic_combo_without_devices_yields_no_selection(recorder):
    mac.ScreenRecorderMac._populate_mic_combo(recorder, [])
    assert recorder.mic_combo.count() == 0
    assert recorder.selected_mic_index() is None


def test_mic_combo_keeps_the_previous_choice_when_devices_are_relisted(recorder):
    devices = [(0, "BlackHole 2ch"), (1, "Built-in Microphone")]
    mac.ScreenRecorderMac._populate_mic_combo(recorder, devices)
    recorder.mic_combo.setCurrentIndex(1)

    mac.ScreenRecorderMac._populate_mic_combo(recorder, devices)   # e.g. Refresh

    assert recorder.selected_mic_index() == 1


def test_mic_combo_is_disabled_while_recording(recorder):
    mac.ScreenRecorderMac._populate_mic_combo(recorder, [(0, "Mic")])
    recorder._set_controls(False)
    assert recorder.mic_combo.isEnabled() is False
    recorder._set_controls(True)
    assert recorder.mic_combo.isEnabled() is True
