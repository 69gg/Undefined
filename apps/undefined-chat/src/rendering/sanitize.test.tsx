import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom";
import { renderWithProviders } from "../test-utils";
import { MarkdownContent } from "./MarkdownContent";
import { markdownRehypePlugins, markdownSanitizeSchema } from "./sanitize";

/**
 * XSS sanitize 回归测试。
 *
 * 守护 P-render 启用的「正文内联 HTML 渲染 + sanitize」安全行为：
 * MarkdownContent 经 rehype-raw 解析正文原始 HTML，再经 rehype-sanitize 按
 * {@link markdownSanitizeSchema} 白名单清洗。任何放宽白名单、误删 sanitize 插件、
 * 调换插件顺序的回退都会让本组测试变红。
 *
 * 实现细节（按 sanitize.ts / hast-util-sanitize defaultSchema 写断言，非臆测）：
 * - script 在 defaultSchema.strip 中，标签连同内容被剥离。
 * - on*（onerror/onclick…）不在任何 attributes 白名单中，被剥离。
 * - href 协议白名单 = http/https/irc/ircs/mailto/xmpp；src = http/https；
 *   javascript:/data: 等危险协议的属性被整条移除。
 * - iframe/object/embed/form 不在 tagNames 中，标签被剥离（子文本保留）。
 * - 安全内容（b/strong/a[https]/img[https]/span[class]/table/列表）正常渲染。
 */

const noop = () => {};

function renderMarkdown(content: string) {
	return renderWithProviders(
		<MarkdownContent content={content} onPreviewHtml={noop} />,
	);
}

