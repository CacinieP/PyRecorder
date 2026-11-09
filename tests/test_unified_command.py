"""Tests for pyrecorder.command: the single ffmpeg command, per platform.

Each test names the production change that would make it fail. Commands are
built with fake pipe fds (they are never opened here).
"""
import pytest

pytest.importorskip("PyQt6", reason="pyrecorder imports PyQt6 at module level")

from pyrecorder.command import (CameraInput, ExtraAudioInput, NativeScreenInput,  # noqa: E402
                                PipeScreenInput, build_command)

FFMPEG = "/usr/bin/ffmpeg"
OUT = "/tmp/out/recording_20260101_120000.mp4"


def mac_screen(mic_on=True):
    mic = "0" if mic_on else "none"
    return NativeScreenInput(
        ["-f", "avfoundation", "-framerate", "30", "-capture_cursor", "1",
         "-capture_mouse_clicks", "1", "-i", f"2:{mic}"],
        audio_stream="0:a" if mic_on else None)


def win_mic():
    return ExtraAudioInput(["-f", "dshow", "-i", 'audio="Microphone (Realtek)"'],
                           stream="1:a")


# --------------------------------------------------------------------------
# macOS: avfoundation screen (mic rides input 0), camera pipe is input 1
# --------------------------------------------------------------------------

def test_mac_full_command_shape():
    cmd, extra = build_command(
        FFMPEG, OUT, 30, screen=mac_screen(), mic=None,
        camera=CameraInput(4, 28.0, (640, 360)),
        pip=(320, 100, 200), layout="pip",
        encoder_main=["-c:v", "h264_videotoolbox", "-b:v", "8M"],
        encoder_camera=["-c:v", "h264_videotoolbox", "-b:v", "2M"])
    assert cmd[:3] == [FFMPEG, "-hide_banner", "-loglevel"]
    # screen input first, camera pipe second, no third input
    inputs = [i for i, a in enumerate(cmd) if a == "-i"]
    assert len(inputs) == 2
    assert cmd[inputs[0] + 1] == "2:0"          # screen 2 + mic 0
    assert cmd[inputs[1] + 1] == "pipe:4"       # camera on fd 4
    assert "-filter_complex" in cmd
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "overlay=100:200" in fc
    assert "scale=320:-2[cam]" in fc
    # audio mapped from the avfoundation input, right after the video map
    map_at = cmd.index("-map")
    assert cmd[map_at + 1] == "[out]"
    audio_at = cmd.index("0:a")
    assert cmd[audio_at - 1:audio_at + 4] == ["-map", "0:a", "-c:a", "aac", "-b:a"]
    assert "h264_videotoolbox" in cmd


def test_mac_region_crop_is_scaled_and_even():
    # fractional scales can produce odd sizes: 721*1.5=1081.5 -> 1080
    cmd, _ = build_command(
        FFMPEG, OUT, 30, screen=mac_screen(),
        region=(100, 50, 721, 401), screen_scale=1.5,
        encoder_main=["-c:v", "h264_videotoolbox", "-b:v", "8M"])
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "crop=1080:600:150:75" in fc


def test_mac_odd_full_screen_gets_even_guard():
    cmd, _ = build_command(
        FFMPEG, OUT, 30, screen=mac_screen(),
        capture_size=(2815, 1763),
        encoder_main=["-c:v", "h264_videotoolbox", "-b:v", "8M"])
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "scale=2814:1762" in fc


def test_mac_even_screen_gets_no_guard_filter():
    cmd, _ = build_command(
        FFMPEG, OUT, 30, screen=mac_screen(),
        capture_size=(2816, 1762),
        encoder_main=["-c:v", "h264_videotoolbox", "-b:v", "8M"])
    assert "-filter_complex" not in cmd


# --------------------------------------------------------------------------
# Windows/Linux: mss screen pipe + extra audio input
# --------------------------------------------------------------------------

