# file_analysis_agent 智能体

用于文件解析与分析（PDF/Word/Excel/PPT 等），并支持代码分析、多模态解析、arXiv 论文 PDF 获取分析、Bilibili 视频与图文获取分析和抖音视频获取分析。

目录结构：
- `config.json`：智能体定义
- `intro.md`：能力说明
- `prompt.md`：系统提示词
- `tools/`：文件解析与分析工具
- 共享主工具：通过 callable 仅可调用 `arxiv_paper(output_mode=uid)`、`bilibili_video(output_mode=uid)`、`bilibili_opus(output_mode=uid)`、`douyin_video(output_mode=uid)` 与 `jm_book(output_mode=uid)`，用于把 arXiv / Bilibili 视频与图文 / 抖音 / 禁漫车号转换为当前会话附件 UID 后再分析（图文会把正文图片逐张登记为 `pic_xxx`，禁漫车号输出未加密整本 PDF）

运行机制：
- 由 `AgentRegistry` 自动发现并注册
- 通过 `prompt` 输入任务描述并调用内部工具
- 内部附件 UID（`pic_xxx` / `file_xxx`）由工具按当前会话作用域解析；多模态分析可直接传 UID，其他解析工具先用 `download_file` 转成本地路径
- `download_file` 的附件回源遇到目标策略拒绝、响应读取异常等失败时，会记录日志并返回“附件 UID 本地化失败”，不会继续尝试 URL 下载；`TimeoutError` 及其他 `OSError` 仍返回“附件文件读取失败”，任务取消正常向上传递
- PDF 文字提取走 `extract_pdf`；扫描版、图表、版式或指定页码范围视觉分析走 `describe_pdf_page`
- `extract_archive(list)` 可以列出本地压缩包；解压前先用 `download_file` 取得下载缓存内路径，解压目标限定为压缩包所在目录的子目录。TAR 显式使用 `data` 安全过滤器，拒绝越界成员、指向外部的链接及设备文件。缺少 `tarfile.data_filter` 的旧 Python 补丁版本仍可列出文件，但会拒绝 TAR 解压并提示更新补丁版本，不回退到无过滤解压。
- `cleanup_temp.task_uuid` 只接受下载缓存的直接子目录名，拒绝绝对路径、路径跳转和符号链接；留空清理时跳过符号链接目录。

开发提示：
- 解析类工具尽量使用异步 I/O 或 `asyncio.to_thread`
