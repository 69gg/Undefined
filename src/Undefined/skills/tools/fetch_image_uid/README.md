# fetch_image_uid 工具

从 URL 获取图片并注册到附件系统，返回可在回复中嵌入的图片 UID。仅支持图片类型（PNG, JPEG, GIF, WebP, BMP）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `url` | `string` | 是 | 图片 URL（必须是 http/https 链接） |
| `display_name` | `string` | 否 | 图片的显示名称（可选，默认从 URL 推断） |

目录结构：
- `config.json`：工具定义
- `handler.py`：执行逻辑
