"""Windows backend: mss screen pipe + dshow microphone + libx264.

The screen is captured with mss (BGRA straight into the pipe, no conversion)
and the microphone is a dshow input of the same ffmpeg process — replacing
the legacy Pro path (PyAudio -> WAV -> MoviePy re-encode) with the unified
single-process pipeline (ADR-0001/0002/0004).
"""
import re

from pyrecorder.platforms.base import AudioDevice, Backend


def parse_dshow_device_lists(text):
    r"""Parse dshow `-list_devices` output into (cameras, mics).

    Real ffmpeg 7/8 output shape (each device may be followed by an
    "Alternative name" line, which is ignored):

        [dshow @ ...]  "Integrated Webcam" (video)
        [dshow @ ...]    Alternative name "@device_pnp_\\?\usb#..."
        [dshow @ ...]  "Microphone (Realtek(R) Audio)" (audio)
    """
    cameras, mics = [], []
    for line in (text or "").splitlines():
        m = re.search(r'"(.+?)"\s+\((audio|video)\)', line)
        if not m or line.strip().startswith("Alternative"):
            continue
        name, kind = m.group(1), m.group(2)
        (mics if kind == "audio" else cameras).append(name)
    return cameras, mics


class WindowsBackend(Backend):
    id = "win32"

    # ---- microphone --------------------------------------------------------

    def list_audio_inputs(self):
        from pyrecorder.ffmpeg_exe import run_tool
        proc = run_tool(["-list_devices", "-f", "dshow", "-i", "dummy"], timeout=20)
        if proc is None:
            return []
        _, mics = parse_dshow_device_lists(proc.stderr)
        return [AudioDevice(name, name) for name in mics]

    def audio_input_args(self, device_id):
        # Quotes are literal here: ffmpeg's dshow demuxer needs them to keep
        # device names with spaces/commas in one piece (no shell involved).
        return ["-f", "dshow", "-i", f'audio="{device_id}"']

    def audio_stream_label(self):
        return "1:a"

    def probe_audio(self, device_id):
        from pyrecorder.ffmpeg_exe import run_tool
        proc = run_tool(["-f", "dshow", "-i", f'audio="{device_id}"',
                         "-t", "0.2", "-f", "null", "-"], timeout=10)
        return proc is not None and proc.returncode == 0

    # ---- screen -------------------------------------------------------------

    def check_screen(self):
        try:
            import mss
            with mss.mss() as sct:
                if sct.monitors:
                    return True, ""
        except Exception:
            pass
        return False, "mss could not open the Windows screen capture API."

    # ---- UX -------------------------------------------------------------------

    def region_origin_physical(self, widget):
        # ClientToScreen returns native desktop coordinates; deriving the
        # origin from mapToGlobal * devicePixelRatio breaks on mixed-DPI
        # screens (validated in the legacy Pro edition).
        try:
            import ctypes
            import ctypes.wintypes as wintypes
            point = wintypes.POINT()
            if ctypes.windll.user32.ClientToScreen(
                    ctypes.c_void_p(int(widget.winId())), ctypes.byref(point)):
                return point.x, point.y
        except Exception:
            pass
        return super().region_origin_physical(widget)

    def permission_hint(self):
        return "Windows needs no extra permissions for screen, camera or mic."

    def default_output_folder(self):
        import os
        return os.path.join(os.path.expanduser("~"), "Videos")
