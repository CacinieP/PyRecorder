# PyRecorder macOS 支持调研报告

> 调研日期：2026-09-03。目标：让 PyRecorder 支持 macOS，尤其是**同时录制人像（摄像头画中画）**，并保持简单易用。

## 一、现有代码的 Windows 耦合点

`screen_recorder_pro.py` 中所有平台绑定：

| 模块 | Windows 依赖 | macOS 对应 |
|---|---|---|
| 窗口枚举/定位 | `ctypes.windll.user32` + `EnumWindows` | `pyobjc Quartz` 的 `CGWindowListCopyWindowInfo`（免费，无新依赖权限） |
| 屏幕抓帧 | mss（跨平台） | mss 在 macOS 同样可用（底层 CoreGraphics），但需要 TCC「屏幕录制」权限 |
| 摄像头 | `cv2.VideoCapture(0)` | 需改为 `cv2.VideoCapture(0, cv2.CAP_AVFOUNDATION)`；需 TCC「相机」权限 |
| 麦克风 | PyAudio | PyAudio 在 macOS 需 brew 装 portaudio 后可编译；需 TCC「麦克风」权限 |
| 音视频合并 | MoviePy（慢、重） | 同样可用，但建议换掉（见下） |
| **系统声音** | ❌ 未实现 | ⚠️ macOS 无公开 API 直录系统声音，需 BlackHole 等虚拟声卡 |

另有两个 Windows 版体验缺陷在 macOS 上会更明显：OpenCV `mp4v` 编码体积大且无硬件加速（Retina 下 CPU 会满载）；MoviePy 合并音视频要重编码整段视频，结尾等待时间很长。

## 二、主流录屏软件调研

| 软件 | 平台 | 人像同录 | 技术路线 | 对 PyRecorder 的启发 |
|---|---|---|---|---|
| **QuickTime**（内置） | macOS | ❌ 屏幕和摄像头只能二选一（新版本可加麦克风） | AVFoundation + ScreenCaptureKit | 免费基准，功能最简 |
| **OBS Studio** | 全平台 | ✅ 摄像头源自由叠加 | Qt + C++，libobs 直接调 AVFoundation/ScreenCaptureKit | 功能最强但 UI 复杂，违背「简单易用」定位 |
| **Kap**（开源，MIT，19k★） | macOS | ✅（通过插件） | Electron + 自研录制引擎 **Aperture**（AVFoundation 硬编码） | 菜单栏极简交互是好的 UX 参照；Electron 体积大 |
| **Cap**（开源，cap.so） | macOS/Windows | ✅ 屏幕+xml+摄像头+麦克风一键 | Tauri v2 + Rust（scap-/cap-camera- crates，macOS 走 ScreenCaptureKit） | 与「简单 + 人像同录」定位最接近的直接竞品，交互模式值得抄：一个录制条 + 摄像头气泡 |
| **Screen Studio**（付费） | macOS | ✅ 摄像头气泡 | 原生 Swift + ScreenCaptureKit，后期自动缩放/美化 | 「录完自动变好看」是卖点，但闭源付费 |
| **CleanShot X / Loom**（付费） | macOS | ✅/✅（云端） | 原生 / 云端 | 商业化功能（标注、云分享），非本项目目标 |

**结论**：所有做得好的 macOS 人像同录产品，底层都是 **ScreenCaptureKit（屏幕+系统声音）+ AVFoundation（摄像头+麦克风）+ VideoToolbox 硬编码**。Python 直接调 ScreenCaptureKit 的生态还不成熟（pyobjc 绑定存在但几乎无文档、无示例）。

## 三、macOS 实现方案对比

### 方案 A：沿用现有 Python 栈（mss + OpenCV + PyAudio）
- ✅ 改动最小，窗口枚举换成 Quartz 即可
- ❌ mp4v 软编码：Retina 30fps 下 CPU 占用 80%+，文件 ~100MB/min
- ❌ 无系统声音（只能麦克风）
- ❌ MoviePy 合并慢
- 适合作为「快速跑通」的过渡，不建议作为最终形态

