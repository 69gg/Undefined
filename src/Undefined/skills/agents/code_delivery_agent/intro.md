# 代码交付助手

用于把用户的代码需求实际做成可交付文件或工程。

可处理：
- 单个脚本、配置、文档等轻量文本文件交付
- 多文件工程创建、修改、调试、测试和打包
- 从空目录开始，或从 Git 仓库指定分支/tag/commit 开始
- 在隔离 Docker 容器中安装依赖、执行命令和运行验证

不适合：
- 只读解释 Undefined 源码，交给 `undefined_self_code_agent`
- 只读解释 NagaAgent 源码，交给 `naga_code_analysis_agent`
- 用户上传文件内容解析，交给 `file_analysis_agent`

调用时需要明确任务目标、初始化来源、交付目标类型和目标 ID。
