"""Environment-level regression guards.

These protect against dependency resolutions that import cleanly on paper but
crash at runtime — the kind of breakage a green CI used to hide.
"""
import pytest

pytest.importorskip("PyQt6", reason="PyQt6 is a hard dependency of both recorders")


def test_pyqt6_wrapper_matches_the_installed_qt_binaries():
    """PyQt6 and PyQt6-Qt6 must share a minor version.

    `PyQt6==6.6.1` declares only `PyQt6-Qt6>=6.6.0` (no upper bound), so pip
    happily installs Qt 6.11 next to the 6.6 wrapper and every import dies with:

        ImportError: PyQt6/QtGui.abi3.so: undefined symbol:
                     _ZN5QFont11tagToStringEj, version Qt_6

    Observed in CI on 2026-09-18 (PyQt6-6.6.1 + PyQt6-Qt6-6.11.2). PyQt6 6.7.0
    and later pin PyQt6-Qt6 to the matching minor, which is why requirements
    ask for >=6.7.
    """
    from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

    wrapper = ".".join(PYQT_VERSION_STR.split(".")[:2])
    qt = ".".join(QT_VERSION_STR.split(".")[:2])
    assert wrapper == qt, (
        f"PyQt6 wrapper {PYQT_VERSION_STR} is paired with Qt {QT_VERSION_STR}; "
        f"install PyQt6>=6.7 so pip picks a matching PyQt6-Qt6")


def test_both_recorders_import():
    """The macOS recorder must import anywhere; the Windows one must at least
    import off-Windows (window capture raises a clear error when called)."""
    import screen_recorder_mac as mac
    import screen_recorder_pro as pro

    assert callable(mac.build_command)        # macOS: ffmpeg command assembly
    assert callable(pro.merge_audio_video)    # Windows: moviepy 2.x merge helper
