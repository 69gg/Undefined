# scheduler 工具集

定时任务工具集合，工具名以 `scheduler.*` 命名。

主要能力：
- 创建/更新/删除定时任务
- 列出定时任务
- 支持“调用未来的自己”：通过 `self_instruction` 让定时任务在触发时调用 AI 自身

目录结构：
- 每个子目录对应一个工具（`config.json` + `handler.py`）

## 调用未来自己的模式

在 `create_schedule_task` 或 `update_schedule_task` 中传入 `self_instruction`，即可创建“向未来自己下指令”的任务。

注意：
- `self_instruction` 与 `tool_name`、`tools` 三选一，不能同时传。
- 任务触发后会调用 AI 主流程，相当于“延迟执行一条给自己的自然语言指令”。

示例：

```json
{
  "cron_expression": "0 9 * * *",
  "self_instruction": "请总结昨天群里提到的待办，并提醒我今天优先处理前三项。"
}
```
