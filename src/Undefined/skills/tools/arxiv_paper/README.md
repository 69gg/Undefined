# arxiv_paper 工具

下载并发送 arXiv 论文到群聊或私聊。支持 arXiv ID、`arXiv:` 前缀和 arXiv 页面链接。

常用参数：
- `paper_id`：论文标识（如 `2501.01234`、`arXiv:2501.01234v2`、`https://arxiv.org/abs/2501.01234`）
- `target_type`：可选，目标会话类型（`group`/`private`）
- `target_id`：可选，目标会话 ID

运行流程：
1. 解析 `paper_id` 为标准 arXiv 标识
2. 调用 arXiv 官方 API 获取论文元信息
3. 先发送标题/作者/摘要/链接信息
4. 尝试下载并上传 PDF
5. 下载超限或 PDF 失败时仅保留信息消息

配置依赖：
- `config.toml` 中的 `[arxiv]` 段控制 PDF 大小上限、作者预览和摘要预览等

目录结构：
- `config.json`：工具定义
- `handler.py`：执行逻辑
