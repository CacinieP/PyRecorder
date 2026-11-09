# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: one self-contained PyRecorder app per platform.

Built by CI on every platform (see .github/workflows/release.yml) and usable
locally:

    pip install -e ".[ffmpeg-binary,dev]" pyinstaller
    pyinstaller packaging/pyinstaller.spec --noconfirm

The `[ffmpeg-binary]` extra ships a private static ffmpeg inside the app, so
the produced bundle records out of the box with zero system setup.
"""
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH is injected by PyInstaller)

with open(REPO_ROOT / "pyproject.toml", "rb") as _pyproject:
    VERSION = tomllib.load(_pyproject)["project"]["version"]

# The platform backends are imported lazily (backend_for), so PyInstaller's
# static analysis never sees the two modules this build will NOT bundle.
hiddenimports = ["pyrecorder.platforms", "imageio_ffmpeg"]
if sys.platform == "darwin":
    hiddenimports.append("pyrecorder.platforms.macos")
elif sys.platform == "win32":
    hiddenimports += ["pyrecorder.platforms.windows", "mss"]
else:
    hiddenimports += ["pyrecorder.platforms.linux", "mss"]

a = Analysis(
    [str(REPO_ROOT / "pyrecorder" / "__main__.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyQt6.QtNetwork", "PyQt6.QtWebEngineCore"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PyRecorder",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # GUI app; ffmpeg output is captured via pipes
)

if sys.platform == "darwin":
    # Usage descriptions make the camera/mic permission prompts explain
    # themselves; screen recording is authorized in System Settings.
    app = BUNDLE(
        exe,
        name="PyRecorder.app",
        info_plist={
            "CFBundleName": "PyRecorder",
            "CFBundleShortVersionString": VERSION,
            "NSCameraUsageDescription":
                "PyRecorder shows your camera as the face bubble in teaching videos.",
            "NSMicrophoneUsageDescription":
                "PyRecorder records your voice into the teaching video.",
        },
    )
