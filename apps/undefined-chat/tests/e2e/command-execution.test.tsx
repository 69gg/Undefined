import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { App } from "../../src/App";
import { createTauriRuntimeClient } from "../../src/runtime-client/tauri";
import { runtimeClientStub } from "../../src/test-fixtures";

vi.mock("../../src/runtime-client/tauri", () => ({
	createTauriRuntimeClient: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-dialog", () => ({
	open: vi.fn(),
}));

describe("E2E: Command Execution", () => {
	beforeEach(() => {
		vi.resetAllMocks();
	});

	test("通过斜杠快捷键打开命令面板", async () => {
		const client = runtimeClientStub({
			listCommands: vi.fn(async () => ({
				commands: [
					{ name: "/help", description: "显示帮助信息" },
					{ name: "/clear", description: "清空会话历史" },
					{ name: "/model", description: "切换模型" },
				],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		// 在输入框中输入 /
		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "/");

		// 命令面板应该打开
		expect(await screen.findByText("/help")).toBeInTheDocument();
		expect(screen.getByText("显示帮助信息")).toBeInTheDocument();
	});

	test("过滤命令列表", async () => {
		const client = runtimeClientStub({
			listCommands: vi.fn(async () => ({
				commands: [
					{ name: "/help", description: "显示帮助信息" },
					{ name: "/history", description: "查看历史记录" },
					{ name: "/model", description: "切换模型" },
					{ name: "/clear", description: "清空会话" },
				],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "/h");

		// 应该只显示包含 h 的命令
		expect(await screen.findByText("/help")).toBeInTheDocument();
		expect(screen.getByText("/history")).toBeInTheDocument();
		expect(screen.queryByText("/model")).not.toBeInTheDocument();
		expect(screen.queryByText("/clear")).not.toBeInTheDocument();
	});

	test("使用键盘导航命令列表", async () => {
		const client = runtimeClientStub({
			listCommands: vi.fn(async () => ({
				commands: [
					{ name: "/help", description: "显示帮助" },
					{ name: "/history", description: "历史记录" },
					{ name: "/model", description: "切换模型" },
				],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "/");

		await screen.findByText("/help");

		// 按下方向键导航
		await userEvent.keyboard("{ArrowDown}");
		await userEvent.keyboard("{ArrowDown}");

		// 验证导航状态（通过 CSS 类或 aria-selected）
		const modelItem = screen.getByText("/model").closest("button");
		expect(modelItem?.classList.contains("active")).toBe(true);
	});

	test("选择命令后填充到输入框", async () => {
		const client = runtimeClientStub({
			listCommands: vi.fn(async () => ({
				commands: [{ name: "/help", description: "显示帮助" }],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入") as HTMLTextAreaElement;
		await userEvent.type(input, "/");

		const helpCmd = await screen.findByText("/help");
		await userEvent.click(helpCmd);

		// 命令应该被填充到输入框
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
					{ name: "/help", description: "显示帮助" },
					{ name: "/clear", description: "清空会话" },
				],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入") as HTMLTextAreaElement;
		await userEvent.type(input, "/");

		await screen.findByText("/help");

		// 按下向下键选择第二个命令
		await userEvent.keyboard("{ArrowDown}");

		// 按 Enter 选择
		await userEvent.keyboard("{Enter}");

		// 应该填充第二个命令
		expect(input.value).toBe("/clear");
	});

	test("Escape 键关闭命令面板", async () => {
		const client = runtimeClientStub({
			listCommands: vi.fn(async () => ({
				commands: [{ name: "/help", description: "显示帮助" }],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "/");

		await screen.findByText("/help");

		// 按 Escape 关闭
		await userEvent.keyboard("{Escape}");

		// 命令面板应该关闭
		await waitFor(() => {
			expect(screen.queryByText("/help")).not.toBeInTheDocument();
		});
	});

	test("删除斜杠后关闭命令面板", async () => {
		const client = runtimeClientStub({
			listCommands: vi.fn(async () => ({
				commands: [{ name: "/help", description: "显示帮助" }],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "/h");

		await screen.findByText("/help");

		// 删除所有字符
		await userEvent.keyboard("{Backspace}{Backspace}");

		// 命令面板应该关闭
		await waitFor(() => {
			expect(screen.queryByText("/help")).not.toBeInTheDocument();
		});
	});

	test("没有匹配的命令时显示空状态", async () => {
		const client = runtimeClientStub({
			listCommands: vi.fn(async () => ({
				commands: [
					{ name: "/help", description: "显示帮助" },
					{ name: "/clear", description: "清空会话" },
				],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "/xyz");

		// 应该显示空状态或者命令面板关闭
		await waitFor(() => {
			expect(screen.queryByText("/help")).not.toBeInTheDocument();
			expect(screen.queryByText("/clear")).not.toBeInTheDocument();
		});
	});

	test("发送命令消息", async () => {
		const client = runtimeClientStub({
			listCommands: vi.fn(async () => ({
				commands: [{ name: "/help", description: "显示帮助" }],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "/");

		const helpCmd = await screen.findByText("/help");
		await userEvent.click(helpCmd);

		// 发送命令
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
				commands: [{ name: "/help", description: "显示帮助" }],
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

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入") as HTMLTextAreaElement;

		// 在会话一打开命令面板
		await userEvent.type(input, "/h");
		await screen.findByText("/help");

		// 切换到会话二
		await userEvent.click(screen.getByRole("button", { name: /会话二/ }));

		// 命令面板应该关闭，输入框清空
		await waitFor(() => {
			expect(screen.queryByText("/help")).not.toBeInTheDocument();
			expect(input.value).toBe("");
		});
	});
});
