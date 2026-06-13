import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { App } from "../../src/App";
import { createTauriRuntimeClient } from "../../src/runtime-client/tauri";
import {
	conversation,
	historyItem,
	job,
	runtimeClientStub,
} from "../../src/test-fixtures";

vi.mock("../../src/runtime-client/tauri", () => ({
	createTauriRuntimeClient: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-dialog", () => ({
	open: vi.fn(),
}));

describe("E2E: Message Sending", () => {
	beforeEach(() => {
		vi.resetAllMocks();
	});

	test("发送文本消息并接收回复", async () => {
		const client = runtimeClientStub({
			listConversations: vi.fn(async () => ({
				conversations: [conversation({ id: "default", title: "测试会话" })],
				activeJob: null,
				defaultConversationId: "default",
				virtualUserId: "webchat",
			})),
			getHistory: vi
				.fn()
				.mockResolvedValueOnce({
					conversationId: "default",
					virtualUserId: "webchat",
					permission: "superadmin",
					count: 0,
					items: [],
					limit: 50,
					before: null,
					hasMore: false,
					nextBefore: null,
					total: 0,
				})
				.mockResolvedValueOnce({
					conversationId: "default",
					virtualUserId: "webchat",
					permission: "superadmin",
					count: 2,
					items: [
						historyItem({ messageId: "user-1", content: "你好", role: "user" }),
						historyItem({
							messageId: "bot-1",
							content: "你好！有什么可以帮助你的吗？",
							role: "bot",
						}),
					],
					limit: 50,
					before: null,
					hasMore: false,
					nextBefore: null,
					total: 2,
				}),
			sendMessage: vi.fn(async () =>
				job({
					jobId: "job-1",
					conversationId: "default",
					status: "running",
				}),
			),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		// 输入消息
		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "你好");

		// 发送消息
		const sendBtn = screen.getByRole("button", { name: "发送" });
		await userEvent.click(sendBtn);

		// 验证 API 调用
		await waitFor(() => {
			expect(client.sendMessage).toHaveBeenCalledWith({
				conversationId: "default",
				message: {
					text: "你好",
					attachmentIds: [],
					references: [],
				},
			});
		});

		// 输入框应该被清空
		expect((input as HTMLTextAreaElement).value).toBe("");

		// 验证发送后禁用输入（因为 job 在运行）
		expect(sendBtn).toBeDisabled();
	});

	test("阻止在 job 运行时发送消息", async () => {
		const client = runtimeClientStub({
			listConversations: vi.fn(async () => ({
				conversations: [conversation({ id: "default", title: "测试会话" })],
				activeJob: null,
				defaultConversationId: "default",
				virtualUserId: "webchat",
			})),
			getActiveJobs: vi.fn(async () => ({
				job: job({ jobId: "job-1", conversationId: "default", status: "running" }),
				jobs: [
					job({ jobId: "job-1", conversationId: "default", status: "running" }),
				],
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		// 输入框和发送按钮应该被禁用
		const input = screen.getByLabelText("消息输入");
		const sendBtn = screen.getByRole("button", { name: "发送" });

		expect(input).toBeDisabled();
		expect(sendBtn).toBeDisabled();
	});

	test("阻止发送空消息", async () => {
		const client = runtimeClientStub();
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		// 不输入任何内容，直接点击发送
		const sendBtn = screen.getByRole("button", { name: "发送" });
		await userEvent.click(sendBtn);

		// 不应该调用 sendMessage
		expect(client.sendMessage).not.toHaveBeenCalled();
	});

	test("支持换行输入（Shift+Enter）", async () => {
		const client = runtimeClientStub();
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入") as HTMLTextAreaElement;

		// 输入多行文本
		await userEvent.type(input, "第一行{Shift>}{Enter}{/Shift}第二行");

		expect(input.value).toContain("第一行\n第二行");

		// 不应该触发发送
		expect(client.sendMessage).not.toHaveBeenCalled();
	});

	test("Enter 键发送消息", async () => {
		const client = runtimeClientStub();
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "测试消息{Enter}");

		await waitFor(() => {
			expect(client.sendMessage).toHaveBeenCalledWith({
				conversationId: "default",
				message: {
					text: "测试消息",
					attachmentIds: [],
					references: [],
				},
			});
		});
	});

	test("显示发送错误", async () => {
		const client = runtimeClientStub({
			sendMessage: vi.fn(async () => {
				throw new Error("网络请求失败");
			}),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "测试");

		const sendBtn = screen.getByRole("button", { name: "发送" });
		await userEvent.click(sendBtn);

		// 应该显示错误消息
		expect(await screen.findByText("网络请求失败")).toBeInTheDocument();
	});

	test("草稿在会话间独立保存", async () => {
		const client = runtimeClientStub({
			listConversations: vi.fn(async () => ({
				conversations: [
					conversation({ id: "conv-1", title: "会话一" }),
					conversation({ id: "conv-2", title: "会话二" }),
				],
				activeJob: null,
				defaultConversationId: "conv-1",
				virtualUserId: "webchat",
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

		// 在会话一中输入草稿
		const input = screen.getByLabelText("消息输入") as HTMLTextAreaElement;
		await userEvent.type(input, "会话一的草稿");
		expect(input.value).toBe("会话一的草稿");

		// 切换到会话二
		await userEvent.click(screen.getByRole("button", { name: /会话二/ }));

		// 输入框应该清空
		await waitFor(() => {
			expect(input.value).toBe("");
		});

		// 在会话二中输入
		await userEvent.type(input, "会话二的草稿");
		expect(input.value).toBe("会话二的草稿");

		// 切换回会话一
		await userEvent.click(screen.getByRole("button", { name: /会话一/ }));

		// 应该恢复会话一的草稿
		await waitFor(() => {
			expect(input.value).toBe("会话一的草稿");
		});
	});

	test("发送后清空草稿和附件", async () => {
		const client = runtimeClientStub({
			sendMessage: vi.fn(async () =>
				job({ jobId: "job-1", conversationId: "default", status: "running" }),
			),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		// 输入消息
		const input = screen.getByLabelText("消息输入") as HTMLTextAreaElement;
		await userEvent.type(input, "测试消息");

		// 发送
		await userEvent.click(screen.getByRole("button", { name: "发送" }));

		// 验证草稿被清空
		await waitFor(() => {
			expect(input.value).toBe("");
		});
	});

	test("没有可用会话时显示错误", async () => {
		const client = runtimeClientStub({
			listConversations: vi.fn(async () => ({
				conversations: [],
				activeJob: null,
				defaultConversationId: "",
				virtualUserId: "webchat",
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		// 尝试发送消息
		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "测试");

		const sendBtn = screen.getByRole("button", { name: "发送" });
		await userEvent.click(sendBtn);

		// 应该显示错误
		expect(await screen.findByText("没有可用会话")).toBeInTheDocument();
	});
});
