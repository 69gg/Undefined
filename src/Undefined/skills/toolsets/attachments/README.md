# attachments 工具集

## get_uid_by_url

通过 URL 查询对应的附件 UID。适用于需要从已知来源链接查找已注册附件的场景。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `url` | `string` | 是 | 来源 URL |

## get_url_by_uid

通过附件 UID 查询对应的 URL（source_ref）。适用于需要从已注册的附件追溯其来源链接的场景。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `uid` | `string` | 是 | 附件 UID，如 pic_xxx 或 file_xxx |

