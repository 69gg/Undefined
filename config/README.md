# 配置目录

本目录存放配置示例与 MCP 配置样例，便于快速搭建运行环境。

- `../config.toml.example`：仓库根目录的主配置示例文件
- `mcp.json.example`：MCP 服务器配置示例

使用方式：
1. 在仓库根目录复制 `config.toml.example` 为 `config.toml` 并填入实际参数
2. 如需 MCP，复制 `config/mcp.json.example` 为 `config/mcp.json`，并在 `config.toml` 中配置 `[mcp].config_path`
3. 如需补充本地 Prompt，把 UTF-8 文件放在 `config/prompts/*.local.*`，并配置 `[prompt.file_includes]` 的固定插槽

注意事项：
- `config.local.json` 为运行时自动生成文件，请勿提交
- `config/prompts/*.local.*` 可能包含身份或权限信息，已被 Git 和构建配置排除；文件内容仍会发送给模型供应商
- 请妥善保护日志路径、Token 等敏感信息
