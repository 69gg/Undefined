import { open } from "@tauri-apps/plugin-dialog";
import {
	fireEvent,
	render,
	screen,
	waitFor,
	within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { App } from "./App";
import { createTauriRuntimeClient } from "./runtime-client/tauri";
import { conversation, historyItem, runtimeClientStub } from "./test-fixtures";

vi.mock("./runtime-client/tauri", () => ({
	createTauriRuntimeClient: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-dialog", () => ({
	open: vi.fn(),
}));

describe("App", () => {
	beforeEach(() => {
		vi.resetAllMocks();
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

		render(<App />);

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

		render(<App />);
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

		render(<App />);
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

		render(<App />);
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

		render(<App />);
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

		render(<App />);
		await screen.findByRole("navigation", { name: "会话" });
		const menuButton = screen.getByRole("button", { name: "打开会话列表" });
		expect(menuButton).toHaveAttribute("aria-expanded", "false");

		await userEvent.click(menuButton);

		expect(menuButton).toHaveAttribute("aria-expanded", "true");
		expect(screen.getByRole("navigation", { name: "会话" })).toHaveClass(
			"active",
		);

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

	test("registers desktop shortcuts for new chat and command mode", async () => {
		const client = runtimeClientStub();
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);
		await screen.findByRole("navigation", { name: "会话" });

		fireEvent.keyDown(window, { key: "n", ctrlKey: true });
		expect(client.createConversation).toHaveBeenCalledOnce();

		fireEvent.keyDown(window, { key: "k", ctrlKey: true });
		const editor = await screen.findByDisplayValue("/");
		await waitFor(() => {
			expect(editor).toHaveFocus();
		});
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

		render(<App />);
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

		render(<App />);
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

		render(<App />);
		await screen.findByText("report.pdf");

		await userEvent.click(screen.getByRole("button", { name: "下载" }));

		expect(client.saveAttachment).toHaveBeenCalledWith({
			attachmentId: "att-1",
			fileName: "report.pdf",
		});
	});
});
