# Changelog

本项目的显著变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [3.0.0] - 2026-11-09

### 新增

- **统一跨平台应用 `pyrecorder`**：macOS / Windows / Linux 同一套代码与界面,
  单入口 `pyrecorder` / `python -m pyrecorder`（此前是三个平台各一份脚本）
- **Linux 支持**：mss/X11 屏幕管道 + PulseAudio 麦克风 + pactl 设备枚举；
  Wayland 显式报错并指引
- **Windows 管线重写**：mss→BGRA 管道 + dshow 麦克风直入 ffmpeg，删除
  「PyAudio→WAV→MoviePy 重编码合并」路径，停止即成片
- **WYSIWYG 人像气泡**与**演讲者模式**扩展到全部平台（移植自 legacy macOS 版）
- **pyproject 打包**：pip 可编辑安装，`[ffmpeg-binary]` extra 携带静态 ffmpeg，
  `[legacy]` / `[dev]` extras 承载冻结版与开发依赖
- **独立安装包流水线**：PyInstaller spec + release workflow（三平台产物附到 Release）
- **文档体系**：产品定位、架构（含不变量清单）、6 篇 ADR、已知问题档案

### 变更

- README 重写为产品优先（历史修复流水移入 docs/known-issues.md）
- CI 改为安装包本体（`pip install -e ".[dev,legacy]"`），requirements*.txt 移除
- start.command / start.bat 启动统一应用（含 Python 3.11+ 版本检查）

### 变更

- README 重写为产品优先（历史修复流水移入 docs/known-issues.md）
- CI 改为安装包本体（`pip install -e ".[dev,legacy]"`），requirements*.txt 移除
- start.command / start.bat 启动统一应用

### 冻结

- `screen_recorder.py` / `screen_recorder_pro.py` / `screen_recorder_mac.py` /
  `process_output.py` 移入 `legacy/`，测试保留（ADR-0006）

## [2.x] - 2026-09 ~ 2026-10

三套平台各自演进的时期（对应 tag [v2.0.0]），包含 17 项实测修复（复制帧风暴、二次
SIGTERM 打断 muxer、预览几何错位、摄像头管道带宽、moviepy/PyQt6 版本坑等），详见
[docs/known-issues.md](docs/known-issues.md)。

三套平台各自演进的时期，包含 17 项实测修复（复制帧风暴、二次 SIGTERM 打断
muxer、预览几何错位、摄像头管道带宽、moviepy/PyQt6 版本坑等），详见
[docs/known-issues.md](docs/known-issues.md)。
