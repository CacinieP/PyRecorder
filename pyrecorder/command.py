"""Assemble the single ffmpeg command that records screen + camera + mic.

One process, one filter graph, one output file (ADR-0001). The platform
backends supply the *inputs*:

- ``NativeScreenInput`` — ffmpeg captures the screen itself (macOS
  avfoundation, cursor included). The microphone may ride the same input.
- ``PipeScreenInput`` — mss grabs the screen and a feeder thread pushes raw
  BGRA frames into a pipe (Windows/Linux); the feeder already cropped the
  region and guarantees even dimensions.
- ``ExtraAudioInput`` — the microphone as its own ffmpeg input (dshow on
  Windows, pulse on Linux).
- ``CameraInput`` — raw BGR frames from OpenCV on a pipe (all platforms;
  ffmpeg's own camera demuxers are unreliable, ADR-0003).

Everything downstream of the inputs (crop guard, bubble overlay, speaker
layout, live preview, encoders, muxing) is platform-independent.
"""
import os
from dataclasses import dataclass, field
from typing import Optional, Sequence, Tuple

# The live-preview stream is letterboxed onto this fixed canvas so the reader
# never has to guess the geometry (it used to, and got Speaker modes wrong).
LIVE_PREVIEW_W, LIVE_PREVIEW_H = 480, 270


@dataclass
class NativeScreenInput:
    input_args: list          # full input args incl. "-i <screen[:mic]>"
    audio_stream: Optional[str] = "0:a"   # mic stream label, None = no audio


@dataclass
class PipeScreenInput:
    pipe_fd: int
    size: Tuple[int, int]     # declared (w, h), already even


@dataclass
class ExtraAudioInput:
    input_args: list          # e.g. ["-f", "dshow", "-i", 'audio="Mic"']
    stream: str = "1:a"


@dataclass
class CameraInput:
    pipe_fd: int
    fps: float                # measured delivery rate — becomes the camera clock
    size: Tuple[int, int]


def _even(value):
    return int(value) & ~1


def _rawvideo_input(pipe_fd, size, fps, pix_fmt):
    size_str = f"{int(size[0])}x{int(size[1])}"
    return ["-f", "rawvideo", "-pix_fmt", pix_fmt,
            "-video_size", size_str,
            "-framerate", str(round(float(fps), 3)),
            "-i", f"pipe:{pipe_fd}"]


def _secondary_path(output_path, suffix):
    base, _ = os.path.splitext(output_path)
    return base + suffix


