# naga_code_analysis_agent 智能体

面向 NagaAgent 代码库的分析助手，提供读取文件、目录遍历与内容检索能力。

目录结构：
- `config.json`：智能体定义
- `intro.md`：能力说明
- `prompt.md`：系统提示词
- `tools/`：代码分析工具集合（读取/检索/路径工具）

运行机制：
- 由 `AgentRegistry` 自动发现并注册
- 子工具在 `tools/` 下按功能拆分

开发提示：
- 工具应避免平台专用依赖，优先复用 `Undefined.utils`
