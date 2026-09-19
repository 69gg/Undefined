# get_picture 工具

用于获取指定类型的图片，默认以可嵌入回复的图片 UID 返回（不直接发送）；也可以选择立即发送到群聊或私聊。

## 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `delivery` | string | `embed` | `embed`：返回可插入回复的图片 UID；`send`：立即发送到目标 |
| `message_type` | string | 从会话推断 | 消息类型（`group`/`private`），仅 `delivery=send` 时需要 |
| `target_id` | integer | 从会话推断 | 目标 ID（群号或 QQ 号），仅 `delivery=send` 时需要 |
| `picture_type` | string | `acg` | 图片类型：`baisi`/`heisi`/`head`/`jk`/`acg`/`meinvpic`/`wallpaper`/`ys`/`historypic`/`random4kPic` |
| `count` | integer | `1` | 获取图片数量 |
| `device` | string | `pc` | 设备类型（`pc`/`wap`），仅 `acg` 类型支持 |
| `fourk_type` | string | `acg` | 4K 图片类型（`acg`/`wallpaper`），仅 `random4kPic` 类型支持 |

目录结构：
- `config.json`：工具定义
- `handler.py`：执行逻辑
