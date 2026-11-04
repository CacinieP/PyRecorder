# PyRecorder

**录教学视频的最简工具：你的屏幕、你的脸、你的声音 → 一个 MP4。**

PyQt6 + 单进程 ffmpeg。macOS / Windows / Linux 三平台同一套代码、同一个界面。

```
┌─────────────────────────────────────────┐
│  Output   ~/Movies                [Choose] │
│  Area     Full screen  [Select Region]    │
│  Camera   ☑ overlay   [Preview & Position]│   ← 拖拽气泡 = 录制中的位置（所见即所得）
│           Layout: Corner PiP / Speaker L/R│
│  Audio    ☑ Microphone  [内置麦克风 ▾]     │
│           FPS 30   ☐ 另存分轨              │
│  ───────────────────────────────────────  │
│  [        Start Recording              ]  │
└─────────────────────────────────────────┘
```

## 为什么是 PyRecorder

录课要的无非三样：**屏幕内容、出镜的人像气泡、讲解的声音**。OBS 全能但臃肿，QuickTime 不能同录人像，Cap/Screen Studio 好用但闭源或收费。PyRecorder 只做这一件事，并把它做对：

- **一个进程**：屏幕、摄像头、麦克风全部喂给同一条 ffmpeg 命令，直接输出成片——没有「先录再合并」的漫长等待（旧版 Windows 路径已因此被替换，见 [ADR-0001](docs/adr/0001-unified-single-ffmpeg-pipeline.md)）
- **所见即所得的人像气泡**：录制前把摄像头气泡拖到任意位置、拖角缩放，气泡在哪录制出来就在哪
- **演讲者模式**：不想当「角落里的头像」？人像与屏幕内容等高并排（腾讯会议式）
- **可靠收尾**：停止只发一次 SIGTERM，成片必须通过 MP4 moov 完整性校验才算成功；摄像头/麦克风打不开自动降级继续录，绝不静默丢失
- **零系统依赖可选用**：`pip install pyrecorder[ffmpeg-binary]` 自带静态 ffmpeg；本机已装 ffmpeg 则优先用你自己的

## 安装

| 方式 | 命令 |
|---|---|
| pipx（推荐） | `pipx install "pyrecorder[ffmpeg-binary]"`，然后运行 `pyrecorder` |
| pip | `pip install "pyrecorder[ffmpeg-binary]" && pyrecorder` |
| 源码 | `git clone … && cd PyRecorder && ./start.command`（mac）/ `start.bat`（Win） |
| 安装包 | [Releases](https://github.com/CacinieP/PyRecorder/releases) 下载三平台独立包（CI 构建） |

不带 `[ffmpeg-binary]` 时需要系统 ffmpeg：macOS `brew install ffmpeg`，Windows `winget install Gyan.FFmpeg`，Linux `sudo apt install ffmpeg`。

> macOS 首次使用需在「系统设置 → 隐私与安全性」为终端/应用授权屏幕录制、相机、麦克风，改完重启应用。Linux 需要 X11 会话（Wayland 暂不支持，会明确提示而非录黑屏）。

## 用法（录一节课）

1. 启动 → 状态栏出现 `Devices: screen OK, mic OK`
2. （可选）`Select Region` 框选区域；`Preview & Position` 打开人像气泡，拖到合适位置
3. `Start Recording` → 弹出实时预览窗口（所见即所录）→ 讲课
4. `Stop Recording` → 成片落在输出目录（默认 `~/Movies` / `~/Videos`）

## 系统要求

- Python 3.11+（安装包不需要）
- macOS 12+ / Windows 10+ / Linux X11
- 编码：macOS 走 VideoToolbox 硬编；Windows/Linux 走 libx264（`veryfast`, CRF 20），4K 高帧率建议降 FPS 或缩区域

## 文档

| 文档 | 内容 |
|---|---|
| [产品定位](docs/product.md) | 目标用户、范围与非目标、路线图 |
| [架构](docs/architecture.md) | 管线图、模块分层、平台后端接口、与 legacy 的对应 |
| [架构决策记录 (ADR)](docs/adr/) | 为什么是单 ffmpeg 进程、mss 管道、OpenCV 摄像头…… |
| [已知问题与修复档案](docs/known-issues.md) | 历史缺陷的实测复现数据与性能参考 |
| [贡献指南](CONTRIBUTING.md) | 分支/PR 流程、本地验证、真机验收清单 |

## 开发

```bash
pip install -e ".[dev,legacy]"
python -m pytest -q        # 无设备测试（CI 同口径）
python -m flake8 . --count --select=E9,F63,F7,F82
python -m pyrecorder       # 从源码运行
```

旧版三件套（Windows 基础/Pro、macOS 版）已冻结在 [`legacy/`](legacy/README.md)，测试仍在 CI 中运行，但不再加功能。

## 许可证

[MIT](LICENSE)
