# file_analysis_agent 智能体

用于文件解析与分析（PDF/Word/Excel/PPT 等），并支持代码分析、多模态解析、arXiv 论文 PDF 获取分析和 Bilibili 视频获取分析。

目录结构：
- `config.json`：智能体定义
- `intro.md`：能力说明
- `prompt.md`：系统提示词
- `tools/`：文件解析与分析工具
- 共享主工具：通过 callable 仅可调用 `arxiv_paper(output_mode=uid)` 与 `bilibili_video(output_mode=uid)`，用于把 arXiv / Bilibili 标识转换为当前会话附件 UID 后再分析

运行机制：
- 由 `AgentRegistry` 自动发现并注册
- 通过 `prompt` 输入任务描述并调用内部工具
- 内部附件 UID（`pic_xxx` / `file_xxx`）由工具按当前会话作用域解析；多模态分析可直接传 UID，其他解析工具先用 `download_file` 转成本地路径
- PDF 文字提取走 `extract_pdf`；扫描版、图表、版式或指定页码范围视觉分析走 `describe_pdf_page`

开发提示：
- 解析类工具尽量使用异步 I/O 或 `asyncio.to_thread`
