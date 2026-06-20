import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LOCALE_STORAGE_KEY, LanguageProvider } from "../i18n";
import type { MessageReference } from "../runtime-client/types";
import { ReferenceChips } from "./ReferenceChips";

// 固定为简体中文，使断言不受测试环境 navigator.language 影响
beforeEach(() => {
	window.localStorage.setItem(LOCALE_STORAGE_KEY, "zh-CN");
});

// ReferenceChips 内部使用 useTranslation，需置于 LanguageProvider 下
function renderChips(node: ReactNode) {
	return render(<LanguageProvider>{node}</LanguageProvider>);
}

describe("ReferenceChips", () => {
	it("不渲染任何内容当引用列表为空", () => {
		const { container } = renderChips(
			<ReferenceChips references={[]} onClear={vi.fn()} />,
		);
		expect(container.firstChild).toBeNull();
	});

	it("渲染单个引用芯片", () => {
		const references: MessageReference[] = [
			{
				messageId: "msg-1",
				quote: "这是一条引用的消息内容",
			},
		];

		renderChips(<ReferenceChips references={references} onClear={vi.fn()} />);

		expect(screen.getByText("这是一条引用的消息内容")).toBeInTheDocument();
		expect(screen.getByText("↩")).toBeInTheDocument();
	});

	it("渲染多个引用芯片", () => {
		const references: MessageReference[] = [
			{
				messageId: "msg-1",
				quote: "第一条引用",
			},
			{
				messageId: "msg-2",
				quote: "第二条引用",
			},
		];

		renderChips(<ReferenceChips references={references} onClear={vi.fn()} />);

		expect(screen.getByText("第一条引用")).toBeInTheDocument();
		expect(screen.getByText("第二条引用")).toBeInTheDocument();
	});

	it("截断超长文本到 180 字符", () => {
		const longText = "a".repeat(200);
		const references: MessageReference[] = [
			{
				messageId: "msg-1",
				quote: longText,
			},
		];

		renderChips(<ReferenceChips references={references} onClear={vi.fn()} />);

		const truncatedText = `${"a".repeat(180)}...`;
		expect(screen.getByText(truncatedText)).toBeInTheDocument();
	});

	it("不截断短于 180 字符的文本", () => {
		const shortText = "这是一条短消息";
		const references: MessageReference[] = [
			{
				messageId: "msg-1",
				quote: shortText,
			},
		];

		renderChips(<ReferenceChips references={references} onClear={vi.fn()} />);

		expect(screen.getByText(shortText)).toBeInTheDocument();
	});

	it("调用 onClear 当点击清除按钮", async () => {
		const user = userEvent.setup();
		const onClear = vi.fn();
		const references: MessageReference[] = [
			{
				messageId: "msg-1",
				quote: "测试引用",
			},
		];

		renderChips(<ReferenceChips references={references} onClear={onClear} />);

		const clearButton = screen.getByRole("button", {
			name: /取消引用消息 msg-1/i,
		});
		await user.click(clearButton);

		expect(onClear).toHaveBeenCalledTimes(1);
		expect(onClear).toHaveBeenCalledWith("msg-1");
	});

	it("点击引用主体时调用 onJump", async () => {
		const user = userEvent.setup();
		const onJump = vi.fn();
		const references: MessageReference[] = [
			{
				messageId: "msg-1",
				quote: "测试引用",
			},
		];

		renderChips(
			<ReferenceChips
				references={references}
				onClear={vi.fn()}
				onJump={onJump}
			/>,
		);

		await user.click(screen.getByRole("button", { name: "测试引用" }));

		expect(onJump).toHaveBeenCalledOnce();
		expect(onJump).toHaveBeenCalledWith("msg-1");
	});

	it("每个引用芯片有正确的清除按钮", async () => {
		const user = userEvent.setup();
		const onClear = vi.fn();
		const references: MessageReference[] = [
			{
				messageId: "msg-1",
				quote: "第一条引用",
			},
			{
				messageId: "msg-2",
				quote: "第二条引用",
			},
		];

		renderChips(<ReferenceChips references={references} onClear={onClear} />);

		const clearButton1 = screen.getByRole("button", {
			name: /取消引用消息 msg-1/i,
		});
		await user.click(clearButton1);
		expect(onClear).toHaveBeenCalledWith("msg-1");

		const clearButton2 = screen.getByRole("button", {
			name: /取消引用消息 msg-2/i,
		});
		await user.click(clearButton2);
		expect(onClear).toHaveBeenCalledWith("msg-2");
	});

	it("渲染清除按钮文本为 ×", () => {
		const references: MessageReference[] = [
			{
				messageId: "msg-1",
				quote: "测试引用",
			},
		];

		renderChips(<ReferenceChips references={references} onClear={vi.fn()} />);

		const clearButton = screen.getByRole("button", {
			name: /取消引用消息 msg-1/i,
		});
		expect(clearButton).toHaveTextContent("×");
	});
});
