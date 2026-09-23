# PyRecorder

基于 PyQt6 的录屏工具，含 **Windows** 与 **macOS** 两套实现。支持全屏 / 自定义区域录制、摄像头人像画中画（PiP）、麦克风录音。

> ## ✅ 状态速览（录制管线已修复）
>
> | 版本 | 状态 | 说明 |
> |---|---|---|
> | Windows 基础版 `screen_recorder.py` | ✅ 可用 | 仅屏幕录制 |
> | Windows Pro 版 `screen_recorder_pro.py` | ✅ 已修复 | 改用 moviepy 2.x API，录音边录边写盘，非 Windows 也能导入以便测试 |
> | macOS 版 `screen_recorder_mac.py` | ✅ 已修复 | PiP / PiP+区域 / Speaker Left / Speaker Right / 仅屏幕（含分轨）实测均产出可播放文件 |
>
> 实测环境：macOS 26.6.2 / Apple A18 Pro（6 核，8GB）/ ffmpeg 8.1.2 / Python 3.13.13 / PyQt6 6.11.0 / opencv 5.0.0；屏幕采集分辨率 2816×1762。
> 修复前的缺陷与复现数据见 [已知问题与修复状态](#已知问题与修复状态)，运行方式见 [测试](#测试)。

2026-09-23 迭代补齐了录制生命周期：macOS 连续点击 Stop 只请求一次停止，收尾期间界面保持响应，关闭窗口会先结束探测或录制；ffmpeg 意外退出会自动报告结果，诊断输出持续读取并只保留末尾 8 KiB。Windows Pro 修正屏幕红蓝通道、检查编码器是否成功打开，并在失败时释放录音与捕获资源、保留可恢复文件，不再误报保存成功。以上有无设备回归测试；本轮未重新进行真实屏幕、摄像头或 Windows 桌面录制验收。

## 版本与平台

| 文件 | 平台 | 捕获方式 | 麦克风 | 人像 PiP | 录制后端 | 音视频合并 |
|---|---|---|---|---|---|---|
| `screen_recorder.py` | Windows | 全屏 / 自定义区域 | ❌ | ❌ | mss + OpenCV `VideoWriter` | — |
| `screen_recorder_pro.py` | Windows | 全屏 / 自定义区域 / **窗口捕获** | ✅ PyAudio | ✅ 四角 + 尺寸 | mss + OpenCV `VideoWriter` | MoviePy 重编码 |
| `screen_recorder_mac.py` | macOS | 全屏 / 自定义区域 | ✅ ffmpeg avfoundation | ✅ 可拖拽气泡 / 演讲者模式 | **ffmpeg + VideoToolbox 硬件编码** | 无需合并（单进程直接输出） |

`screen_recorder_pro.py` 的窗口捕获依赖 Win32 API，只能在 Windows 上运行（模块本身已做平台守卫，非 Windows 下可导入，调用窗口捕获时抛出带指引的 `RuntimeError`）；`screen_recorder_mac.py` 依赖 macOS 的 AVFoundation / VideoToolbox。

## 功能特点

### Windows 基础版

- 全屏或自定义区域录制（拖拽框选，ESC 取消）
- 帧率可调（10–60 FPS，默认 30）
- 编码下拉：`mp4v` / `XVID` / `H264` / `MJPG`（**输出文件名恒为 `.mp4`**，不生成 AVI；实测部分 fourcc 在 mp4 容器中不被支持，见[已知问题与修复状态](#已知问题与修复状态)）
- 帧计数 + 录制时长显示，录制结束后弹窗汇总
- 自动时间戳文件名

### Windows Pro 版

在基础版之上增加（编码下拉为 `mp4v` / `XVID` / `MJPG`，比基础版少 `H264`）：

- **窗口捕获** — 通过 Win32 `EnumWindows` 列出可见窗口（标题 > 60 字符会截断显示），可在窗口内再裁剪子区域；录制开始时固定窗口位置，录制中移动窗口不会跟随
- **麦克风录音** — PyAudio，44.1kHz / 16bit / 立体声，**边录边写入 wav**（不再全量缓存内存），录制结束后用 MoviePy 2.x 与视频合并
- **摄像头画中画** — 4 个位置（右下 / 左下 / 左上 / 右上），宽度 100–640px（默认 240），numpy 直接覆盖像素；摄像头打不开时自动跳过 PiP
- **摄像头预览** — 独立置顶对话框
- **实时录制预览** — 主窗口右侧面板，约 5fps（`fps // 5` 抽帧）
- 双栏界面（左设置 / 右预览），最小窗口 960×660

### macOS 版

- 全屏 / 自定义区域录制（半透明遮罩拖拽框选，显示实时尺寸，ESC 取消）
- **单条 ffmpeg 命令**同时完成：屏幕采集（含光标与鼠标点击）+ 摄像头叠加 + 麦克风 AAC，VideoToolbox 硬件编码直接输出 H.264 MP4，**无需后期合并**
- **摄像头气泡（Corner PiP）**：点击 `Preview & Position` 弹出置顶气泡，可拖到屏幕任意位置、右下角拖拽缩放（锁定 16:9）、`+ / −` 按钮档位缩放（气泡宽度范围 120–800px；主界面的 Default size 只决定气泡初始宽度，范围 120–640px，气泡打开后该输入框失效）。**气泡在屏幕上的位置和大小就是录制时的 PiP 位置和大小**
- **演讲者模式（Speaker Left / Right）**：人像与屏幕内容**等高（均缩放到 1080 高）横向并排**，各自保留原宽高比（实测本机：屏幕 1726×1080 + 人像 1920×1080 → 合成 3646×1080），参考腾讯会议「演讲者模式」；此布局下气泡位置/大小不生效
- **Live Preview**：录制期间自动弹出置顶窗口显示合成后的最终画面（无开关，恒定开启）；预览流固定 letterbox 到 **480×270**，因此任何布局下都不会错位
- **分轨保存**（可选）：除合成的 `recording_*.mp4` 外，另存纯屏幕 `_screen.mp4`（8 Mbit/s，**与主文件同区域**）与纯人像 `_camera.mp4`（2 Mbit/s）
- **音频输入可选**：`Options → Audio input` 下拉列出 ffmpeg 看到的全部 avfoundation 音频设备（含 BlackHole 之类虚拟声卡），不再固定用列表里的第一个
- **麦克风探测与降级**：开始录制前用 `ffmpeg -i ":<index>" -t 0.2` 实探一次（约 0.4s）；打不开就弹窗提示并**自动降级为仅视频**，而不是让整条命令失败
- 麦克风开关、FPS 10–60（默认 30）、输出目录可选（默认 `~/Movies`）
- **设备探测在后台线程**：按下 Start 后界面不冻结，状态显示 `Preparing devices…`，探测完成后才真正开始录制（`start_recording()` 实测 1–3ms 返回，探测本身约 1.5–4s，其中摄像头开启最慢）
- **摄像头保持原始宽高比**：4:3 摄像头不再被拉伸成 16:9（实测录出的画中画 h/w = 0.750，正是 4:3）；预览气泡同样按 letterbox 显示不变形
- 摄像头由 **OpenCV 的 AVFoundation 路径**采集后通过管道喂给 ffmpeg，绕开 ffmpeg 自带摄像头输入在部分设备上输出冻结帧的问题；录制前会先探测摄像头，不可用时弹窗降级为「仅屏幕（+麦克风）」
- 摄像头与麦克风都不可用时均不影响录屏：两者都会探测、弹窗、降级
- **摄像头写入按声明帧率节流**（`frames_due()`：设备慢就补帧、快就丢帧、卡顿后重新对齐而不是突然爆发），使分轨的 `_camera.mp4` 与合成文件时长基本一致

## 安装与运行

### Windows

```bat
:: 方式一：双击 start.bat，按菜单选择（[1] 基础版 / [2] Pro 版 / [3] 安装依赖 / [4] 项目信息）
start.bat

:: 方式二：命令行
pip install -r requirements.txt
python screen_recorder.py       :: 基础版
python screen_recorder_pro.py   :: Pro 版
```

`start.bat` 显示的版本号为 2.0.0，安装菜单使用当前 Python 的 `python -m pip` 安装 `requirements.txt`，已有旧版 MoviePy 也会按声明升级。建议使用 Python 3.11 或 3.12。

> 依赖注意事项（均已在 `requirements.txt` 中修正，历史坑见[已知问题与修复状态](#已知问题与修复状态)）：
>
> - **`moviepy>=2.0`**：旧的 `moviepy==1.0.3` 无法从顶层 `moviepy` 导入 `VideoFileClip`，Pro 版会启动即失败（第 8 条）
> - **`PyQt6>=6.7,<7`**：`PyQt6==6.6.1` 不约束 `PyQt6-Qt6` 上界，全新安装会装出 ABI 不匹配的组合并直接 `ImportError`（第 14 条）
> - **`pyaudio`** 需要系统的 portaudio；Linux/CI 上装 `portaudio19-dev`，Windows 上装不上可用 `pip install pipwin && pipwin install pyaudio`

### macOS

```bash
# 1. 安装 ffmpeg（唯一系统依赖，需带 avfoundation 与 h264_videotoolbox；brew 版即满足）
brew install ffmpeg

# 2. 安装 Python 依赖（PyQt6 + opencv-python）
python3 -m pip install -r requirements-mac.txt

# 3. 运行
python3 screen_recorder_mac.py
# 或在 Finder 中双击 start.command（会自动建 .venv、装依赖、检查 ffmpeg）
```

启动时若检测不到 ffmpeg 会弹窗提示 `brew install ffmpeg`；随后自动探测设备并在状态栏显示 `Devices: screen OK, camera OK, mic OK`。

### macOS 权限（必读）

在「系统设置 → 隐私与安全性」中，为**运行 PyRecorder 的那个程序**（终端 / iTerm / 打包后的 App）授予：

| 权限 | 何时需要 | 未授权的后果 |
|---|---|---|
| 屏幕录制 | 始终 | 录到黑屏 / 空文件，或找不到屏幕采集设备 |
| 相机 | 勾选人像 PiP 时 | 摄像头探测失败，自动降级为仅屏幕 |
| 麦克风 | 勾选 Microphone 时 | 探测失败 → 弹窗提示并自动降级为仅视频（不再是整条命令失败） |

授权后必须重启终端 / 应用才生效。找不到屏幕设备时程序会弹出带上述路径的提示。

## 使用方法

### macOS

1. （可选）`Choose...` 选择输出目录，默认 `~/Movies`
2. （可选）`Select Region` 拖拽框选区域，`Clear` 恢复全屏
3. 勾选 `Record camera overlay` → 点 `Preview & Position` → **把气泡拖到想要的位置、拉到想要的大小**
4. `Layout` 选择 Corner PiP 或 Speaker Left/Right
5. 按需勾选 `Microphone`，在 `Audio input` 下拉选择音频设备（默认第一个；录系统声音可选 BlackHole），再勾选 `Also save separate screen & camera files`、设置 FPS
6. `Start Recording` → 状态变为 `Preparing devices…`（后台探测摄像头/麦克风，约 1.5–4s，界面不冻结）→ 弹出 Live Preview 置顶窗口 → `Stop Recording` 结束，弹窗列出保存的文件

### Windows Pro

1. `Browse...` 选择保存文件夹（未选择时点开始会自动弹出）
2. `Capture` 选择 Full Screen / Custom Region / Window Capture（窗口模式下点 `Refresh` 刷新列表）
3. Custom Region 与 Window Capture 模式下可点 `Select Region` 进一步裁剪
4. 勾选 `Record Audio (Microphone)`、`Enable Webcam Overlay`，选择位置与大小，可用 `Preview Webcam` 确认画面
5. `Start Recording` / `Stop Recording`

### 教学录屏推荐设置（macOS）

| 设置项 | 推荐值 | 说明 |
|---|---|---|
| Capture Area | Select Region | 只框课件区域，文件更小 |
| Layout | Corner PiP | 人像不遮挡主要内容，气泡位置即录制位置 |
| Microphone | 勾选 | 录讲解语音 |
| FPS | 30 | 教学视频无需高帧率 |
| Separate files | 不勾选 | 勾选会多两路编码，明显更吃资源 |

## 输出文件

```
recording_YYYYMMDD_HHMMSS.mp4              # 主输出（合成后）
recording_YYYYMMDD_HHMMSS_screen.mp4       # macOS 勾选分轨时的纯屏幕（与主文件同区域，无人像）
recording_YYYYMMDD_HHMMSS_camera.mp4       # macOS 勾选分轨时的纯人像（可能比主文件短 0.2–0.4s）
```

Windows Pro 合并音视频前先写 `*_temp.mp4` 与 `*_audio.wav`，合并结果先写入 `*_merged.mp4`，成功后才发布最终文件并清理中间文件；失败时报告错误并保留可恢复的原始视频和音频。失败留下的 `*_merged.mp4` 可能不完整，不能视为已完成的成片。

macOS 版体积参考（`-b:v 8M` 目标码率，2026-09-18 实测本机桌面内容）：全屏 2816×1762 约 **37–67 MB/分钟**（上限≈60 MB/分钟 = 8 Mbit/s，随画面复杂度波动），区域裁剪 1280×960 约 **25 MB/分钟**，纯人像分轨（`-b:v 2M`）约 **15–18 MB/分钟**。摄像头默认按 1920×1080 采集。

Windows 版体积参考（作者提供的经验值，未在本次实测中复核）：1080p@30fps 约 100 MB/分钟。

## 系统要求

**Windows**

- Windows 10 / 11，建议 Python 3.11 / 3.12（当前依赖不支持 Python 3.8），≥2GB 可用内存
- 麦克风（录音，可选）、摄像头（人像，可选）

**macOS**

- 需授予「屏幕录制」权限的 macOS 版本（10.15+）
- `ffmpeg`（含 avfoundation 输入与 `h264_videotoolbox` 编码器）
- Python 3 + `PyQt6` + `opencv-python`
- 仅支持主显示器（坐标换算固定使用 `QGuiApplication.primaryScreen()`，ffmpeg 侧只取设备列表中第一个名字含 `Capture screen` 的设备）

**快捷键**：ESC 取消区域选择（两平台一致）。

## 已知问题与修复状态

下列历史缺陷与性能数据来自 2026-09-18 实测（环境见开头）。✅ = 已修复；⚠️ = 仍存在。2026-09-23 的生命周期改动通过自动回归验证，未重复上述真机性能测量。

### macOS 版

1. ✅ **默认 Corner PiP 布局录出 0 字节文件（致命）**
   原因：命令没有为任何输出固定帧率，而 avfoundation 屏幕输入报告 `1000k tbr`（日志 `not enough frames to estimate rate`）；PiP 的 `overlay` 把畸形帧率传给预览用的 rawvideo 输出，ffmpeg 于是疯狂复制帧去填满「100 万 fps」的时间轴——实测 8 秒内向预览管道推送 **51654 帧（6445fps，预期 30fps）**，进程无法响应停止，5 秒后被 `kill()`，三个 mp4 全部 **0.00MB / 无法解析**。Speaker 布局因 `hstack` 会重算帧率而幸免。
   修复：`build_command()` 为每个输出（主文件 / `_screen` / `_camera` / 预览管道）加 `-r <fps>`。复测：全屏 PiP+分轨 6 秒会话 → 4.87–5.83s 可播放文件，无 dup 警告。

2. ✅ **停止路径两处致命问题**
   - `stop_recording()` 执行 `self.proc.stdin.write("q")`，而 subprocess 的 stdin 是二进制管道 → 实测抛 `TypeError: a bytes-like object is required, not 'str'`，被 `except Exception` 吞掉后退回 `terminate()`；且实测**带管道摄像头输入时 ffmpeg 完全不响应 `q`**（发出后仍继续编码 11 秒），SIGTERM 才能正常收尾（`rc=255`）。
   - **二次信号打断收尾（A/B 实测）**：`stop_recording()` 发一次 SIGTERM，300ms 后 `_finalize()` 又发一次 → ffmpeg 在 flush muxer 期间被第二个信号打死，**文件有体积但没有 moov atom，无法播放**（2.10MB / 无 moov，对比单次 SIGTERM 4.04MB / dur 5.33s）。
   修复：停止只发一次 SIGTERM（`_stop_requested` 标记），`_finalize()` 仅在超时时升级；成功判定改为「退出码 ∈ {0,255} **且**文件含 moov」（`recording_succeeded()` / `_mp4_has_moov()`）。复测四种组合均为 info 弹窗 + 可播放文件。

3. ✅ **Speaker 布局 Live Preview 画面错乱**
   原因：`preview_dims()` 只按屏幕/区域尺寸推算，不含 layout；实测 speaker-right 全屏时 ffmpeg 的 `[prev]` 是 **480×142**，代码按 **480×300** 读 → 每帧字节数错误，画面持续撕裂。
   修复：预览统一 letterbox 到固定 **480×270**（`scale=480:270:force_original_aspect_ratio=decrease` + `pad`），`preview_dims()` 不再依赖几何与布局。复测四种布局预览尺寸恒为 (480,270)。

4. ✅ **摄像头帧率声明与设备实际不符 → 大量复制帧、时间轴偏慢**
   原因：管道声明 `-framerate 30`，设备实测只有 **24–28fps**（`CAP_PROP_FPS` 还谎报 15）。实测声明 30 时 `speed=0.956x`、`dup=332`；声明实测值 28 后 `speed=0.997x`、`dup=7`。
   修复：摄像头探测顺带用 `estimate_fps()` 实测交付帧率（跳过首帧预热），`pick_camera_fps()` 夹到 5–60 后作为管道输入的声明帧率；输出仍按 GUI 的 FPS 做 CFR。

5. ✅ **分轨 `_screen.mp4` 录的是全屏而非所选区域**
   原因：滤镜图先 `split` 后 `crop`，实测区域录制时主文件 1280×960 而 `_screen.mp4` 是 2816×1762。修复：改为先 `crop` 后 `split`，复测两者均为 1280×960。

6. ✅ **分轨 `_camera.mp4` 比主文件短**（已基本对齐）
   原因：管道输入没有自己的时间戳，ffmpeg 完全按声明帧率推算，而 feeder 原本是「摄像头给多快就写多快」。实测演进：未处理时主文件 9.03s / `_camera.mp4` 6.37s（短 30%）；仅修声明帧率后 5.63s vs 4.90s（短 13%）；加上 `frames_due()` 节流后 **5.44s vs 5.10s（差 0.34s）**，另一次 **5.07s vs 5.13s（差 −0.07s）**；`_screen.mp4` 与主文件差 0.00–0.04s。仍非逐帧精确（停止时不补尾帧）。

7. ⚠️ **其他实现层面的限制**（麦克风探测与音频设备选择本轮已补，见下）
   - ✅ 麦克风探测/降级：已加 `probe_audio_device()`，打不开就弹窗并降级为仅视频。实测把设备指向不存在的索引 99 → 弹出 `Microphone is unavailable — recording video only`，仍产出 5.53s 纯视频可播放文件，无错误弹窗
   - ✅ 音频设备可选：`Audio input` 下拉列出全部 avfoundation 音频设备（`parse_av_device_lists()`），录制时使用所选索引，重新探测时保留上次选择；BlackHole 因此可以在界面里选中（本次实测的是下拉能选中任意索引，未实装 BlackHole）
   - ✅ ~~探测在 GUI 线程内阻塞~~ → 见第 15 条；`probe_devices()` 的 `-list_devices` 仍在主线程（启动时约 0.2–1s）
   - ✅ `stderr` 现由后台 reader 持续读取，仅保留末尾 8 KiB，避免长录制时日志填满管道而阻塞 ffmpeg
   - ✅ ~~非 16:9 摄像头被拉伸~~ → 见第 16 条
   - 仅支持主显示器；录制中部分控件仍可点
   - 顺手修掉的：父进程泄漏管道读端 fd、`live_thread` 只 stop 不 `wait()`、`CameraPipeFeed` 中未使用的变量

### macOS 版（第二批，2026-09-18）

15. ✅ **按下 Start 会冻结界面 1.1–1.4s**
    原因：当时的 `_camera_probe()`（约 0.7–1s，第二批已并入 `probe_camera()`）与 `probe_audio_device()`（约 0.4s）都在 GUI 线程里串行执行。
    修复：`PreRecordProbe(QThread)` 在后台跑完两个探测再回调 `_on_probes_done()` 启动 ffmpeg；`start_recording()` 只做几何计算。实测 `start_recording()` **1–3ms 返回**，界面不再冻结（代价是「真正开始录制」仍要等 1.5–4s，状态栏显示 `Preparing devices…`；摄像头开启本身就慢，无法省掉）。

16. ✅ **非 16:9 摄像头被拉伸**
    原因：`CameraPipeFeed` 把每一帧都 `cv2.resize` 到 1920×1080，管道又固定声明 `-video_size 1920x1080`，4:3 画面被横向拉宽；预览气泡同样直接 resize 到 640×360。
    修复：`probe_camera()` 一次探测同时返回**实测帧率与真实分辨率**，管道按真实尺寸声明；预览改用 `letterbox()`（等比缩放 + 补边）；PiP 落位用 `clamp_pip(aspect=真实高宽比)`，保证 4:3 的画中画也完整落在画面内。实测注入 1280×960 的 4:3 摄像头 → 录出的画中画框为 **640×480（h/w = 0.750）**，而非拉伸后的 0.562。

17. ✅ **摄像头管道带宽压不住 → 成片比会话短很多**
    原因：1920×1080 的 BGR 原始帧是 **6.2MB/帧**（18fps 就要 112MB/s），Python feeder 在与界面、预览读取线程抢 GIL 时只能交付 13.2fps（声明 18.7fps）；`overlay` 要等两路输入，摄像头时间轴一落后，整段录制就被拖短——实测 **6 秒会话只录到 1.67 秒**。另外 `frames_due()` 原先「落后超过 0.5s 就重新对齐」，等于把落后的时间直接丢掉。
    修复：`pipe_camera_size()` 只在真正需要时才发全分辨率（分轨人像文件、演讲者模式），角落画中画一律缩到画中画实际宽度（640×360 = 0.69MB/帧，约 13MB/s）；`frames_due()` 改为**落后就补帧**，只有超过 2s 的卡顿才重新对齐。实测：8 秒会话成片 7.43s（**93%**），feeder 交付 20.5fps、最大落后 0.59s、重新对齐 0 次；6 秒会话成片 5.33s（89%）。

### Windows Pro 版

8. ✅ **moviepy 版本与代码 API 双向不兼容（致命）**
   实测：`moviepy==1.0.3` 下 `from moviepy import VideoFileClip` → `ImportError`（1.0.3 需 `from moviepy.editor import ...`），Pro 版**启动即失败**；`moviepy 2.1.2` 下导入成功，但 `set_audio()` / `subclip()` 已改名，且 `write_videofile()` 签名里已无 `verbose` 参数 → 勾选录音必失败、退化成无声视频。
   修复：`requirements.txt` 改 `moviepy>=2.0`；合并逻辑抽成 `merge_audio_video()`，改用 `with_audio()` / `subclipped()`、去掉 `verbose=`。复测：真实 ffmpeg 生成 1s 视频 + 1s/3s 音频，输出含 video+audio 两路，音频长于视频时被裁到 1s。

9. ✅ **录音全程缓存在内存**
   原来 `AudioRecorder` 把每个音频块 append 到 list、停止时才一次性写 wav（44.1kHz/16bit/立体声 ≈ **10.6MB/分钟**，崩溃即全丢）。现改为 `wave` 边录边写 + flush、用 `frames_written` 计数。复测：录制过程中文件已增长、对象上不再有 `frames` 列表、wav 帧数与回调次数一致。

10. ✅ **收尾预览可能抛 `UnboundLocalError`**：录制线程在循环外引用 `img`，刚点开始就停止会触发未定义变量；现初始化为 `None` 并判空。

11. ✅ **平台耦合导致模块无法在非 Windows 下导入/测试**：`ctypes.windll` 加平台守卫，`pyaudio` / `mss` / `moviepy` 改为惰性导入，`get_visible_windows()` 与 `_get_selected_window_rect()` 在其他平台抛出带指引的 `RuntimeError`。

12. ⚠️ **编码下拉与容器不匹配**（未改；macOS/OpenCV 5.0.0 实测，Windows 行为待核实）
    输出恒为 `.mp4`，实测 OpenCV 对 `XVID`、`MJPG` 报警告并静默回退：`tag 0x44495658/'XVID' is not supported with codec id 12 and format 'mp4'` → `fallback to use tag 'mp4v'`（`mp4v` 与 `XVID` 产物字节数完全相同可证回退），`H264` 回退 `avc1`。

### 依赖与仓库层面

13. ✅ **CI 不构成质量门禁** — 已修复：原来安装/测试/flake8 三步全部以 `|| true` 结尾，而且 CI 里根本没装 pytest。PR #1 首次运行的日志实测为 `line 1: pytest: command not found` → 回退的 `unittest discover` 输出 `Ran 0 tests in 0.000s / OK` → 恒绿、一个用例都没跑。现已显式安装 pytest、去掉三处 `|| true`，并补装 PyQt6 offscreen 运行所需的系统库（`libegl1`/`libgl1`/`libxkbcommon0` 等）与 `portaudio19-dev`（否则 pyaudio 在 ubuntu 上编译失败，整步安装会中断）。

14. ✅ **`requirements.txt` 的 PyQt6 pin 会让全新安装直接崩**（把 CI 改成阻断后才暴露）
    `PyQt6==6.6.1` 的元数据只声明 `PyQt6-Qt6>=6.6.0`（无上界，已查 PyPI 元数据确认），pip 于是把 **PyQt6-Qt6 6.11.2** 装在 6.6.1 的 wrapper 旁边，导入即报：
    `ImportError: PyQt6/QtGui.abi3.so: undefined symbol: _ZN5QFont11tagToStringEj, version Qt_6`。
    逐版本核对元数据：6.6.1 无上界，**6.7.0 起才有 `PyQt6-Qt6<6.8.0,>=6.7.0`** 这类同 minor 约束。
    修复：`requirements.txt` 与 `requirements-mac.txt` 均改为 `PyQt6>=6.7,<7`，并新增 `tests/test_environment.py` 校验 wrapper 与 Qt 二进制的 minor 版本一致。

## 本次修复涉及的文件

| 文件 | 改动 |
|---|---|
| `screen_recorder_mac.py` | 每个输出加 `-r`；预览固定 480×270 letterbox；停止改为单次 SIGTERM + moov 校验；摄像头实测帧率 + `frames_due()` 节流写入；先 crop 后 split；关闭泄漏的管道 fd；新增音频输入下拉与 `probe_audio_device()` 降级；抽出 `parse_av_device_lists()` / `estimate_fps()` / `pick_camera_fps()` / `frames_due()` / `probe_audio_device()` / `recording_succeeded()` / `_mp4_has_moov()` 便于测试 |
| `screen_recorder_pro.py` | moviepy 2.x API；抽出 `merge_audio_video()`；流式写 wav；平台守卫 + 惰性导入；`img` 判空 |
| `requirements.txt` / `requirements-mac.txt` | `moviepy==1.0.3` → `moviepy>=2.0`；`PyQt6==6.6.1` → `PyQt6>=6.7,<7`（6.6.x 不锁 `PyQt6-Qt6` 上界，全新安装会 ImportError） |
| `tests/` | 录制命令、设备降级、停止/关闭/异常退出、资源释放与真实媒体合并回归；真实设备测试显式启用 |
| `screen_recorder_mac.py`（第二批） | 探测移到 `PreRecordProbe` 后台线程（`start_recording()` 拆成两段）；`probe_camera()` 一次拿到帧率+分辨率；`letterbox()` 预览不变形；`pipe_camera_size()` 按需要缩小管道载荷；`frames_due()` 落后补帧；`clamp_pip()` 按真实宽高比落位；抽出 `GO_STYLE`/`STOP_STYLE` 去掉三份重复样式 |
| `.github/workflows/ci.yml` | 显式安装 pytest 与系统库，去掉三处 `\|\| true`，让测试/lint 真正阻断 |

## 测试

```bash
python -m pip install PyQt6 opencv-python numpy mss pytest "moviepy>=2"
python -m pytest -q     # 默认不访问摄像头/麦克风，3 条硬件用例会跳过

# 仅在已授权屏幕/相机/麦克风的 macOS 真机上主动运行：
python -m pytest -q --run-hardware -m hardware
```

- `tests/test_mac_command.py` — ffmpeg 命令拼装（每个输出都有 `-r`、预览固定尺寸、先 crop 后 split、分轨命名与码率、区域按 DPR 缩放、麦克风映射、Speaker 左右顺序）、avfoundation 设备列表解析（含真实 ffmpeg 8.1.2 输出与多屏/BlackHole 场景）、摄像头帧率测量与夹取、成功判定（含 moov 缺失的截断文件）
- `tests/test_mac_stop.py` / `tests/test_mac_lifecycle.py` — 重复停止只发一次 SIGTERM、异步收尾、窗口关闭、意外退出、过期会话回调隔离与真实 ffmpeg 合成媒体收尾
- `tests/test_process_output.py` — 大量子进程日志不会阻塞编码器，诊断尾部内存有界且支持非 UTF-8 字节
- `frames_due()` 节流（在 `tests/test_mac_command.py`）— 未到点不写、准点写一帧、设备慢时补帧、卡顿后重对齐而非爆发、90 帧稳定时钟不多不少
- `tests/test_pro_recording.py` — 非 Windows 可导入、音频边录边落盘且不再缓存内存、真实 moviepy 合并出带音轨的文件、音频长于视频时被裁剪
- `tests/test_pro_lifecycle.py` — BGRA 颜色、编码器/录音/合并失败、资源释放、保留原始文件、不误报成功，以及实际 QThread 的完成通知
- `tests/test_mac_devices.py` — 列出全部音频/摄像头/屏幕设备（含 BlackHole 在首位的多设备场景）、麦克风探测跟随 ffmpeg 退出码与设备索引（用桩脚本，跨平台）、无效索引在真机上返回 False、音频下拉的填充/选择/重列保持/录制中禁用
- `tests/test_mac_probes.py` — `probe_camera()` 返回实测帧率+真实分辨率（含后端损坏时返回 None）、`PreRecordProbe` 确实在非 GUI 线程跑且按需跳过、`letterbox()` 的补边位置与不变形、管道声明探测到的尺寸、feeder 按探测尺寸写入（注入假摄像头，逐字节比对未被拉伸）、落后时补帧而超长卡顿才重对齐、`pipe_camera_size()` 的四类分支
- `tests/test_environment.py` — PyQt6 wrapper 与 Qt 二进制的 minor 版本一致（防止 `PyQt6==6.6.1` + `PyQt6-Qt6 6.11` 这种装得上却导入即崩的组合）、两个录制模块都能导入

默认用例覆盖纯逻辑、模拟设备的生命周期和真实生成媒体的合并，不需要录制用户屏幕或声音。标记为 `hardware` 的 3 条用例需要 `--run-hardware`，其中一条要求相机 0 可用。完整端到端录制仍需人工验证：2026-09-18 曾人工运行 PiP+分轨、PiP+区域+分轨、Speaker Left/Right、仅屏幕，各 6 秒会话，并用 ffprobe 校验时长、分辨率与音轨。

## 性能参考

**macOS 实测**（Apple A18 Pro 6 核 / 8GB，采集 2816×1762，设定 30fps，6 秒会话，修复后）：

| 配置 | 成片时长（占会话） | Live Preview | 备注 |
|---|---|---|---|
| 仅屏幕 + 麦克风 | 5.45–5.61s（91–93%） | 27fps @480×270 | 最轻 |
| Corner PiP + 区域裁剪 + 分轨 | 5.50s（92%） | 27.5fps | 主文件与 `_screen` 均为 1280×960 |
| Speaker Left / Right | 4.97–5.53s（83–92%） | 25–27fps | 合成 3646×1080 |
| Corner PiP + 分轨（全屏，最重） | 4.87–5.83s（81–97%） | 23–26fps | 三路 VideoToolbox 编码 |
| Corner PiP（管道降到 640×360 后） | 5.33s / 6s 会话（89%）、7.43s / 8s（93%） | 25–28fps | feeder 20.5fps、最大落后 0.59s、0 次重新对齐 |

会话时长包含 ffmpeg 启动（约 0.3–0.7s）与收尾，成片略短属正常；分轨的 `_camera.mp4` 会比主文件短 0.2–0.4s。修复前对照：未固定输出帧率时 PiP 路径会出现 6445fps 的复制帧风暴、停止无响应、成片 0 字节。

预览帧率明显低于设定 FPS 说明 GUI 侧消费不过来，ffmpeg 写预览管道会被反压，长时间录制时会拖累主输出；减负手段是不勾选分轨、缩小采集区域。全分辨率摄像头管道也可能成为瓶颈，Corner PiP 在不保存分轨时已按实际画中画宽度缩小传输尺寸。

**Windows CPU 占用**（作者提供的经验值，本次未复核）：

| 分辨率 | FPS | 音频 | 摄像头 | CPU 占用 |
|---|---|---|---|---|
| 1920×1080 | 30 | 无 | 无 | 15–25% |
| 1920×1080 | 30 | 有 | 有 | 25–40% |
| 1920×1080 | 60 | 有 | 有 | 40–60% |
| 2560×1440 | 30 | 有 | 有 | 35–55% |
| 窗口捕获（小窗口） | 30 | 有 | 有 | 15–30% |

## 故障排除

### macOS

| 现象 | 原因 / 处理 |
|---|---|
| 弹窗 `ffmpeg not found` | `brew install ffmpeg`，然后重启程序 |
| 状态栏 `screen NOT found` | 未授予「屏幕录制」权限；授权后重启终端与程序 |
| 录出的文件 0 字节 / 打不开 | 曾是已知问题 1/2（已修复）；若仍出现，检查磁盘空间与 ffmpeg 是否被系统 kill |
| 点 Stop 后弹窗 `Recording failed` | `_finalize` 要求退出码 ∈ {0,255} **且**文件含 moov atom；弹窗内会附 ffmpeg 输出末尾 800 字符 |
| Live Preview 画面撕裂 | 曾是已知问题 3（已修复：预览固定 480×270 letterbox） |
| 成片动作卡顿、时长略短于实际录制 | 曾是已知问题 4（已修复）；短片仍会少 0.3–0.7s 的 ffmpeg 启动时间 |
| 弹窗 `Microphone is unavailable — recording video only` | 探测到该音频设备打不开（多为麦克风权限未授予或被占用）；已自动降级为仅视频，授权后在 `Audio input` 里重选即可 |
| 按下 Start 后要等几秒才开始录 | 正常：后台在探测摄像头与麦克风（`Preparing devices…`），摄像头开启本身就要 1–3s；界面此时不会冻结 |
| 气泡里显示 `Camera unavailable` | 摄像头被其他程序占用或未授予相机权限 |
| 想录系统内部声音 | macOS 限制，无法直接录制；装 BlackHole 并配置「多输出设备」后，可在 `Audio input` 下拉里选中它 |

### Windows

| 现象 | 原因 / 处理 |
|---|---|
| Pro 版启动报 `ImportError: cannot import name 'VideoFileClip'` | 装的是 moviepy 1.x；`pip install -U "moviepy>=2"`（已知问题 8，已修复） |
| 录完报告合并失败 | 查看弹窗中的编码错误，确认 MoviePy 2.x 与磁盘空间；原始 `*_temp.mp4` / `*_audio.wav` 会保留供恢复，`*_merged.mp4` 可能是不完整文件 |
| PyAudio 安装失败 | `pip install pipwin && pipwin install pyaudio` |
| 程序无法启动 | 建议使用 Python 3.11 / 3.12，并按 requirements.txt 安装依赖 |
| 视频无声音 | 确认勾选了 `Record Audio (Microphone)` 且麦克风权限已开 |
| 摄像头画面不显示 / 预览黑屏 | 摄像头被占用或未连接 |
| 窗口列表为空 | 点 `Refresh`；仅列出标题非空且大于 50×50 的可见窗口 |
| 长时间录音后内存暴涨 | 曾是已知问题 9（已修复：改为边录边写 wav） |
| CPU 占用过高 | 降低 FPS，或改用 Window Capture 只录小窗口 |

## 技术架构

**Windows（基础版 / Pro 版）**

```
┌──────────────────────────────────────────────────────────┐
│                  PyRecorder GUI (PyQt6)                   │
│              ┌──────────┬───────────────────┐             │
│              │ Settings │   Live Preview    │  ← Pro 版    │
│              └──────────┴───────────────────┘             │
├──────────────────────────────────────────────────────────┤
│                   录制线程 (QThread)                       │
├─────────────┬──────────────┬─────────────────────────────┤
│ mss         │ OpenCV       │ PyAudio (Pro)                │
│ 屏幕/区域   │ 摄像头采集   │ 音频 → 流式写入 wav          │
├─────────────┴──────────────┴─────────────────────────────┤
│      numpy 画中画叠加 + OpenCV VideoWriter 编码            │
├──────────────────────────────────────────────────────────┤
│      MoviePy 2.x 音视频合并（Pro 版）                      │
└──────────────────────────────────────────────────────────┘
```

**macOS**

```
┌──────────────────────────────────────────────────────────┐
│              PyRecorder for macOS GUI (PyQt6)             │
│  Output / Capture Area / Camera PiP / Options / Status    │
├───────────────┬──────────────────────┬───────────────────┤
│ 气泡定位      │ CameraPipeFeed       │ LivePreviewThread │
│ PipPreview    │ OpenCV(AVFoundation) │ 读 ffmpeg 的      │
│ Window        │ → 原始 BGR 帧        │ rawvideo 预览流   │
│               │ → os.pipe            │                   │
├───────────────┴──────────────────────┴───────────────────┤
│   一个 ffmpeg 子进程：avfoundation 屏幕+麦克风 / 管道摄像头 │
│   filter_complex: crop → overlay | hstack → split(预览)   │
│   h264_videotoolbox 硬件编码 → mp4（可另出分轨文件）       │
└──────────────────────────────────────────────────────────┘
停止：单次 SIGTERM → ffmpeg flush muxer → rc=255 → 校验 moov 后收尾
```

## 相关文档

- [开发与分支](CONTRIBUTING.md) — 分支命名、PR 合并和清理约定、本地验证与真机测试。
- `docs/macos-research.md` — macOS 支持调研报告（调研日期 2026-09-03）：Windows 耦合点梳理、QuickTime/OBS/Kap/Cap/Screen Studio 对比、三种实现方案（mss+OpenCV / **ffmpeg+avfoundation** / 原生 ScreenCaptureKit）与落地路线。文中"~10MB/min"为方案阶段的估算，与当前代码的 `-b:v 8M`（实测 25–67MB/min，见[输出文件](#输出文件)）不符。

## CI

`.github/workflows/ci.yml` 在 push / PR 到 `main`、`master` 时运行 Ubuntu + Python 3.11 / 3.12 矩阵：安装系统库（PyQt6 offscreen 所需 + portaudio + ffmpeg）与 `requirements.txt` → `python -m pytest -q` → flake8（`E9,F63,F7,F82`）。测试与 lint 都是**阻断性**的，每个任务最多运行 10 分钟；CI 不启用真实硬件测试。Windows 原生捕获和 macOS 权限/设备仍需要各平台真机验收。

本分支之前 CI 恒绿：三步都带 `|| true`，且 runner 里没有 pytest。PR #1 首次运行的实测日志：

```
line 1: pytest: command not found
Ran 0 tests in 0.000s
OK
```

改成阻断后连跑三次的实测结果（ubuntu-latest / Python 3.11）：

| run | 结果 | 说明 |
|---|---|---|
| 35316018466 | `success`（假绿） | `pytest: command not found` → `Ran 0 tests` → `OK` |
| 35316516581 | **`failure`** | 装上了 pytest，暴露 `PyQt6 6.6.1 + PyQt6-Qt6 6.11.2` 的 ABI 崩溃（已知问题 14） |
| 35317091089 | `success` | `30 passed, 4 skipped` —— ffmpeg 缺失，4 个 fixture 用例被跳过 |
| 35317276962 | `success` | 补装 ffmpeg 后 **`34 passed in 1.89s`**，flake8 `--count` 输出 `0` |

第一次真正阻断的运行就抓到真实缺陷：`PyQt6==6.6.1` 与 pip 解析出的 `PyQt6-Qt6 6.11.2` ABI 不匹配（已知问题 14）——这类问题在 `|| true` 下永远不会暴露。

CI 覆盖的是纯逻辑用例（命令拼装、设备解析、帧率测量、停止路径、真实 moviepy 合并、依赖一致性）；需要屏幕录制权限、真实摄像头与窗口系统的 macOS 端到端验证无法在 CI 中运行，详见[测试](#测试)。

## 许可证

MIT License（见 `LICENSE`）

## GitHub

https://github.com/CacinieP/PyRecorder
