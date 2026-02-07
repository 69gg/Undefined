# get_picture 工具

用于获取指定类型图片并发送到群聊或私聊。

常用参数：
- `message_type`：消息类型（`group`/`private`）
- `target_id`：目标 ID（群号或 QQ 号）
- `picture_type`：图片类型（如二次元、壁纸等）
- `count`：图片数量
- `device`：设备类型（acg 类型支持 pc/wap）
- `fourk_type`：4K 图片类型（随机 4K 时使用）

目录结构：
- `config.json`：工具定义
- `handler.py`：执行逻辑
