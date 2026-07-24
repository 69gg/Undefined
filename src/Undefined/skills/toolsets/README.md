# 工具集 (Toolsets)

> 👈 **[返回技能中心主页](../README.md)** | **[阅读详细扩展开发指南](../../../../../docs/development.md)**

工具集用于按功能分类组织互相有关联的工具，便于分组管理与统一结构化命名。

## 目录结构

```
toolsets/
├── music/                   # lxmusic2api 高层音乐能力
│   ├── search_songs/        # 歌曲搜索
│   ├── browse_playlists/    # 歌单标签、列表与详情
│   ├── browse_rankings/     # 排行榜列表与详情
│   └── get_audio/           # 直链或会话音频附件
├── memes/                   # 表情包工具集
│   ├── search_memes/        # 表情包检索
│   └── send_meme_by_uid/    # 按 uid 发送表情包
├── render/                  # 渲染工具集
│   ├── render_html/         # HTML 渲染
│   ├── render_latex/        # LaTeX 渲染
│   └── render_markdown/     # Markdown 渲染
└── scheduler/               # 定时任务工具集
    ├── create_schedule_task/
    ├── delete_schedule_task/
    ├── list_schedule_tasks/
    └── update_schedule_task/
```

## 命名规范

- **目录结构**: `toolsets/{category}/{tool_name}/`
- **注册名称**: `{category}.{tool_name}`
- **示例**:
  - `toolsets/render/render_html/` → 注册为 `render.render_html`
  - `toolsets/scheduler/create_schedule_task/` → 注册为 `scheduler.create_schedule_task`

## 暴露给 Agent（callable.json）

默认情况下，工具集工具仅主 AI 可见。可通过 `callable.json` 按白名单暴露给 Agent：

**单个工具**（放在工具目录下）：

```
toolsets/{category}/{tool_name}/callable.json
```

**整个分类**（放在分类目录下，上级覆盖下级）：

```
toolsets/{category}/callable.json
```

```json
{
    "enabled": true,
    "allowed_callers": ["*"]
}
```

注册名为 `{category}.{tool_name}`。分类级与工具级同时存在时，分类级优先。详见 [docs/callable.md](../../../../docs/callable.md)。

## 添加新工具

1. 在对应分类目录下创建新目录
2. 添加 `config.json`（工具定义，使用 OpenAI 函数调用格式）
3. 添加 `handler.py`（执行逻辑，必须包含 `async def execute(args, context)`）
4. 自动被 `ToolRegistry` 发现和注册

## 运行特性

- **延迟加载**：仅在首次调用时导入 `handler.py`。
- **超时与取消**：单次执行默认 120 秒超时，超时会返回提示并记录统计。
- **结构化日志**：统一输出 `event=execute`、`status=success/timeout/error` 等字段。
- **热重载**：检测到 `toolsets/` 中的变更会自动重新加载。

热重载参数可通过 `config.toml` 的 `[skills]` 段配置；也支持同名环境变量覆盖。

## 示例：添加一个新工具

### 1. 创建目录

```bash
mkdir -p toolsets/my_category/my_new_tool
```

### 2. 创建 config.json

```json
{
    "type": "function",
    "function": {
        "name": "my_new_tool",
        "description": "工具描述",
        "parameters": {
            "type": "object",
            "properties": {
                "param1": {
                    "type": "string",
                    "description": "参数描述"
                }
            },
            "required": ["param1"]
        }
    }
}
```

### 3. 创建 handler.py

```python
from typing import Any
import logging

logger = logging.getLogger(__name__)

async def execute(args: dict[str, Any], context: dict[str, Any]) -> str:
    """执行工具逻辑"""
    param1 = args.get("param1")

    # 获取上下文中的回调函数
    send_message_callback = context.get("send_message_callback")

    # 执行你的逻辑
    result = f"处理结果: {param1}"

    return result
```

## 上下文参数

`context` 字典包含以下可用参数：

- `send_message_callback`: 发送消息的回调函数
- `send_image_callback`: 发送图片的回调函数
- `db`: 数据库连接
- 其他自定义上下文

## 现有工具集

### Render（渲染）

