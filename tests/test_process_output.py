"""A noisy encoder must keep running even when diagnostics exceed pipe capacity."""
import io
import subprocess
import sys

from process_output import ProcessOutputReader


def test_reader_drains_more_than_a_pipe_buffer_and_retains_only_the_tail():
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "import sys; sys.stderr.buffer.write(b'x' * 2_000_000 + b'FINAL ERROR'); "
         "sys.stderr.flush()"], stderr=subprocess.PIPE)
    reader = ProcessOutputReader(proc.stderr, limit=64)
    reader.start()
    try:
        assert proc.wait(timeout=10) == 0
        reader.join(timeout=2)
        assert not reader.is_alive()
        assert reader.tail_text(1000) == "x" * 53 + "FINAL ERROR"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        reader.join(timeout=2)
        proc.stderr.close()


def test_reader_decodes_broken_utf8_without_losing_the_error():
    reader = ProcessOutputReader(io.BytesIO(b"\xff\xe4\xb8\xad\xe6\x96\x87 ERROR"))
    reader.run()
    assert reader.tail_text() == "\ufffd中文 ERROR"
    assert reader.tail_text(5) == "ERROR"
    assert reader.tail_text(0) == ""
