import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CodeBlock } from "./CodeBlock";

describe("CodeBlock", () => {
	// Mock clipboard API
	const mockWriteText = vi.fn();

	beforeEach(() => {
		// Mock clipboard API
		Object.defineProperty(navigator, "clipboard", {
			value: {
				writeText: mockWriteText,
			},
			writable: true,
			configurable: true,
		});
		mockWriteText.mockResolvedValue(undefined);
	});

	afterEach(() => {
		vi.clearAllMocks();
	});

	it("应该渲染代码块", () => {
		const code = 'console.log("Hello, World!");';
		render(<CodeBlock code={code} language="javascript" />);

		// 检查语言标签
		expect(screen.getByText(/javascript/i)).toBeInTheDocument();
		// 检查代码内容（使用 textContent 因为可能被拆分成多个 span）
		const codeElement = document.querySelector("code");
		expect(codeElement?.textContent).toContain("console");
		expect(codeElement?.textContent).toContain("log");
	});

	it("应该自动检测语言", () => {
		const code = 'print("Hello, World!")';
		render(<CodeBlock code={code} />);

		// highlight.js 应该自动检测语言
		const languageLabel = screen.getByText(/python|stylus|plaintext/i);
		expect(languageLabel).toBeInTheDocument();
	});

	it("应该在超过 maxLines 行时显示折叠按钮", () => {
		const code = Array.from({ length: 10 }, (_, i) => `line ${i + 1}`).join(
			"\n",
		);
		render(<CodeBlock code={code} maxLines={8} collapsible={true} />);

		expect(screen.getByText("展开")).toBeInTheDocument();
	});

	it("应该在不超过 maxLines 行时不显示折叠按钮", () => {
		const code = Array.from({ length: 5 }, (_, i) => `line ${i + 1}`).join(
			"\n",
		);
		render(<CodeBlock code={code} maxLines={8} collapsible={true} />);

		expect(screen.queryByText("展开")).not.toBeInTheDocument();
		expect(screen.queryByText("折叠")).not.toBeInTheDocument();
	});

	it("应该在 collapsible=false 时不显示折叠按钮", () => {
		const code = Array.from({ length: 10 }, (_, i) => `line ${i + 1}`).join(
			"\n",
		);
		render(<CodeBlock code={code} maxLines={8} collapsible={false} />);

		expect(screen.queryByText("展开")).not.toBeInTheDocument();
		expect(screen.queryByText("折叠")).not.toBeInTheDocument();
	});

	it("应该切换折叠状态", async () => {
		const user = userEvent.setup();
		const code = Array.from({ length: 10 }, (_, i) => `line ${i + 1}`).join(
			"\n",
		);
		const { container } = render(
			<CodeBlock code={code} maxLines={8} collapsible={true} />,
		);

		const codeBlock = container.querySelector(".runtime-code-block");

		// 初始状态应该是折叠的
		expect(codeBlock).toHaveClass("is-collapsed");
		expect(screen.getByText("展开")).toBeInTheDocument();

		// 点击展开
		await user.click(screen.getByText("展开"));
		expect(screen.getByText("折叠")).toBeInTheDocument();
		expect(codeBlock).not.toHaveClass("is-collapsed");

		// 点击折叠
		await user.click(screen.getByText("折叠"));
		expect(screen.getByText("展开")).toBeInTheDocument();
		expect(codeBlock).toHaveClass("is-collapsed");
	});

	it("应该复制代码到剪贴板", async () => {
		const code = 'console.log("test");';

		render(<CodeBlock code={code} language="javascript" />);

		const copyButton = screen.getByText("复制");

		// 验证 navigator.clipboard 是否存在
		expect(navigator.clipboard).toBeDefined();
		expect(navigator.clipboard.writeText).toBeDefined();

		// 使用 fireEvent 直接触发点击
		fireEvent.click(copyButton);

		// 等待一下确保异步操作完成
		await new Promise((resolve) => setTimeout(resolve, 100));

		expect(mockWriteText).toHaveBeenCalledWith(code);
		await waitFor(() => {
			expect(screen.getByText("已复制")).toBeInTheDocument();
		});

		// 2秒后应该恢复为"复制"
		await waitFor(
			() => {
				expect(screen.getByText("复制")).toBeInTheDocument();
			},
			{ timeout: 2500 },
		);
	});

	it("应该为 HTML 代码显示预览按钮", () => {
		const code = "<div>Hello</div>";
		const onPreviewHtml = vi.fn();
		render(
			<CodeBlock code={code} language="html" onPreviewHtml={onPreviewHtml} />,
		);

		expect(screen.getByText("预览 HTML")).toBeInTheDocument();
	});

	it("应该调用 onPreviewHtml", async () => {
		const user = userEvent.setup();
		const code = "<div>Hello</div>";
		const onPreviewHtml = vi.fn();
		render(
			<CodeBlock code={code} language="html" onPreviewHtml={onPreviewHtml} />,
		);

		const previewButton = screen.getByText("预览 HTML");
		await user.click(previewButton);

		expect(onPreviewHtml).toHaveBeenCalledWith({
			title: "HTML 预览",
			html: code,
		});
	});

	it("应该为非 HTML 代码不显示预览按钮", () => {
		const code = 'console.log("test");';
		const onPreviewHtml = vi.fn();
		render(
			<CodeBlock
				code={code}
				language="javascript"
				onPreviewHtml={onPreviewHtml}
			/>,
		);

		expect(screen.queryByText("预览 HTML")).not.toBeInTheDocument();
	});

	it("应该处理语法高亮错误", () => {
		const code = "some invalid code that might break highlighting";
		// 不应该抛出错误
		expect(() => {
			render(<CodeBlock code={code} language="invalid-language-xyz" />);
		}).not.toThrow();
	});

	it("应该正确渲染空代码", () => {
		const code = "";
		render(<CodeBlock code={code} language="javascript" />);

		const languageLabel = screen.getByText(/javascript/i);
		expect(languageLabel).toBeInTheDocument();
	});

	it("应该处理包含特殊字符的代码", () => {
		const code = "const str = \"<script>alert('XSS')</script>\";";
		render(<CodeBlock code={code} language="javascript" />);

		const codeElement = document.querySelector("code");
		expect(codeElement?.textContent).toContain("const str");
		expect(codeElement?.textContent).toContain("script");
	});
});
