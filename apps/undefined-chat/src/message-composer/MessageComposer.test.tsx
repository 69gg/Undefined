import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";
import { commandInfo, subcommandInfo } from "../test-fixtures";
import { MessageComposer } from "./MessageComposer";

describe("MessageComposer", () => {
	test("sends on Enter, inserts newline with Shift+Enter, and shows command suggestions", async () => {
		const onDraftChange = vi.fn();
		const onSend = vi.fn();

		render(
			<MessageComposer
				attachmentQueue={[]}
				commandSuggestions={[
					commandInfo({ name: "help", description: "显示帮助" }),
					commandInfo({
						name: "version",
						trigger: "/version",
						description: "显示版本",
						usage: "/version",
					}),
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

		// 命令面板展示 /help（matchLabel 带前导斜杠）及其描述
		expect(screen.getByText("显示帮助")).toBeInTheDocument();
		const options = screen.getAllByRole("option");
		expect(options).toHaveLength(1);
		expect(options[0]).toHaveTextContent("/help");

		await userEvent.type(editor, "{Shift>}{Enter}{/Shift}");
		expect(onDraftChange).toHaveBeenLastCalledWith("/he\n");

		// 输入普通文本后发送
		await userEvent.clear(editor);
		await userEvent.type(editor, "hello{Enter}");
		expect(onSend).toHaveBeenCalledOnce();
	});

	test("进入带子命令的命令时展示子命令提示，Tab 补全当前项", async () => {
		const onDraftChange = vi.fn();

		render(
			<MessageComposer
				attachmentQueue={[]}
				commandSuggestions={[
					commandInfo({ name: "help", description: "显示帮助" }),
					commandInfo({
						name: "conv",
						trigger: "/conv",
						description: "管理会话",
						usage: "/conv <子命令>",
						subcommands: [
							subcommandInfo({
								name: "new",
								trigger: "/conv new",
								usage: "/conv new [标题]",
								description: "新建会话",
							}),
							subcommandInfo({
								name: "list",
								trigger: "/conv list",
								usage: "/conv list",
								args: "",
								description: "列出会话",
							}),
						],
					}),
				]}
				disabled={false}
				draft=""
				references={[]}
				onAddAttachment={vi.fn()}
				onClearAttachment={vi.fn()}
				onClearReference={vi.fn()}
				onDraftChange={onDraftChange}
				onSend={vi.fn()}
			/>,
		);

		const editor = screen.getByLabelText("消息输入");
		await userEvent.type(editor, "/conv ");

		expect(screen.getByText("选择子命令")).toBeInTheDocument();
		const options = screen.getAllByRole("option");
		expect(options[0]).toHaveTextContent("/conv new");
		expect(options[1]).toHaveTextContent("/conv list");

		// Tab 补全到当前选中的子命令（带参数 → 末尾补空格）
		await userEvent.keyboard("{Tab}");
		expect(onDraftChange).toHaveBeenLastCalledWith("/conv new ");
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
