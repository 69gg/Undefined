# file_analysis_agent 智能体

用于文件解析与分析（PDF/Word/Excel/PPT 等），并支持代码分析与多模态解析。

目录结构：
- `config.json`：智能体定义
- `intro.md`：能力说明
- `prompt.md`：系统提示词
- `tools/`：文件解析与分析工具

运行机制：
- 由 `AgentRegistry` 自动发现并注册
- 通过 `prompt` 输入任务描述并调用内部工具

开发提示：
- 解析类工具尽量使用异步 I/O 或 `asyncio.to_thread`
