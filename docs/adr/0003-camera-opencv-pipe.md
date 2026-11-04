# ADR-0003: 摄像头一律走 OpenCV → rawvideo 管道

- 状态：已接受（2026-11）

## 背景

ffmpeg 自带摄像头 demuxer（avfoundation / dshow / v4l2）理论上更省一层。实测：

- macOS 上 ffmpeg 的 avfoundation **摄像头**输入在部分设备上输出冻结帧
  （legacy 调研与实机结论），屏幕输入则正常；
- 直接声明 1920×1080 而设备实际是 1280×960 时会被拉伸；
- 管道裸 BGR 1080p 是 6.2MB/帧，Python feeder 在 GIL 竞争下只能交付 ~13fps，
  曾把 6 秒会话拖成 1.67 秒成片。

## 决策

三平台统一用 OpenCV 采集摄像头（mac `CAP_AVFOUNDATION` / Win `CAP_DSHOW` /
Linux `CAP_V4L2`），raw BGR 帧写入 ffmpeg 的 rawvideo 管道。录制前
`probe_camera()` 实测**帧率与真实分辨率**：

- 管道按实测尺寸声明（4:3 不被拉伸），帧率按实测值夹取（上限 = 输出 FPS）；
- `pipe_camera_size()`：只有分轨或演讲者模式才传全分辨率，角落气泡一律降到
  气泡实际宽度（~0.69MB/帧）；
- `frames_due()` 按声明帧率节流（落后补帧，>2s 卡顿重对齐）；
- 预览气泡用 `letterbox()` 保比例，PiP 落位用 `clamp_pip(真实高宽比)`。

## 后果

- 正：绕开 ffmpeg 摄像头 demuxer 的冻结帧问题；分辨率/帧率声明永远与设备
  实际一致；同一套节流与降级逻辑三平台复用。
- 负：多一个 OpenCV 依赖（pip 轮子成熟，可接受）；气泡预览与录制共用摄像头，
  必须先关气泡再开录（UI 状态机已保证）。
