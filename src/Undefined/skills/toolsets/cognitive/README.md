# cognitive 工具集

## get_profile

获取认知记忆中的用户或群聊侧写信息。该工具是检索用途，不用于手动写入长期事实；手动长期事实请使用 memory.add。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `entity_type` | `string(user/group)` | 是 | 实体类型 |
| `entity_id` | `string` | 是 | 用户ID或群ID，不接受路径、空值或 Windows 盘符 |

实体类型仅支持 `user` / `group`。侧写与历史版本都只能访问配置的侧写存储目录；指向目录外的符号链接会被拒绝。非法查询在工具中返回参数错误，在 Runtime API 中返回 HTTP 400。

## search_events

搜索认知记忆中的历史事件，用于回忆之前发生过的事情。支持用户/群与时间范围过滤，并应用时间衰减加权排序。该工具是检索用途，不用于手动写入长期事实；手动长期事实请使用 memory.add。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | `string` | 是 | 搜索关键词或语义描述 |
| `target_user_id` | `string` | 否 | 限定用户ID（可选） |
| `target_group_id` | `string` | 否 | 限定群ID（可选） |
| `sender_id` | `string` | 否 | 限定发送者ID（可选，与target_user_id可组合使用） |
| `request_type` | `string(private/group)` | 否 | 限定消息来源类型：private=私聊，group=群聊（可选） |
| `top_k` | `integer` | 否 | 返回条数，默认取配置 cognitive.query.tool_default_top_k |
| `time_from` | `string` | 否 | 起始时间 ISO格式（可选） |
| `time_to` | `string` | 否 | 截止时间 ISO格式（可选） |

## search_profiles

语义搜索认知记忆中的用户/群聊侧写，用于查找具有特定特征的用户或群。该工具是检索用途，不用于手动写入长期事实；手动长期事实请使用 memory.add。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | `string` | 是 | 搜索关键词 |
| `entity_type` | `string(user/group)` | 否 | 限定类型（可选） |
| `top_k` | `integer` | 否 | 返回条数，默认8 |
