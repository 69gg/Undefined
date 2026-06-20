import type { Options as ReactMarkdownOptions } from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import type { Options as SanitizeSchema } from "rehype-sanitize";

/** react-markdown `rehypePlugins` 的列表类型（来源于 unified 的 PluggableList）。 */
type RehypePlugins = NonNullable<ReactMarkdownOptions["rehypePlugins"]>;

/**
 * 正文内联 HTML 渲染的 sanitize 白名单 schema。
 *
 * 以 `hast-util-sanitize` 的 {@link defaultSchema} 为安全基线（已天然剥离
 * `script`、`on*` 事件处理属性、`style` 属性，并将协议限制为 `http/https/mailto`
 * 等安全协议，未收录 `iframe`/`object`/`embed`/`form` 等危险标签），在其上做
 * **最小化扩展**，仅放开纯展示需要的安全属性，绝不放开任何可执行向量。
 *
 * 设计原则：宁严勿宽。新增项仅限不可能承载脚本的展示属性（如 `className`）。
 *
 * 注意：正文内联 HTML 渲染与「HTML 预览窗口」是两回事——预览窗口可运行脚本，
 * 正文内联 HTML 经此 schema 后绝不执行任何脚本。
 */
export const markdownSanitizeSchema: SanitizeSchema = {
	...defaultSchema,
	// 允许 className 用于纯展示样式（class 名无法承载脚本）。
	// defaultSchema 仅在 code / li 上允许 className，这里补充常见展示标签，
	// 以保留来源 HTML 的排版样式（如 <span class="...">、<div class="...">）。
	attributes: {
		...defaultSchema.attributes,
		"*": [...(defaultSchema.attributes?.["*"] ?? []), "className"],
	},
};

/**
 * react-markdown `rehypePlugins` 列表：先 `rehype-raw` 把正文里的原始 HTML
 * 解析进 hast 树，再用 `rehype-sanitize` 按 {@link markdownSanitizeSchema}
 * 白名单清洗。
 *
 * **顺序不可调换**：必须先解析再清洗，否则原始 HTML 不会被白名单过滤。
 */
export const markdownRehypePlugins: RehypePlugins = [
	rehypeRaw,
	[rehypeSanitize, markdownSanitizeSchema],
];
