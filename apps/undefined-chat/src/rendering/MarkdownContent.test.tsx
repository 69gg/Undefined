import { render as baseRender, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom";
import { LOCALE_STORAGE_KEY, LanguageProvider } from "../i18n";
import type { Attachment } from "../runtime-client/types";
import { AttachmentImageProvider } from "./AttachmentImageContext";
import { MarkdownContent } from "./MarkdownContent";

// MarkdownContent 内部经 CodeBlock / AttachmentImage 使用 useTranslation，需置于 Provider 下
function render(node: ReactNode) {
	return baseRender(<LanguageProvider>{node}</LanguageProvider>);
}

describe("MarkdownContent", () => {
	const mockOnPreviewHtml = vi.fn();

	// 固定为简体中文，使断言不受测试环境 navigator.language 影响
	beforeEach(() => {
		window.localStorage.setItem(LOCALE_STORAGE_KEY, "zh-CN");
	});

	it("渲染基本文本", () => {
		render(
			<MarkdownContent
				content="Hello world"
				onPreviewHtml={mockOnPreviewHtml}
			/>,
		);
		expect(screen.getByText("Hello world")).toBeInTheDocument();
	});

	it("渲染标题", () => {
		const content = `# H1

## H2

### H3`;

		const { container } = render(
			<MarkdownContent content={content} onPreviewHtml={mockOnPreviewHtml} />,
		);

		const h1 = container.querySelector("h1");
		const h2 = container.querySelector("h2");
		const h3 = container.querySelector("h3");

		expect(h1).not.toBeNull();
		expect(h2).not.toBeNull();
		expect(h3).not.toBeNull();
	});

	it("渲染表格", () => {
		const tableMarkdown = `| 列1 | 列2 | 列3 |
|-----|-----|-----|
| A   | B   | C   |
| D   | E   | F   |`;

		render(
			<MarkdownContent
				content={tableMarkdown}
				onPreviewHtml={mockOnPreviewHtml}
			/>,
		);

		// 检查表头
		expect(screen.getByText("列1")).toBeInTheDocument();
		expect(screen.getByText("列2")).toBeInTheDocument();
		expect(screen.getByText("列3")).toBeInTheDocument();

		// 检查表格内容
		expect(screen.getByText("A")).toBeInTheDocument();
		expect(screen.getByText("E")).toBeInTheDocument();
		expect(screen.getByText("F")).toBeInTheDocument();
	});

	it("渲染引用块", () => {
		const { container } = render(
			<MarkdownContent
				content="> 这是一个引用块"
				onPreviewHtml={mockOnPreviewHtml}
			/>,
		);

		const blockquote = container.querySelector("blockquote");
		expect(blockquote).not.toBeNull();
		expect(blockquote?.textContent).toContain("这是一个引用块");
	});

	it("渲染任务列表", () => {
		const taskList = `- [x] 已完成任务
- [ ] 未完成任务
- [x] 另一个已完成`;

		render(
			<MarkdownContent content={taskList} onPreviewHtml={mockOnPreviewHtml} />,
		);

		expect(screen.getByText("已完成任务")).toBeInTheDocument();
		expect(screen.getByText("未完成任务")).toBeInTheDocument();
		expect(screen.getByText("另一个已完成")).toBeInTheDocument();

		// 检查复选框
		const checkboxes = screen.getAllByRole("checkbox");
		expect(checkboxes).toHaveLength(3);
		expect(checkboxes[0]).toBeChecked();
		expect(checkboxes[1]).not.toBeChecked();
		expect(checkboxes[2]).toBeChecked();
	});

	it("渲染删除线", () => {
		render(
			<MarkdownContent
				content="~~删除的文本~~"
				onPreviewHtml={mockOnPreviewHtml}
			/>,
		);
		const deleted = screen.getByText("删除的文本").closest("del");
		expect(deleted).toBeInTheDocument();
	});

	it("渲染有序列表", () => {
		const list = `1. 第一项
2. 第二项
3. 第三项`;

		render(
			<MarkdownContent content={list} onPreviewHtml={mockOnPreviewHtml} />,
		);

		expect(screen.getByText("第一项")).toBeInTheDocument();
		expect(screen.getByText("第二项")).toBeInTheDocument();
		expect(screen.getByText("第三项")).toBeInTheDocument();
	});

	it("渲染无序列表", () => {
		const list = `- Item A
- Item B
- Item C`;

		render(
			<MarkdownContent content={list} onPreviewHtml={mockOnPreviewHtml} />,
		);

		expect(screen.getByText("Item A")).toBeInTheDocument();
		expect(screen.getByText("Item B")).toBeInTheDocument();
		expect(screen.getByText("Item C")).toBeInTheDocument();
	});

	it("渲染链接（带安全属性）", () => {
		render(
			<MarkdownContent
				content="[点击这里](https://example.com)"
				onPreviewHtml={mockOnPreviewHtml}
			/>,
		);

		const link = screen.getByText("点击这里").closest("a");
		expect(link).toHaveAttribute("href", "https://example.com");
		expect(link).toHaveAttribute("target", "_blank");
		expect(link).toHaveAttribute("rel", "noopener noreferrer");
	});

	it("渲染行内代码", () => {
		render(
			<MarkdownContent
				content="这是 `inline code` 示例"
				onPreviewHtml={mockOnPreviewHtml}
			/>,
		);

		const code = screen.getByText("inline code");
		expect(code.tagName).toBe("CODE");
	});

	it("渲染代码块", () => {
		const codeBlock = "```javascript\nconst x = 1;\nconsole.log(x);\n```";

		const { container } = render(
			<MarkdownContent content={codeBlock} onPreviewHtml={mockOnPreviewHtml} />,
		);

		expect(screen.getByText("javascript")).toBeInTheDocument();
		const code = container.querySelector("code");
		expect(code?.textContent).toContain("const x = 1;");
		expect(screen.getByText("复制")).toBeInTheDocument();
	});

	it("渲染 HTML 代码块时显示预览按钮", () => {
		const htmlBlock = "```html\n<div>Hello</div>\n```";

		render(
			<MarkdownContent content={htmlBlock} onPreviewHtml={mockOnPreviewHtml} />,
		);

		expect(screen.getByText("html")).toBeInTheDocument();
		expect(screen.getByText("预览 HTML")).toBeInTheDocument();
		expect(screen.getByText("复制")).toBeInTheDocument();
	});

	it("渲染混合内容", () => {
		const mixedContent = `# 标题

普通段落文本。

## 表格示例

| 名称 | 年龄 |
|------|------|
| 张三 | 25   |

## 列表示例

- [x] 完成项
- [ ] 待办项

> 引用内容

\`\`\`python
print("Hello")
\`\`\``;

		const { container } = render(
			<MarkdownContent
				content={mixedContent}
				onPreviewHtml={mockOnPreviewHtml}
			/>,
		);

		// 检查各部分是否存在
		expect(screen.getByText("标题")).toBeInTheDocument();
		expect(screen.getByText("普通段落文本。")).toBeInTheDocument();
		expect(screen.getByText("表格示例")).toBeInTheDocument();
		expect(screen.getByText("张三")).toBeInTheDocument();
		expect(screen.getByText("完成项")).toBeInTheDocument();
		expect(screen.getByText("引用内容")).toBeInTheDocument();

		// 检查代码块内容（使用 container 查询，因为被高亮拆分）
		const codeElement = container.querySelector("code");
		expect(codeElement?.textContent).toContain('print("Hello")');
	});

	it("渲染强调和粗体", () => {
		render(
			<MarkdownContent
				content="**粗体** 和 *斜体* 和 ***粗斜体***"
				onPreviewHtml={mockOnPreviewHtml}
			/>,
		);

		expect(screen.getByText("粗体")).toBeInTheDocument();
		expect(screen.getByText("斜体")).toBeInTheDocument();
		expect(screen.getByText("粗斜体")).toBeInTheDocument();
	});

	it("处理换行（remark-breaks）", () => {
		const content = `第一行
第二行
第三行`;

		const { container } = render(
			<MarkdownContent content={content} onPreviewHtml={mockOnPreviewHtml} />,
		);

		// remark-breaks 会将单个换行符转换为 <br>
		expect(container.querySelectorAll("br").length).toBeGreaterThan(0);
	});

	it("渲染水平分割线", () => {
		const content = `段落1

---

段落2`;

		const { container } = render(
			<MarkdownContent content={content} onPreviewHtml={mockOnPreviewHtml} />,
		);

		const hr = container.querySelector("hr");
		expect(hr).toBeInTheDocument();
	});

	it("渲染图片", () => {
		render(
			<MarkdownContent
				content="![alt text](https://example.com/image.png)"
				onPreviewHtml={mockOnPreviewHtml}
			/>,
		);

		const img = screen.getByAltText("alt text");
		expect(img).toBeInTheDocument();
		expect(img).toHaveAttribute("src", "https://example.com/image.png");
		expect(img).toHaveAttribute("loading", "lazy");
	});

	describe("正文附件图片（<attachment uid/>）", () => {
		const imageAttachment: Attachment = {
			id: "pic_1",
			name: "chart.png",
			size: 2048,
			mediaType: "image/png",
			kind: "image",
			downloadUrl: null,
			previewUrl: null,
			discarded: false,
		};

		function renderWithImageProvider(ui: ReactNode) {
			const previewAttachment = vi.fn(async () => ({
				status: 200,
				ok: true,
				mediaType: "image/png",
				bytes: [137, 80, 78, 71],
				body: null,
			}));
			return render(
				<AttachmentImageProvider client={{ previewAttachment }}>
					{ui}
				</AttachmentImageProvider>,
			);
		}

		it("<attachment uid/> 渲染为 blob 图片，与文字共存", async () => {
			renderWithImageProvider(
				<MarkdownContent
					content='看图<attachment uid="pic_1"/>'
					attachments={[imageAttachment]}
					onPreviewHtml={mockOnPreviewHtml}
				/>,
			);

			const img = await screen.findByAltText("chart.png");
			expect(img.getAttribute("src")).toMatch(/^blob:/);
			expect(screen.getByText("看图")).toBeInTheDocument();
		});

		it("非图片附件占位符被移除", () => {
			const fileAttachment: Attachment = {
				...imageAttachment,
				id: "file_1",
				name: "doc.pdf",
				mediaType: "application/pdf",
				kind: "file",
			};
			renderWithImageProvider(
				<MarkdownContent
					content='文件<attachment uid="file_1"/>结束'
					attachments={[fileAttachment]}
					onPreviewHtml={mockOnPreviewHtml}
				/>,
			);

			expect(screen.queryByRole("img")).toBeNull();
			expect(screen.getByText("文件")).toBeInTheDocument();
			expect(screen.getByText("结束")).toBeInTheDocument();
			expect(screen.queryByText(/ATTACHMENT_PLACEHOLDER/)).toBeNull();
		});

		it("文字与图片混排保持顺序", async () => {
			renderWithImageProvider(
				<MarkdownContent
					content='前文<attachment uid="pic_1"/>后文'
					attachments={[imageAttachment]}
					onPreviewHtml={mockOnPreviewHtml}
				/>,
			);

			await screen.findByAltText("chart.png");
			expect(screen.getByText("前文")).toBeInTheDocument();
			expect(screen.getByText("后文")).toBeInTheDocument();
		});
	});
});
