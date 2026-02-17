# Agent 互调用功能文档

## 概述

Agent 互调用功能允许 Undefined 项目中的 Agent 之间相互调用，实现复杂的多 Agent 协作场景。通过简单的配置文件，您可以将某个 Agent 注册为其他 Agent 的可调用工具，并支持细粒度的访问控制。

## 核心特性

- **简单配置**：只需在 Agent 目录下添加一个 `callable.json` 文件即可启用
- **访问控制**：支持指定哪些 Agent 可以调用，提供白名单机制
- **自动注册**：系统自动扫描并注册可调用的 Agent，无需手动配置
- **参数透传**：保持每个 Agent 原有的参数定义，无需额外的参数映射
- **工具命名**：自动生成 `call_{agent_name}` 格式的工具名称

## 快速开始

### 1. 让 Agent 可被调用

在 Agent 目录下创建 `callable.json` 文件：

```json
{
    "enabled": true,
    "allowed_callers": ["*"]
}
```

例如，让 `web_agent` 可被所有 Agent 调用：

```bash
# 创建配置文件
cat > src/Undefined/skills/agents/web_agent/callable.json << 'EOF'
{
    "enabled": true,
    "allowed_callers": ["*"]
}
EOF
```

### 2. 限制调用权限

如果只想让特定 Agent 调用，可以指定允许的调用方列表：

```json
{
    "enabled": true,
    "allowed_callers": ["code_delivery_agent", "info_agent"]
}
```

### 3. 在其他 Agent 中调用

当 Agent 初始化时，会自动发现可调用的 Agent 并注册为工具。例如，`code_delivery_agent` 会自动获得 `call_web_agent` 工具，可以这样调用：

```python
# AI 模型会看到 call_web_agent 工具
{
    "name": "call_web_agent",
    "arguments": {
        "prompt": "搜索 Python 异步编程的最新发展"
    }
}
```

### 4. 让 `skills/tools` 下的主工具对 Agent 可见

除了 Agent 互调用外，也可以把主工具按白名单暴露给 Agent，避免在每个 Agent 下重复复制工具目录。

在主工具目录下添加 `callable.json`：

```json
{
    "enabled": true,
    "allowed_callers": ["*"]
}
```

文件位置：

```
src/Undefined/skills/tools/{tool_name}/callable.json
```

规则：
- 不存在 `callable.json`：仅主 AI 可调用该工具（默认行为）
- `enabled: true` + `allowed_callers`：对应 Agent 可调用
- 若 Agent 本地 `tools/` 下存在同名工具：本地优先，共享主工具会被跳过

## 配置文件详解

### 文件位置

```
src/Undefined/skills/agents/{agent_name}/callable.json
```

### 配置格式

```json
{
    "enabled": true,
    "allowed_callers": ["agent1", "agent2", ...]
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `enabled` | boolean | 是 | 是否启用该 Agent 作为可调用工具 |
| `allowed_callers` | array | 是 | 允许调用此 Agent 的 Agent 名称列表 |

### allowed_callers 详解

- **允许所有 Agent 调用**：使用 `["*"]`
- **允许特定 Agent 调用**：使用具体的 Agent 名称列表，如 `["info_agent", "code_delivery_agent"]`
- **不允许任何 Agent 调用**：使用空列表 `[]` 或设置 `enabled: false`

## 工具命名规则

可调用的 Agent 会被注册为工具，命名格式为：`call_{agent_name}`

示例：
- `web_agent` → `call_web_agent`
- `info_agent` → `call_info_agent`
- `code_delivery_agent` → `call_code_delivery_agent`

## 参数传递

Agent 互调用保持每个 Agent 原有的参数定义，无需额外的参数映射。调用方传入的参数会直接透传给目标 Agent。

例如，`web_agent` 的参数定义为：

```json
{
    "prompt": {
        "type": "string",
        "description": "用户的搜索需求"
    }
}
```

那么 `call_web_agent` 工具也会使用相同的参数定义。

## 访问控制机制

### 权限检查流程

1. 调用方 Agent 尝试调用 `call_{target_agent}`
2. 系统从 context 中获取当前 Agent 名称（`agent_name`）
3. 检查当前 Agent 是否在目标 Agent 的 `allowed_callers` 列表中
4. 如果在列表中或列表包含 `"*"`，则允许调用
5. 否则返回权限错误

### 权限错误示例

```
错误：code_delivery_agent 无权调用 info_agent
```

## 使用场景

### 场景 1：网络搜索代理

让 `web_agent` 可被所有 Agent 调用，提供统一的网络搜索能力：

```json
// src/Undefined/skills/agents/web_agent/callable.json
{
    "enabled": true,
    "allowed_callers": ["*"]
}
```

### 场景 2：代码分析代理

让 `naga_code_analysis_agent` 只能被 `code_delivery_agent` 调用，避免其他 Agent 误用：

```json
// src/Undefined/skills/agents/naga_code_analysis_agent/callable.json
{
    "enabled": true,
    "allowed_callers": ["code_delivery_agent"]
}
```

### 场景 3：信息查询代理

让 `info_agent` 可被多个特定 Agent 调用：

```json
// src/Undefined/skills/agents/info_agent/callable.json
{
    "enabled": true,
    "allowed_callers": ["code_delivery_agent", "web_agent", "entertainment_agent"]
}
```

## 实现原理

### 自动扫描机制

当 Agent 初始化其工具注册表（`AgentToolRegistry`）时，系统会：

1. 扫描 `agents/` 根目录下的所有 Agent 目录
2. 查找包含 `callable.json` 且 `enabled: true` 的 Agent
3. 读取 Agent 的 `config.json` 获取参数定义
4. 为每个可调用的 Agent 创建工具 schema 和 handler
5. 使用 `register_external_item()` 注册为外部工具

### 调用流程

```
调用方 Agent
  ↓
