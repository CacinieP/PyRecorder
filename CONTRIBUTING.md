# 开发与分支

`main` 保存已合并、通过 CI 的版本。每轮修改从最新 `main` 建立一个短期分支：

- `fix/<topic>`：缺陷修复。
- `feat/<topic>`：新功能。
- `docs/<topic>`：独立文档变更；同一功能的说明和测试应与代码放在同一个 PR。

PR 说明应描述当前最终改动、验证结果和未验证的平台，追加修改后同步更新标题与说明。合并前等待当前提交的全部 CI 通过（Ubuntu 3.11/3.12、Windows 3.12、macOS 3.12）；合并后确认分支提交已包含在 `main`，再删除该分支。未合并的独有提交应保留，不能仅因分支陈旧就删除。

架构变更请同时更新或新增 [ADR](docs/adr/)；改动录制管线时对照 [architecture.md](docs/architecture.md) 的不变量清单。

## 本地验证

建议 Python 3.11 / 3.12，项目虚拟环境安装依赖（含冻结的 legacy 测试所需依赖）：

```bash
python -m pip install -e ".[dev,legacy]"
python -m pytest -q
python -m flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
python -m pyrecorder        # 从源码启动
```

真实合成媒体测试还需要 PATH 中有 `ffmpeg` 与 `ffprobe`，CI 会强制检查，缺失即失败。

默认测试使用模拟设备，不采集屏幕、摄像头或麦克风（馈送线程用假 mss/假摄像头，
UI 用 offscreen 平台 + 假后端）。真实 AVFoundation 硬件用例需要在已授权的
macOS 上显式启用：

```bash
python -m pytest -q --run-hardware -m hardware
```

## 真机人工验收清单（合并录制管线相关改动前）

无设备测试通过**不能替代**以下验证。至少在改动者自己的平台过一遍：

- [ ] 全屏 + 麦克风 10s：文件可播放、时长 ≈ 会话、有音轨
- [ ] 区域录制 10s：成片尺寸 = 框选尺寸（Retina 乘 DPR）
- [ ] 摄像头气泡：拖到四角各录 5s，PiP 位置与预览一致、4:3 相机不拉伸
- [ ] 演讲者模式 L/R 各 5s：左右顺序正确
- [ ] 授权降级：撤销麦克风权限 → 弹窗后仍产出纯视频
- [ ] 停止响应 < 3s；录制中关闭窗口 → 收尾完成后再退出
- Windows/Linux 改动：另跑一次 CI 产物（release workflow 的 dispatch 构建）冒烟

legacy 目录冻结（ADR-0006）：不要在那里加功能或重构，修统一包并让它的测试说话。
