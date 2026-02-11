# PyRecorder

一个简单易用的Windows录屏软件，具有图形用户界面。

## 版本说明

| 版本 | 文件 | 功能 |
|------|------|------|
| 基础版 | `screen_recorder.py` | 屏幕录制 |
| Pro版 | `screen_recorder_pro.py` | 屏幕录制 + 音频录制 |

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
- 麦克风音频录制（44.1kHz 立体声）
- 音视频自动同步合并
- 录制时长无限制
- 完善的错误处理机制

## 快速开始

### 方式一：使用启动脚本（推荐）

双击 `start.bat` 即可运行，脚本会自动检测环境并提供菜单选项：

```
===============================================================
              PyRecorder - Windows Screen Recorder
                       Version 1.0.0
                       MIT License
===============================================================

[OK] Python 3.x.x installed
[OK] pip ready

Select version to run:
  [1] Basic (Screen recording only)
  [2] Pro   (Screen + Audio recording)
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
2. **Pro版勾选音频**：勾选"Record Audio (Microphone)"启用音频录制
3. **调整帧率**：设置录制帧率（默认30 FPS）
4. **选择编码格式**：选择视频编码器（默认mp4v）
5. **选择录制区域**：选择"Full Screen"或点击"Select Region"自定义区域
6. **开始录制**：点击"Start Recording"
7. **停止录制**：点击"Stop Recording"保存视频

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

| 分辨率 | FPS | 音频 | CPU占用 |
|--------|-----|------|---------|
| 1920x1080 | 30 | 无 | 15-25% |
| 1920x1080 | 30 | 有 | 20-35% |
| 1920x1080 | 60 | 无 | 30-45% |
| 1920x1080 | 60 | 有 | 35-55% |
| 2560x1440 | 30 | 有 | 30-50% |
| 3840x2160 | 30 | 无 | 40-70% |

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
- 麦克风（Pro版音频录制需要）

## 快捷键

- **ESC**: 取消区域选择

## 注意事项

- 录制高帧率会占用更多CPU和内存
- 保存视频前请确保磁盘空间充足
- Pro版首次录制时会下载ffmpeg，可能需要几秒钟
- 麦克风权限需要在Windows设置中允许

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
| CPU占用过高 | 降低帧率或缩小录制区域 |
| 视频文件过大 | 选择XVID编码格式 |

## 技术架构

```
┌─────────────────────────────────────────┐
│           PyRecorder GUI (PyQt6)         │
├─────────────────────────────────────────┤
│         录制线程 (QThread)               │
├──────────────────┬──────────────────────┤
│   mss 屏幕捕获   │  PyAudio 音频捕获    │
├──────────────────┴──────────────────────┤
│         OpenCV 视频编码                  │
├─────────────────────────────────────────┤
│      MoviePy 音视频合并 (Pro版)          │
└─────────────────────────────────────────┘
```

## 许可证

MIT License

## GitHub

https://github.com/CacinieP/PyRecorder
