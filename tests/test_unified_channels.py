"""Tests for the feeder->ffmpeg channels (pipes on POSIX, loopback TCP on
Windows)."""
import os
import socket
import threading
import time

import pytest

from pyrecorder.channels import (FdSink, PosixPipeChannel, TcpListenChannel,
                                 open_channel)


def test_open_channel_selects_by_platform():
    assert isinstance(open_channel("darwin"), PosixPipeChannel)
    assert isinstance(open_channel("linux"), PosixPipeChannel)
    assert isinstance(open_channel("win32"), TcpListenChannel)


def test_pipe_channel_end_to_end():
    ch = PosixPipeChannel()
    assert ch.input_arg() == f"pipe:{ch.pass_fd()}"
    sink = ch.connect()
    sink.write(b"hello")
    # reader consumes, then the writer closes -> EOF
    got = os.read(ch.pass_fd(), 8)
    assert got == b"hello"
    ch.after_spawn()                       # parent drops its read end copy
    sink.close()
    with pytest.raises(OSError):
        os.fstat(ch.pass_fd())


def test_pipe_channel_discard_closes_both_ends():
    ch = PosixPipeChannel()
    read_fd, _ = ch.pass_fd(), None
    ch.discard()
    with pytest.raises(OSError):
        os.fstat(read_fd)


def test_fd_sink_reports_dead_reader():
    r, w = os.pipe()
    os.close(r)
    sink = FdSink(w)
    assert sink.write(b"x" * 8) is False   # EPIPE, not an exception
    sink.close()


def test_tcp_channel_input_arg_and_streaming_with_connect_retry():
    ch = TcpListenChannel()
    arg = ch.input_arg()
    assert arg.startswith("tcp://127.0.0.1:") and "?listen=1" in arg
    assert ch.pass_fd() is None            # nothing to hand to Popen
    ch.after_spawn()                       # and nothing to close afterwards

    received = bytearray()

    def listener():
        # delay the bind so connect() must retry at least once
        time.sleep(0.3)
        with socket.socket() as srv:
            srv.bind((ch.host, ch._port))
            srv.listen(1)
            conn, _ = srv.accept()
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                received.extend(data)
            conn.close()

    thread = threading.Thread(target=listener)
    thread.start()
    sink = ch.connect(timeout=5)
    assert sink.write(b"hello ") and sink.write(b"world")
    sink.close()                           # EOF for the listener
    thread.join(5)
    assert bytes(received) == b"hello world"


def test_tcp_channel_connect_times_out_cleanly():
    ch = TcpListenChannel()
    # nobody ever listens on that port
    with pytest.raises(ConnectionError):
        ch.connect(timeout=0.3)
    ch.discard()                           # must not raise
