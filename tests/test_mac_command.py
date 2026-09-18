"""Tests for the pure, platform-independent parts of screen_recorder_mac.py:
device-list parsing, ffmpeg command assembly, preview stream geometry, and
camera frame-rate measurement.

Each test names the production change that would make it fail.
"""
import itertools
import shutil
import subprocess

import pytest

pytest.importorskip("PyQt6", reason="screen_recorder_mac imports PyQt6 at module level")

import screen_recorder_mac as mac  # noqa: E402


# --------------------------------------------------------------------------
# avfoundation device listing (real ffmpeg 8.1.2 output, captured 2026-09-18)
# --------------------------------------------------------------------------

FFMPEG_8_1_2 = """\
[AVFoundation indev @ 0x9b9014140] AVFoundation video devices:
[AVFoundation indev @ 0x9b9014140] [0] MacBook Neo\u76f8\u673a
[AVFoundation indev @ 0x9b9014140] [1] Capture screen 0
[AVFoundation indev @ 0x9b9014140] AVFoundation audio devices:
[AVFoundation indev @ 0x9b9014140] [0] MacBook Neo\u9ea6\u514b\u98ce
[in#0 @ 0x9b9014000] Error opening input: Input/output error
Error opening input file .
"""

NO_CAMERA = """\
[AVFoundation indev @ 0x1] AVFoundation video devices:
[AVFoundation indev @ 0x1] [0] Capture screen 0
[AVFoundation indev @ 0x1] AVFoundation audio devices:
[AVFoundation indev @ 0x1] [0] Built-in Microphone
"""

TWO_SCREENS_AND_BLACKHOLE = """\
[AVFoundation indev @ 0x1] AVFoundation video devices:
[AVFoundation indev @ 0x1] [0] FaceTime HD Camera
[AVFoundation indev @ 0x1] [1] Capture screen 0
[AVFoundation indev @ 0x1] [2] Capture screen 1
[AVFoundation indev @ 0x1] AVFoundation audio devices:
[AVFoundation indev @ 0x1] [0] BlackHole 2ch
[AVFoundation indev @ 0x1] [1] Built-in Microphone
"""


def test_parses_screen_camera_and_mic_indices_from_real_ffmpeg_output():
    assert mac.parse_av_devices(FFMPEG_8_1_2) == (1, 0, 0)


def test_reports_missing_camera_as_none():
    assert mac.parse_av_devices(NO_CAMERA) == (0, None, 0)


def test_picks_the_first_screen_and_first_audio_device():
    # Documents current behaviour: no in-app device chooser, so index 0 of each
    # list wins (this is why BlackHole cannot be selected from the UI).
    assert mac.parse_av_devices(TWO_SCREENS_AND_BLACKHOLE) == (1, 0, 0)


def test_garbage_input_yields_no_devices():
    assert mac.parse_av_devices("") == (None, None, None)
    assert mac.parse_av_devices("not ffmpeg output at all") == (None, None, None)


# --------------------------------------------------------------------------
# ffmpeg command assembly
# --------------------------------------------------------------------------

def _build(**kw):
    args = dict(output_path="/tmp/out/rec.mp4", fps=30, screen_idx=1, mic_idx=0,
                camera_idx=0, mic_enabled=True, camera_enabled=True,
                pip=(320, 100, 100), region=None, screen_scale=2.0,
                layout="pip", separate=False, preview=True, camera_pipe_fd=7)
    args.update(kw)
    return mac.build_command(**args)


def _outputs(cmd):
    """Indices of every output target (files written + the preview pipe)."""
    return [i for i, tok in enumerate(cmd)
            if tok == "pipe:1" or (isinstance(tok, str) and tok.endswith(".mp4"))]


def test_every_output_pins_its_framerate():
    # Without this the rawvideo preview inherits avfoundation's bogus
    # "1000k tbr" and ffmpeg duplicates frames without bound (0-byte files).
    cmd, _ = _build(separate=True, camera_fps=27.5)
    outs = _outputs(cmd)
    assert len(outs) == 4, outs          # main, _screen, _camera, preview pipe
    for i in outs:
        assert cmd[i - 2:i] == ["-r", "30"], f"output {cmd[i]} not rate-pinned"


def test_single_output_command_also_pins_framerate():
    cmd, _ = _build(separate=False, preview=False)
    outs = _outputs(cmd)
    assert len(outs) == 1
    assert cmd[outs[0] - 2:outs[0]] == ["-r", "30"]


def test_preview_stream_is_letterboxed_to_a_fixed_size():
    # A fixed preview size means the reader can never guess the geometry wrong
    # (it did for Speaker layouts: ffmpeg emitted 480x142, code read 480x300).
    cmd, _ = _build(layout="speaker-right")
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "scale=480:270:force_original_aspect_ratio=decrease" in graph
    assert "pad=480:270:(ow-iw)/2:(oh-ih)/2" in graph


def test_preview_dims_does_not_depend_on_geometry_or_layout():
    from PyQt6.QtCore import QRect
    geo = QRect(0, 0, 1408, 881)
    assert mac.preview_dims(None, geo, 2.0) == (480, 270)
    assert mac.preview_dims((0, 0, 640, 480), geo, 2.0) == (480, 270)
    assert mac.preview_dims(None, geo, 2.0, layout="speaker-left") == (480, 270)
    assert mac.preview_dims(None, geo, 1.0, layout="speaker-right") == (480, 270)


