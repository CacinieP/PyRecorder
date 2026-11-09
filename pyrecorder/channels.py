"""Byte-stream channels from feeder threads into the ffmpeg child process.

POSIX passes extra input pipes to a child via ``pass_fds``. Windows
subprocess does not support that (``AssertionError: pass_fds not supported
on Windows``), so there the channel is a loopback TCP listener and ffmpeg
connects the input with ``tcp://127.0.0.1:<port>?listen=1`` — a built-in
ffmpeg protocol that behaves exactly like a pipe for raw streams (found by
the Windows CI leg; see docs/adr/0001).

Both flavors expose the same tiny surface used by the feeders:
``sink.write(payload) -> bool`` (False once the reader is gone) and
``sink.close()`` (EOF).
"""
import os
import socket
import sys
import time


class Sink:
    def write(self, payload):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


class FdSink(Sink):
    """Raw fd writer with POSIX partial-write handling."""

    def __init__(self, fd):
        self.fd = fd

    def write(self, payload):
        remaining = memoryview(payload)
        try:
            while remaining:
                written = os.write(self.fd, remaining)
                if written <= 0:
                    return False
                remaining = remaining[written:]
        except OSError:
            return False  # reader gone — recording stopped
        return True

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


class SocketSink(Sink):
    """Connected socket writer; sendall blocks until all bytes are shipped."""

    def __init__(self, sock):
        self.sock = sock

    def write(self, payload):
        try:
            self.sock.sendall(payload)
            return True
        except OSError:
            return False

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class PosixPipeChannel:
    """os.pipe with an inheritable read end (the pre-Windows-fix behaviour)."""

    def __init__(self):
        read_fd, write_fd = os.pipe()
        os.set_inheritable(read_fd, True)
        self._read_fd = read_fd
        self._write_fd = write_fd

    def input_arg(self):
        return f"pipe:{self._read_fd}"

    def pass_fd(self):
        """The fd to hand to Popen(pass_fds=...); None on non-pipe channels."""
        return self._read_fd

    def after_spawn(self):
        """The child has its own copy of the read end; drop ours."""
        try:
            os.close(self._read_fd)
        except OSError:
            pass

    def connect(self, timeout=15.0):
        return FdSink(self._write_fd)

    def discard(self):
        """Release everything when the spawn never happened."""
        for fd in (self._read_fd, self._write_fd):
            try:
                os.close(fd)
            except OSError:
                pass


class TcpListenChannel:
    """ffmpeg listens on loopback; the feeder connects and streams.

    Windows-compatible replacement for an inherited pipe. Loopback binds do
    not trigger the firewall prompt, and the rawvideo framing is identical
    over a byte stream, so the feeders do not care which flavor they got.
    """

    CONNECT_INTERVAL = 0.05

    def __init__(self, host="127.0.0.1"):
        self.host = host
        self._port = _pick_free_port(host)

    def input_arg(self):
        return f"tcp://{self.host}:{self._port}?listen=1"

    def pass_fd(self):
        return None

    def after_spawn(self):
        pass  # nothing inherited

    def connect(self, timeout=15.0):
        """Block until ffmpeg's listener accepts (it binds during startup)."""
        deadline = time.monotonic() + timeout
        last_error = None
        while time.monotonic() < deadline:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.connect((self.host, self._port))
                return SocketSink(sock)
            except OSError as exc:
                last_error = exc
                sock.close()
                time.sleep(self.CONNECT_INTERVAL)
        raise ConnectionError(
            f"ffmpeg did not accept the stream connection: {last_error}")

    def discard(self):
        pass


def _pick_free_port(host):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return probe.getsockname()[1]


def open_channel(platform_id=None):
    """A channel suited to the platform: pipes where they work, TCP elsewhere."""
    pid = platform_id or sys.platform
    if pid == "win32":
        return TcpListenChannel()
    return PosixPipeChannel()
