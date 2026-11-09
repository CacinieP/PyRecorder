# ADR-0002: 屏幕采集按平台分层——avfoundation（mac）/ mss 管道（Win/Linux）

- 状态：已接受（2026-11）

## 背景

可选路线：a) 全平台 ffmpeg 原生抓屏（gdigrab / x11grab）；b) 全平台 mss→管道；
c) 按平台择优。

评估：

- **gdigrab**（Windows）：DPI 感知与区域几何易踩坑，ffmpeg 构建需含该组件；
  legacy Pro 已在 mss 上验证过区域/混合 DPI/BGRA 颜色的正确性。
- **x11grab**（Linux）：X11 直连可用，但 Wayland 完全不可用；mss 同样基于 X11，
  没有差别；mss 还是纯 Python 安装、无编译问题。
- **avfoundation**（macOS）：唯一能**录到光标与点击**的路线（教学视频刚需），
  且帧率由 ffmpeg 声明，无需自建节流。mss 在 macOS 拿不到光标且需 TCC 授权相同。

## 决策

- macOS：avfoundation 原生输入（含 `-capture_cursor 1 -capture_mouse_clicks 1`）。
- Windows/Linux：mss 抓屏，BGRA 字节**原样直通** rawvideo 管道（不做 BGRA→BGR
  的逐帧 numpy 转换——legacy 路径做过，这是纯浪费），由 `ScreenPipeFeed` 按声明
  帧率节流。
- Wayland：显式报错 + 指引（X11 会话 / OBS），绝不静默录出黑屏。原生 portal
  捕获列入路线图。

## 后果

- 正：每个平台用各自最可靠的抓屏方式；mss 路径与摄像头管道同构，复用
  `frames_due()` 节流。
- 负：屏幕输入有两种形态（原生参数 vs 管道 spec），`build_command` 需同时支持
  ——用 `NativeScreenInput` / `PipeScreenInput` dataclass 显式建模。
- 负：Win/Linux 成片时长依赖 feeder 节流精度（有测试 + legacy 实测数据背书）。
- 负：馈送字节流在 Windows 上不能走 `pass_fds` 管道，由
  `channels.py` 的回环 TCP 通道承载（详见 ADR-0001 的后果与
  `pyrecorder/channels.py`）。
