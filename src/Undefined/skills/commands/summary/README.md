# /summary（/sum）

总结聊天消息。

- 用法：`/summary [条数|时间范围] [自定义描述]`
- 数据来源：`fetch_session_messages_callback` 拉取当前会话消息后交给 summary 模型总结；
  未单独配置 `[models.summary]` 时回退 `[models.agent]`
- 别名：`sum`
- 注意：斜杠命令由命令层直连 summary 模型；主 AI 对话里的 `summary_agent` 走 agent 模型，
  两者互不影响

目录结构：
- `config.json`：命令定义（权限 / 限流 / 别名）
- `handler.py`：执行逻辑
