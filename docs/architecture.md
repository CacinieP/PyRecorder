# 架构

> 一条 ffmpeg 命令吃进三路输入，吐出一个 MP4（外加可选分轨和预览流）。
> 平台差异只存在于「输入怎么来」，其余全部共享。

## 录制管线

```
                ┌─────────────────── 平台后端 (platforms/) ───────────────────┐
                │                                                                │
   macOS        │  avfoundation:  "-i <screen>:<mic>"  （光标含在内，麦克风同路）   │
   Win/Linux    │  mss ──BGRA──▶ ScreenPipeFeed ──通道(管道/TCP)──┐  dshow/pulse │
                └─────────────────────────────────────────────────┼─────────────┘
                                                                           │
   所有平台     │  OpenCV ──BGR──▶ CameraPipeFeed ──通道(管道/TCP)──┐        │
                └──────────────────────────────────────────────────┼────────┤
                                                                     ▼        ▼
   ffmpeg 单进程:  [screen] ─crop/even-guard→ ─split→ ┐
                   [camera] ─scale→ ─overlay/hstack→ filter_complex ─→ H.264 + AAC ─→ recording_*.mp4
                                                             │
                                                             ├─→ _screen.mp4 / _camera.mp4 （可选分轨）
                                                             └─→ 480×270 rgb24 预览流 ─→ LivePreviewWindow
```

### 通道（channels/）：馈送线程 → ffmpeg 的字节流

Windows 的 subprocess **不支持 `pass_fds`**（CI 实测 AssertionError），所以馈送通道按平台二选一
（`pyrecorder/channels.py`）：

- **POSIX**：`os.pipe` + `pass_fds`，ffmpeg 读 `pipe:N`（legacy 验证过的原路径）
- **Windows**：ffmpeg 监听回环地址，输入写 `tcp://127.0.0.1:<port>?listen=1`，馈送线程连上去
  `sendall`——ffmpeg 内建协议、字节数学完全一致、回环绑定不触发防火墙弹窗

关键不变量（每一条都有测试或实测数据背书，见 [known-issues.md](known-issues.md)）：

- **每个输出都显式 `-r <fps>`**：avfoundation 会报 `1000k tbr`，不固定帧率会触发复制帧风暴（曾 8 秒推 51654 帧、成片 0 字节）
- **管道没有时间戳**：feeder 必须按声明帧率节流（`frames_due()`：落后补帧、>2s 卡顿才重对齐），否则成片比会话短
- **停止 = EOF 优先，信号兜底**：先停所有馈送线程（关闭通道 → 全部 rawvideo 输入 EOF）→ ffmpeg 自行排空滤镜图并写 moov 干净退出（真 ffmpeg 实测退出码 0，且这是 Windows 上唯一能落盘 trailer 的停止方式——TerminateProcess 是硬杀）；5 秒未退再发 SIGTERM/CTRL_BREAK，15 秒才 kill。成功判定 = 退出码 ∈ {0,255} **且** moov 存在
- **GUI 线程永不阻塞**：设备枚举、录制前探测、ffmpeg 收尾全部在后台线程/定时器轮询
- **降级优于失败**：摄像头/麦克风探测不过 → 弹窗 + 去掉该路继续录；屏幕不可用才中止

## 模块分层

```
pyrecorder/
├── ffmpeg_exe.py      ffmpeg 定位（PATH → 常见路径 → imageio-ffmpeg）+ stderr 排水（ProcessOutputReader）
├── pacing.py          frames_due / estimate_fps —— 管道节流的全部数学
├── mp4check.py        moov box 遍历 + 成功判定
├── command.py         build_command(): 平台无关的滤镜图与输出组装（输入用 spec 对象描述）
├── channels.py        馈送线程→ffmpeg 的字节流通道：POSIX 管道 / Windows 回环 TCP 监听
├── camera.py          OpenCV 摄像头：探测（帧率+分辨率）、预览线程、录制馈送线程、letterbox/clamp
├── screenfeed.py      mss 屏幕馈送（Win/Linux）：BGRA 直通管道，无逐帧 numpy 转换
├── platforms/
│   ├── base.py        Backend 基类：设备枚举 / 输入参数 / 编码器 / 权限提示 / 坐标转换
│   ├── macos.py       avfoundation（解析 ffmpeg 真实输出）+ VideoToolbox
│   ├── windows.py     dshow（设备名带引号转义）+ mss + ClientToScreen 混合 DPI 处理
│   └── linux.py       pulse（pactl 枚举，无 pactl 回退 default）+ mss + Wayland 显式拒绝
└── ui/
    ├── main_window.py RecorderWindow：idle→probing→recording→stopping→finalizing 状态机
    ├── region.py      全屏框选遮罩（按平台输出逻辑/物理坐标）
    ├── bubble.py      可拖拽摄像头气泡（几何 = 录制 PiP 位置）
    ├── live.py        480×270 固定画布实时预览
    └── app.py         入口（console script / python -m pyrecorder）
```

