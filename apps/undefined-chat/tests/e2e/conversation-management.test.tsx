import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { App } from "../../src/App";
import { createTauriRuntimeClient } from "../../src/runtime-client/tauri";
import {
	conversation,
	historyItem,
	runtimeClientStub,
} from "../../src/test-fixtures";

vi.mock("../../src/runtime-client/tauri", () => ({
	createTauriRuntimeClient: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-dialog", () => ({
	open: vi.fn(),
}));

describe("E2E: Conversation Management", () => {
	beforeEach(() => {
		vi.resetAllMocks();
	});

	test("创建新会话", async () => {
		const client = runtimeClientStub({
			listConversations: vi.fn(async () => ({
				conversations: [conversation({ id: "default", title: "默认会话" })],
				activeJob: null,
				defaultConversationId: "default",
				virtualUserId: "webchat",
			})),
			createConversation: vi.fn(async () =>
				conversation({ id: "new", title: "新会话", messageCount: 0 }),
			),
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
					conversationId: "new",
					virtualUserId: "webchat",
					permission: "superadmin",
					count: 0,
					items: [],
					limit: 50,
					before: null,
					hasMore: false,
					nextBefore: null,
					total: 0,
				}),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		// 点击新建按钮
		const createBtn = screen.getByRole("button", { name: "新建" });
		await userEvent.click(createBtn);

		// 验证 API 调用
		await waitFor(() => {
			expect(client.createConversation).toHaveBeenCalledOnce();
		});

		// 新会话应该出现并被选中
		expect(await screen.findByRole("button", { name: /新会话/ })).toBeInTheDocument();
		expect(client.getHistory).toHaveBeenCalledWith({
			conversationId: "new",
			limit: 50,
		});
	});

	test("在不同会话间切换", async () => {
		const client = runtimeClientStub({
			listConversations: vi.fn(async () => ({
				conversations: [
					conversation({ id: "conv-1", title: "会话一" }),
					conversation({ id: "conv-2", title: "会话二" }),
					conversation({ id: "conv-3", title: "会话三" }),
				],
				activeJob: null,
				defaultConversationId: "conv-1",
				virtualUserId: "webchat",
			})),
			getHistory: vi
				.fn()
				.mockResolvedValueOnce({
					conversationId: "conv-1",
					virtualUserId: "webchat",
					permission: "superadmin",
					count: 1,
					items: [historyItem({ messageId: "msg-1", content: "消息1" })],
					limit: 50,
					before: null,
					hasMore: false,
					nextBefore: null,
					total: 1,
				})
				.mockResolvedValueOnce({
					conversationId: "conv-2",
					virtualUserId: "webchat",
					permission: "superadmin",
					count: 1,
					items: [historyItem({ messageId: "msg-2", content: "消息2" })],
					limit: 50,
					before: null,
					hasMore: false,
					nextBefore: null,
					total: 1,
				})
				.mockResolvedValueOnce({
					conversationId: "conv-3",
					virtualUserId: "webchat",
					permission: "superadmin",
					count: 1,
					items: [historyItem({ messageId: "msg-3", content: "消息3" })],
					limit: 50,
					before: null,
					hasMore: false,
					nextBefore: null,
					total: 1,
				}),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		// 等待初始会话加载
		expect(await screen.findByText("消息1")).toBeInTheDocument();

		// 切换到会话二
		await userEvent.click(screen.getByRole("button", { name: /会话二/ }));
		expect(await screen.findByText("消息2")).toBeInTheDocument();
		expect(screen.queryByText("消息1")).not.toBeInTheDocument();

		// 切换到会话三
		await userEvent.click(screen.getByRole("button", { name: /会话三/ }));
		expect(await screen.findByText("消息3")).toBeInTheDocument();
		expect(screen.queryByText("消息2")).not.toBeInTheDocument();

		// 切换回会话一
		await userEvent.click(screen.getByRole("button", { name: /会话一/ }));
		expect(await screen.findByText("消息1")).toBeInTheDocument();

		// 验证历史只加载一次（缓存生效）
		expect(client.getHistory).toHaveBeenCalledTimes(3);
	});

	test("显示会话列表中的消息计数", async () => {
		const client = runtimeClientStub({
			listConversations: vi.fn(async () => ({
				conversations: [
					conversation({ id: "conv-1", title: "空会话", messageCount: 0 }),
					conversation({ id: "conv-2", title: "有消息", messageCount: 42 }),
				],
				activeJob: null,
				defaultConversationId: "conv-1",
				virtualUserId: "webchat",
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		// 验证会话标题显示（使用 getAllByText 因为可能在列表和主区域都显示）
		expect(screen.getAllByText("空会话").length).toBeGreaterThan(0);
		expect(screen.getByText("有消息")).toBeInTheDocument();
	});

	test("高亮当前选中的会话", async () => {
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

		const conv1Btn = screen.getByRole("button", { name: /会话一/ });
		const conv2Btn = screen.getByRole("button", { name: /会话二/ });

		// 初始选中会话一（通过 aria-current="page" 标识）
		expect(conv1Btn.getAttribute("aria-current")).toBe("page");
		expect(conv2Btn.getAttribute("aria-current")).toBe(null);

		// 切换到会话二
		await userEvent.click(conv2Btn);

		await waitFor(() => {
			expect(conv1Btn.getAttribute("aria-current")).toBe(null);
			expect(conv2Btn.getAttribute("aria-current")).toBe("page");
		});
	});

	test("在移动端视口关闭侧边栏选择会话后", async () => {
		// 模拟移动端宽度
		Object.defineProperty(window, "innerWidth", {
			writable: true,
			configurable: true,
			value: 375,
		});

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

		const nav = await screen.findByRole("navigation", { name: "会话" });

		// 打开移动端菜单
		const menuBtn = screen.getByRole("button", { name: "打开会话列表" });
		await userEvent.click(menuBtn);
		expect(nav.classList.contains("active")).toBe(true);

		// 选择会话二
		await userEvent.click(screen.getByRole("button", { name: /会话二/ }));

		// 侧边栏应该自动关闭（overlay 和侧栏本体都不再 active）
		const overlay = document.querySelector(".sidebar-overlay");
		await waitFor(() => {
			expect(overlay?.classList.contains("active")).toBe(false);
			expect(nav.classList.contains("active")).toBe(false);
		});

		// 恢复窗口宽度
		Object.defineProperty(window, "innerWidth", {
			writable: true,
			configurable: true,
			value: 1024,
		});
	});

	test("默认选中第一个会话如果没有指定默认会话", async () => {
		const client = runtimeClientStub({
			listConversations: vi.fn(async () => ({
				conversations: [
					conversation({ id: "first", title: "第一个" }),
					conversation({ id: "second", title: "第二个" }),
				],
				activeJob: null,
				defaultConversationId: "", // 空默认
				virtualUserId: "webchat",
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		// 应该加载第一个会话的历史
		await waitFor(() => {
			expect(client.getHistory).toHaveBeenCalledWith({
				conversationId: "first",
				limit: 50,
			});
		});
	});
});
