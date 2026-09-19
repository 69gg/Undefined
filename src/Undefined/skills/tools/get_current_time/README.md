# get_current_time 工具

用于获取当前系统时间，可附带农历与黄历信息。

## 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `format` | string | `iso` | 输出格式：`iso`=ISO8601（仅时间戳），`text`=人类可读文本，`json`=结构化 JSON |
| `include_lunar` | boolean | `false` | 是否包含农历信息（年、月、日、生肖、干支等），需显式开启 |
| `include_almanac` | boolean | `false` | 是否包含黄历信息（宜忌、节气、节日、冲煞、胎神等），需显式开启 |

默认只返回 ISO8601 时间戳；农历 / 黄历 / 文本输出需要显式传参。

目录结构：
- `config.json`：工具定义
- `handler.py`：执行逻辑