describe("MarkdownContent XSS sanitize", () => {
	it("剥离 <script> 标签：不入 DOM、不执行", () => {
		const spy = vi.fn();
		(window as unknown as { __xss_script__?: () => void }).__xss_script__ = spy;
		const { container } = renderMarkdown(
			"前文<script>window.__xss_script__&&window.__xss_script__()</script>后文",
		);

		// script 标签不出现在 DOM
		expect(container.querySelector("script")).toBeNull();
		// 标签内容不作为可见文本注入
		expect(container.textContent).not.toContain("window.__xss_script__");
		// 周边安全文本仍正常渲染
		expect(screen.getByText(/前文/)).toBeInTheDocument();
		expect(screen.getByText(/后文/)).toBeInTheDocument();
		// 脚本未执行（rehype-raw 经 sanitize 不会运行脚本，双保险断言）
		expect(spy).not.toHaveBeenCalled();

		(window as unknown as { __xss_script__?: () => void }).__xss_script__ =
			undefined;
	});

	it("剥离 <img onerror=...> 等 on* 事件处理属性", () => {
		const { container } = renderMarkdown(
			'<img src="x" onerror="window.__xss_onerror__=1" onclick="window.__xss_click__=1">',
		);

		const img = container.querySelector("img");
		// 图片标签本身在白名单内，被保留
		expect(img).not.toBeNull();
		// 但 on* 事件处理属性被剥离
		expect(img?.getAttribute("onerror")).toBeNull();
		expect(img?.getAttribute("onclick")).toBeNull();
		expect(img?.hasAttribute("onerror")).toBe(false);
		expect(img?.hasAttribute("onclick")).toBe(false);
	});

	it('中和 <a href="javascript:..."> 危险协议', () => {
		const { container } = renderMarkdown(
			'<a href="javascript:window.__xss_href__=1">点我</a>',
		);

		const anchor = container.querySelector("a");
		expect(anchor).not.toBeNull();
		// javascript: 不在 href 协议白名单（http/https/irc/ircs/mailto/xmpp），
		// 危险属性被整条移除，绝不保留 javascript: 协议。
		const href = anchor?.getAttribute("href") ?? "";
		expect(href.toLowerCase()).not.toContain("javascript:");
		// 链接文本保留
		expect(screen.getByText("点我")).toBeInTheDocument();
	});

	it('中和 <img src="javascript:..."> 危险协议（src 白名单仅 http/https）', () => {
		const { container } = renderMarkdown(
			'<img src="javascript:window.__xss_imgsrc__=1" alt="bad">',
		);

		const img = container.querySelector("img");
		expect(img).not.toBeNull();
		const src = img?.getAttribute("src") ?? "";
		expect(src.toLowerCase()).not.toContain("javascript:");
	});

	it("剥离 <iframe>/<object>/<embed>/<form> 等危险标签", () => {
		const { container } = renderMarkdown(
			[
				'<iframe src="https://evil.example.com"></iframe>',
				'<object data="https://evil.example.com/x.swf"></object>',
				'<embed src="https://evil.example.com/x.swf">',
				'<form action="https://evil.example.com"><input type="text"></form>',
			].join("\n"),
		);

		// 这些标签均不在 markdownSanitizeSchema.tagNames 白名单中，被剥离
		expect(container.querySelector("iframe")).toBeNull();
		expect(container.querySelector("object")).toBeNull();
		expect(container.querySelector("embed")).toBeNull();
		expect(container.querySelector("form")).toBeNull();
	});

	it("保留安全内联 HTML：粗体/链接/图片/带 class 的 span", () => {
		const { container } = renderMarkdown(
			[
				"<b>加粗</b> <strong>强调</strong>",
				'<a href="https://example.com">安全链接</a>',
				'<img src="https://example.com/ok.png" alt="安全图片">',
				'<span class="highlight">高亮文字</span>',
			].join("\n"),
		);

		// 粗体 / 强调标签保留
		expect(screen.getByText("加粗").tagName).toBe("B");
		expect(screen.getByText("强调").tagName).toBe("STRONG");

		// https 链接保留 href，并由组件附加安全属性
		const anchor = screen.getByText("安全链接").closest("a");
		expect(anchor).toHaveAttribute("href", "https://example.com");
		expect(anchor).toHaveAttribute("target", "_blank");
		expect(anchor).toHaveAttribute("rel", "noopener noreferrer");

		// https 图片保留 src
		const img = screen.getByAltText("安全图片");
		expect(img).toHaveAttribute("src", "https://example.com/ok.png");

		// 带 class 的 span 保留（className 是 schema 唯一放宽的展示属性）
		const span = container.querySelector("span.highlight");
		expect(span).not.toBeNull();
		expect(span?.textContent).toBe("高亮文字");
	});

	it("保留 HTML 表格与列表结构", () => {
		const { container } = renderMarkdown(
			[
				"<table><thead><tr><th>列</th></tr></thead>",
				"<tbody><tr><td>值</td></tr></tbody></table>",
				"<ul><li>项一</li><li>项二</li></ul>",
			].join("\n"),
		);

		expect(container.querySelector("table")).not.toBeNull();
		expect(container.querySelector("th")?.textContent).toBe("列");
		expect(container.querySelector("td")?.textContent).toBe("值");
		const items = container.querySelectorAll("li");
		expect(items.length).toBe(2);
		expect(items[0]?.textContent).toBe("项一");
		expect(items[1]?.textContent).toBe("项二");
	});

	it("混合（恶意 + 安全）内容：剥离恶意、保留安全", () => {
		const spy = vi.fn();
		(window as unknown as { __xss_mixed__?: () => void }).__xss_mixed__ = spy;
		const { container } = renderMarkdown(
			[
				"<b>保留这个</b>",
				"<script>window.__xss_mixed__&&window.__xss_mixed__()</script>",
				'<img src="https://example.com/ok.png" alt="留" onerror="window.__xss_mixed__&&window.__xss_mixed__()">',
				'<a href="javascript:window.__xss_mixed__&&window.__xss_mixed__()">坏链</a>',
			].join("\n"),
		);

		// 安全标签保留
		expect(screen.getByText("保留这个").tagName).toBe("B");
		const img = screen.getByAltText("留");
		expect(img).toHaveAttribute("src", "https://example.com/ok.png");

		// 恶意向量被中和
		expect(container.querySelector("script")).toBeNull();
		expect(img.hasAttribute("onerror")).toBe(false);
		const badAnchor = screen.getByText("坏链").closest("a");
		expect((badAnchor?.getAttribute("href") ?? "").toLowerCase()).not.toContain(
			"javascript:",
		);
		expect(spy).not.toHaveBeenCalled();

		(window as unknown as { __xss_mixed__?: () => void }).__xss_mixed__ =
			undefined;
	});
});

