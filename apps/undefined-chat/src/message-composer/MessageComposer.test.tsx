import {
	fireEvent,
	render,
	screen,
	waitFor,
	within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { LOCALE_STORAGE_KEY, LanguageProvider } from "../i18n";
import { commandInfo, subcommandInfo } from "../test-fixtures";
import { MessageComposer } from "./MessageComposer";

// 固定为简体中文，使断言不受测试环境 navigator.language 影响
beforeEach(() => {
	window.localStorage.setItem(LOCALE_STORAGE_KEY, "zh-CN");
});

// MessageComposer 内部使用 useTranslation，需置于 LanguageProvider 下
function withProvider(node: ReactNode): ReactNode {
	return <LanguageProvider>{node}</LanguageProvider>;
}

describe("MessageComposer", () => {
	test("sends on Enter, inserts newline with Shift+Enter, and shows command suggestions", async () => {
		const onDraftChange = vi.fn();
		const onSend = vi.fn();

		render(
			withProvider(
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
			),
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
			withProvider(
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
			),
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

	test("回车选中带子命令的主命令后立即展示其子命令", async () => {
		render(
			withProvider(
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
					onDraftChange={vi.fn()}
					onSend={vi.fn()}
				/>,
			),
		);

		const editor = screen.getByLabelText("消息输入");
		await userEvent.type(editor, "/conv");
		// 命令模式：仅命中 /conv（用命令名 span 精确定位，避免与右侧用法 code 重复命中）
		const nameSelector = ".runtime-chat-command-name";
		expect(
			screen.getByText("/conv", { selector: nameSelector }),
		).toBeInTheDocument();

		// 回车选中主命令后，面板保持打开并展示其子命令
		await userEvent.keyboard("{Enter}");
		expect(
			await screen.findByText("/conv new", { selector: nameSelector }),
		).toBeInTheDocument();
		expect(
			screen.getByText("/conv list", { selector: nameSelector }),
		).toBeInTheDocument();
	});

	test("IME 合成中的回车不触发发送", async () => {
		const onSend = vi.fn();

		render(
			withProvider(
				<MessageComposer
					attachmentQueue={[]}
					commandSuggestions={[]}
					disabled={false}
					draft="你好"
					references={[]}
					onAddAttachment={vi.fn()}
					onClearAttachment={vi.fn()}
					onClearReference={vi.fn()}
					onDraftChange={vi.fn()}
					onSend={onSend}
				/>,
			),
		);

		const editor = screen.getByLabelText("消息输入");
		// 模拟输入法合成期间的回车（isComposing=true）：应被守卫拦截，不发送
		fireEvent.keyDown(editor, { key: "Enter", isComposing: true });
		expect(onSend).not.toHaveBeenCalled();

		// 合成结束后的普通回车正常发送
		fireEvent.keyDown(editor, { key: "Enter" });
		expect(onSend).toHaveBeenCalledOnce();
	});

	test("requests timeline bottom scroll on focus and send", () => {
		const onRequestScrollToBottom = vi.fn();
		const onSend = vi.fn();

		render(
			withProvider(
				<MessageComposer
					attachmentQueue={[]}
					commandSuggestions={[]}
					disabled={false}
					draft="你好"
					references={[]}
					onAddAttachment={vi.fn()}
					onClearAttachment={vi.fn()}
					onClearReference={vi.fn()}
					onDraftChange={vi.fn()}
					onRequestScrollToBottom={onRequestScrollToBottom}
					onSend={onSend}
				/>,
			),
		);

		const editor = screen.getByLabelText("消息输入");
		fireEvent.focus(editor);
		expect(onRequestScrollToBottom).toHaveBeenCalledOnce();

		fireEvent.keyDown(editor, { key: "Enter" });
		expect(onRequestScrollToBottom).toHaveBeenCalledTimes(2);
		expect(onSend).toHaveBeenCalledOnce();
	});

	test("requests timeline bottom scroll on submit button send", async () => {
		const onRequestScrollToBottom = vi.fn();
		const onSend = vi.fn();

		render(
			withProvider(
				<MessageComposer
					attachmentQueue={[]}
					commandSuggestions={[]}
					disabled={false}
					draft="你好"
					references={[]}
					onAddAttachment={vi.fn()}
					onClearAttachment={vi.fn()}
					onClearReference={vi.fn()}
					onDraftChange={vi.fn()}
					onRequestScrollToBottom={onRequestScrollToBottom}
					onSend={onSend}
				/>,
			),
		);

		await userEvent.click(screen.getByRole("button", { name: "发送" }));

		expect(onRequestScrollToBottom).toHaveBeenCalledOnce();
		expect(onSend).toHaveBeenCalledOnce();
	});

	test("renders attachment queue and references with clear actions", async () => {
		const onClearAttachment = vi.fn();
		const onClearReference = vi.fn();
		const onJumpReference = vi.fn();

		render(
			withProvider(
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
					onJumpReference={onJumpReference}
					onDraftChange={vi.fn()}
					onSend={vi.fn()}
				/>,
			),
		);

		const attachments = screen.getByLabelText("附件队列");
		expect(within(attachments).getByText("trace.log")).toBeTruthy();
		expect(screen.getByText("错误堆栈")).toBeTruthy();

		await userEvent.click(screen.getByRole("button", { name: "错误堆栈" }));
		expect(onJumpReference).toHaveBeenCalledWith("msg-1");

		await userEvent.click(
			screen.getByRole("button", { name: "移除 trace.log" }),
		);
		await userEvent.click(
			screen.getByRole("button", { name: "取消引用消息 msg-1" }),
		);

		expect(onClearAttachment).toHaveBeenCalledWith("local-1");
		expect(onClearReference).toHaveBeenCalledWith("msg-1");
	});

	test("focusRequest focuses the editor and opens command mode", async () => {
		const onDraftChange = vi.fn();
		const { rerender } = render(
			withProvider(
				<MessageComposer
					attachmentQueue={[]}
					commandSuggestions={[commandInfo({ name: "help" })]}
					disabled={false}
					draft=""
					focusRequest={null}
					references={[]}
					onAddAttachment={vi.fn()}
					onClearAttachment={vi.fn()}
					onClearReference={vi.fn()}
					onDraftChange={onDraftChange}
					onSend={vi.fn()}
				/>,
			),
		);

		rerender(
			withProvider(
				<MessageComposer
					attachmentQueue={[]}
					commandSuggestions={[commandInfo({ name: "help" })]}
					disabled={false}
					draft=""
					focusRequest={{ id: 1, commandMode: true }}
					references={[]}
					onAddAttachment={vi.fn()}
					onClearAttachment={vi.fn()}
					onClearReference={vi.fn()}
					onDraftChange={onDraftChange}
					onSend={vi.fn()}
				/>,
			),
		);

		const editor = await screen.findByDisplayValue("/");
		await waitFor(() => {
			expect(editor).toHaveFocus();
		});
		expect(onDraftChange).toHaveBeenCalledWith("/");
	});

	test("disables sending for a running current conversation", () => {
		render(
			withProvider(
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
			),
		);

		expect(screen.getByRole("button", { name: "发送" })).toBeDisabled();
		expect(screen.getByText("当前会话仍在运行")).toBeTruthy();
	});
});
