# arxiv_paper 工具

处理 arXiv 论文。默认发送到群聊或私聊；也支持只注册为附件 UID 供文件分析使用，或只获取论文信息。支持 arXiv ID、`arXiv:` 前缀和 arXiv 页面链接。

常用参数：
- `paper_id`：论文标识（如 `2501.01234`、`arXiv:2501.01234v2`、`https://arxiv.org/abs/2501.01234`）
- `target_type`：可选，目标会话类型（`group`/`private`）
- `target_id`：可选，目标会话 ID
- `output_mode`：可选，`send`（默认，发送论文信息和 PDF）、`uid`（只返回 `<attachment uid="file_xxx"/>`，不发送消息）或 `info`（只返回论文信息，不下载不发送）

`send` 模式流程：
1. 解析 `paper_id` 为标准 arXiv 标识
2. 调用 arXiv 官方 API 获取论文元信息
3. 先发送标题/作者/摘要/链接信息
4. 尝试下载并上传 PDF
5. 下载超限或 PDF 失败时仅保留信息消息

`uid` 模式流程：
1. 下载 PDF
2. 注册为当前会话附件 UID
3. 返回论文概要和 `<attachment uid="file_xxx"/>`，供 `file_analysis_agent` 继续下载和分析

`info` 模式流程：
1. 调用 arXiv 官方 API 获取论文元信息
2. 返回标题、作者、分类、日期、摘要预览和链接
3. 不下载 PDF、不发送消息、不注册附件

配置依赖：
- `config.toml` 中的 `[arxiv]` 段控制 PDF 大小上限、作者预览和摘要预览等

目录结构：
- `config.json`：工具定义
- `handler.py`：执行逻辑
