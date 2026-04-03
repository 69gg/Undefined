# memes 工具集

表情包相关工具集合，工具名以 `memes.*` 命名。

主要能力：
- 在全局表情包库中做关键词检索
- 在全局表情包库中做语义检索
- 将关键词检索与语义检索混合使用
- 根据统一图片 `uid` 直接发送独立表情包消息

当前工具：
- `memes.search_memes`
- `memes.send_meme_by_uid`

检索说明：
- `query_mode=keyword`：只跑关键词检索
- `query_mode=semantic`：只跑语义检索
- `query_mode=hybrid`：同时跑关键词和语义检索，再合并排序
- `keyword_query` 与 `semantic_query` 可分开传；未单独提供时，回退使用 `query`

统一图片 `uid`：
- 表情包与普通图片复用同一套 `uid` 语义
- `memes.search_memes` 返回的 `uid` 既可用于 `memes.send_meme_by_uid`，也可直接插入 `<pic uid="..."/>`