- `render.render_html`: 将 HTML 渲染为普通图片或指定宽度的单张长图
- `render.render_latex`: 将 LaTeX 渲染为图片；常见公式本地渲染，复杂内容回退 MathJax + Playwright
- `render.render_markdown`: 将 Markdown 渲染为普通图片或指定宽度的单张长图

### Memes（表情包）

- `memes.search_memes`: 支持 `keyword` / `semantic` / `hybrid` 三种检索模式
- `memes.send_meme_by_uid`: 根据统一图片 `uid` 发送独立表情包消息

### Scheduler（定时任务）

- `scheduler.create_schedule_task`: 创建定时任务
- `scheduler.delete_schedule_task`: 删除定时任务
- `scheduler.list_schedule_tasks`: 列出所有定时任务
- `scheduler.update_schedule_task`: 更新定时任务
- `scheduler.create_schedule_task` / `scheduler.update_schedule_task` 支持 `self_instruction` 参数，可在未来时刻调用 AI 自己执行一条延迟指令

### Messages（消息）

- `messages.send_message`: 发送文本、图片或普通文件附件
- `messages.send_voice`: 将当前会话可访问的音频附件 UID 显式作为语音发送；QQ 使用 `CQ:record`，微信使用原生 iLink 语音

### Music（音乐）

音乐工具集对接独立部署的 [lxmusic2api](https://github.com/69gg/lxmusic2api)。配置 `[lxmusic2api].base_url` 和 `api_key` 后，主 AI 可使用歌曲/歌单搜索、热搜、歌单与排行榜浏览、歌词、封面、评论、跨平台匹配和音频附件等高层能力。

- `music.search_songs` / `music.search_playlists` / `music.get_hot_search`
- `music.browse_playlists` / `music.browse_rankings`
- `music.get_lyrics` / `music.get_cover` / `music.get_comments`
- `music.find_song_matches` / `music.get_audio`

该分类没有 `callable.json`，因此默认仅主 AI 可见；同时不注册下载任务或作业管理类底层工具（例如 `music.download_jobs`、`music.create_download`）。搜索、歌单详情、排行榜详情和匹配结果会把完整 Track 保存到本次 AI 任务共享的 `MusicTrackReferenceStore`，只向模型返回精简候选及 `track_ref`；后续歌曲工具通过引用恢复原始 Track。

`track_ref` 可以跨同一次 `ask()` 内的工具轮次和 `tool_search`，任务结束即释放，不落盘也不跨用户消息。公开工具 schema 只包含 `track_ref`；执行层在未提供 `track_ref` 时暂时兼容旧的完整 `track` 参数，供已有代码和灰度调用使用，但这不是面向模型的公开契约。若两者同时存在，以 `track_ref` 为准。

音乐搜索与音频获取都不会自行发送消息。用户明确要音频时，主 AI 会根据搜索结果中的歌名、歌手、专辑、版本标记和 `qualities` 灵活选择原唱标准版及其最高可用音质，不固定第一条、平台或音质；用户已有具体要求时以其要求为准，只有没有结果或无法可靠判断原唱/目标版本时才追问。选定后把 `track_ref` 交给 `music.get_audio` 登记附件；普通音频把返回的 `<attachment uid="..."/>` 原样交给 `messages.send_message`，只有用户明确要求原生语音时才把返回的 `uid` 交给 `messages.send_voice`。

### Group Analysis（群聊深度分析）

- `group_analysis.member_structure`: 统计成员结构事实
- `group_analysis.message_mix`: 统计消息构成事实
- `group_analysis.member_activity`: 分析群成员活跃度
- `group_analysis.rank_members`: 对群成员进行多维度排名
- `group_analysis.filter_members`: 按条件过滤群成员
- `group_analysis.inactive_risk`: 检测长期潜水或新成员沉默等活跃风险
- `group_analysis.activity_trend`: 分析群活跃趋势变化
- `group_analysis.level_distribution`: 统计群成员等级分布
- `group_analysis.member_messages`: 分析指定成员消息情况
- `group_analysis.join_statistics`: 统计群成员加入趋势
- `group_analysis.new_member_activity`: 分析新成员活跃度变化