def build_command(ffmpeg, output_path, fps, screen, mic=None, camera=None,
                  region=None, screen_scale=1.0, pip=None, layout="pip",
                  separate=False, preview=False, capture_size=None,
                  encoder_main=(), encoder_camera=()):
    """Assemble the recording command. Returns (cmd, extra_files).

    region: (x, y, w, h) in logical points — only meaningful for a native
        screen input; a pipe screen is cropped by its feeder.
    pip: (w, x, y) camera bubble in OUTPUT device pixels, relative to the
        capture origin (layout="pip" only).
    layout: "pip" | "speaker-right" | "speaker-left" (presenter style,
        composited at 1080p height).
    separate: also write screen-only and camera-only files next to the output.
    preview: also output a downscaled composited rawvideo stream on stdout.
    capture_size: (w, h) of the native capture in device pixels, used to add
        an even-dimension guard (yuv420p cannot encode odd sizes).
    encoder_main / encoder_camera: per-platform codec args for the composite
        and camera-only outputs, e.g. ["-c:v", "libx264", "-crf", "20"].
    """
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "warning", "-y"]

    if isinstance(screen, NativeScreenInput):
        cmd += screen.input_args
    else:
        cmd += _rawvideo_input(screen.pipe_fd, screen.size, fps, "bgra")

    if mic is not None and isinstance(mic, ExtraAudioInput):
        cmd += mic.input_args

    camera_index = None
    if camera is not None:
        # inputs are ordered screen(0), extra audio(1), camera(next)
        camera_index = 1 + (1 if isinstance(mic, ExtraAudioInput) else 0)
        cmd += _rawvideo_input(camera.pipe_fd, camera.size, camera.fps, "bgr24")

    filters = []
    base = "[0:v]"

    # Native capture may report odd dimensions (a 1367-point-wide region under
    # a 2x scale, say) which yuv420p cannot encode. A pipe screen is already
    # cropped to even by its feeder.
    if isinstance(screen, NativeScreenInput):
        if region:
            x, y, w, h = region
            x, y = int(x * screen_scale), int(y * screen_scale)
            w, h = _even(w * screen_scale), _even(h * screen_scale)
            filters.append(f"{base}crop={w}:{h}:{x}:{y}[crp]")
            base = "[crp]"
        elif capture_size and (int(capture_size[0]) & 1 or int(capture_size[1]) & 1):
            filters.append(f"{base}scale={_even(capture_size[0])}:{_even(capture_size[1])}[evn]")
            base = "[evn]"

    # split the (already cropped/guarded) screen if it is also wanted as a file
    scr_stream = base
    if separate:
        filters.append(f"{base}split=2[scrA][scrB]")
        scr_stream, base = "[scrA]", "[scrB]"

    cam_stream = None
    if camera is not None:
        cam_in = f"[{camera_index}:v]"
        if separate:
            filters.append(f"{cam_in}split=2[camA][camB]")
            cam_stream, cam_in = "[camA]", "[camB]"

        if layout == "pip":
            pip_w, pip_x, pip_y = _even(pip[0]), int(pip[1]), int(pip[2])
            filters.append(f"{cam_in}scale={pip_w}:-2[cam]")
            filters.append(f"{base}[cam]overlay={pip_x}:{pip_y}[out]")
        elif layout == "speaker-right":
            filters.append(
                f"{cam_in}scale=-2:1080[spk];"
                f"{base}scale=-2:1080[scrS];"
                f"[scrS][spk]hstack=inputs=2[out]")
        else:  # speaker-left
            filters.append(
                f"{cam_in}scale=-2:1080[spk];"
                f"{base}scale=-2:1080[scrS];"
                f"[spk][scrS]hstack=inputs=2[out]")
        base = "[out]"

    if preview:
        filters.append(
            f"{base}split=2[rec][pv];"
            f"[pv]scale={LIVE_PREVIEW_W}:{LIVE_PREVIEW_H}:"
            f"force_original_aspect_ratio=decrease,"
            f"pad={LIVE_PREVIEW_W}:{LIVE_PREVIEW_H}:(ow-iw)/2:(oh-ih)/2[prev]")
        base = "[rec]"

    if filters:
        cmd += ["-filter_complex", ";".join(filters)]

    cmd += ["-map", base]

    # Audio routing: an extra audio input owns its stream; a native screen
    # input may carry the mic itself (macOS avfoundation, mic=None then).
    audio_stream = None
    if mic is not None:
        audio_stream = mic.stream
    elif isinstance(screen, NativeScreenInput):
        audio_stream = screen.audio_stream
    if audio_stream:
        cmd += ["-map", audio_stream, "-c:a", "aac", "-b:a", "128k"]

    # `-r` on every output: some inputs report a bogus "1000k tbr", and any
    # output inheriting it (the rawvideo preview above all) makes ffmpeg
    # duplicate frames without bound.
    cmd += list(encoder_main) + ["-pix_fmt", "yuv420p", "-r", str(fps), output_path]

    extra_files = []
    if separate and scr_stream:
        screen_path = _secondary_path(output_path, "_screen.mp4")
        cmd += ["-map", scr_stream] + list(encoder_main) + \
            ["-pix_fmt", "yuv420p", "-r", str(fps), screen_path]
        extra_files.append(screen_path)
    if separate and cam_stream:
        camera_path = _secondary_path(output_path, "_camera.mp4")
        cmd += ["-map", cam_stream] + list(encoder_camera) + \
            ["-pix_fmt", "yuv420p", "-r", str(fps), camera_path]
        extra_files.append(camera_path)

    if preview:
        cmd += ["-map", "[prev]", "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-r", str(fps), "pipe:1"]
    return cmd, extra_files


@dataclass
class CommandPlan:
    """Everything the caller needs to launch one recording session."""
    cmd: list = field(default_factory=list)
    extra_files: list = field(default_factory=list)
    screen_pipe_write_fd: Optional[int] = None   # feeder writes here (win/linux)
    camera_pipe_write_fd: Optional[int] = None   # camera feed writes here
    camera_fps: Optional[float] = None
    camera_size: Optional[Tuple[int, int]] = None
