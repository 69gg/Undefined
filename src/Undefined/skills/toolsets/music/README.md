# music 工具集

## browse_playlists

浏览指定平台的歌单。action=tags 获取可用分类与排序；action=list 按 tag_id/sort_id 分页列出歌单；action=detail 按 playlist_id 读取歌单歌曲，并为每首歌返回当前任务有效的 track_ref。后续歌曲工具只需传递所选引用，不要构造 Track。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `action` | `string(tags/list/detail)` | 是 | 浏览动作 |
| `source` | `string(kw/kg/tx/wy/mg)` | 是 | 音乐平台（默认 `wy`） |
| `tag_id` | `string` | 否 | action=list 时可选，来自 tags 结果 |
| `sort_id` | `string` | 否 | action=list 时可选，来自 tags 结果 |
| `playlist_id` | `string` | 否 | action=detail 时必填，来自搜索或列表结果 |
| `page` | `integer` | 否 | list/detail 的页码（默认 `1`） |

## browse_rankings

浏览指定音乐平台的排行榜。action=list 获取榜单及 ranking_id；action=detail 分页读取榜单歌曲，并为每首歌返回当前任务有效的 track_ref。后续歌曲工具只需传递所选引用，不要构造 Track。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `action` | `string(list/detail)` | 是 | 浏览动作 |
| `source` | `string(kw/kg/tx/wy/mg)` | 是 | 音乐平台（默认 `wy`） |
| `ranking_id` | `string` | 否 | action=detail 时必填，来自 list 结果 |
| `page` | `integer` | 否 | 榜单详情页码（默认 `1`） |

## find_song_matches

根据当前任务中的 track_ref 查找其他音乐平台上的匹配版本，可用于比较音质或在原平台音频不可用时选择候选。返回精简候选列表，每项的新 track_ref 可直接传给其他歌曲工具。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `track_ref` | `string` | 是 | 歌曲候选返回的当前任务内引用 |

## get_audio

下载或解析 track_ref 对应歌曲的音频，但只准备交付内容，本工具本身绝不会向用户发送消息或文件。track_ref 必须来自当前任务中的歌曲候选，不要自行构造 Track。若用户未指定音质，应先查看该候选的 qualities，灵活选择其中实际列出的最高可用值并显式传入 quality；用户指定版本、格式或音质时优先遵从，不要用固定音质覆盖。delivery=attachment（默认）会下载音频、注册当前会话附件，并返回 JSON 中的 attachment 标签和 uid：普通音频文件必须在下一轮调用 messages.send_message，把返回的 <attachment uid="..."/> 原样放入 message；仅当用户明确要求原生语音消息时，才调用 messages.send_voice 并传入返回的 uid，不要两种方式重复发送。delivery=url 只返回可能快速失效的直链，也必须再用 messages.send_message 发给用户。获取成功不等于交付完成，发送工具成功后才可结束。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `track_ref` | `string` | 是 | 歌曲候选返回的当前任务内引用 |
| `quality` | `string(flac24bit/flac/wav/ape/320k/192k/128k)` | 否 | 期望音质。用户未指定时，不要机械省略或固定填写；应检查所选候选的 qualities 并传入其中实际列出的最高可用值 |
| `strict_quality` | `boolean` | 否 | 是否禁止自动降级到其他音质（默认 `False`） |
| `delivery` | `string(attachment/url)` | 否 | attachment=只下载并注册会话普通音频附件，不发送；url=只解析短时有效直链，不发送。两种模式都必须再调用相应消息工具完成交付（默认 `attachment`） |

## get_comments

分页获取 track_ref 对应歌曲的最新评论、热门评论或指定评论的回复。mode=replies 时必须传入前一次评论结果中的 comment_id。track_ref 必须来自当前任务中的歌曲候选。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `track_ref` | `string` | 是 | 歌曲候选返回的当前任务内引用 |
| `mode` | `string(latest/hot/replies)` | 否 | 评论类型（默认 `latest`） |
| `comment_id` | `string` | 否 | mode=replies 时必填 |
| `page` | `integer` | 否 | 页码（默认 `1`） |
| `limit` | `integer` | 否 | 每页数量（默认 `20`） |

## get_cover

获取 track_ref 对应歌曲的封面。默认下载并注册为当前会话图片附件，返回的 <attachment uid="..."/> 应直接嵌入回复；只有明确需要原始地址时才使用 delivery=url。track_ref 必须来自当前任务中的歌曲候选。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `track_ref` | `string` | 是 | 歌曲候选返回的当前任务内引用 |
| `delivery` | `string(attachment/url)` | 否 | attachment=返回会话附件；url=返回封面原始地址（默认 `attachment`） |

## get_hot_search

获取一个或全部音乐平台的实时热搜词，可用于发现当前热门歌曲后再调用 music.search_songs。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source` | `string(all/kw/kg/tx/wy/mg)` | 否 | 平台，all 表示汇总全部平台（默认 `all`） |

## get_lyrics

获取歌曲歌词及平台提供的翻译、逐字歌词等数据。track_ref 必须来自当前任务中的 music.search_songs、歌单详情、排行榜详情或匹配结果；不要自行构造 Track。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `track_ref` | `string` | 是 | 歌曲候选返回的当前任务内引用 |

## search_playlists

按关键词跨平台搜索歌单。先从结果取得歌单的平台和 ID，再用 music.browse_playlists 的 detail 动作读取歌曲；详情内每首歌曲会提供当前任务有效的 track_ref，后续歌曲能力只需传递该引用。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | `string` | 是 | 歌单名称或主题关键词 |
| `source` | `string(all/kw/kg/tx/wy/mg)` | 否 | 搜索平台（默认 `all`） |
| `page` | `integer` | 否 | 页码（默认 `1`） |
| `limit` | `integer` | 否 | 每页数量（默认 `20`） |

## search_songs

仅按关键词跨平台搜索歌曲并返回精简候选；每项包含当前任务内有效的 track_ref、歌名、歌手、专辑、时长、平台和可用音质，不包含需要复制的底层 Track。本工具不下载音频、不注册附件，也不向用户发送任何内容。若用户要求收听、下载或发送音频，看到结果后必须继续自主完成任务：不要固定取第一条或固定平台；先遵循用户指定的歌手、版本、平台和音质，未指定时结合歌名、歌手、专辑、版本标记与 qualities 灵活选择明确的原唱标准版，避开非用户所求的翻唱、现场、DJ、Remix、伴奏或纯音乐。匹配明确时无需询问，直接把所选候选的 track_ref 传给 music.get_audio；调用时从该候选的 qualities 中选择实际列出的最高可用音质，再按其返回说明调用消息发送工具。仅当没有结果或无法可靠判断原唱/目标版本时才询问用户。仅搜索成功不代表发歌任务完成。后续获取歌词、封面、评论、跨平台匹配或音频时只需传递对应 track_ref，不要自行构造 Track、歌曲 ID 或平台字段。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `query` | `string` | 是 | 歌曲名、歌手或组合关键词 |
| `source` | `string(all/kw/kg/tx/wy/mg)` | 否 | 平台：all=全部，kw=酷我，kg=酷狗，tx=QQ 音乐，wy=网易云，mg=咪咕（默认 `all`） |
| `page` | `integer` | 否 | 页码（默认 `1`） |
| `limit` | `integer` | 否 | 每页数量（默认 `20`） |

