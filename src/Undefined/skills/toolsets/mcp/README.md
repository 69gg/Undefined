# MCP (Model Context Protocol) 工具集

MCP 工具集允许 Undefined 机器人连接外部 MCP 服务器，扩展 AI 的工具能力。

## 架构

MCP 工具集通过 `Undefined.mcp.MCPToolRegistry` 实现（兼容别名：`MCPToolSetRegistry`），负责：

1. 加载 MCP 配置文件（`config/mcp.json`）
2. 连接配置的 MCP 服务器
3. 获取服务器提供的工具列表
4. 将 MCP 工具转换为 toolsets 格式
5. 集成到主工具注册表中

## 工具命名

MCP 工具的命名格式为：`mcp.{server_name}.{tool_name}`

例如：
- `mcp.filesystem.read_file`
- `mcp.brave-search.search`
- `mcp.sqlite.query`

## 配置

### MCP 配置文件格式

```json
{
  "mcpServers": {
    "server_name": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-name", "arg1", "arg2"]
    }
  }
}
```

### 环境变量

- `MCP_CONFIG_PATH`：MCP 配置文件路径（默认：`config/mcp.json`）

## 使用示例

### 1. 文件系统访问

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/data"]
    }
  }
}
```

AI 可以使用：
- `mcp.filesystem.read_file`：读取文件
- `mcp.filesystem.write_file`：写入文件
- `mcp.filesystem.list_directory`：列出目录

### 2. Web 搜索

```json
{
  "mcpServers": {
    "brave-search": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"]
    }
  }
}
```

AI 可以使用：
- `mcp.brave-search.search`：执行搜索

### 3. 数据库查询

```json
{
  "mcpServers": {
    "sqlite": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-sqlite", "--db-path", "/path/to/db.sqlite"]
    }
  }
}
```

AI 可以使用：
- `mcp.sqlite.query`：执行 SQL 查询

### 4. GitHub API

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"]
    }
  }
}
```

### 5. 代码文档查询 (Context7)

```json
{
  "mcpServers": {
    "context7": {
      "command": "npx",
      "args": ["-y", "@upstash/context7-mcp"]
    }
  }
}
```

### 6. 烹饪食谱查询 (HowToCook)

```json
{
  "mcpServers": {
    "howtocook": {
      "command": "npx",
      "args": ["-y", "howtocook-mcp"]
    }
  }
}
```

AI 可以使用：
- `mcp.howtocook.get_recipe`：获取烹饪食谱
- `mcp.howtocook.search_ingredients`：搜索食材

## 注意事项

1. **依赖安装**：使用 MCP 功能需要安装 `fastmcp` 库
2. **Node.js 要求**：某些 MCP 服务器需要 Node.js 环境
3. **安全性**：配置文件包含敏感信息，已添加到 `.gitignore`
4. **性能**：MCP 工具调用需要网络或进程间通信，可能较慢
5. **错误处理**：MCP 服务器不可用时会优雅降级，不影响其他功能

## 故障排除

### MCP 工具未加载

1. 检查 `fastmcp` 是否安装：`pip list | grep fastmcp`
2. 检查配置文件路径是否正确
3. 查看日志中的错误信息

### MCP 工具调用失败

1. 检查 MCP 服务器是否正常运行
2. 检查工具参数是否正确
3. 查看日志中的详细错误信息

### Node.js 相关问题

如果使用基于 Node.js 的 MCP 服务器：

1. 确保已安装 Node.js：`node --version`
2. 确保 `npx` 可用：`npx --version`
3. 检查网络连接（首次运行需要下载包）

## 更多资源

- [MCP 官方文档](https://modelcontextprotocol.io/)
- [MCP Servers 仓库](https://github.com/modelcontextprotocol/servers)
- [fastmcp 文档](https://github.com/jlowin/fastmcp)
