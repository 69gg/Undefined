# render 工具集

渲染相关工具集合，工具名以 `render.*` 命名。

主要能力：
- HTML 渲染，保留完整 CSS、外部资源与脚本执行
- Markdown 渲染
- LaTeX 渲染
- HTML/Markdown 可显式传 `layout=long`、`width`、`padding` 输出无两侧外部留白的单张长图

`layout=default` 保持原有布局。`layout=long` 时，`width` 是最终图片像素宽度，高度按内容自动延伸；`padding=0` 可用于 HTML 全幅设计。

目录结构：
- 每个子目录对应一个工具（`config.json` + `handler.py`）
