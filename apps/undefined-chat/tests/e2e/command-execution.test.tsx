import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { App } from "../../src/App";
import { createTauriRuntimeClient } from "../../src/runtime-client/tauri";
import { commandInfo, runtimeClientStub } from "../../src/test-fixtures";
import { renderWithProviders } from "../../src/test-utils";

vi.mock("../../src/runtime-client/tauri", () => ({
	createTauriRuntimeClient: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-dialog", () => ({
	open: vi.fn(),
}));

// 命令名（如 "/help"）在面板里既出现在命令名标题、也出现在右侧用法 code 中，
// 与 WebUI 一致。测试中统一用命令名 span（.runtime-chat-command-name）精确定位。
const NAME_SELECTOR = ".runtime-chat-command-name";
const findCmd = (label: string) =>
	screen.findByText(label, { selector: NAME_SELECTOR });
const getCmd = (label: string) =>
	screen.getByText(label, { selector: NAME_SELECTOR });
const queryCmd = (label: string) =>
	screen.queryByText(label, { selector: NAME_SELECTOR });

describe("E2E: Command Execution", () => {
	beforeEach(() => {
		vi.resetAllMocks();
	});

	test("通过斜杠快捷键打开命令面板", async () => {
		const client = runtimeClientStub({
			listCommands: vi.fn(async () => ({
				commands: [
					commandInfo({ name: "help", description: "显示帮助信息" }),
					commandInfo({ name: "clear", description: "清空会话历史" }),
					commandInfo({ name: "model", description: "切换模型" }),
				],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderWithProviders(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		// 在输入框中输入 /
		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "/");

		// 命令面板应该打开
		expect(await findCmd("/help")).toBeInTheDocument();
		expect(screen.getByText("显示帮助信息")).toBeInTheDocument();
	});

	test("过滤命令列表", async () => {
		const client = runtimeClientStub({
			listCommands: vi.fn(async () => ({
				commands: [
					commandInfo({ name: "help", description: "显示帮助信息" }),
					commandInfo({ name: "history", description: "查看历史记录" }),
					commandInfo({ name: "model", description: "切换模型" }),
					commandInfo({ name: "clear", description: "清空会话" }),
				],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderWithProviders(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "/h");

		// 应该只显示名称以 h 开头的命令
		expect(await findCmd("/help")).toBeInTheDocument();
		expect(getCmd("/history")).toBeInTheDocument();
		expect(queryCmd("/model")).not.toBeInTheDocument();
		expect(queryCmd("/clear")).not.toBeInTheDocument();
	});

	test("使用键盘导航命令列表", async () => {
		const client = runtimeClientStub({
			listCommands: vi.fn(async () => ({
				commands: [
					commandInfo({ name: "help", description: "显示帮助" }),
					commandInfo({ name: "history", description: "历史记录" }),
					commandInfo({ name: "model", description: "切换模型" }),
				],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderWithProviders(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "/");

		await findCmd("/help");

		// 按下方向键导航
		await userEvent.keyboard("{ArrowDown}");
		await userEvent.keyboard("{ArrowDown}");

		// 验证导航状态（通过 aria-selected）
		const modelItem = (await findCmd("/model")).closest(
			'[role="option"]',
		) as HTMLElement;
		expect(modelItem?.getAttribute("aria-selected")).toBe("true");
	});

	test("选择命令后填充到输入框", async () => {
		const client = runtimeClientStub({
			listCommands: vi.fn(async () => ({
				commands: [commandInfo({ name: "help", description: "显示帮助" })],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderWithProviders(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入") as HTMLTextAreaElement;
		await userEvent.type(input, "/");

		const helpCmd = await findCmd("/help");
		await userEvent.click(helpCmd);

		// 无参数命令选择后不追加空格（与 WebUI 一致）
		expect(input.value).toBe("/help");

		// 命令面板应该关闭
		await waitFor(() => {
			expect(screen.queryByText("显示帮助")).not.toBeInTheDocument();
		});
	});

	test("Enter 键选择当前高亮的命令", async () => {
		const client = runtimeClientStub({
			listCommands: vi.fn(async () => ({
				commands: [
					commandInfo({ name: "help", description: "显示帮助" }),
					commandInfo({ name: "clear", description: "清空会话" }),
				],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderWithProviders(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入") as HTMLTextAreaElement;
		await userEvent.type(input, "/");

		await findCmd("/help");

		// 按下向下键选择第二个命令
		await userEvent.keyboard("{ArrowDown}");

		// 按 Enter 选择
		await userEvent.keyboard("{Enter}");

		// 应该填充第二个命令（无参数命令不追加空格）
		expect(input.value).toBe("/clear");
	});

	test("Escape 键关闭命令面板", async () => {
		const client = runtimeClientStub({
			listCommands: vi.fn(async () => ({
				commands: [commandInfo({ name: "help", description: "显示帮助" })],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderWithProviders(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "/");

		await findCmd("/help");

		// 按 Escape 关闭
		await userEvent.keyboard("{Escape}");

		// 命令面板应该关闭（只检查描述文本）
		await waitFor(() => {
			expect(screen.queryByText("显示帮助")).not.toBeInTheDocument();
		});
	});

	test("删除斜杠后关闭命令面板", async () => {
		const client = runtimeClientStub({
			listCommands: vi.fn(async () => ({
				commands: [commandInfo({ name: "help", description: "显示帮助" })],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderWithProviders(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "/h");

		await findCmd("/help");

		// 删除所有字符
		await userEvent.keyboard("{Backspace}{Backspace}");

		// 命令面板应该关闭
		await waitFor(() => {
			expect(queryCmd("/help")).not.toBeInTheDocument();
		});
	});

	test("没有匹配的命令时关闭命令面板", async () => {
		const client = runtimeClientStub({
			listCommands: vi.fn(async () => ({
				commands: [
					commandInfo({ name: "help", description: "显示帮助" }),
					commandInfo({ name: "clear", description: "清空会话" }),
				],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderWithProviders(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "/xyz");

		// 无匹配项时命令面板不展示任何候选
		await waitFor(() => {
			expect(queryCmd("/help")).not.toBeInTheDocument();
			expect(queryCmd("/clear")).not.toBeInTheDocument();
		});
	});

	test("发送命令消息", async () => {
		const client = runtimeClientStub({
			listCommands: vi.fn(async () => ({
				commands: [commandInfo({ name: "help", description: "显示帮助" })],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderWithProviders(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "/");

		const helpCmd = await findCmd("/help");
		await userEvent.click(helpCmd);

		// 选择后输入框是 "/help"，发送时会 trim
		const sendBtn = screen.getByRole("button", { name: "发送" });
		await userEvent.click(sendBtn);

		// 验证发送命令消息
		await waitFor(() => {
			expect(client.sendMessage).toHaveBeenCalledWith({
				conversationId: "default",
				message: {
					text: "/help",
					attachmentIds: [],
					references: [],
				},
			});
		});
	});

	test("命令面板在不同会话间保持独立", async () => {
		const client = runtimeClientStub({
			listConversations: vi.fn(async () => ({
				conversations: [
					{ id: "conv-1", title: "会话一" },
					{ id: "conv-2", title: "会话二" },
				],
				activeJob: null,
				defaultConversationId: "conv-1",
				virtualUserId: "webchat",
			})),
			listCommands: vi.fn(async () => ({
				commands: [commandInfo({ name: "help", description: "显示帮助" })],
			})),
			getHistory: vi.fn(async ({ conversationId }) => ({
				conversationId,
				virtualUserId: "webchat",
				permission: "superadmin",
				count: 0,
				items: [],
				limit: 50,
				before: null,
				hasMore: false,
				nextBefore: null,
				total: 0,
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderWithProviders(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入") as HTMLTextAreaElement;

		// 在会话一打开命令面板
		await userEvent.type(input, "/h");
		await findCmd("/help");

		// 切换到会话二
		await userEvent.click(screen.getByRole("button", { name: /会话二/ }));

		// 命令面板应该关闭，输入框清空
		await waitFor(() => {
			expect(queryCmd("/help")).not.toBeInTheDocument();
			expect(input.value).toBe("");
		});
	});
});
