# undefined_self_code_agent 智能体

面向 Undefined 当前仓库的只读代码查阅助手，提供受限文件读取、目录浏览、glob 匹配和内容检索能力。

目录结构：
- `config.json`：智能体定义
- `intro.md`：给主 AI 看的能力说明
- `prompt.md`：智能体系统提示词
- `tools/`：只读代码查阅工具集合

访问范围：
- 目录：`src/`、`scripts/`、`tests/`、`res/`、`docs/`、`apps/`
- 根文件：`README.md`、`CHANGELOG.md`、`ARCHITECTURE.md`、`config.toml.example`

运行机制：
- 由 `AgentRegistry` 自动发现并注册
- 子工具统一复用 `tools/_shared.py` 的路径白名单与文本读取逻辑
- 不提供写入、命令执行或联网能力
