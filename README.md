# PyRecorder

一个简单易用的Windows录屏软件，具有图形用户界面。

## 版本说明

| 版本 | 文件 | 功能 |
|------|------|------|
| 基础版 | `screen_recorder.py` | 屏幕录制 |
| Pro版 | `screen_recorder_pro.py` | 屏幕录制 + 音频 + 摄像头画中画 + 窗口捕获 + 实时预览 |

## 功能特点

### 基础版
- 全屏或自定义区域录制
- 可调节帧率（10-60 FPS）
- 多种视频编码格式支持（MP4, AVI）
- 实时录制进度显示
- 简洁直观的用户界面
- 自动生成带时间戳的文件名

### Pro版
- 包含基础版所有功能
- **三种捕获模式**
  - 全屏录制
  - 自定义区域 — 拖拽选择屏幕任意区域
  - 窗口捕获 — 从打开的窗口列表中选择特定窗口，支持裁剪子区域
- 麦克风音频录制（44.1kHz 立体声）
- 音视频自动同步合并
- **摄像头画中画叠加** — 录屏同时录制人像，适合教学演示
  - 支持4个画中画位置（左上/右上/左下/右下）
  - 可调节画中画窗口大小（100-640px）
  - 摄像头实时预览功能
- **实时录制预览** — 录制过程中右侧面板实时显示画面
- 录制时长无限制
- 完善的错误处理机制

## 快速开始

### 方式一：使用启动脚本（推荐）

双击 `start.bat` 即可运行，脚本会自动检测环境并提供菜单选项：

```
===============================================================
              PyRecorder - Windows Screen Recorder
                       Version 2.0.0
                       MIT License
===============================================================

[OK] Python 3.x.x installed
[OK] pip ready

Select version to run:
  [1] Basic (Screen recording only)
  [2] Pro   (Screen + Audio + Webcam + Window capture)
  [3] Install/Update dependencies
  [4] Project info
  [0] Exit
```

### 方式二：命令行运行

**基础版：**
```bash
python screen_recorder.py
```

**Pro版：**
```bash
python screen_recorder_pro.py
```

## 安装

### 自动安装

运行 `start.bat`，选择选项 `[3]` 自动安装所有依赖。

### 手动安装

**基础版：**
```bash
pip install PyQt6 mss opencv-python numpy Pillow
```

**Pro版（需要额外安装）：**
```bash
pip install pyaudio moviepy
```

**一键安装所有依赖：**
```bash
pip install -r requirements.txt
```

## 使用方法

### 操作步骤

1. **选择保存文件夹**：点击"Browse..."选择保存视频的文件夹
2. **选择捕获模式**：
   - **Full Screen** — 录制整个屏幕
   - **Custom Region** — 拖拽选择屏幕区域
   - **Window Capture** — 从下拉列表选择特定窗口（点击 Refresh 刷新列表）
3. **裁剪区域（可选）**：在 Custom Region 或 Window Capture 模式下，点击"Select Region"选择子区域
4. **勾选音频**：勾选"Record Audio (Microphone)"启用麦克风录制
5. **启用摄像头**：勾选"Enable Webcam Overlay"启用画中画人像叠加
6. **选择画中画位置和大小**：从下拉菜单选择位置，设置宽度
7. **预览摄像头**：点击"Preview Webcam"确认摄像头画面正常
8. **开始录制**：点击"Start Recording"，右侧面板实时预览录制画面
9. **停止录制**：点击"Stop Recording"保存视频

### 教学录屏推荐设置

| 设置项 | 推荐值 | 说明 |
|--------|--------|------|
| Capture | Window Capture | 选择教学软件窗口 |
| Record Audio | 开启 | 录制讲解语音 |
| Webcam Overlay | 开启 | 录制人像画中画 |
| Position | Bottom-Right | 右下角不影响内容 |
| Size | 240 px | 不遮挡主要内容 |
| FPS | 30 | 教学视频无需高帧率 |
| Codec | mp4v | 兼容性最好 |

### 文件命名

录制完成后，视频会自动保存为：
```
recording_YYYYMMDD_HHMMSS.mp4
例如：recording_20250211_143052.mp4
```

## 视频编码格式说明

| 格式 | 特点 | 推荐用途 |
|------|------|----------|
| mp4v | MP4格式，兼容性好 | 日常录制 |
| XVID | 压缩率高，文件较小 | 长时间录制 |
| MJPG | 无损压缩，文件较大 | 高质量需求 |

## 性能要求

### CPU占用参考

| 分辨率 | FPS | 音频 | 摄像头 | CPU占用 |
|--------|-----|------|--------|---------|
| 1920x1080 | 30 | 无 | 无 | 15-25% |
| 1920x1080 | 30 | 有 | 有 | 25-40% |
| 1920x1080 | 60 | 有 | 有 | 40-60% |
| 2560x1440 | 30 | 有 | 有 | 35-55% |
| 窗口捕获 (小窗口) | 30 | 有 | 有 | 15-30% |

### 录制时长

| 限制因素 | 说明 |
|----------|------|
| 磁盘空间 | ~100MB/分钟（1080p@30fps），1TB ≈ 160小时 |
| 内存占用 | 稳定，不随录制时间增长 |
| 帧数限制 | 无限制 |

