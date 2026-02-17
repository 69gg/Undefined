# 配置目录

本目录存放配置示例与 MCP 配置样例，便于快速搭建运行环境。

- `config.toml.example`：主配置示例文件
- `mcp.json.example`：MCP 服务器配置示例

使用方式：
1. 复制 `config.toml.example` 为 `config.toml` 并填入实际参数
2. 如需 MCP，复制 `config/mcp.json.example` 为 `config/mcp.json`，并在 `config.toml` 中配置 `[mcp].config_path`

推荐关注的新增配置：
- `[features].inflight_summary_enabled`：并发防重摘要总开关（默认 `true`）
- `[models.inflight_summary]`：进行中摘要模型（可选）；未完整配置时自动回退 `models.chat`

注意事项：
- `config.local.json` 为运行时自动生成文件，请勿提交
- 请妥善保护日志路径、Token 等敏感信息
