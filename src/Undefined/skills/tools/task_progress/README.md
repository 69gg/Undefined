# task_progress 工具

任务进度追踪。处理需要多步骤、多 Agent 协作的复杂请求时，先用 plan 动作规划步骤，再在每步完成后用 update 动作标记进度。每次调用都会返回当前完整进度。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `action` | `string(plan/update)` | 是 | plan: 创建任务计划（会替换已有计划）；update: 更新指定步骤的状态 |
| `tasks` | `list[object]` | 是 | plan: 完整步骤列表（需要 id + description）；update: 要更新的步骤（需要 id + status） |

目录结构：
- `config.json`：工具定义
- `handler.py`：执行逻辑
