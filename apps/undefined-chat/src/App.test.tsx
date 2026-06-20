import { open } from "@tauri-apps/plugin-dialog";
import {
	fireEvent,
	render,
	screen,
	waitFor,
	within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { App } from "./App";
import { LOCALE_STORAGE_KEY, LanguageProvider } from "./i18n";
import { createTauriRuntimeClient } from "./runtime-client/tauri";
import { conversation, historyItem, runtimeClientStub } from "./test-fixtures";

vi.mock("./runtime-client/tauri", () => ({
	createTauriRuntimeClient: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-dialog", () => ({
	open: vi.fn(),
}));

/**
 * App 依赖 LanguageProvider；平台上下文走默认值（DEFAULT_PLATFORM_INFO，
 * os="unknown" → 非移动/桌面/Android），由测试用 innerWidth 控制移动布局。
 */
function renderApp(ui: ReactElement = <App />) {
	return render(<LanguageProvider>{ui}</LanguageProvider>);
}

describe("App", () => {
	beforeEach(() => {
		vi.resetAllMocks();
		localStorage.clear();
		// 固定 locale 为 zh-CN，断言依赖简体中文文案
		localStorage.setItem(LOCALE_STORAGE_KEY, "zh-CN");
		// 复位视口宽度，避免移动端用例失败时残留 innerWidth 污染后续用例
		Object.defineProperty(window, "innerWidth", {
			configurable: true,
			value: 1280,
		});
		window.dispatchEvent(new Event("resize"));
	});

	test("boots into a Chinese chat-first workspace", async () => {
		vi.mocked(createTauriRuntimeClient).mockReturnValue(
			runtimeClientStub({
				listConversations: vi.fn(async () => ({
					conversations: [
						conversation({ id: "default", title: "默认会话" }),
						conversation({ id: "ops", title: "运维排障", messageCount: 4 }),
					],
					activeJob: null,
					defaultConversationId: "default",
					virtualUserId: "webchat",
				})),
				getHistory: vi.fn(async () => ({
					conversationId: "default",
					virtualUserId: "webchat",
					permission: "superadmin",
					count: 1,
					items: [
						historyItem({
							messageId: "msg-1",
							content: "今天需要做什么？",
						}),
					],
					limit: 50,
					before: null,
					hasMore: false,
					nextBefore: null,
					total: 1,
				})),
			}),
		);

		renderApp();

		expect(
			await screen.findByRole("navigation", { name: "会话" }),
		).toBeTruthy();
		expect(screen.getByRole("log", { name: "消息" })).toBeTruthy();
		expect(screen.getByLabelText("消息输入")).toBeTruthy();
		expect(screen.getByText("今天需要做什么？")).toBeTruthy();
		expect(screen.queryByText(/PoC/)).toBeNull();
		expect(screen.queryByText("原生优先 WebChat 客户端验证")).toBeNull();
	});

	test("keeps different conversations independently selectable", async () => {
		const client = runtimeClientStub({
			listConversations: vi.fn(async () => ({
				conversations: [
					conversation({ id: "default", title: "默认会话" }),
					conversation({ id: "ops", title: "运维排障", messageCount: 4 }),
				],
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
					count: 1,
					items: [
						historyItem({
							messageId: "default-msg",
							content: "默认消息",
						}),
					],
					limit: 50,
					before: null,
					hasMore: false,
					nextBefore: null,
					total: 1,
				})
				.mockResolvedValueOnce({
					conversationId: "ops",
					virtualUserId: "webchat",
					permission: "superadmin",
					count: 1,
					items: [
						historyItem({
							messageId: "ops-msg",
							content: "运维消息",
						}),
					],
					limit: 50,
					before: null,
					hasMore: false,
					nextBefore: null,
					total: 1,
				}),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderApp();
		await screen.findByText("默认消息");
		await userEvent.click(screen.getByRole("button", { name: /运维排障/ }));

		expect(await screen.findByText("运维消息")).toBeTruthy();
		expect(client.getHistory).toHaveBeenLastCalledWith({
			conversationId: "ops",
			limit: 50,
		});
	});

	test("saves initial Runtime config and API key before reconnecting", async () => {
		const client = runtimeClientStub({
			getRuntimeConfig: vi
				.fn()
				.mockResolvedValueOnce(null)
				.mockResolvedValueOnce({
					runtimeUrl: "http://127.0.0.1:8788",
					hasApiKey: true,
				}),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderApp();
		expect(await screen.findByText("保存并连接")).toBeTruthy();

		await userEvent.clear(screen.getByLabelText("Runtime URL"));
		await userEvent.type(
			screen.getByLabelText("Runtime URL"),
			"http://127.0.0.1:8788",
		);
		await userEvent.type(screen.getByLabelText("API Key"), "sk-test");
		await userEvent.click(screen.getByRole("button", { name: "保存并连接" }));

		expect(client.saveRuntimeConfig).toHaveBeenCalledWith(
			"http://127.0.0.1:8788",
		);
		expect(client.saveApiKey).toHaveBeenCalledWith("sk-test");
		expect(await screen.findByRole("log", { name: "消息" })).toBeTruthy();
	});

	test("requires an explicit opt-in before confirming insecure API key storage fallback", async () => {
		const client = runtimeClientStub({
			getRuntimeConfig: vi
				.fn()
				.mockResolvedValueOnce(null)
				.mockResolvedValueOnce({
					runtimeUrl: "http://127.0.0.1:8788",
					hasApiKey: true,
				}),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderApp();
		expect(await screen.findByText("保存并连接")).toBeTruthy();

		await userEvent.clear(screen.getByLabelText("Runtime URL"));
		await userEvent.type(
			screen.getByLabelText("Runtime URL"),
			"http://127.0.0.1:8788",
		);
		await userEvent.type(screen.getByLabelText("API Key"), "sk-test");
		await userEvent.click(screen.getByLabelText("允许不安全存储降级"));
		await userEvent.click(screen.getByRole("button", { name: "保存并连接" }));

		expect(client.confirmInsecureStorageFallback).toHaveBeenCalledOnce();
		expect(client.saveApiKey).toHaveBeenCalledWith("sk-test");
	});

	test("creates conversations from the rail action", async () => {
		const client = runtimeClientStub();
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderApp();
		await screen.findByRole("navigation", { name: "会话" });
		await userEvent.click(screen.getByRole("button", { name: "新建" }));

		expect(client.createConversation).toHaveBeenCalledOnce();
		expect(await screen.findByRole("button", { name: /新会话/ })).toBeTruthy();
	});

	test("opens and closes the mobile conversation drawer with accessible state", async () => {
		const originalInnerWidth = window.innerWidth;
		Object.defineProperty(window, "innerWidth", {
			configurable: true,
			value: 390,
		});
		window.dispatchEvent(new Event("resize"));
		const client = runtimeClientStub();
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderApp();
		await screen.findByRole("navigation", { name: "会话" });
		const menuButton = screen.getByRole("button", { name: "打开会话列表" });
		expect(menuButton).toHaveAttribute("aria-expanded", "false");

		await userEvent.click(menuButton);

		expect(menuButton).toHaveAttribute("aria-expanded", "true");
		// 移动端抽屉激活时容器为 role="dialog" aria-modal（无障碍语义）
		const drawer = screen.getByRole("dialog", { name: "会话" });
		expect(drawer).toHaveClass("active");
		expect(drawer).toHaveAttribute("aria-modal", "true");

		fireEvent.keyDown(window, { key: "Escape" });

		await waitFor(() => {
			expect(menuButton).toHaveAttribute("aria-expanded", "false");
		});

		Object.defineProperty(window, "innerWidth", {
			configurable: true,
			value: originalInnerWidth,
		});
		window.dispatchEvent(new Event("resize"));
	});

	test("closes the mobile conversation drawer after creating a conversation", async () => {
		const originalInnerWidth = window.innerWidth;
		Object.defineProperty(window, "innerWidth", {
			configurable: true,
			value: 390,
		});
		window.dispatchEvent(new Event("resize"));
		const client = runtimeClientStub();
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderApp();
		await screen.findByRole("navigation", { name: "会话" });
		const menuButton = screen.getByRole("button", { name: "打开会话列表" });
		await userEvent.click(menuButton);
		// 抽屉激活时为 dialog
		expect(screen.getByRole("dialog", { name: "会话" })).toHaveClass("active");

		await userEvent.click(screen.getByRole("button", { name: "新建" }));

		await waitFor(() => {
			expect(menuButton).toHaveAttribute("aria-expanded", "false");
		});
		// 抽屉关闭后恢复为 navigation 且无 active
		expect(screen.getByRole("navigation", { name: "会话" })).not.toHaveClass(
			"active",
		);
		expect(client.createConversation).toHaveBeenCalledOnce();

		Object.defineProperty(window, "innerWidth", {
			configurable: true,
			value: originalInnerWidth,
		});
		window.dispatchEvent(new Event("resize"));
	});

	test("registers desktop shortcuts for new chat and command mode", async () => {
		const client = runtimeClientStub();
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderApp();
		await screen.findByRole("navigation", { name: "会话" });

		fireEvent.keyDown(window, { key: "n", ctrlKey: true });
		expect(client.createConversation).toHaveBeenCalledOnce();

		fireEvent.keyDown(window, { key: "k", ctrlKey: true });
		const editor = await screen.findByDisplayValue("/");
		await waitFor(() => {
			expect(editor).toHaveFocus();
		});
	});

	test("registers desktop shortcuts for settings and sidebar visibility", async () => {
		const client = runtimeClientStub();
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderApp();
		await screen.findByRole("navigation", { name: "会话" });

		fireEvent.keyDown(window, { key: ",", ctrlKey: true });
		expect(
			await screen.findByRole("heading", { name: "Runtime 配置" }),
		).toBeTruthy();

		fireEvent.keyDown(window, { key: "Escape" });
		await waitFor(() => {
			expect(
				screen.queryByRole("heading", { name: "Runtime 配置" }),
			).toBeNull();
		});

		fireEvent.keyDown(window, { key: "/", ctrlKey: true });
		expect(screen.getByRole("navigation", { name: "会话" })).toHaveClass(
			"collapsed",
		);
		expect(screen.getByRole("button", { name: "展开菜单" })).toBeTruthy();

		fireEvent.keyDown(window, { key: "/", ctrlKey: true });
		expect(screen.getByRole("navigation", { name: "会话" })).not.toHaveClass(
			"collapsed",
		);
	});

	test("jumps from a reference chip to the loaded source message", async () => {
		const scrollIntoView = vi.fn();
		const originalScrollIntoView = Element.prototype.scrollIntoView;
		Element.prototype.scrollIntoView = scrollIntoView;
		const client = runtimeClientStub({
			getHistory: vi.fn(async () => ({
				conversationId: "default",
				virtualUserId: "webchat",
				permission: "superadmin",
				count: 2,
				items: [
					historyItem({
						messageId: "source-msg",
						role: "bot",
						content: "源消息内容",
					}),
					historyItem({
						messageId: "reply-msg",
						role: "bot",
						content: "回复消息",
						references: [
							{
								messageId: "source-msg",
								quote: "源消息内容",
							},
						],
					}),
				],
				limit: 50,
				before: null,
				hasMore: false,
				nextBefore: null,
				total: 2,
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderApp();
		await screen.findByText("回复消息");
		const sourceMessage = document.querySelector(
			'[data-message-id="source-msg"]',
		);
		expect(sourceMessage).toBeTruthy();
		await userEvent.click(
			within(sourceMessage as HTMLElement).getByRole("button", {
				name: "引用",
			}),
		);
		await userEvent.click(screen.getByRole("button", { name: "源消息内容" }));

		expect(scrollIntoView).toHaveBeenCalledWith({
			block: "center",
			behavior: "smooth",
		});
		expect(
			document.querySelector('[data-message-id="source-msg"]'),
		).toHaveClass("message-jump-highlight");
		Element.prototype.scrollIntoView = originalScrollIntoView;
	});

	test("uses the native file picker when adding attachments", async () => {
		vi.mocked(open).mockResolvedValue("/tmp/trace.log");
		const promptSpy = vi
			.spyOn(window, "prompt")
			.mockImplementation(() => "/tmp/legacy.log");
		const client = runtimeClientStub();
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderApp();
		await screen.findByRole("navigation", { name: "会话" });
		await userEvent.click(screen.getByRole("button", { name: "添加附件" }));

		expect(open).toHaveBeenCalledWith({
			multiple: false,
			directory: false,
			title: "选择附件",
			pickerMode: "document",
			fileAccessMode: "copy",
		});
		expect(promptSpy).not.toHaveBeenCalled();
		await waitFor(() => {
			expect(client.uploadAttachment).toHaveBeenCalledWith({
				filePath: "/tmp/trace.log",
			});
		});
	});

	test("uses native attachment bridges for timeline actions", async () => {
		const client = runtimeClientStub({
			getHistory: vi.fn(async () => ({
				conversationId: "default",
				virtualUserId: "webchat",
				permission: "superadmin",
				count: 1,
				items: [
					historyItem({
						messageId: "msg-attachment",
						role: "bot",
						content: "附件已生成",
						attachments: [
							{
								id: "att-1",
								name: "report.pdf",
								size: 2048,
								mediaType: "application/pdf",
								kind: "file",
								downloadUrl: "/api/v1/chat/attachments/att-1",
								previewUrl: "/api/v1/chat/attachments/att-1/preview",
								discarded: false,
							},
						],
					}),
				],
				limit: 50,
				before: null,
				hasMore: false,
				nextBefore: null,
				total: 1,
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);
		vi.spyOn(window, "alert").mockImplementation(() => undefined);

		renderApp();
		await screen.findByText("report.pdf");

		await userEvent.click(screen.getByRole("button", { name: "下载" }));

		expect(client.saveAttachment).toHaveBeenCalledWith({
			attachmentId: "att-1",
			fileName: "report.pdf",
		});
	});

	test("opens image attachment previews in the in-app viewer and releases blob URLs", async () => {
		const createObjectUrlSpy = vi
			.spyOn(URL, "createObjectURL")
			.mockReturnValue("blob:preview-att-1");
		const revokeObjectUrlSpy = vi.spyOn(URL, "revokeObjectURL");
		const client = runtimeClientStub({
			getHistory: vi.fn(async () => ({
				conversationId: "default",
				virtualUserId: "webchat",
				permission: "superadmin",
				count: 1,
				items: [
					historyItem({
						messageId: "msg-image",
						role: "bot",
						content: "图片已生成",
						attachments: [
							{
								id: "att-1",
								name: "large.png",
								size: 20 * 1024 * 1024,
								mediaType: "image/png",
								kind: "image",
								downloadUrl: "/api/v1/chat/attachments/att-1",
								previewUrl: "/api/v1/chat/attachments/att-1/preview",
								discarded: false,
							},
						],
					}),
				],
				limit: 50,
				before: null,
				hasMore: false,
				nextBefore: null,
				total: 1,
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		renderApp();
		await screen.findByText("large.png");
		await userEvent.click(screen.getByRole("button", { name: "预览" }));

		expect(client.previewAttachment).toHaveBeenCalledWith({
			attachmentId: "att-1",
		});
		expect(createObjectUrlSpy).toHaveBeenCalled();
		const viewer = await screen.findByRole("dialog", { name: "图片查看器" });
		expect(
			within(viewer).getByRole("img", { name: "large.png" }),
		).toHaveAttribute("src", "blob:preview-att-1");

		fireEvent.keyDown(window, { key: "n", ctrlKey: true });
		expect(client.createConversation).not.toHaveBeenCalled();

		fireEvent.keyDown(window, { key: "Escape" });
		await waitFor(() => {
			expect(screen.queryByRole("dialog", { name: "图片查看器" })).toBeNull();
		});
		expect(revokeObjectUrlSpy).toHaveBeenCalledWith("blob:preview-att-1");
	});
});
