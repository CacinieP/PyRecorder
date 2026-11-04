"""macOS backend: avfoundation screen (cursor included) + VideoToolbox.

One avfoundation input carries both the screen and the microphone
(``-i "<screen>:<mic>"``); the camera arrives on its own OpenCV pipe like on
every platform. This is the capture route the legacy macOS edition validated
on real hardware (see docs/known-issues.md).
"""
import re

from pyrecorder.platforms.base import AudioDevice, Backend


def parse_av_device_lists(text):
    """Parse avfoundation `-list_devices` output into (screens, cameras, mics).

    Each is a list of (index, name) in the order ffmpeg reported them, so the UI
    can offer every audio input (e.g. BlackHole for system audio) instead of
    silently hard-coding the first one.
    """
    screens, cameras, mics = [], [], []
    section = "video"
    for line in (text or "").splitlines():
        if "AVFoundation video devices" in line:
            section = "video"
            continue
        if "AVFoundation audio devices" in line:
            section = "audio"
            continue
        m = re.search(r"\[(\d+)\]\s+(.+)$", line.strip())
        if not m:
            continue
        idx, name = int(m.group(1)), m.group(2).strip()
        if section == "audio":
            mics.append((idx, name))
        elif "Capture screen" in name:
            screens.append((idx, name))
        else:
            cameras.append((idx, name))
    return screens, cameras, mics


def first_screen_index(text):
    screens, _, _ = parse_av_device_lists(text)
    return screens[0][0] if screens else None


class MacosBackend(Backend):
    id = "darwin"

    def __init__(self):
        self._screen_index = None

    # ---- devices ------------------------------------------------------------

    def list_all_av_devices(self):
        from pyrecorder.ffmpeg_exe import run_tool
        proc = run_tool(["-f", "avfoundation", "-list_devices", "true", "-i", ""],
                        timeout=20)
        if proc is None:
            return [], [], []
        return parse_av_device_lists(proc.stderr)

    def list_audio_inputs(self):
        _, _, mics = self.list_all_av_devices()
        return [AudioDevice(str(idx), name) for idx, name in mics]

    def refresh_screen_index(self):
        screens, _, _ = self.list_all_av_devices()
        self._screen_index = screens[0][0] if screens else None
        return self._screen_index

    def audio_input_args(self, device_id):
        return None  # the mic rides the avfoundation screen input

    def audio_stream_label(self):
        return "0:a"

    def probe_audio(self, device_id):
        """True when ffmpeg can actually open this avfoundation audio device.

        Appearing in the device list is not enough: with Microphone permission
        denied (or the device busy) avfoundation fails to open it, and because
        audio shares the recording command the *whole* capture would die.
        Probing first lets the recorder degrade to video-only with a warning.
        """
        try:
            idx = int(device_id)
        except (TypeError, ValueError):
            return False
        proc = self._run(["-f", "avfoundation", "-i", f":{idx}",
                          "-t", "0.2", "-f", "null", "-"], timeout=10)
        return proc is not None and proc.returncode == 0

    def _run(self, args, timeout):
        from pyrecorder.ffmpeg_exe import run_tool
        return run_tool(args, timeout=timeout)

    # ---- screen ---------------------------------------------------------------

    def screen_capture_kind(self):
        return "native"

    def check_screen(self):
        if self.refresh_screen_index() is None:
            return False, ("No screen capture device found.\n\n"
                           "Grant Screen Recording permission:\n"
                           "System Settings → Privacy & Security → Screen Recording, "
                           "enable your terminal/app, then restart it and PyRecorder.")
        return True, ""

    def native_screen_args(self, fps, mic_device_id=None):
        if self._screen_index is None:
            self.refresh_screen_index()
        if self._screen_index is None:
            raise RuntimeError("no avfoundation screen device available")
        mic = "none" if mic_device_id is None else str(mic_device_id)
        return ["-f", "avfoundation", "-framerate", str(fps),
                "-capture_cursor", "1", "-capture_mouse_clicks", "1",
                "-i", f"{self._screen_index}:{mic}"]

    # ---- encoding / UX --------------------------------------------------------

    def encoder_args(self, which):
        bitrate = "8M" if which == "main" else "2M"
        return ["-c:v", "h264_videotoolbox", "-b:v", bitrate]

    def permission_hint(self):
        return ("Screen Recording, Camera and Microphone permissions live in\n"
                "System Settings → Privacy & Security; changes need an app restart.")

    def region_to_physical(self, region, origin_logical, device_pixel_ratio):
        # avfoundation captures logical points; the crop filter in
        # build_command() applies the scale itself, so keep points here.
        x, y, w, h = region
        return int(x), int(y), int(w), int(h)

    def region_coords_kind(self):
        return "logical"

    def default_output_folder(self):
        import os
        return os.path.expanduser("~/Movies")
