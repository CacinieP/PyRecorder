# ADR-0005: 编码器——macOS VideoToolbox，Win/Linux 暂用 libx264

- 状态：已接受（2026-11），硬件编码探测在路线图中

## 背景

教学视频是长录制（30–60 分钟），编码必须稳定优先。可选：

- **VideoToolbox**（mac）：`h264_videotoolbox`，硬编，brew ffmpeg 即含；legacy
  macOS 版真机验证过三路并发（主+分轨）稳定。
- **AMF/QSV/NVENC**（Win）与 **VAAPI**（Linux）：性能好，但存在性与可用性
  依赖驱动与 ffmpeg 构建，探测/回退逻辑不平凡，且本仓库当前没有 Windows/Linux
  真机做回归。
- **libx264**：所有 ffmpeg 构建都有；`-preset veryfast -crf 20` 对屏幕内容
  质量足够。

## 决策

mac 用 `h264_videotoolbox -b:v 8M`（分轨摄像头 2M）；Win/Linux 用
`libx264 -preset veryfast -crf 20`（分轨摄像头 CRF 23）。硬件编码探测
（先试 `h264_amf`/`h264_qsv`/`h264_nvenc`/`h264_vaapi` 编码 1 帧成功才启用，
失败静默回退 libx264）列入路线图第一位。

## 后果

- 正：三平台开箱即用，无驱动依赖的坑；质量/速度行为可预期。
- 负：高分辨率高帧率下 Win/Linux CPU 占用偏高——文档建议降 FPS 或缩区域；
  这是有意识的「先正确后快」取舍。
