# social_agent 智能体

用于社交媒体检索与内容推荐，如音乐、视频、用户信息等。

目录结构：
- `config.json`：智能体定义
- `intro.md`：能力说明
- `prompt.md`：系统提示词
- `tools/`：社交相关工具集合

运行机制：
- 由 `AgentRegistry` 自动发现并注册
- 通过 `prompt` 接收任务描述并分解执行

开发提示：
- 工具新增放在 `tools/` 下，配套 `config.json` + `handler.py`
