# 文件分析助手

用于分析用户提供的附件、内部 UID、URL、legacy file_id、arXiv 论文标识或 Bilibili 视频标识，并从文件内容中识别、提取、摘要或统计信息。

可处理：
- PDF、Word、Excel、PPT、文本、代码和压缩包
- 图片、音频、视频等多模态内容识别
- arXiv ID/URL 对应的论文 PDF 分析
- Bilibili BV/AV/URL 对应的视频内容分析
- 表格、文字、错误日志、代码结构、文件清单和客观画面信息提取

不适合：
- 没有文件来源的开放式搜索或知识问答
- 需要联网查资料才能回答的问题，交给 `web_agent`
- 执行可疑文件、安全鉴定或修改文件内容

输入最好包含明确的附件 UID、URL、file_id、arXiv ID/URL、Bilibili BV/AV/URL，以及希望提取或关注的内容；PDF 视觉分析可指定页码范围。
