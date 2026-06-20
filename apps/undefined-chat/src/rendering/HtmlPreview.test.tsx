import { render as baseRender, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LOCALE_STORAGE_KEY, LanguageProvider } from "../i18n";
import type { MarkdownContentProps } from "./MarkdownContent";
import { MarkdownContent } from "./MarkdownContent";

// MarkdownContent 内部经 CodeBlock 使用 useTranslation，需置于 LanguageProvider 下
function render(node: ReactNode) {
	return baseRender(<LanguageProvider>{node}</LanguageProvider>);
}

describe("HTML Preview", () => {
	let onPreviewHtml: MarkdownContentProps["onPreviewHtml"];

	beforeEach(() => {
		// 固定为简体中文，使断言不受测试环境 navigator.language 影响
		window.localStorage.setItem(LOCALE_STORAGE_KEY, "zh-CN");
		onPreviewHtml = vi.fn();
	});

	it("should show preview button for HTML code blocks", () => {
		const content = "```html\n<h1>Hello</h1>\n```";
		render(<MarkdownContent content={content} onPreviewHtml={onPreviewHtml} />);

		expect(screen.getByText("预览 HTML")).toBeInTheDocument();
	});

	it("should show preview button for HTM code blocks", () => {
		const content = "```htm\n<p>Test</p>\n```";
		render(<MarkdownContent content={content} onPreviewHtml={onPreviewHtml} />);

		expect(screen.getByText("预览 HTML")).toBeInTheDocument();
	});

	it("should not show preview button for non-HTML code blocks", () => {
		const content = "```javascript\nconsole.log('hi');\n```";
		render(<MarkdownContent content={content} onPreviewHtml={onPreviewHtml} />);

		expect(screen.queryByText("预览 HTML")).not.toBeInTheDocument();
	});

	it("should call onPreviewHtml with correct data when clicked", async () => {
		const user = userEvent.setup();
		const htmlCode = "<h1>Test Page</h1>";
		const content = `\`\`\`html\n${htmlCode}\n\`\`\``;

		render(<MarkdownContent content={content} onPreviewHtml={onPreviewHtml} />);

		const previewButton = screen.getByText("预览 HTML");
		await user.click(previewButton);

		expect(onPreviewHtml).toHaveBeenCalledOnce();
		expect(onPreviewHtml).toHaveBeenCalledWith({
			title: "HTML 预览",
			html: htmlCode,
		});
	});

	it("should handle multiple code blocks", async () => {
		const user = userEvent.setup();
		const content = `
\`\`\`html
<div>First</div>
\`\`\`

Some text

\`\`\`html
<div>Second</div>
\`\`\`
`;
		render(<MarkdownContent content={content} onPreviewHtml={onPreviewHtml} />);

		const buttons = screen.getAllByText("预览 HTML");
		expect(buttons).toHaveLength(2);

		await user.click(buttons[0]);
		expect(onPreviewHtml).toHaveBeenLastCalledWith({
			title: "HTML 预览",
			html: "<div>First</div>",
		});

		await user.click(buttons[1]);
		expect(onPreviewHtml).toHaveBeenLastCalledWith({
			title: "HTML 预览",
			html: "<div>Second</div>",
		});
	});
});
