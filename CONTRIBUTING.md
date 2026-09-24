# 开发与分支

`main` 保存已合并、通过 CI 的版本。每轮修改从最新 `main` 建立一个短期分支：

- `fix/<topic>`：缺陷修复。
- `feat/<topic>`：新功能。
- `docs/<topic>`：独立文档变更；同一功能的说明和测试应与代码放在同一个 PR。

PR 说明应描述当前最终改动、验证结果和未验证的平台，追加修改后同步更新标题与说明。合并前等待当前提交的全部 CI 通过；合并后确认分支提交已包含在 `main`，再删除该分支。未合并的独有提交应保留，不能仅因分支陈旧就删除。

## 本地验证

建议 Python 3.11 / 3.12，并在项目虚拟环境中安装依赖。Windows/Linux 使用 `python -m pip install -r requirements.txt -r requirements-test.txt`；macOS 使用 `python -m pip install -r requirements-mac.txt -r requirements-test.txt`。Windows 的 start.bat 会创建 `.venv`，可使用 `.venv\Scripts\python.exe` 执行测试。真实合成媒体测试还需要 PATH 中有 `ffmpeg` 与 `ffprobe`，CI 会强制检查，缺失即失败。

```bash
python -m pytest -q
python -m flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
```

默认测试使用模拟设备，不采集屏幕、摄像头或麦克风。真实 AVFoundation 测试需要在已授权且有可用摄像头的 macOS 上显式启用：

```bash
python -m pytest -q --run-hardware -m hardware
```

真实屏幕捕获、平台权限、摄像头/音频同步和 Windows 窗口捕获需要人工验收。无设备测试通过不能替代这些验证。

CI 包含 Ubuntu 3.11/3.12、Windows 3.12 和 macOS 3.12。POSIX SIGTERM 的 ffmpeg 收尾测试在 Windows 上明确跳过；Windows 两版通过模拟屏幕和真实编码器验证停止/关闭后的 MP4 封装。修改共享 Windows RecordingThread 时，同时检查 Basic/Pro 的 GUI 交互回归。
