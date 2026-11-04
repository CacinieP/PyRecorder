# Legacy editions (frozen)

These are the three pre-unification recorders, kept runnable but **no longer
developed** (ADR-0006). The unified app (`pyrecorder`) replaces them — see the
top-level README.

| File | What it was | Why it was kept |
|---|---|---|
| `screen_recorder.py` | Windows basic (screen only) | Reference for the minimal UI |
| `screen_recorder_pro.py` | Windows Pro (mic via PyAudio, MoviePy merge, window capture) | Only implementation of Win32 window capture; its mixed-DPI region handling was ported to the unified backend |
| `screen_recorder_mac.py` | macOS edition (single ffmpeg pipeline) | Direct ancestor of the unified pipeline: pacing, moov check, bubble and lifecycle all came from here |
| `process_output.py` | stderr drain helper | Superseded by `pyrecorder.ffmpeg_exe.ProcessOutputReader` (same code) |

Run them with the `[legacy]` extra installed (`pip install -e ".[legacy]"`);
their tests still run in CI. Do not add features here — fix the unified app
instead and let this folder rot gracefully.
