import { open } from "@tauri-apps/plugin-dialog";
import { render, screen, waitFor } from "@testing-library/react";
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
								name: "report.png",
								size: 2048,
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
		vi.spyOn(window, "alert").mockImplementation(() => undefined);
		vi.spyOn(window, "open").mockImplementation(() => null);
		vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview");

		render(<App />);
		await screen.findByText("report.png");

		await userEvent.click(screen.getByRole("button", { name: "预览" }));
		await userEvent.click(screen.getByRole("button", { name: "保存" }));

		expect(client.previewAttachment).toHaveBeenCalledWith({
			attachmentId: "att-1",
		});
		expect(client.saveAttachment).toHaveBeenCalledWith({
			attachmentId: "att-1",
			fileName: "report.png",
		});
		expect(window.open).toHaveBeenCalledWith(
			"blob:preview",
			"_blank",
			"noopener,noreferrer",
		);
	});
});
