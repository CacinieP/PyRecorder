# 已知问题与修复档案（历史实测）

> 本档案记录 legacy 三件套时期逐项实测的缺陷与修复（2026-09 至 2026-11）。
> 统一包 `pyrecorder` **继承了全部修复**——pacing、moov 校验、单次 SIGTERM、
> 预览固定画布、摄像头实测帧率、管道降载、设备探测降级等逻辑都是从这里移植的，
> 模块对应关系见 [architecture.md](architecture.md#与-legacy-的对应关系)。
> 下文提到的 `screen_recorder_mac.py` 等文件现位于 `legacy/`。

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

## 性能参考

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

