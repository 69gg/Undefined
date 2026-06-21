# Undefined 自身代码查阅助手

用于只读查阅 **Undefined 项目自身** 的源码、测试、文档、资源、脚本、配置示例和 App 实现细节。

可处理：
- 查阅 `src/`、`scripts/`、`tests/`、`res/`、`docs/`、`apps/`
- 查阅根目录 `README.md`、`CHANGELOG.md`、`ARCHITECTURE.md`、`config.toml.example`
- 浏览目录、按 glob 查找文件、按关键词或正则搜索内容
- 基于当前文件内容解释 Undefined 的实现、配置和测试覆盖

不适合：
- 写代码、改文件、运行命令、验证或打包交付，交给 `code_delivery_agent`
- NagaAgent 子模块问题；`code/NagaAgent/` 是 NagaAgent 子模块，不属于 Undefined 自身代码查阅范围，交给 `naga_code_analysis_agent`
- 用户上传/外部文件解析，交给 `file_analysis_agent`
- `.env`、`data/`、`logs/`、`.git/`、`code/`、`pyproject.toml` 等未列入白名单的路径

输入最好包含模块、文件、报错、配置项、测试名或功能点。
