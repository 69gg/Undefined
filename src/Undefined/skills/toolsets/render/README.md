# render 工具集

渲染相关工具集合，工具名以 `render.*` 命名。

主要能力：
- HTML 渲染，支持内联 CSS、脚本和 `data:` / `blob:` 资源；浏览器上下文默认完全离线，不加载外部资源
- Markdown 渲染
- LaTeX 渲染
- HTML/Markdown 可显式传 `layout=long`、`width`、`padding` 输出无两侧外部留白的单张长图

`layout=default` 保持原有布局。`layout=long` 时，`width` 是最终图片像素宽度，高度按内容自动延伸；`padding=0` 可用于 HTML 全幅设计。

交付参数（`render_html` / `render_markdown` 均支持，`render_latex` 不支持）：
- `delivery`（默认 `embed`）：`embed` 返回可插入回复的图片 UID；`send` 立即发送到目标
- `target_id` / `message_type`：仅 `delivery=send` 时需要，缺省时从当前会话推断

`render_latex` 额外支持 `output_format`（`png` / `pdf`）。

目录结构：
- 每个子目录对应一个工具（`config.json` + `handler.py`）
