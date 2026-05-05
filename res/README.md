# 资源目录

本目录用于存放提示词、模板与文案资源。

加载规则（运行时）：
1. 优先读取运行目录下同名 `res/` 资源
2. 若不存在，则回退到安装包内置资源

常见子目录：
- `res/prompts/`：模型提示词与模板
- `res/agents/intro/`：智能体介绍与自动生成内容

主系统提示词约定：
- `res/prompts/undefined.xml` 与 `res/prompts/undefined_nagaagent.xml` 共享 Undefined 的基础身份、昵称与项目归属边界。
- `undefined_nagaagent.xml` 只在上下文明确涉及 NagaAgent 时承接相关工具接入关系，不应在普通自我介绍或无关对话里主动提起。

自定义建议：
- 在运行目录放置同名文件覆盖默认资源
- 需要全局默认修改时，建议在源码中更新 `res/` 后运行
