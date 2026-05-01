# /help 命令说明

## 功能
查看命令列表，或查看某个命令的详细帮助。帮助内容默认渲染为图片，便于阅读较长文档。

## 用法
- `/help`
- `/help -t`
- `/help <command>`
- `/help <command> -t`

## 示例
- `/help`
- `/help -t`
- `/help stats`
- `/help /faq`
- `/help stats -t`

## 说明
- `<command>` 支持带或不带 `/` 前缀。
- `<command>` 支持命令别名（若该命令配置了别名）。
- `-t` 会直接发送纯文本帮助，不进行图片渲染。
- 列表页尾部提示文案由 `help/config.json` 的 `help_footer` 字段配置并自动渲染。