def test_windows_inputs_order_screen_audio_camera():
    cmd, _ = build_command(
        FFMPEG, OUT, 30,
        screen=PipeScreenInput(3, (1920, 1080)), mic=win_mic(),
        camera=CameraInput(5, 30.0, (640, 360)), pip=(240, 10, 10),
        encoder_main=["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"])
    inputs = [i for i, a in enumerate(cmd) if a == "-i"]
    assert cmd[inputs[0] + 1] == "pipe:3"       # screen first
    assert cmd[inputs[1] + 1] == 'audio="Microphone (Realtek)"'
    assert cmd[inputs[2] + 1] == "pipe:5"       # camera after audio
    assert "bgra" in cmd and "1920x1080" in cmd
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "crop=" not in fc                    # pipe screens are never cropped here
    maps = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-map"]
    assert "[out]" in maps and "1:a" in maps


def test_linux_pulse_audio_without_camera():
    cmd, extra = build_command(
        FFMPEG, OUT, 24,
        screen=PipeScreenInput(3, (1920, 1080)),
        mic=ExtraAudioInput(["-f", "pulse", "-i", "alsa_input.pci-0000_00_1f.3"],
                            stream="1:a"),
        encoder_main=["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"])
    assert "-filter_complex" not in cmd         # nothing to filter
    assert extra == []
    assert "alsa_input.pci-0000_00_1f.3" in cmd
    # with no filter graph the label syntax would be invalid; expect 0:v
    assert "-map" in cmd and "0:v" in cmd and "[0:v]" not in cmd


def test_no_audio_when_mic_missing_or_degraded():
    cmd, _ = build_command(
        FFMPEG, OUT, 30, screen=PipeScreenInput(3, (1920, 1080)), mic=None,
        encoder_main=["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"])
    assert "-c:a" not in cmd and "aac" not in cmd


# --------------------------------------------------------------------------
# Layouts, separate files, preview
# --------------------------------------------------------------------------

def test_speaker_layouts_stack_screen_and_camera():
    for layout, expected in (
            ("speaker-right", "[scrS][spk]hstack"),
            ("speaker-left", "[spk][scrS]hstack")):
        cmd, _ = build_command(
            FFMPEG, OUT, 30, screen=mac_screen(), camera=CameraInput(4, 30.0, (1920, 1080)),
            pip=(320, 0, 0), layout=layout,
            encoder_main=["-c:v", "h264_videotoolbox", "-b:v", "8M"])
        fc = cmd[cmd.index("-filter_complex") + 1]
        assert "scale=-2:1080[spk]" in fc and expected in fc


def test_separate_files_use_their_own_encoders():
    cmd, extra = build_command(
        FFMPEG, OUT, 30, screen=mac_screen(),
        camera=CameraInput(4, 30.0, (1920, 1080)), pip=(320, 0, 0),
        separate=True,
        encoder_main=["-c:v", "h264_videotoolbox", "-b:v", "8M"],
        encoder_camera=["-c:v", "h264_videotoolbox", "-b:v", "2M"])
    assert extra == [OUT.replace(".mp4", "_screen.mp4"),
                     OUT.replace(".mp4", "_camera.mp4")]
    # camera-only output carries the 2M args, the composite the 8M ones
    assert cmd.count("8M") >= 2 and "2M" in cmd
    camera_at = [i for i, a in enumerate(cmd) if a.endswith("_camera.mp4")][0]
    assert "2M" in cmd[:camera_at]              # its encoder args precede it


def test_preview_stream_is_last_output():
    cmd, _ = build_command(
        FFMPEG, OUT, 30, screen=mac_screen(), preview=True,
        encoder_main=["-c:v", "h264_videotoolbox", "-b:v", "8M"])
    assert cmd[-9:] == ["-map", "[prev]", "-f", "rawvideo", "-pix_fmt",
                        "rgb24", "-r", "30", "pipe:1"]
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "scale=480:270" in fc


def test_secondary_paths_survive_dots_in_folder_names():
    from pyrecorder.command import _secondary_path
    assert _secondary_path("/tmp/a.mp4.folder/rec.mp4", "_screen.mp4") == \
        "/tmp/a.mp4.folder/rec_screen.mp4"


def test_every_output_carries_explicit_framerate():
    cmd, _ = build_command(
        FFMPEG, OUT, 25, screen=mac_screen(), camera=CameraInput(4, 25.0, (640, 360)),
        pip=(320, 0, 0), separate=True, preview=True,
        encoder_main=["-c:v", "h264_videotoolbox", "-b:v", "8M"])
    outputs = sum(1 for a in cmd if str(a).endswith(".mp4")) + 1  # + pipe:1
    assert cmd.count("-r") == outputs