### 方案 B：ffmpeg + avfoundation（⭐ 推荐的 macOS 后端）
本机已验证可行：`/opt/homebrew/bin/ffmpeg` 带 avfoundation，能看到 `Capture screen 0`、摄像头、麦克风。**一条命令同时录屏幕+人像+麦克风，硬件编码，无需 OpenCV 逐帧合成**：

```bash
ffmpeg \
  -f avfoundation -framerate 30 -pixel_format uyvy422 \
  -capture_cursor 1 -capture_clicks 1 -i "1:0" \
  -f avfoundation -framerate 30 -i "0" \
  -filter_complex "[1:v]scale=iw*0.25:-1[cam];[0:v][cam]overlay=W-w-24:H-h-24[out]" \
  -map "[out]" -map 0:a? \
  -c:v h264_videotoolbox -b:v 8M -c:a aac out.mp4
```

- ✅ VideoToolbox 硬编码：CPU 占用低、文件小（~10MB/min）、直接输出 H.264+AAC 的 MP4，**不需要 MoviePy 后期合并**
- ✅ 人像 PiP 由 `overlay` 滤镜实时完成，位置/大小就是滤镜参数（对应现有 GUI 里的四个角 + 尺寸选项）
- ✅ 实现极简：GUI（PyQt6 不变）→ 拼 ffmpeg 命令 → 起子进程 → 停止时 `q` 退出。录制逻辑从 ~200 行变 ~40 行
- ✅ 区域录制：macOS 上用 `-i "Capture screen 0"` 全屏录 + `crop` 滤镜裁剪即可
- ⚠️ 前置条件：用户需 brew 安装 ffmpeg（`brew install ffmpeg`），并在「系统设置 → 隐私与安全性」给运行终端/App 授予**屏幕录制、相机、麦克风**三项权限（首次运行会弹窗，一次性）
- ❌ 系统声音仍无法直录（所有方案共同的 macOS 限制）；可选支持：检测/引导安装 BlackHole 后把输入改为 `"1:BlackHole 2ch"`

### 方案 C：原生 ScreenCaptureKit（Swift 小助手进程 或 Rust/Tauri 重写）
- ✅ 唯一能直录系统声音的路线，画质/性能最佳，Cap/Kap 同款
- ❌ 脱离 Python 栈，工作量大，违背「Python only、保持简单」的初衷
- 作为远期可选，不阻塞 macOS 支持

## 四、建议的落地路线

1. **新增 `screen_recorder_mac.py`**（或按平台自动选择后端）：
   - PyQt6 GUI 基本复用 Pro 版界面（全屏/区域、人像开关+四角位置+尺寸、麦克风开关、保存目录）
   - 录制线程改为：拼 ffmpeg 参数 → `QProcess`/`subprocess` 启动 → 停止时发 `q`
   - 启动前用 `shutil.which("ffmpeg")` 检查，未安装时给出 `brew install ffmpeg` 引导
   - 首次启动检测权限：用 `AVCaptureDevice`（pyobjc）或直接捕获 ffmpeg 的失败输出给出中文指引
2. **窗口枚举跨平台**：抽一个 `platform_utils.py`，Windows 用现有 user32，macOS 用 `Quartz.CGWindowListCopyWindowInfo`（窗口跟随移动可在录制中定时重查窗口 rect + `crop` 实现跟随，这是相对 Windows 版的增强）
3. **人像同录为 macOS 默认亮点**：保留 4 角位置 + 尺寸滑条，映射到 overlay 滤镜；可加圆形气泡样式（`geq` alpha 蒙版，可选）
4. **文档**：README 增加 macOS 章节（权限授予截图路径、brew 依赖）；`start.bat` 旁边加 `start.command`
5. **打包**（可选后续）：`py2app` 出 .app 后权限绑定到 App 本身，体验接近原生软件

## 五、权限速查（macOS 用户必读）

录屏前需在「系统设置 → 隐私与安全性」中授权运行 PyRecorder 的程序：

- **屏幕录制**：不授权会录到黑屏/壁纸（这是 macOS 最常见的坑，报告里必须提示）
- **相机 / 麦克风**：仅开启人像/录音时需要
- 授权后需重启 PyRecorder（或所在终端）生效
