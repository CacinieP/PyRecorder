# ADR-0001: 全平台统一为单 ffmpeg 进程管线

- 状态：已接受（2026-11）
- 关联：ADR-0002（屏幕）、ADR-0003（摄像头）、ADR-0004（音频）

## 背景

legacy Windows Pro 的路径是三段式：mss→OpenCV `VideoWriter` 写无声视频 + PyAudio 写 WAV，
停止后用 MoviePy 把音轨合并进视频（整段重编码）。实测问题：

- 合并等待与录制时长成正比，长课要等很久；
- 三段各自失败模式不同（编码器失败/录音失败/合并失败），恢复路径复杂；
- MoviePy API 在 1.x/2.x 间不兼容，两次升级踩坑（known-issues 第 8 条）；
- PyAudio 依赖系统 portaudio，三个平台安装体验都不好。

legacy macOS 版则用**一条 ffmpeg 命令**（avfoundation 屏幕+麦克风、滤镜合成、
VideoToolbox 编码）直接出片，真机验证稳定。

## 决策

统一包只保留单进程管线：屏幕、摄像头、麦克风都是同一个 ffmpeg 进程的输入，
滤镜图内合成，一次编码出片。删除 PyAudio / MoviePy 依赖。停止即收尾，
无二次处理。

## 后果

- 正：停止后即刻拿到成品；音画天然同步（同一时钟编码）；失败面收敛为
  「ffmpeg 进退码 + moov 完整性」一个判定。
- 正：`build_command()` 成为唯一需要跨平台测试的编排点，纯函数、易测。
- 负：ffmpeg 成为硬依赖（用 `[ffmpeg-binary]` extra 携带静态二进制缓解）；
  无法在录制中途动态增删输入（接受，教学场景不需要）。
