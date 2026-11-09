"""Frame pacing for the rawvideo pipes feeding ffmpeg.

Both pipes (screen on Windows/Linux, camera everywhere) carry no timestamps:
ffmpeg derives their timeline from the declared `-framerate`, so a feeder must
deliver exactly that rate — duplicating frames when the device is slow and
dropping the backlog when it stalls — or the composited recording ends up
shorter than the session (measured on the macOS camera pipe: a 6 s session
came out 1.67 s long before this existed).
"""
import time


def frames_due(next_due, now, interval, max_catchup=2.0):
    """(copies_to_write, new_next_due) for a writer pacing to `interval`.

    Falling behind is paid back by duplicating frames; only a stall longer
    than `max_catchup` seconds resyncs, to avoid flooding the pipe.
    """
    if now < next_due:
        return 0, next_due
    backlog = now - next_due
    if backlog > max_catchup:
        return 1, now + interval
    n = int(backlog // interval) + 1
    return n, next_due + n * interval


def estimate_fps(read_frame, window=1.0, clock=time.monotonic):
    """Measure a capture device's real delivery rate in frames/second.

    read_frame() must return True when it delivered a frame. The first frame is
    treated as warm-up (device start latency) and excluded. Returns None when
    the device delivers too few frames to trust.
    """
    t0 = clock()
    elapsed = 0.0
    frames = 0
    warmed = False
    while True:
        got = read_frame()
        now = clock()
        if got:
            if warmed:
                frames += 1
            else:
                warmed = True
                t0 = now
        elapsed = now - t0
        if elapsed >= window:
            break
        if not warmed and elapsed >= window * 3:
            break   # device never produced a frame
    if frames < 2 or elapsed <= 0:
        return None
    return frames / elapsed


def pick_camera_fps(measured, fallback, lo=5.0, hi=60.0):
    """Clamp a measured camera rate into a usable range, else use the fallback."""
    if not measured:
        return float(fallback)
    return float(min(hi, max(lo, measured)))
