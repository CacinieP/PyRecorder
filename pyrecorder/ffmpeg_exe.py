"""Locate ffmpeg and drain its diagnostic output without blocking.

ffmpeg is the only media engine in PyRecorder (ADR-0001). It is resolved from
PATH, then from a few well-known install locations, then from the optional
`imageio-ffmpeg` package (`pip install pyrecorder[ffmpeg-binary]`), which
ships a private static build and keeps the app usable with zero system setup.
"""
import os
import shutil
import subprocess
import threading

# Resolution order for the ffmpeg executable. PATH wins so a user's own build
# (custom encoders, newer version) is always preferred over the bundled one.
_COMMON_LOCATIONS = (
    "/opt/homebrew/bin/ffmpeg",   # macOS Apple Silicon (brew)
    "/usr/local/bin/ffmpeg",      # macOS Intel / manual installs
    "/usr/bin/ffmpeg",            # Linux distro packages
)

INSTALL_HINTS = {
    "darwin": "brew install ffmpeg    (or: pip install pyrecorder[ffmpeg-binary])",
    "win32": ("winget install Gyan.FFmpeg    (or scoop/choco install ffmpeg, "
              "or pip install pyrecorder[ffmpeg-binary])"),
    "linux": "sudo apt install ffmpeg    (or your distro's equivalent)",
}


class ProcessOutputReader(threading.Thread):
    """Consume a binary pipe while retaining only its most recent diagnostics."""

    def __init__(self, stream, limit=8192):
        super().__init__(daemon=True)
        if limit <= 0:
            raise ValueError("limit must be positive")
        self.stream = stream
        self.limit = limit
        self._tail = bytearray()
        self._lock = threading.Lock()

    def run(self):
        # BufferedReader.read1 returns available bytes without waiting to fill
        # the whole request. BytesIO and unbuffered pipes offer only read.
        read = getattr(self.stream, "read1", self.stream.read)
        try:
            while True:
                chunk = read(4096)
                if not chunk:
                    return
                with self._lock:
                    self._tail.extend(chunk)
                    del self._tail[:-self.limit]
        except (OSError, ValueError):
            # The process may have disappeared during application shutdown.
            return

    def tail_text(self, max_chars=800):
        if max_chars <= 0:
            return ""
        with self._lock:
            return bytes(self._tail).decode("utf-8", errors="replace")[-max_chars:]


def find_ffmpeg():
    """Absolute path to an ffmpeg executable, or None when none is installed."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    for path in _COMMON_LOCATIONS:
        if os.path.exists(path) and os.access(path, os.X_OK):
            return path
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def install_hint():
    import sys
    if sys.platform == "darwin":
        return INSTALL_HINTS["darwin"]
    if sys.platform == "win32":
        return INSTALL_HINTS["win32"]
    return INSTALL_HINTS["linux"]


def run_tool(args, timeout=20):
    """Run ffmpeg with `args` and return the completed process (stderr captured).

    Never raises: callers treat exceptions and non-zero exits alike (the device
    simply is not usable). ffmpeg's `-list_devices` probes exit non-zero by
    design, so the return code alone is not an error.
    """
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        return None
    try:
        return subprocess.run(
            [ffmpeg, "-hide_banner"] + list(args),
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception:
        return None
