# ADR-0006: legacy 三件套冻结保留

- 状态：已接受（2026-11）

## 背景

统一包落地前，仓库有三个入口：`screen_recorder.py`（Win 基础）、
`screen_recorder_pro.py`（Win Pro）、`screen_recorder_mac.py`（mac）。它们
承载了大量真机验证过的修复（见 [known-issues.md](../known-issues.md)），其中
Pro 的 Win32 窗口捕获在统一包中没有对应功能。

选项：a) 删除（靠 git 历史）；b) 原地保留（根目录五入口并存）；c) 移入
`legacy/` 冻结。

## 决策

移入 `legacy/`，保持可导入、可运行、测试继续跑（conftest 把 `legacy/` 加进
`sys.path`，旧测试零改动），但**不再加功能、不做重构**。统一包取代它们成为
唯一推荐入口。`[legacy]` extra 承载它们独有的依赖（pyaudio/moviepy/Pillow）。

## 后果

- 正：根目录干净，产品入口唯一；真机修复成果仍可随时对照/回滚；Pro 的
  窗口捕获仍可用（想用的人装 `[legacy]` extra）。
- 负：测试矩阵多一份维护面（接受——冻结意味着改动概率趋零）；
  `pyaudio` 在部分环境安装困难，仅影响 legacy 用户。
- 明确信号：若统一包稳定两个大版本，可在未来删除 `legacy/`。
