# info_agent 智能体

用于信息查询类任务，如天气、热搜、价格、B 站信息查询等。

目录结构：
- `config.json`：智能体定义
- `intro.md`：能力说明（提供给主 AI）
- `prompt.md`：系统提示词
- `tools/`：该智能体可调用的子工具集合

运行机制：
- 由 `AgentRegistry` 自动发现并注册
- 调用方式为 `prompt` 参数驱动

开发提示：
- 更新能力说明请修改 `intro.md`
- 行为约束与思考风格请修改 `prompt.md`
