"""Linux backend: mss screen pipe (X11) + PulseAudio microphone + libx264.

Wayland has no mss support — instead of silently recording a black or partial
frame, check_screen() explains the situation and points at the alternatives
(ADR-0002).
"""
import os
import shutil
import subprocess

from pyrecorder.platforms.base import AudioDevice, Backend


def parse_pactl_sources(text):
    """Parse `pactl list short sources` into [AudioDevice].

    Each line: NAME<TAB>DESCRIPTION<TAB>DRIVER... Pulse monitors (application
    outputs) are kept — they are the easiest way to record system audio.
    """
    devices = []
    for line in (text or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[0]:
            continue
        devices.append(AudioDevice(parts[0], parts[1]))
    return devices


class LinuxBackend(Backend):
    id = "linux"

    # ---- microphone --------------------------------------------------------

    def list_audio_inputs(self):
        if not shutil.which("pactl"):
            return [AudioDevice("default", "Default (PulseAudio)")]
        try:
            proc = subprocess.run(
                ["pactl", "list", "short", "sources"],
                capture_output=True, text=True, timeout=10,
            )
            devices = parse_pactl_sources(proc.stdout)
        except Exception:
            devices = []
        if devices:
            return devices
        return [AudioDevice("default", "Default (PulseAudio)")]

    def audio_input_args(self, device_id):
        return ["-f", "pulse", "-i", str(device_id)]

    def audio_stream_label(self):
        return "1:a"

    def probe_audio(self, device_id):
        from pyrecorder.ffmpeg_exe import run_tool
        proc = run_tool(["-f", "pulse", "-i", str(device_id),
                         "-t", "0.2", "-f", "null", "-"], timeout=10)
        return proc is not None and proc.returncode == 0

    # ---- screen -------------------------------------------------------------

    def check_screen(self):
        session = os.environ.get("XDG_SESSION_TYPE", "").lower()
        if session == "wayland" and not os.environ.get("DISPLAY"):
            return False, (
                "Wayland sessions cannot be captured by this recorder yet.\n\n"
                "Options: log into an X11/Xorg session, or use a tool with\n"
                "PipeWire portal support (e.g. OBS Studio) for Wayland.")
        try:
            import mss
            with mss.mss() as sct:
                if sct.monitors:
                    return True, ""
        except Exception:
            pass
        return False, ("mss could not open the X11 screen capture API.\n"
                       "Running under Wayland? Log into an X11/Xorg session.")

    # ---- UX -------------------------------------------------------------------

    def permission_hint(self):
        return ("Screen capture needs X11. Camera/mic access may be gated by\n"
                "Flatpak/portal permissions depending on your distribution.")
