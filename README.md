# PyRecorder

基于 PyQt6 的录屏工具，含 **Windows** 与 **macOS** 两套实现。支持全屏 / 自定义区域录制、摄像头人像画中画（PiP）、麦克风录音。

> ## ⚠️ 状态速览（2026-09-18 实测）
>
> | 版本 | 状态 | 说明 |
> |---|---|---|
> | Windows 基础版 `screen_recorder.py` | ✅ 可用 | 仅屏幕录制，代码与文档一致 |
> | Windows Pro 版 `screen_recorder_pro.py` | ❌ 启动即失败 | 按 `requirements.txt`（moviepy 1.0.3）安装时 `from moviepy import VideoFileClip` 直接 ImportError；换 moviepy 2.x 则录音合并必失败（详见[已知问题](#已知问题已验证)） |
> | macOS 版 `screen_recorder_mac.py` | ⚠️ 部分可用 | **默认 Corner PiP 布局录出 0 字节文件**；Speaker 布局能得到可播放文件，但复制帧很多（画面卡顿）、实时预览画面错乱 |
>
> 实测环境：macOS 26.6.2 / Apple A18 Pro（6 核，8GB）/ ffmpeg 8.1.2 / Python 3.13.13 / PyQt6 6.11.0 / opencv 5.0.0；屏幕采集分辨率 2816×1762。
> 结论与复现数据见 [已知问题](#已知问题已验证) 与 [修复方向](#修复方向已验证)。

## 版本与平台

| 文件 | 平台 | 捕获方式 | 麦克风 | 人像 PiP | 录制后端 | 音视频合并 |
|---|---|---|---|---|---|---|
| `screen_recorder.py` | Windows | 全屏 / 自定义区域 | ❌ | ❌ | mss + OpenCV `VideoWriter` | — |
| `screen_recorder_pro.py` | Windows | 全屏 / 自定义区域 / **窗口捕获** | ✅ PyAudio | ✅ 四角 + 尺寸 | mss + OpenCV `VideoWriter` | MoviePy 重编码 |
| `screen_recorder_mac.py` | macOS | 全屏 / 自定义区域 | ✅ ffmpeg avfoundation | ✅ 可拖拽气泡 / 演讲者模式 | **ffmpeg + VideoToolbox 硬件编码** | 无需合并（单进程直接输出） |

`screen_recorder_pro.py` 在导入阶段就使用 `ctypes.windll.user32`，只能在 Windows 上运行；`screen_recorder_mac.py` 依赖 macOS 的 AVFoundation / VideoToolbox。两者都没有做平台判断，在错误的平台上会直接报错。

## 功能特点

### Windows 基础版

- 全屏或自定义区域录制（拖拽框选，ESC 取消）
- 帧率可调（10–60 FPS，默认 30）
- 编码下拉：`mp4v` / `XVID` / `H264` / `MJPG`（**输出文件名恒为 `.mp4`**，不生成 AVI；实测部分 fourcc 在 mp4 容器中不被支持，见[已知问题](#已知问题已验证)）
- 帧计数 + 录制时长显示，录制结束后弹窗汇总
- 自动时间戳文件名

### Windows Pro 版

在基础版之上增加（编码下拉为 `mp4v` / `XVID` / `MJPG`，比基础版少 `H264`）：

- **窗口捕获** — 通过 Win32 `EnumWindows` 列出可见窗口（标题 > 60 字符会截断显示），可在窗口内再裁剪子区域；录制开始时固定窗口位置，录制中移动窗口不会跟随
- **麦克风录音** — PyAudio，44.1kHz / 16bit / 立体声，录制结束后用 MoviePy 与视频合并
- **摄像头画中画** — 4 个位置（右下 / 左下 / 左上 / 右上），宽度 100–640px（默认 240），numpy 直接覆盖像素；摄像头打不开时自动跳过 PiP
- **摄像头预览** — 独立置顶对话框
- **实时录制预览** — 主窗口右侧面板，约 5fps（`fps // 5` 抽帧）
- 双栏界面（左设置 / 右预览），最小窗口 960×660

### macOS 版

- 全屏 / 自定义区域录制（半透明遮罩拖拽框选，显示实时尺寸，ESC 取消）
- **单条 ffmpeg 命令**同时完成：屏幕采集（含光标与鼠标点击）+ 摄像头叠加 + 麦克风 AAC，VideoToolbox 硬件编码直接输出 H.264 MP4，**无需后期合并**
- **摄像头气泡（Corner PiP）**：点击 `Preview & Position` 弹出置顶气泡，可拖到屏幕任意位置、右下角拖拽缩放（锁定 16:9）、`+ / −` 按钮档位缩放（气泡宽度范围 120–800px；主界面的 Default size 只决定气泡初始宽度，范围 120–640px，气泡打开后该输入框失效）。**气泡在屏幕上的位置和大小就是录制时的 PiP 位置和大小**
- **演讲者模式（Speaker Left / Right）**：人像与屏幕内容**等高（均缩放到 1080 高）横向并排**，各自保留原宽高比（实测本机：屏幕 1726×1080 + 人像 1920×1080 → 合成 3646×1080），参考腾讯会议「演讲者模式」；此布局下气泡位置/大小不生效
- **Live Preview**：录制期间自动弹出置顶窗口显示合成后的最终画面（无开关，恒定开启）
- **分轨保存**（可选）：除合成的 `recording_*.mp4` 外，另存纯屏幕 `_screen.mp4`（8 Mbit/s）与纯人像 `_camera.mp4`（2 Mbit/s）
- 麦克风开关、FPS 10–60（默认 30）、输出目录可选（默认 `~/Movies`）
- 摄像头由 **OpenCV 的 AVFoundation 路径**采集后通过管道喂给 ffmpeg，绕开 ffmpeg 自带摄像头输入在部分设备上输出冻结帧的问题；录制前会先探测摄像头，不可用时弹窗降级为「仅屏幕（+麦克风）」
- 摄像头不可用时不影响录屏；**麦克风没有探测与降级逻辑**（设备存在即写入命令）

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

`start.bat` 显示的版本号为 2.0.0。Pro 版额外需要 `pyaudio`、`moviepy`；若 PyAudio 装不上可用 `pip install pipwin && pipwin install pyaudio`。

> ⚠️ `requirements.txt` 钉的 `moviepy==1.0.3` 与 Pro 版代码的导入方式不兼容，**当前 Pro 版无法正常启动**，详见[已知问题](#已知问题已验证)。

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
| 麦克风 | 勾选 Microphone 时 | ffmpeg 打开音频设备失败，**整条命令失败** |

授权后必须重启终端 / 应用才生效。找不到屏幕设备时程序会弹出带上述路径的提示。

## 使用方法

### macOS

1. （可选）`Choose...` 选择输出目录，默认 `~/Movies`
2. （可选）`Select Region` 拖拽框选区域，`Clear` 恢复全屏
3. 勾选 `Record camera overlay` → 点 `Preview & Position` → **把气泡拖到想要的位置、拉到想要的大小**
4. `Layout` 选择 Corner PiP 或 Speaker Left/Right
5. 按需勾选 `Microphone`、`Also save separate screen & camera files`，设置 FPS
6. `Start Recording` → 弹出 Live Preview 置顶窗口 → `Stop Recording` 结束，弹窗列出保存的文件

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
| Layout | Corner PiP | 人像不遮挡主要内容（**注意当前该布局有致命 bug**，修复前可先用 Speaker Right） |
| Microphone | 勾选 | 录讲解语音 |
| FPS | 30 | 教学视频无需高帧率 |
| Separate files | 不勾选 | 勾选会多两路编码，明显更吃资源 |

## 输出文件

```
recording_YYYYMMDD_HHMMSS.mp4              # 主输出（合成后）
recording_YYYYMMDD_HHMMSS_screen.mp4       # macOS 勾选分轨时的纯屏幕
recording_YYYYMMDD_HHMMSS_camera.mp4       # macOS 勾选分轨时的纯人像
```

Windows 版在合并音视频时会先写 `*_temp.mp4` 与 `*_audio.wav`，成功后删除；合并失败则把 `*_temp.mp4` 改名为最终文件（**结果是无声视频**）。

macOS 版体积参考（`-b:v 8M` 目标码率，实测本机 2816×1762 桌面内容）：主文件约 **40–50 MB/分钟**，纯人像分轨（`-b:v 2M`）约 **15 MB/分钟**。摄像头默认按 1920×1080 采集。

Windows 版体积参考（作者提供的经验值，未在本次实测中复核）：1080p@30fps 约 100 MB/分钟。

## 系统要求

**Windows**

- Windows 10 / 11，Python 3.8+，≥2GB 可用内存
- 麦克风（录音，可选）、摄像头（人像，可选）

**macOS**

- 需授予「屏幕录制」权限的 macOS 版本（10.15+）
- `ffmpeg`（含 avfoundation 输入与 `h264_videotoolbox` 编码器）
- Python 3 + `PyQt6` + `opencv-python`
- 仅支持主显示器（坐标换算固定使用 `QGuiApplication.primaryScreen()`，ffmpeg 侧只取设备列表中第一个名字含 `Capture screen` 的设备）

**快捷键**：ESC 取消区域选择（两平台一致）。

## 已知问题（已验证）

以下问题均在 2026-09-18、macOS 26.6.2 + ffmpeg 8.1.2 + Python 3.13.13 环境下实测复现（Windows 项在 macOS 上以依赖版本实测 + 代码审阅方式确认，标注见各条）。

### macOS 版

1. **默认 Corner PiP 布局录出 0 字节文件（致命）**
   ffmpeg 命令没有为任何输出固定帧率，而 avfoundation 屏幕输入报告的是 `1000k tbr`（日志：`not enough frames to estimate rate`）。PiP 的 `overlay` 滤镜会把这个畸形帧率传给预览用的 `rawvideo` 输出，ffmpeg 于是疯狂复制帧去填满「100 万 fps」的时间轴：实测 8 秒内向预览管道推送 **51654 帧（6445 fps，预期 30fps）**，进程无法响应停止请求，5 秒后被 `kill()`，三个 mp4 全部 **0.00MB / 无法解析**。
   Speaker 布局因为 `hstack` 会重算帧率而不触发该问题。

2. **停止逻辑写的是 `str`，“优雅停止”实际是死代码**
   `stop_recording()` 执行 `self.proc.stdin.write("q")`，而 subprocess 的 stdin 是二进制管道 → 实测抛 `TypeError: a bytes-like object is required, not 'str'` → 被 `except Exception` 吞掉并退回 `terminate()`（SIGTERM）。
   另外即使把这行改成 `b"q"` 也不解决问题：实测**带管道摄像头输入时 ffmpeg 完全不响应 `q`**（发出 `q` 后仍继续编码 11 秒不退出），而 300ms 后触发的 `_finalize()` 同样会发 SIGTERM。
   好消息是 SIGTERM 能正常收尾（实测 `rc=255`，文件可播放，5.0 秒会话得到 4.31 秒视频），而 `_finalize()` 的判定白名单恰好包含 255 → 停止路径实际靠信号走通。但一旦命中问题 1 的复制帧风暴，ffmpeg **5 秒内不响应 SIGTERM** → 走到 `kill()` → 0 字节文件（已实测复现）。

3. **Speaker 布局的 Live Preview 画面错乱**
   `preview_dims()` 只按屏幕/区域尺寸推算，不含 layout 参数。实测 speaker-right 全屏时 ffmpeg 的 `[prev]` 实际是 **480×142**，而代码按 **480×300** 读取 → 每帧读取字节数错误，画面持续撕裂/滚动。（Corner PiP 与自定义区域下两者一致：480×300 / 480×360 ✅）

4. **摄像头帧率声明与设备实际不符 → 大量复制帧、时间轴偏慢**
   摄像头管道声明 `-framerate 30`，但设备实测只能交付 **24–28fps**（`CAP_PROP_FPS` 还谎报 15）。管道输入的时间戳按声明帧率生成，与屏幕输入的实时时钟对不上：声明 30（当前代码）时 15.0s 会话 → `speed=0.956x`、**`dup=332`**（全片 431 帧）、成片 14.37s；把声明值改成实测的 28 → `speed=0.997x`、**`dup=7`**、成片 14.63s。此外合成/预览通道在本机也跑不满 30fps（打上修复补丁后实测预览仅 17–23fps），画面仍有顿挫；成片时长总会略短于会话时长（还叠加 ffmpeg 启动开销）。

5. **分轨 `_camera.mp4` 明显比主文件短**
   同一次录制实测（已打上下方修复补丁的情况下仍存在）：主文件 9.03s / 271 帧、`_screen.mp4` 9.03s / 271 帧，而 `_camera.mp4` 只有 **6.37s / 191 帧**（摄像头流未与合成时间轴对齐）。

6. **其他实现层面的问题（代码审阅）**
   - 麦克风没有探测/降级：只判断设备是否存在，权限或设备异常时整条 ffmpeg 命令失败（摄像头有 `_camera_probe()`，麦克风没有）
   - 音频设备固定取 avfoundation 列表中的**第一个**，界面无设备选择；因此"装 BlackHole 后切换输入设备"在当前实现下无法通过界面完成
   - `_camera_probe()` 在 GUI 线程内最多阻塞约 1 秒（10 次 × 0.1s）；`probe_devices()` 的 `ffmpeg -list_devices` 同样在主线程
   - 父进程从不关闭管道读端 `cam_pipe_fd`（每次录制泄漏一个 fd）；`live_thread` 只调 `stop()` 不 `wait()`
   - `stderr` 用 PIPE 但录制期间不读取，只在结束时 `read()`；实测 30 秒仅约 1KB，短期无溢出风险，但属于潜在阻塞点
   - 摄像头帧按 `cap.read()` 的速度直写管道，无节流、无时间戳（问题 4 的根因）；非 16:9 的摄像头会被强行拉伸到 1920×1080
   - 仅支持主显示器；`RegionSelector` 与 PiP 坐标换算都基于 `primaryScreen()`
   - 录制中只禁用部分控件（输出目录 `Choose...`、Default size 仍可点）

### Windows Pro 版

7. **moviepy 版本与代码 API 双向不兼容（致命）** — 实测
   - `requirements.txt` 钉 `moviepy==1.0.3`：代码写的是 `from moviepy import VideoFileClip, AudioFileClip`，实测在 1.0.3 下抛 `ImportError: cannot import name 'VideoFileClip' from 'moviepy'`（1.0.3 需 `from moviepy.editor import ...`）→ **模块导入即失败，Pro 版启动不了**
   - 改装 `moviepy 2.1.2`：导入成功，但代码用的 `video_clip.set_audio()` 与 `audio_clip.subclip()` 实测已不存在（2.x 改名为 `with_audio()` / `subclipped()`）→ 勾选录音后合并必然抛异常，被捕获后回退为**无声视频** + 错误弹窗
   - 结论：不存在能同时满足这两处调用的 moviepy 版本

8. **录音全程缓存在内存**（代码审阅）
   `AudioRecorder` 把所有音频块 `append` 到 `self.frames` 列表，直到停止才一次性写 wav。44.1kHz / 16bit / 立体声 ≈ **10.6 MB/分钟**（≈635 MB/小时）。旧版 README 声称"内存占用稳定，不随录制时间增长""录制时长无限制"，与实际实现不符。

9. **编码下拉与容器不匹配** — macOS/OpenCV 5.0.0 实测（Windows 行为待核实）
   输出文件名恒为 `.mp4`，实测 OpenCV 对 `XVID`、`MJPG` 报警告并静默回退：
   `tag 0x44495658/'XVID' is not supported with codec id 12 and format 'mp4'` → `fallback to use tag 'mp4v'`（`mp4v` 与 `XVID` 产物字节数完全相同，可证回退）。`H264` 回退为 `avc1`。旧版 README 的"MP4, AVI""MJPG 无损压缩"表述不准确（MJPG 为逐帧 JPEG，有损）。

10. **Pro 版收尾预览可能抛 `UnboundLocalError`**（代码审阅）：录制线程在循环外引用循环变量 `img`，若刚点开始就立刻停止（一帧都没抓到），会触发未定义变量异常。

### 仓库层面

11. **CI 不构成质量门禁**：`.github/workflows/ci.yml` 的安装、测试、flake8 三步全部以 `|| true` 结尾，且仓库内没有任何测试文件（`pytest` / `unittest discover` 都会空跑）→ 无论代码状态如何都是绿灯。

## 修复方向（已验证）

macOS 版按下面四点改，实测三种组合（PiP+分轨 / Speaker / PiP+区域）均能产出可播放文件、预览帧率与尺寸正确、`rc=255` 正常收尾：

1. **给每个输出固定帧率**：在 `build_command()` 里为主输出、`_screen.mp4`、`_camera.mp4` 与预览 `pipe:1` 都加上 `-r <fps>`（解决问题 1；实测加上后无 dup 警告、三个 mp4 均可播放，仅屏幕路径 `speed=0.987x`）
2. **停止改用 SIGTERM**：删掉必然抛 `TypeError` 的 `write("q")`，直接依赖 `_finalize()` 的 `terminate()`，并适当放宽 5 秒等待窗口（解决问题 2）
3. **`preview_dims()` 增加 layout 参数**：speaker 布局需按 `hstack` 后的合成宽度计算（屏幕缩放到 1080 高后的宽度 + 1920），实测应为 480×142（全屏）而非 480×300（解决问题 3）
4. **摄像头帧率对齐**：录制前实测摄像头交付帧率（`_camera_probe()` 已经在读 10 帧，顺手计时即可），用实测值作为管道输入的 `-framerate`，或在 feeder 中按时钟补帧（解决问题 4；实测声明值改为 28 后 `dup` 从 332 降到 7、`speed` 从 0.956x 升到 0.997x）。问题 5 还需对 `_camera.mp4` 输出单独做 CFR 对齐

Windows Pro 版最小修复：`requirements.txt` 改为 `moviepy>=2`，并把 `set_audio(...)` → `with_audio(...)`、`subclip(...)` → `subclipped(...)`；音频改为边录边写 wav（`wave` 支持流式写入）以消除内存增长。

## 性能参考

**macOS 实测**（Apple A18 Pro 6 核 / 8GB，采集 2816×1762，30fps，均为 5–15 秒短录制）：

| 配置 | 实测结果 | 备注 |
|---|---|---|
| 仅屏幕 + 麦克风（无摄像头、无预览；已加 `-r`） | `speed=0.987x`，5.0s 会话得到 5.06s 成片，`rc=0`（`q` 可正常停止） | 最轻的可用路径 |
| 屏幕 + 摄像头 + 预览（已加 `-r`，PiP） | 预览 17–20fps，成片 9.03s / 会话 10.0s | 2816×1762 原始帧约 9.9MB/帧，带宽是主要开销 |
| 屏幕 + 摄像头 + 预览（已加 `-r`，Speaker） | 预览 23fps，成片 8.77s / 会话 10.0s | 合成宽度 3646×1080 |
| 再叠加「分轨保存」 | 预览降到 ~15fps | 多两路 VideoToolbox 编码 |
| 未加 `-r`（当前代码，PiP） | 预览管道 6445fps 的复制帧风暴，停止无响应，成片 0 字节 | 见已知问题 1 |

预览帧率明显低于设定 FPS 说明 GUI 侧消费不过来；ffmpeg 写预览管道会被反压，长时间录制时会拖累主输出。减负手段：不勾选分轨、缩小采集区域。摄像头一路（1920×1080 原始帧经 Python 管道）本身不是瓶颈——实测 feeder 稳定交付 24–28fps。

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
| 录出的文件 0 字节 / 打不开 | 命中已知问题 1（Corner PiP 布局）；改用 Speaker 布局，或按[修复方向](#修复方向已验证)打补丁 |
| 点 Stop 后弹窗 `Recording failed` 但文件存在 | `_finalize` 只接受返回码 0/255；被 `kill()` 时为 -9 |
| Live Preview 画面撕裂 | 命中已知问题 3（Speaker 布局预览尺寸算错） |
| 成片动作卡顿、时长略短于实际录制 | 命中已知问题 4（摄像头帧率声明不符，大量复制帧） |
| 勾选 Microphone 后整段录制失败 | ffmpeg 打不开音频设备（多为麦克风权限未授予）；取消勾选可继续录屏 |
| 气泡里显示 `Camera unavailable` | 摄像头被其他程序占用或未授予相机权限 |
| 想录系统内部声音 | macOS 限制，无法直接录制；需 BlackHole 等虚拟声卡，且当前版本没有音频设备选择界面（已知问题 6） |

### Windows

| 现象 | 原因 / 处理 |
|---|---|
| Pro 版启动报 `ImportError: cannot import name 'VideoFileClip'` | 已知问题 7：moviepy 1.0.3 与代码不兼容 |
| 录完提示 `Failed to merge audio/video` 且视频无声 | 已知问题 7：moviepy 2.x 的 API 改名 |
| PyAudio 安装失败 | `pip install pipwin && pipwin install pyaudio` |
| 程序无法启动 | 确认 Python ≥ 3.8、依赖已装齐 |
| 视频无声音 | 确认勾选了 `Record Audio (Microphone)` 且麦克风权限已开 |
| 摄像头画面不显示 / 预览黑屏 | 摄像头被占用或未连接 |
| 窗口列表为空 | 点 `Refresh`；仅列出标题非空且大于 50×50 的可见窗口 |
| 长时间录音后内存暴涨 | 已知问题 8：音频全量缓存在内存 |
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
│ 屏幕/区域   │ 摄像头采集   │ 音频 → 内存 → wav            │
├─────────────┴──────────────┴─────────────────────────────┤
│      numpy 画中画叠加 + OpenCV VideoWriter 编码            │
├──────────────────────────────────────────────────────────┤
│      MoviePy 音视频合并（Pro 版，当前不可用）              │
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
停止：stdin 写 "q"（抛 TypeError）→ 实际走 SIGTERM → rc=255 → 收尾
```

## 相关文档

- `docs/macos-research.md` — macOS 支持调研报告（调研日期 2026-09-03）：Windows 耦合点梳理、QuickTime/OBS/Kap/Cap/Screen Studio 对比、三种实现方案（mss+OpenCV / **ffmpeg+avfoundation** / 原生 ScreenCaptureKit）与落地路线。文中"~10MB/min"为方案阶段的估算，与当前代码的 `-b:v 8M`（实测 40–50MB/min）不符。

## CI

`.github/workflows/ci.yml` 在 push / PR 到 `main`、`master` 时运行：安装依赖 → `pytest`（仓库无测试）→ flake8（`E9,F63,F7,F82`）。三步均带 `|| true`，因此**当前 CI 恒为绿灯，不能作为质量门禁**（已知问题 11）。

## 许可证

MIT License（见 `LICENSE`）

## GitHub

https://github.com/CacinieP/PyRecorder