调用 call_{target_agent} 工具
  ↓
AgentToolRegistry.execute_tool()
  ↓
权限检查（检查 allowed_callers）
  ↓
ai_client.agent_registry.execute_agent()
  ↓
目标 Agent 执行
  ↓
返回结果
```

### 避免循环调用

- **自调用保护**：Agent 不会将自己注册为可调用工具
- **迭代限制**：Agent 执行受 `max_iterations` 限制（默认 20 次）
- **上下文隔离**：每次调用都有独立的上下文，不会无限递归

## 日志与调试

### 注册日志

当 Agent 初始化时，会记录注册的可调用 Agent：

```
[AgentToolRegistry] 注册可调用 agent: call_web_agent，允许调用方: 所有 agent
[AgentToolRegistry] 注册可调用 agent: call_info_agent，允许调用方: code_delivery_agent
```

### 调用日志

当 Agent 调用其他 Agent 时，会记录调用信息：

```
[AgentCall] code_delivery_agent 调用 web_agent，参数: {'prompt': '搜索...'}
```

### 权限拒绝日志

当权限检查失败时，会记录警告：

```
[AgentCall] web_agent 尝试调用 info_agent，但未被授权
```

## 最佳实践

### 1. 合理设置访问权限

- 对于通用工具型 Agent（如 `web_agent`），使用 `["*"]` 允许所有 Agent 调用
- 对于专用 Agent（如 `code_delivery_agent`），限制只有特定 Agent 可以调用
- 避免过度开放权限，防止 Agent 误用

### 2. 避免循环依赖

- 设计 Agent 调用关系时，避免 A 调用 B，B 又调用 A 的情况
- 如果确实需要双向调用，确保有明确的终止条件

### 3. 参数设计

- 保持 Agent 参数定义的简洁性
- 使用清晰的参数描述，帮助调用方理解如何使用

### 4. 测试验证

- 创建配置文件后，重启机器人验证功能
- 检查日志确认 Agent 是否正确注册
- 测试权限控制是否按预期工作

## 故障排查

### 问题 1：Agent 没有被注册为可调用工具

**可能原因**：
- `callable.json` 文件格式错误
- `enabled` 设置为 `false`
- `allowed_callers` 为空列表

**解决方法**：
1. 检查 `callable.json` 文件格式是否正确
2. 确认 `enabled: true`
3. 确认 `allowed_callers` 不为空
4. 查看日志中的警告信息

### 问题 2：调用时提示权限错误

**可能原因**：
- 调用方 Agent 不在 `allowed_callers` 列表中

**解决方法**：
1. 检查目标 Agent 的 `callable.json` 配置
2. 将调用方 Agent 添加到 `allowed_callers` 列表
3. 或使用 `["*"]` 允许所有 Agent 调用

### 问题 3：调用失败

**可能原因**：
- 目标 Agent 执行出错
- 参数传递错误

**解决方法**：
1. 查看日志中的错误信息
2. 检查传递的参数是否符合目标 Agent 的参数定义
3. 测试直接调用目标 Agent 是否正常

## 配置示例

### 示例 1：开放型 Agent

```json
// src/Undefined/skills/agents/web_agent/callable.json
{
    "enabled": true,
    "allowed_callers": ["*"]
}
```

### 示例 2：受限型 Agent

```json
// src/Undefined/skills/agents/info_agent/callable.json
{
    "enabled": true,
    "allowed_callers": ["code_delivery_agent", "web_agent"]
}
```

### 示例 3：禁用调用

```json
// src/Undefined/skills/agents/entertainment_agent/callable.json
{
    "enabled": false,
    "allowed_callers": []
}
```

## 技术细节

### 代码位置

- **主要实现**：`src/Undefined/skills/agents/agent_tool_registry.py`
- **相关类**：`AgentToolRegistry`
- **相关方法**：
  - `load_tools()`：加载本地工具和可调用的 Agent
  - `_scan_callable_agents()`：扫描所有可被调用的 Agent
  - `_load_agent_config()`：读取 Agent 的 config.json
  - `_create_agent_tool_schema()`：生成工具 schema
  - `_create_agent_call_handler()`：创建 Agent 调用 handler

### 类型定义

```python
def _scan_callable_agents(self) -> list[tuple[str, Path, list[str]]]:
    """扫描所有可被调用的 agent

    返回：[(agent_name, agent_dir, allowed_callers), ...]
    """
```

```python
def _create_agent_call_handler(
    self, target_agent_name: str, allowed_callers: list[str]
) -> Callable[[dict[str, Any], dict[str, Any]], Awaitable[str]]:
    """创建一个通用的 agent 调用 handler，带访问控制"""
```

## 更新日志

### v2.13.0 (2026-02-15)

- 🎉 新增 Agent 互调用功能
- ✨ 支持通过 `callable.json` 配置可调用 Agent
- 🔒 支持细粒度的访问控制（`allowed_callers`）
- 🚀 自动扫描和注册机制
- 📝 完整的日志记录和调试支持

## 相关文档

- [Skills 开发指南](../src/Undefined/skills/README.md)
- [Agent 开发指南](../src/Undefined/skills/agents/README.md)
- [项目架构说明](../CLAUDE.md)

## 反馈与支持

如果您在使用 Agent 互调用功能时遇到问题，或有改进建议，欢迎：

- 提交 Issue：[GitHub Issues](https://github.com/69gg/Undefined/issues)
- 参与讨论：[GitHub Discussions](https://github.com/69gg/Undefined/discussions)
