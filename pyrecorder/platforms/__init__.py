"""Platform backends: everything that differs between macOS, Windows, Linux.

The backend supplies the ffmpeg *inputs* (screen capture route, microphone)
plus encoders, device enumeration and permission hints; the pipeline in
``pyrecorder.command`` and the UI are platform-independent. See
docs/adr/0002 (screen), 0003 (camera), 0004 (audio), 0005 (encoders).
"""
import sys

from pyrecorder.platforms.base import AudioDevice, Backend  # noqa: F401


def current_platform_id():
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform == "win32":
        return "win32"
    return "linux"


def backend_for(platform_id=None):
    """Instantiate the backend for `platform_id` (default: this machine)."""
    pid = platform_id or current_platform_id()
    if pid == "darwin":
        from pyrecorder.platforms.macos import MacosBackend
        return MacosBackend()
    if pid == "win32":
        from pyrecorder.platforms.windows import WindowsBackend
        return WindowsBackend()
    from pyrecorder.platforms.linux import LinuxBackend
    return LinuxBackend()
