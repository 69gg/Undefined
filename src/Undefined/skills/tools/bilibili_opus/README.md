# bilibili_opus 工具

处理 Bilibili 图文（opus / 动态）。默认发送合并转发到群聊或私聊；也支持只把正文图片登记为附件 UID 供文件分析使用、只获取图文信息，或按字数区间 / 关键词读取正文文字。支持 `bilibili.com/opus/<id>`、`m.bilibili.com/opus/<id>`、`t.bilibili.com/<id>`、`b23.tv` 短链、裸动态 ID 与 QQ 小程序分享卡片里提取到的 ID。

常用参数：
- `opus_id`：图文标识（动态 ID、图文链接或 b23.tv 短链）
- `target_type`：可选，目标会话类型（`group`/`private`）
- `target_id`：可选，目标会话 ID
- `output_mode`：可选，`send`（默认，发送合并转发）、`uid`（把正文图片登记为 `<attachment uid="pic_xxx"/>`，不发送消息）、`info`（只返回图文元信息）或 `text`（只返回正文文字）
- `max_images`：可选，`uid` 模式下最多登记多少张图片，默认 9
- `start` / `end`：可选，`text` 模式的起始字与结束字（0 基，`end` 不含），不填即从开头读取
- `limit`：可选，`text` 模式的单次返回字数上限，默认 1000、上限 20000；给了 `end` 时 `limit` 仍作为上界生效，只给 `end` 时不再套默认 1000 字
- `keyword`：可选，`text` 模式的关键词查询，返回命中位置与前后文片段（最多 5 处），此时 `start` / `end` 被忽略

`send` 模式流程：
1. 解析 `opus_id` 为裸动态 ID（必要时解析 b23.tv 短链）
2. 请求 `x/polymer/web-dynamic/v1/opus/detail`，失败时回退 `x/polymer/web-dynamic/v1/detail`（带 WBI 签名）
3. 把 `modules` / `module_content.paragraphs[]` 渲染成块序列（文本、图片、分割线、引用、列表、代码、链接卡片）
4. 发送合并转发：第一条是图文信息（封面、标题、UP主、时间、数据、原文链接），第二条起是正文（文本与图片按原始顺序混排，按单节点 4000 字切分）
5. 正文里的图文/视频卡片各自成为独立嵌套合并转发，按 `opus_nested_depth` / `opus_nested_max_cards` 递归展开，超界降级为一行文本 + 链接

`uid` 模式流程：
1. 拉取图文并收集正文图片 URL
2. 按 `max_images` 上限逐张 `register_remote_url`（超过附件大小上限时自动降级为 URL 引用）
3. 返回图文概要与 `<attachment uid="pic_xxx"/>` 列表，供 `file_analysis_agent` 继续做多模态分析

`info` 模式流程：
1. 拉取图文并解析元数据
2. 返回标题、图文 ID、UP主、发布时间、互动数据、封面、图片数量与原文链接
3. 不发送消息、不注册附件

`text` 模式流程：
1. 把正文块渲染成纯文本（图片以 `[图片 xN]` 占位，卡片以 `[图文]/[视频] 标题 链接` 占位）
2. 无 `keyword` 时按 `[start, end)` 返回字符区间；`end` 缺省取 `start + limit`（默认 1000 字）
3. 有 `keyword` 时返回该词在正文中的命中区间（最多 5 处）与前后各 60 字的上下文，重叠片段自动合并
4. 返回头给出正文总字数与本次范围，未读完时提示下一段可用 `start=N` 继续；关键词未命中时明确说明
5. 不发送消息、不注册附件；`limit<=0`、`limit>20000`、负数 `start`/`end`、关键词短于 2 字或长于 200 字都返回可读错误

配置依赖：
- `config.toml` 中的 `[bilibili]` 段控制 Cookie、清晰度、时长与体积限制（嵌套视频卡片复用这些限制）
- `[bilibili].opus_enabled` 只控制自动提取管线；本工具不受该开关影响

自动提取行为：
- 自动处理管线命中图文链接、短链或分享卡片后，同样发送一次合并转发（元数据 + 内容 + 嵌套节点），每个图文最多处理 `opus_max_items` 条。

目录结构：
- `config.json`：工具定义
- `callable.json`：允许 `file_analysis_agent` 调用
- `handler.py`：执行逻辑
