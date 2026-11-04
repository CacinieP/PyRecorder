"""The interface every platform backend implements.

Kept as a plain base class (not typing.Protocol) so implementations can share
helpers; every method has a conservative default so a partially-capable
backend still works.
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AudioDevice:
    id: str          # opaque backend id: avfoundation index, dshow name, pulse source
    label: str


class Backend:
    id: str = "base"

    # ---- microphone ------------------------------------------------------

    def list_audio_inputs(self):
        """[AudioDevice] the user can pick; may block (shells out to ffmpeg)."""
        return []

    def default_audio_input(self):
        devices = self.list_audio_inputs()
        return devices[0] if devices else None

    def audio_input_args(self, device_id):
        """Extra ffmpeg input args for this mic, or None when the mic rides
        the screen input (macOS avfoundation)."""
        return None

    def audio_stream_label(self):
        """Which input stream carries the mic once recording started."""
        return "1:a"

    def probe_audio(self, device_id):
        """True when ffmpeg can actually open this input (~0.4s)."""
        return False

    # ---- screen ------------------------------------------------------------

    def screen_capture_kind(self):
        """'native' (ffmpeg captures the screen) or 'mss_pipe' (we feed frames)."""
        return "mss_pipe"

    def check_screen(self):
        """(usable, failure_hint). Call before recording; may block."""
        return True, ""

    def native_screen_args(self, fps, mic_device_id=None):
        """ffmpeg input args for a native screen capture (macOS only)."""
        raise NotImplementedError("native screen capture is not available here")

    # ---- encoding ----------------------------------------------------------

    def encoder_args(self, which):
        """Codec args for 'main' (composite/screen output) or 'camera'."""
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf",
                "20" if which == "main" else "23"]

    # ---- UX ----------------------------------------------------------------

    def permission_hint(self):
        return ""

    def region_origin_physical(self, widget):
        """Physical-pixel origin of `widget`'s top-left corner."""
        origin = widget.mapToGlobal(widget.rect().topLeft())
        dpr = widget.devicePixelRatioF() or 1.0
        return int(origin.x() * dpr), int(origin.y() * dpr)

    def region_to_physical(self, region, origin_logical, device_pixel_ratio):
        """Convert a logical-point selection to physical desktop pixels."""
        x, y, width, height = region
        left = round(x * device_pixel_ratio)
        top = round(y * device_pixel_ratio)
        right = round((x + width) * device_pixel_ratio)
        bottom = round((y + height) * device_pixel_ratio)
        return (origin_logical[0] + left, origin_logical[1] + top,
                right - left, bottom - top)

    def region_coords_kind(self):
        """'logical' when a capture region is expressed in logical points
        (macOS avfoundation), 'physical' for pixel-space feeders (mss)."""
        return "physical"

    def default_output_folder(self):
        return os.path.join(os.path.expanduser("~"), "Videos")
