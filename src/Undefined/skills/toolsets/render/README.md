# render 工具集

渲染相关工具集合，工具名以 `render.*` 命名。

主要能力：
- HTML 渲染，支持内联 CSS、脚本和 `data:` / `blob:` 资源；浏览器上下文默认完全离线，不加载外部资源
- Markdown 渲染
- LaTeX 渲染
- HTML/Markdown 可显式传 `layout=long`、`width`、`padding` 输出无两侧外部留白的单张长图

`layout=default` 保持原有布局。`layout=long` 时，`width` 是**最大**图片像素宽度，高度按内容自动延伸；页面自身布局宽度比它窄时，最终图片收敛到「内容宽度 + 2 × `padding`」，收敛下限为 320px。探测保留显式设置的 `html` 宽度，并计算 `body` 的外边距盒宽、滚动宽度和后代最大右边界；默认 `width: auto` 的 `html` 不会阻止固定宽度 `body` 收缩。例如只设置 `body { width: 400px; margin: 0; }`、`padding=28` 时，最终宽度为 456px。`padding=0` 可用于 HTML 全幅设计。

收敛只发生在页面自己更窄的时候，铺满视口的响应式页面（含 Markdown 模板）宽度与旧版完全一致。

真实布局回归测试位于 `tests/test_render_content_width.py`，覆盖固定宽度、响应式页面和大量 DOM 后代。运行前可用 `uv run playwright install chromium` 安装浏览器；缺少 Chromium 时这些用例会明确跳过。

交付参数（`render_html` / `render_markdown` 均支持，`render_latex` 不支持）：
- `delivery`（默认 `embed`）：`embed` 返回可插入回复的图片 UID；`send` 立即发送到目标
- `target_id` / `message_type`：仅 `delivery=send` 时需要，缺省时从当前会话推断

`render_latex` 额外支持 `output_format`（`png` / `pdf`）。

目录结构：
- 每个子目录对应一个工具（`config.json` + `handler.py`）
