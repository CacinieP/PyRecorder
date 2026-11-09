# ADR-0004: 音频走 ffmpeg 原生输入（avfoundation / dshow / pulse）

- 状态：已接受（2026-11）

## 背景

legacy Windows Pro 用 PyAudio 录 WAV 再合并（已在 ADR-0001 中废除）。要在单进程
管线里收麦克风，可让 ffmpeg 自己开音频设备：

- macOS：avfoundation 输入本就是 `屏幕:麦克风` 复合格式，零额外成本；
- Windows：dshow 输入 `audio="设备名"`，ffmpeg 官方构建都支持；
- Linux：`-f pulse -i <source>`，发行版 ffmpeg 均带。

风险：设备出现在列表里 ≠ 能打开（macOS 权限被拒时 avfoundation 打开失败，
会拖死整条录制命令）。

## 决策

麦克风作为 ffmpeg 的原生输入（mac 随屏幕输入、Win/Linux 独立输入）。录制前
用 `-t 0.2` 的空录制**实探**一次（约 0.4s，后台线程）：打不开就弹窗降级为
纯视频，不启动带音频的命令。设备枚举：

- mac：解析 `-list_devices true`（avfoundation，含 BlackHole 等虚拟声卡）；
- Win：解析 dshow 设备列表（注意 `-list_devices` 必须带值 `true`，裸布尔形式在
  ffmpeg 7/8 是 no-op——实测 8.1.1）；设备名整体包进字面双引号；
- Linux：`pactl list short sources`（保留 monitor 源——这是录系统声音最简单的
  合法通道），无 pactl 时回退 `default`。

## 后果

- 正：零 Python 音频依赖；音频与其他输入同进程编码，天然对齐；探测→降级
  的路径统一。
- 负：dshow 设备名含 `"` 会破坏转义（极罕见，接受并记录）；系统声音没有
  跨平台免配置方案（文档引导用虚拟声卡 / pulse monitor）。
