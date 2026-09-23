"""Drain subprocess diagnostics without blocking the process or growing memory."""
import threading


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
