# jm_book 工具

处理禁漫（JM / 18comic）本子。默认下载整本（一章一份加密 PDF，打包成一个无密码 zip）并通过合并转发 + 独立文件消息发送；也支持只注册为附件 UID 供文件分析使用，或只获取本子信息。支持 `JM350234`、`350234`、`https://18comic.vip/album/350234` 与 `?id=` 链接。

常用参数：
- `book_id`：本子车号（`JM350234` / `350234` / 禁漫链接，车号 5-8 位）
- `target_type`：可选，目标会话类型（`group`/`private`）
- `target_id`：可选，目标会话 ID
- `output_mode`：可选，`send`（默认，发送「信息 / 密码」合并转发并单独发送 zip 文件）、`uid`（只返回 `<attachment uid="file_xxx"/>`，不发送消息）或 `info`（只返回本子信息，不下载不发送）

`send` 模式流程：
1. 解析车号
2. 逐章下载，每章合成一份 AES-256 加密 PDF（`[jm].max_chapters` / `chapter_max_file_size` 限制；单章超限只跳过该章）
3. 把各章 PDF 打包成一个**无密码** zip（`JM<车号> <标题>.zip`，内部条目是 `JM<车号> <序号>[ <章节标题>].pdf`）
4. 发送「本子信息 / PDF 解密密码」两节点合并转发，再单独发一条 zip 文件消息（转发里的文件在 QQ 客户端下载会失败，独立文件消息才下得动，zip 同时进入群文件列表）
5. 密码随机生成 8 位，zip 内所有 PDF 共用一个密码；密码只出现在转发节点里，不写入历史

`uid` 模式流程：
1. 下载整本并合成为**一份未加密** PDF（加密会让 PDF 解析工具打不开）
2. 注册为当前会话附件 UID
3. 返回本子概要和 `<attachment uid="file_xxx"/>`，供 `file_analysis_agent` 继续解析

`info` 模式流程：
1. 调用移动端接口获取本子详情
2. 返回标题、作者、章节数、标签、观看/点赞/评论、简介预览、车号与站点链接
3. 不下载、不发送、不注册附件

配置依赖：
- `config.toml` 中的 `[jm]` 段控制功能开关、白名单、单章体积上限、章数上限、DPI 与画质等

目录结构：
- `config.json`：工具定义
- `callable.json`：共享授权（暴露给 `file_analysis_agent`）
- `handler.py`：执行逻辑