## 系统要求

- Windows 10/11
- Python 3.8+
- 至少2GB可用内存
- 麦克风（音频录制需要，可选）
- 摄像头（画中画功能需要，可选）

## 快捷键

- **ESC**: 取消区域选择

## 注意事项

- 录制高帧率会占用更多CPU和内存
- 保存视频前请确保磁盘空间充足
- Pro版首次录制时会下载ffmpeg，可能需要几秒钟
- 麦克风/摄像头权限需要在Windows设置中允许
- 摄像头不可用时自动跳过画中画，不影响正常录屏
- Window Capture 模式在开始录制时捕获窗口位置，录制中移动窗口不影响已捕获区域

## 故障排除

### 依赖安装失败

**PyAudio安装失败：**
```bash
pip install pipwin
pipwin install pyaudio
```

**MoviePy安装失败：**
```bash
pip install --upgrade imageio
python -m imageio_download_bin
```

### 录制问题

| 问题 | 解决方案 |
|------|----------|
| 程序无法启动 | 检查Python版本是否≥3.8 |
| 无法录制音频 | 检查麦克风权限和设备 |
| 视频无声音 | 确保勾选了"Record Audio"选项 |
| 摄像头画面不显示 | 检查摄像头连接和权限设置 |
| Preview Webcam打开黑屏 | 其他程序可能占用了摄像头，关闭后重试 |
| 窗口列表为空 | 点击 Refresh 刷新，确保有可见窗口 |
| 窗口捕获画面不对 | 重新选择窗口或使用 Custom Region 手动选择 |
| CPU占用过高 | 降低帧率或使用 Window Capture 只录小窗口 |
| 视频文件过大 | 选择XVID编码格式 |

## 技术架构

```
┌──────────────────────────────────────────────────────────┐
│                  PyRecorder GUI (PyQt6)                   │
│              ┌──────────┬───────────────────┐            │
│              │ Settings │   Live Preview    │            │
│              │  Panel   │     Panel         │            │
│              └──────────┴───────────────────┘            │
├──────────────────────────────────────────────────────────┤
│                   录制线程 (QThread)                       │
├─────────────┬──────────────┬─────────────────────────────┤
│ mss         │ OpenCV       │ PyAudio                     │
│ 屏幕/窗口   │ 摄像头捕获   │ 音频捕获                    │
│ 区域捕获    │              │                             │
├─────────────┴──────────────┴─────────────────────────────┤
│         numpy 画中画叠加 + OpenCV 视频编码                │
├──────────────────────────────────────────────────────────┤
│         MoviePy 音视频合并 (Pro版)                        │
└──────────────────────────────────────────────────────────┘
```

## 🍎 macOS 支持（新版）

`screen_recorder_mac.py` 是 macOS 原生支持版本：**屏幕 + 人像画中画 + 麦克风**同时录制，由 ffmpeg + AVFoundation 采集、VideoToolbox **硬件编码**，CPU 占用低、文件小（约 10MB/min @1080p30），直接输出 H.264 MP4，无需后期合并。

### 安装

```bash
# 1. 安装 ffmpeg（唯一系统依赖）
brew install ffmpeg

# 2. 安装 Python 依赖（仅需 PyQt6）
python3 -m pip install -r requirements-mac.txt
# （依赖 PyQt6 + opencv-python；摄像头由 OpenCV 的 AVFoundation 路径采集，
#   规避了 ffmpeg 摄像头输入在部分设备上输出冻结帧的问题）

# 3. 运行
python3 screen_recorder_mac.py
# 或在 Finder 中双击 start.command
```

### 首次运行：授予权限（重要）

在「系统设置 → 隐私与安全性」中，为**运行 PyRecorder 的程序**（终端 / iTerm / PyRecorder.app）开启：

- **屏幕录制** — 不授权会录到黑屏或空文件
- **相机** — 开启人像画中画时需要
- **麦克风** — 开启录音时需要

授权后需重启终端/应用才会生效。

### 功能

- 全屏 / 自定义区域录制（拖拽框选）
- 摄像头实时气泡：点击 **Preview & Position** 弹出置顶摄像头气泡，实时预览画面；**拖拽移动、右下角拉边缩放（锁定 16:9，另有 +/− 按钮档位缩放）**，气泡所在位置和大小即录制时的画中画位置和大小
- 布局可选：角落画中画，或**演讲者模式**（Speaker Left/Right，人像竖条与屏幕内容并排，参考腾讯会议分享屏幕演讲者模式）
- 文件输出：合并后的 `recording_xxx.mp4`，可同时勾选保存**分开的纯屏幕**（`_screen.mp4`）与**纯人像**（`_camera.mp4`）文件
- 录制中的 **Live Preview** 置顶窗口：实时看到「屏幕+人像」合成后的最终效果
- 麦克风录音（10–60 FPS，默认 30）
- 输出保存到 `~/Movies`（可自定义），文件名 `recording_YYYYMMDD_HHMMSS.mp4`

> 说明：macOS 系统限制，**系统内部声音**无法直接录制；如需内录系统声音，可安装虚拟声卡 [BlackHole](https://existential.audio/blackhole/) 后将输入设备切换为 BlackHole。

## 许可证

MIT License

## GitHub

https://github.com/CacinieP/PyRecorder