依赖方向严格单向：`ui → command/camera/screenfeed/platforms → pacing/mp4check/ffmpeg_exe`。
`command.py` 不 import 任何平台模块——平台只提供输入描述（`NativeScreenInput` /
`PipeScreenInput` / `ExtraAudioInput` / `CameraInput` dataclass），这让命令组装可以在
任何平台上针对任何平台做单元测试。

## 平台后端接口（platforms/base.py）

| 方法 | 职责 | mac | Win | Linux |
|---|---|---|---|---|
| `screen_capture_kind()` | native / mss_pipe | native | mss_pipe | mss_pipe |
| `check_screen()` | 可用性 + 失败指引 | avfoundation 列表 | mss.monitors | Wayland 检查 + mss |
| `native_screen_args(fps, mic)` | 原生屏幕输入参数 | ✅ | — | — |
| `list_audio_inputs()` | 麦克风下拉 | avfoundation | dshow | pactl（含 monitor） |
| `audio_input_args(id)` | 独立音频输入 | None（随屏幕） | `audio="Name"` | pulse source |
| `probe_audio(id)` | 0.2s 实开探测 | ✅ | ✅ | ✅ |
| `encoder_args(which)` | 编码参数 | VideoToolbox 8M/2M | libx264 CRF 20/23 | 同 Win |
| `region_to_physical(...)` | 框选坐标转换 | 逻辑点（crop 内乘 scale） | ClientToScreen + DPR | mapToGlobal×DPR |

## 坐标系统（容易踩坑的地方）

- **mac**：avfoundation 捕获逻辑点；框选保持逻辑坐标，`build_command` 的 crop 里乘 `screen_scale`（devicePixelRatio）
- **Win**：mss 吃物理像素；混合 DPI 下 `mapToGlobal×DPR` 会错，用 Win32 `ClientToScreen`（legacy Pro 实测教训）
- **Linux/X11**：逻辑≈物理，`mapToGlobal×DPR` 足够
- **人像气泡**：Qt 逻辑几何 × scale 相对捕获原点换算，三平台同一公式
- **偶数尺寸**：yuv420p 不能编码奇数宽高——管道 feeder 声明时取偶，原生路径加 crop/scale 守卫

## 与 legacy 的对应关系

| legacy（冻结） | 统一包继承者 |
|---|---|
| `screen_recorder_mac.py` 的 build_command / frames_due / moov 校验 / 气泡 / 状态机 | `command.py` / `pacing.py` / `mp4check.py` / `ui/bubble.py` / `ui/main_window.py` |
| `screen_recorder_pro.py` 的 mss 区域/DPI/颜色处理 | `platforms/windows.py` + `screenfeed.py`（去掉 cvtColor 与 VideoWriter） |
| `screen_recorder_pro.py` 的 PyAudio→WAV→MoviePy | **删除**，由 dshow 音频输入替代（ADR-0001/0004） |
| `process_output.py` | `ffmpeg_exe.ProcessOutputReader`（同一实现） |

## 测试策略

- **纯逻辑**（命令组装、设备解析、节流数学、moov 遍历）：三平台 fixtures 用真实 ffmpeg 输出样本
- **馈送线程**：假 mss（可控帧率/故障注入）+ 内存管道，验证节流、EOF、故障上报
- **UI/生命周期**：offscreen QApplication + 假后端/假 Popen，走完 idle→…→idle 全循环
- **真机**：CI 全绿不替代真机验收——[CONTRIBUTING](../CONTRIBUTING.md) 里有人工清单
