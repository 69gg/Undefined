# web_agent 智能体

用于网络搜索与网页抓取，支持结合 MCP 的浏览器能力。

目录结构：
- `config.json`：智能体定义
- `intro.md`：能力说明
- `prompt.md`：系统提示词
- `tools/`：网页相关工具
- `mcp.json`（可选）：智能体私有 MCP 配置

运行机制：
- 由 `AgentRegistry` 自动发现并注册
- 若存在 `mcp.json`，调用该智能体时会临时加载 MCP 工具

开发提示：
- 网页抓取需关注网络超时与安全过滤