describe("markdownSanitizeSchema 白名单契约", () => {
	it("script 在 strip 列表中，且不在 tagNames 白名单", () => {
		expect(markdownSanitizeSchema.strip).toContain("script");
		expect(markdownSanitizeSchema.tagNames).not.toContain("script");
	});

	it("危险标签不在 tagNames 白名单", () => {
		for (const tag of ["iframe", "object", "embed", "form", "style"]) {
			expect(markdownSanitizeSchema.tagNames).not.toContain(tag);
		}
	});

	it("on* 事件处理属性不在任何 attributes 白名单", () => {
		const allAttrs = Object.values(
			markdownSanitizeSchema.attributes ?? {},
		).flat();
		// attributes 项可能是字符串或 [name, ...allowedValues] 元组，取名字部分
		const attrNames = allAttrs.map((entry) =>
			Array.isArray(entry) ? entry[0] : entry,
		);
		for (const name of attrNames) {
			if (typeof name === "string") {
				expect(name.toLowerCase().startsWith("on")).toBe(false);
			}
		}
	});

	it("href/src 协议白名单不含危险协议", () => {
		const protocols = markdownSanitizeSchema.protocols ?? {};
		expect(protocols.href).toEqual(
			expect.arrayContaining(["http", "https", "mailto"]),
		);
		expect(protocols.href).not.toContain("javascript");
		expect(protocols.src).toEqual(["http", "https"]);
		expect(protocols.src).not.toContain("javascript");
	});

	it("仅最小化扩展：className 加入通配属性，其余可执行向量未放开", () => {
		const wildcard = markdownSanitizeSchema.attributes?.["*"] ?? [];
		expect(wildcard).toContain("className");
		// style 属性不应被放开（可承载 expression / url(javascript:) 等）
		expect(wildcard).not.toContain("style");
	});

	it("rehype 插件顺序固定：先 rehype-raw 再 rehype-sanitize", () => {
		// [rehypeRaw, [rehypeSanitize, schema]]
		expect(markdownRehypePlugins).toHaveLength(2);
		// 第一项是函数（rehype-raw 默认导出），第二项是 [plugin, schema] 元组
		expect(typeof markdownRehypePlugins[0]).toBe("function");
		expect(Array.isArray(markdownRehypePlugins[1])).toBe(true);
		const sanitizeEntry = markdownRehypePlugins[1] as [unknown, unknown];
		expect(typeof sanitizeEntry[0]).toBe("function");
		expect(sanitizeEntry[1]).toBe(markdownSanitizeSchema);
	});
});

/**
 * SVG / MathML / data: 隐式 XSS 向量回归守护。
 *
 * 这些向量当前都被 {@link markdownSanitizeSchema}（= hast-util-sanitize
 * defaultSchema + className 扩展）天然挡住，但此前无显式测试。本组锁死该行为，
 * 防止未来升级 hast-util-sanitize 或误改 schema 导致回归：
 *
 * - svg/math 系标签（svg/use/animate/math/mtext…）均不在 defaultSchema.tagNames
 *   白名单中 → 标签被整体剥离（实测渲染为空 <p>），其上的 on* 与 href 自然失效。
 * - script 在 strip 列表中 → 标签连同内容删除，绝不执行（全局 spy 断言未调用）。
 * - data: 不在 protocols.href（http/https/irc/ircs/mailto/xmpp）或 protocols.src
 *   （http/https）白名单中 → href/src 属性被整条移除（getAttribute 返回 null）。
 * - 协议规避变体（vbscript:、含 tab 的 java&#9;script:、javascript&colon; 实体）
 *   同样不在协议白名单 → href 被移除。
 */