def test_camera_input_declares_the_measured_rate_not_the_gui_fps():
    cmd, _ = _build(camera_fps=27.5)
    j = cmd.index("pipe:7")
    assert cmd[j - 1] == "-i"
    assert cmd[j - 3:j - 1] == ["-framerate", "27.5"]


def test_camera_input_falls_back_to_gui_fps_when_not_measured():
    cmd, _ = _build(camera_fps=None)
    j = cmd.index("pipe:7")
    assert cmd[j - 3:j - 1] == ["-framerate", "30"]


def test_separate_files_keep_their_own_bitrates():
    cmd, extra = _build(separate=True)
    assert [e.rsplit("/", 1)[-1] for e in extra] == ["rec_screen.mp4", "rec_camera.mp4"]
    assert cmd.count("-b:v") == 3
    assert "8M" in cmd and "2M" in cmd


def test_region_crop_is_scaled_to_device_pixels():
    cmd, _ = _build(region=(60, 60, 640, 480), screen_scale=2.0, separate=False)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "crop=1280:960:120:120" in graph


def test_separate_screen_file_matches_the_cropped_region():
    # The screen-only file must contain what was actually recorded. Splitting
    # before the crop wrote the FULL screen into _screen.mp4 (verified: main was
    # 1280x960 while _screen.mp4 came out 2816x1762).
    cmd, _ = _build(region=(60, 60, 640, 480), screen_scale=2.0, separate=True)
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert graph.index("crop=1280:960:120:120") < graph.index("split=2[scrA][scrB]")


def test_microphone_disabled_maps_no_audio_stream():
    cmd, _ = _build(mic_enabled=False)
    assert "0:a" not in cmd
    assert "-c:a" not in cmd
    assert cmd[cmd.index("-i") + 1] == "1:none"


def test_speaker_layouts_stack_in_the_requested_order():
    right = _build(layout="speaker-right")[0]
    left = _build(layout="speaker-left")[0]
    g_right = right[right.index("-filter_complex") + 1]
    g_left = left[left.index("-filter_complex") + 1]
    assert "[scrS][spk]hstack=inputs=2" in g_right
    assert "[spk][scrS]hstack=inputs=2" in g_left


# --------------------------------------------------------------------------
# camera rate measurement
# --------------------------------------------------------------------------

def _clock(step=0.1, start=0.0):
    counter = itertools.count(start, step)
    return lambda: next(counter)


def test_estimate_fps_counts_frames_after_a_warm_up_frame():
    assert mac.estimate_fps(lambda: True, window=1.0, clock=_clock(0.1)) == pytest.approx(10.0)


def test_estimate_fps_returns_none_when_the_device_never_delivers():
    assert mac.estimate_fps(lambda: False, window=1.0, clock=_clock(0.1)) is None


def test_estimate_fps_returns_none_when_too_few_frames_arrive():
    frames = iter([True, True] + [False] * 200)
    assert mac.estimate_fps(lambda: next(frames), window=1.0, clock=_clock(0.1)) is None


def test_pick_camera_fps_clamps_into_a_usable_range():
    assert mac.pick_camera_fps(27.4, 30) == pytest.approx(27.4)
    assert mac.pick_camera_fps(200.0, 30) == 60.0
    assert mac.pick_camera_fps(0.5, 30) == 5.0


def test_pick_camera_fps_falls_back_when_unmeasurable():
    assert mac.pick_camera_fps(None, 30) == 30.0
    assert mac.pick_camera_fps(0, 45) == 45.0


# --------------------------------------------------------------------------
# success criteria used by _finalize()
# --------------------------------------------------------------------------

FFMPEG = shutil.which("ffmpeg")


def _real_mp4(path, seconds="0.3"):
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", f"testsrc2=size=320x240:rate=30:duration={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    assert path.stat().st_size > 0
    return path


@pytest.mark.skipif(FFMPEG is None, reason="needs ffmpeg to build a real mp4")
def test_recording_succeeded_accepts_a_finalized_file(tmp_path):
    f = _real_mp4(tmp_path / "rec.mp4")
    assert mac.recording_succeeded(255, str(f)) is True      # SIGTERM exit
    assert mac.recording_succeeded(0, str(f)) is True        # graceful 'q' exit


@pytest.mark.skipif(FFMPEG is None, reason="needs ffmpeg to build a real mp4")
def test_recording_succeeded_rejects_a_file_whose_moov_atom_was_never_written(tmp_path):
    # This is exactly what a second SIGTERM during ffmpeg's flush produces:
    # megabytes of mdat, no moov, ffprobe reports no duration, players refuse it.
    good = _real_mp4(tmp_path / "good.mp4")
    broken = tmp_path / "broken.mp4"
    data = good.read_bytes()
    broken.write_bytes(data[: int(len(data) * 0.6)])         # drop the trailer
    assert broken.stat().st_size > 0
    assert mac.recording_succeeded(255, str(broken)) is False


def test_recording_succeeded_rejects_killed_processes_and_missing_files(tmp_path):
    assert mac.recording_succeeded(-9, str(tmp_path / "anything.mp4")) is False
    assert mac.recording_succeeded(-15, str(tmp_path / "anything.mp4")) is False
    assert mac.recording_succeeded(255, str(tmp_path / "missing.mp4")) is False
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    assert mac.recording_succeeded(255, str(empty)) is False
