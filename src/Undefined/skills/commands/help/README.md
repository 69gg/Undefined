# /help 命令说明

## 功能
查看命令列表，或查看某个命令的详细帮助。命令详情默认渲染为图片，便于阅读较长文档。

## 用法
- `/help`
- `/help <command>`
- `/help <command> --text`

## 示例
- `/help`
- `/help stats`
- `/help /faq`
- `/help stats --text`

## 说明
- `<command>` 支持带或不带 `/` 前缀。
- `<command>` 支持命令别名（若该命令配置了别名）。
- `-t` / `--text` / `--plain` / `--plaintext` / `--raw` 会直接发送纯文本详情，不进行图片渲染。
- 列表页尾部提示文案由 `help/config.json` 的 `help_footer` 字段配置并自动渲染。
