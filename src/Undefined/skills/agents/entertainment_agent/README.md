# entertainment_agent 智能体

用于娱乐互动类任务，如绘图、小说、星座、随机视频推荐等。

目录结构：
- `config.json`：智能体定义
- `intro.md`：能力说明
- `prompt.md`：系统提示词
- `tools/`：娱乐相关子工具

运行机制：
- 由 `AgentRegistry` 自动发现并注册
- 根据 `prompt` 调度内部工具完成任务

开发提示：
- 注意对外部接口进行失败兜底与超时控制
