# callable.json 配置指南

通过在技能目录下放置 `callable.json`，可以将工具或 Agent 按白名单暴露给其他 Agent 调用，实现跨 Agent 协作与工具复用。

## 支持的位置

| 位置 | 效果 |
|------|------|
| `skills/agents/{agent_name}/callable.json` | 让该 Agent 可被其他 Agent 以 `call_{agent_name}` 工具调用 |
| `skills/tools/{tool_name}/callable.json` | 让该主工具按白名单暴露给 Agent |
| `skills/toolsets/{category}/{tool_name}/callable.json` | 让该工具集工具按白名单暴露给 Agent，注册名为 `{category}.{tool_name}` |

不存在 `callable.json` 时，工具/Agent 仅主 AI 可见（默认行为）。

## 配置格式

```json
{
    "enabled": true,
    "allowed_callers": ["*"]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `enabled` | boolean | 是否启用 |
| `allowed_callers` | array | 允许调用的 Agent 名称列表；`["*"]` 表示所有 Agent；`[]` 表示禁止所有 |

## Agent 互调用

让 Agent 可被其他 Agent 调用：

```
skills/agents/web_agent/callable.json
```

```json
{
    "enabled": true,
    "allowed_callers": ["*"]
}
```

注册后，其他 Agent 会获得 `call_web_agent` 工具，参数定义与 `web_agent` 的 `config.json` 一致。

限制只有特定 Agent 可调用：

```json
{
    "enabled": true,
    "allowed_callers": ["code_delivery_agent", "info_agent"]
}
```

### 工具命名

`{agent_name}` → 注册为 `call_{agent_name}`

### 调用流程

```
调用方 Agent → call_{target} → 权限检查 → ai_client.agent_registry.execute_agent() → 返回结果
```

- **自调用保护**：Agent 不会将自己注册为可调用工具
- **上下文隔离**：每次调用有独立上下文，历史记录按 Agent 分组保存
- **迭代限制**：受 `max_iterations`（默认 20）约束，防止无限递归

## 主工具共享（tools/）

让 `skills/tools/` 下的工具对 Agent 可见，避免在每个 Agent 下重复复制工具目录：

```
skills/tools/send_message/callable.json
```

```json
{
    "enabled": true,
    "allowed_callers": ["*"]
}
```

- 若 Agent 本地 `tools/` 下存在同名工具，本地优先，共享工具被跳过

## 工具集共享（toolsets/）

让 `skills/toolsets/` 下的工具对 Agent 可见。

**单个工具**：在工具目录下放 `callable.json`：

```
skills/toolsets/render/render_html/callable.json
```

**整个分类**：在分类目录下放 `callable.json`（上级覆盖下级，目录内所有工具均生效）：

```
skills/toolsets/render/callable.json
```

```json
{
    "enabled": true,
    "allowed_callers": ["*"]
}
```

注册名为 `{category}.{tool_name}`（如 `render.render_html`）。若分类级和工具级同时存在，分类级优先。

- 若 Agent 本地 `tools/` 下存在同名工具，本地优先

## 访问控制

权限检查在运行时进行：

1. 系统从 `context["agent_name"]` 获取调用方名称
2. 检查是否在目标的 `allowed_callers` 中
3. 不在列表中则返回权限错误，并记录警告日志

主 AI（非 Agent 上下文）始终可见所有工具，不受 `allowed_callers` 限制。

## 日志

```
[AgentToolRegistry] 注册可调用 agent: call_web_agent，允许调用方: 所有 agent
[AgentToolRegistry] 注册共享主工具: send_message，允许调用方: 所有 agent
[AgentCall] code_delivery_agent 调用 web_agent，参数: {'prompt': '...'}
[AgentCall] web_agent 尝试调用 info_agent，但未被授权
```

## 实现位置

- `src/Undefined/skills/agents/agent_tool_registry.py` — `AgentToolRegistry`
  - `_scan_callable_agents()`：扫描可调用 Agent
  - `_scan_callable_main_tools()`：扫描可共享的 tools/ 和 toolsets/
  - `_create_agent_call_handler()`：Agent 调用 handler（含权限检查）
  - `_create_main_tool_proxy_handler()`：工具代理 handler（含权限检查）
