# chiliarch.call

依赖随项目安装，运行 `Undefined-chiliarch-pair --server <平台地址>` 配对后自动启用；删除 `data/chiliarch/client.db` 即停用，无需配置项或外部客户端。所有聊天平台通过 context 中的 `chiliarch_service` 使用同一原生客户端。

| action | arguments |
| --- | --- |
| `status` | 无；本地就绪不保证网络在线 |
| `contact` | `message`, `client_request_id`，可选 `correlation_id` |
| `request` | `operation`, `arguments`, `client_request_id`，可选 `message`, `wait_seconds` |
| `get_result` | `request_id`，可选 `wait_seconds`（0–30 秒） |
| `read_messages` | 可选 `after`, `limit`；只返回当前聊天关联或逻辑用户可见的消息 |
| `acknowledge_messages` | `cursor`；当前聊天的本地已读游标 |
| `progress` | `progress`（0–1）, `message`；仅当前正式任务 |
| `list_agents` / `list_channels` | 可选 `wait_seconds` |
| `create_channel` | `title`, `members`, `client_request_id` |
| `get_channel` | `channel_id`，可选 `after`, `limit` |
| `send_peer_message` | `message`, `client_request_id`，`recipient_agent_id` / `channel_id` 二选一；可选 `reply_to`, `wake`（默认 false） |
| `acknowledge_peer_message` | `message_id`, `state`（read / processed）, `client_request_id` |
| `get_peer_message` | `message_id` |
| `wait_for_tasks` | `waiting_for`, `reason`, `client_request_id`；只关联当前正式任务 |
| `list_task_waits` | 当前正式任务 |
| `upload_artifact` | `path`, `members`, `client_request_id`；可选 `goal_id`, `timeout_seconds`（大于 0、不超过 30） |
| `download_artifact` | `artifact_id`，可选 `name`, `timeout_seconds`；返回会话 attachment UID |

平台请求可返回 pending/approved/rejected；只有批准且完成的结果才能视为成功。保留原 request_id 查询，不换 ID 重试副作用。同一 client_request_id 在同一聊天只接受同一内容。需要审批的业务由平台处理，Undefined 不伪造批准。

出站请求发送前记录原聊天；回信按持久关联回原会话，重启也不猜最近聊天。同伴消息不自行启动 AI，wake 由平台任务控制。正式任务停止后禁止新协作操作。

跨机器发送文件须经 upload_artifact，不能只发本地路径。download_artifact 复用官方校验，返回附件标签后再 send_message。当前 chiliarch 逻辑会话默认 send_message 回复当前会话；显式 QQ／微信／群地址继续沿用原投递和 ACL。

详见 [接入文档](../../../../../docs/chiliarch.md)。
