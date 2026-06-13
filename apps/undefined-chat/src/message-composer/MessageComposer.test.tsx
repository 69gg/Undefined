import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { MessageComposer } from "./MessageComposer";

describe("MessageComposer", () => {
	test("sends on Enter, inserts newline with Shift+Enter, and shows command suggestions", async () => {
		const onDraftChange = vi.fn();
		const onSend = vi.fn();

		render(
			<MessageComposer
				attachmentQueue={[]}
				commandSuggestions={[
					{
						name: "help",
						description: "显示帮助",
					},
					{
						name: "version",
						description: "显示版本",
					},
				]}
				disabled={false}
				draft=""
				references={[]}
				onAddAttachment={vi.fn()}
				onClearAttachment={vi.fn()}
				onClearReference={vi.fn()}
				onDraftChange={onDraftChange}
				onSend={onSend}
			/>,
		);

		const editor = screen.getByLabelText("消息输入");
		await userEvent.type(editor, "/he");

		// commandSuggestions 是根据名称过滤的，使用 name 而不是显示的 /name
		expect(screen.getByText("help")).toBeTruthy();
		expect(screen.getByText("显示帮助")).toBeTruthy();

		await userEvent.type(editor, "{Shift>}{Enter}{/Shift}");
		expect(onDraftChange).toHaveBeenLastCalledWith("/he\n");

		// 输入普通文本后发送
		await userEvent.clear(editor);
		await userEvent.type(editor, "hello{Enter}");
		expect(onSend).toHaveBeenCalledOnce();
	});

	test("renders attachment queue and references with clear actions", async () => {
		const onClearAttachment = vi.fn();
		const onClearReference = vi.fn();

		render(
			<MessageComposer
				attachmentQueue={[
					{
						id: "local-1",
						name: "trace.log",
						size: 1024,
						status: "ready",
						attachmentId: "att-1",
					},
				]}
				commandSuggestions={[]}
				disabled={false}
				draft="请分析"
				references={[
					{
						messageId: "msg-1",
						quote: "错误堆栈",
					},
				]}
				onAddAttachment={vi.fn()}
				onClearAttachment={onClearAttachment}
				onClearReference={onClearReference}
				onDraftChange={vi.fn()}
				onSend={vi.fn()}
			/>,
		);

		const attachments = screen.getByLabelText("附件队列");
		expect(within(attachments).getByText("trace.log")).toBeTruthy();
		expect(screen.getByText("错误堆栈")).toBeTruthy();

		await userEvent.click(
			screen.getByRole("button", { name: "移除 trace.log" }),
		);
		await userEvent.click(
			screen.getByRole("button", { name: "取消引用消息 msg-1" }),
		);

		expect(onClearAttachment).toHaveBeenCalledWith("local-1");
		expect(onClearReference).toHaveBeenCalledWith("msg-1");
	});

	test("disables sending for a running current conversation", () => {
		render(
			<MessageComposer
				attachmentQueue={[]}
				commandSuggestions={[]}
				disabled={true}
				draft="不能发送"
				references={[]}
				onAddAttachment={vi.fn()}
				onClearAttachment={vi.fn()}
				onClearReference={vi.fn()}
				onDraftChange={vi.fn()}
				onSend={vi.fn()}
			/>,
		);

		expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
		expect(screen.getByText("当前会话仍在运行")).toBeTruthy();
	});
});