describe("MarkdownContent 隐式 XSS 向量（svg/math/data:）", () => {
	it("剥离整个 <svg> 子树并删除内嵌 <script>，脚本不执行", () => {
		const spy = vi.fn();
		(window as unknown as { __xss_svg__?: () => void }).__xss_svg__ = spy;
		const { container } = renderMarkdown(
			"<svg><script>window.__xss_svg__&&window.__xss_svg__()</script></svg>",
		);

		// svg 不在 tagNames 白名单 → 整体剥离；内嵌 script 同时被 strip。
		expect(container.querySelector("svg")).toBeNull();
		expect(container.querySelector("script")).toBeNull();
		// 脚本内容不作为文本注入，脚本未执行。
		expect(container.textContent).not.toContain("window.__xss_svg__");
		expect(spy).not.toHaveBeenCalled();

		(window as unknown as { __xss_svg__?: () => void }).__xss_svg__ = undefined;
	});

	it("剥离 <svg onload=...> 标签与事件属性", () => {
		const { container } = renderMarkdown('<svg onload="window.__xss=1"></svg>');

		// svg 标签被剥离，onload 无处依附。
		expect(container.querySelector("svg")).toBeNull();
		expect(container.querySelector("[onload]")).toBeNull();
	});

	it("剥离 <svg><use href=javascript:...> 危险链接元素", () => {
		const { container } = renderMarkdown(
			'<svg><use href="javascript:window.__xss=1"/></svg>',
		);

		// svg / use 均不在白名单，整体剥离。
		expect(container.querySelector("svg")).toBeNull();
		expect(container.querySelector("use")).toBeNull();
		expect(container.innerHTML.toLowerCase()).not.toContain("javascript:");
	});

	it("剥离 <svg><animate onbegin=...> 动画事件向量", () => {
		const { container } = renderMarkdown(
			'<svg><animate onbegin="window.__xss=1"/></svg>',
		);

		expect(container.querySelector("svg")).toBeNull();
		expect(container.querySelector("animate")).toBeNull();
		expect(container.querySelector("[onbegin]")).toBeNull();
	});

	it("剥离 <math> 子树并删除内嵌 <script>", () => {
		const spy = vi.fn();
		(window as unknown as { __xss_math__?: () => void }).__xss_math__ = spy;
		const { container } = renderMarkdown(
			"<math><mtext><script>window.__xss_math__&&window.__xss_math__()</script></mtext></math>",
		);

		// math/mtext 不在 tagNames 白名单 → 整体剥离；script 被 strip。
		expect(container.querySelector("math")).toBeNull();
		expect(container.querySelector("mtext")).toBeNull();
		expect(container.querySelector("script")).toBeNull();
		expect(container.textContent).not.toContain("window.__xss_math__");
		expect(spy).not.toHaveBeenCalled();

		(window as unknown as { __xss_math__?: () => void }).__xss_math__ =
			undefined;
	});

	it('移除 <a href="data:..."> 的 data: URI（协议白名单不含 data）', () => {
		const { container } = renderMarkdown(
			'<a href="data:text/html,<script>alert(1)</script>">点我</a>',
		);

		// <a> 在白名单内被保留，但 data: 不在 href 协议白名单 → href 被整条移除。
		const anchor = container.querySelector("a");
		expect(anchor).not.toBeNull();
		expect(anchor?.getAttribute("href")).toBeNull();
		expect((anchor?.getAttribute("href") ?? "").toLowerCase()).not.toContain(
			"data:",
		);
		// 链接文本保留。
		expect(screen.getByText("点我")).toBeInTheDocument();
	});

	it('移除 <img src="data:..."> 的 data: URI（src 白名单仅 http/https）', () => {
		const { container } = renderMarkdown(
			'<img src="data:image/svg+xml,<svg onload=alert(1)></svg>" alt="bad">',
		);

		// <img> 在白名单内被保留，但 data: 不在 src 协议白名单 → src 被整条移除。
		const img = container.querySelector("img");
		expect(img).not.toBeNull();
		expect(img?.getAttribute("src")).toBeNull();
		expect((img?.getAttribute("src") ?? "").toLowerCase()).not.toContain(
			"data:",
		);
	});

	it("移除协议规避变体的 href：vbscript:/含 tab 的 javascript/实体编码", () => {
		for (const href of [
			"vbscript:msgbox(1)",
			"java&#9;script:alert(1)", // 含 tab 字符实体的 javascript:
			"javascript&colon;alert(1)", // &colon; 实体形式
		]) {
			const { container } = renderMarkdown(`<a href="${href}">x</a>`);
			const anchor = container.querySelector("a");
			expect(anchor).not.toBeNull();
			// 三种变体均不在 href 协议白名单 → href 被移除，绝不残留可执行协议。
			const got = (anchor?.getAttribute("href") ?? "").toLowerCase();
			expect(got).not.toContain("vbscript:");
			expect(got).not.toContain("javascript:");
		}
	});
});

describe("markdownSanitizeSchema 隐式 XSS 契约（svg/math/data:）", () => {
	it("svg 系标签不在 tagNames 白名单", () => {
		for (const tag of ["svg", "use", "animate", "foreignObject", "set"]) {
			expect(markdownSanitizeSchema.tagNames).not.toContain(tag);
		}
	});

	it("math 系标签不在 tagNames 白名单", () => {
		for (const tag of ["math", "mtext", "annotation", "maction"]) {
			expect(markdownSanitizeSchema.tagNames).not.toContain(tag);
		}
	});

	it("data 不在 href/src 协议白名单", () => {
		const protocols = markdownSanitizeSchema.protocols ?? {};
		expect(protocols.href).not.toContain("data");
		expect(protocols.src).not.toContain("data");
	});

	it("vbscript 不在 href/src 协议白名单", () => {
		const protocols = markdownSanitizeSchema.protocols ?? {};
		expect(protocols.href).not.toContain("vbscript");
		expect(protocols.src).not.toContain("vbscript");
	});
});
