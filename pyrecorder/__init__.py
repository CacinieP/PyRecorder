"""PyRecorder — a minimal screen + face + voice recorder for teaching videos.

The package runs one ffmpeg process per recording: the screen, the camera
bubble and the microphone are inputs to a single filter graph that writes the
final MP4 directly (see docs/architecture.md).
"""

__version__ = "3.0.0"
