import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { MessageReference } from "../runtime-client/types";
import { ReferenceChips } from "./ReferenceChips";

describe("ReferenceChips", () => {
	it("不渲染任何内容当引用列表为空", () => {
		const { container } = render(
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

		render(<ReferenceChips references={references} onClear={vi.fn()} />);

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

		render(<ReferenceChips references={references} onClear={vi.fn()} />);

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

		render(<ReferenceChips references={references} onClear={vi.fn()} />);

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

		render(<ReferenceChips references={references} onClear={vi.fn()} />);

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

		render(<ReferenceChips references={references} onClear={onClear} />);

		const clearButton = screen.getByRole("button", {
			name: /取消引用消息 msg-1/i,
		});
		await user.click(clearButton);

		expect(onClear).toHaveBeenCalledTimes(1);
		expect(onClear).toHaveBeenCalledWith("msg-1");
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

		render(<ReferenceChips references={references} onClear={onClear} />);

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

		render(<ReferenceChips references={references} onClear={vi.fn()} />);

		const clearButton = screen.getByRole("button", {
			name: /取消引用消息 msg-1/i,
		});
		expect(clearButton).toHaveTextContent("×");
	});
});
