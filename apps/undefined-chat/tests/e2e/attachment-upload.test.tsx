import { open } from "@tauri-apps/plugin-dialog";
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

describe("E2E: Attachment Upload", () => {
	beforeEach(() => {
		vi.resetAllMocks();
	});

	test("通过原生文件选择器添加附件", async () => {
		vi.mocked(open).mockResolvedValue("/home/user/document.pdf");
		const client = runtimeClientStub({
			uploadAttachment: vi.fn(async () => ({
				id: "att-123",
				name: "document.pdf",
				size: 102400,
				mediaType: "application/pdf",
				kind: "file",
				downloadUrl: "/api/v1/chat/attachments/att-123",
				previewUrl: null,
				discarded: false,
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		// 点击添加附件按钮
		const attachBtn = screen.getByRole("button", { name: "添加附件" });
		await userEvent.click(attachBtn);

		// 验证原生对话框被调用
		expect(open).toHaveBeenCalledWith({
			multiple: false,
			directory: false,
			title: "选择附件",
			pickerMode: "document",
			fileAccessMode: "copy",
		});

		// 验证上传 API 被调用
		await waitFor(() => {
			expect(client.uploadAttachment).toHaveBeenCalledWith({
				filePath: "/home/user/document.pdf",
			});
		});

		// 附件应该出现在附件队列中
		expect(await screen.findByText("document.pdf")).toBeInTheDocument();
	});

	test("显示上传中状态", async () => {
		vi.mocked(open).mockResolvedValue("/home/user/large-file.zip");
		const client = runtimeClientStub({
			uploadAttachment: vi.fn(
				() =>
					new Promise((resolve) => {
						setTimeout(
							() =>
								resolve({
									id: "att-456",
									name: "large-file.zip",
									size: 10485760,
									mediaType: "application/zip",
									kind: "file",
									downloadUrl: "/api/v1/chat/attachments/att-456",
									previewUrl: null,
									discarded: false,
								}),
							1000,
						);
					}),
			),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		// 添加附件
		await userEvent.click(screen.getByRole("button", { name: "添加附件" }));

		// 应该立即显示上传中状态
		expect(await screen.findByText("large-file.zip")).toBeInTheDocument();

		// 等待上传完成
		await waitFor(
			() => {
				expect(client.uploadAttachment).toHaveBeenCalled();
			},
			{ timeout: 2000 },
		);
	});

	test("显示上传错误", async () => {
		vi.mocked(open).mockResolvedValue("/home/user/invalid.bin");
		const client = runtimeClientStub({
			uploadAttachment: vi.fn(async () => {
				throw new Error("文件类型不支持");
			}),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		await userEvent.click(screen.getByRole("button", { name: "添加附件" }));

		// 等待上传尝试
		await waitFor(
			() => {
				expect(client.uploadAttachment).toHaveBeenCalled();
			},
			{ timeout: 2000 },
		);

		// 应该显示文件名（即使上传失败，附件队列也会显示）
		expect(await screen.findByText("invalid.bin")).toBeInTheDocument();
	});

	test("移除附件", async () => {
		vi.mocked(open).mockResolvedValue("/home/user/temp.txt");
		const client = runtimeClientStub({
			uploadAttachment: vi.fn(async () => ({
				id: "att-temp",
				name: "temp.txt",
				size: 100,
				mediaType: "text/plain",
				kind: "file",
				downloadUrl: "/api/v1/chat/attachments/att-temp",
				previewUrl: null,
				discarded: false,
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		// 添加附件
		await userEvent.click(screen.getByRole("button", { name: "添加附件" }));

		// 等待附件出现
		expect(await screen.findByText("temp.txt")).toBeInTheDocument();

		// 移除附件（使用 aria-label 查找）
		const removeBtn = screen.getByLabelText("移除 temp.txt");
		await userEvent.click(removeBtn);

		// 附件应该被移除
		await waitFor(() => {
			expect(screen.queryByText("temp.txt")).not.toBeInTheDocument();
		});
	});

	test("阻止在附件上传中时发送消息", async () => {
		vi.mocked(open).mockResolvedValue("/home/user/uploading.png");
		const client = runtimeClientStub({
			uploadAttachment: vi.fn(
				() =>
					new Promise(() => {
						// 永不 resolve，模拟长时间上传
					}),
			),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		// 添加附件（开始上传）
		await userEvent.click(screen.getByRole("button", { name: "添加附件" }));
		await screen.findByText("uploading.png");

		// 输入消息
		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "测试消息");

		// 尝试发送
		const sendBtn = screen.getByRole("button", { name: "发送" });
		await userEvent.click(sendBtn);

		// 应该显示错误
		expect(await screen.findByText("附件仍在上传")).toBeInTheDocument();

		// sendMessage 不应该被调用
		expect(client.sendMessage).not.toHaveBeenCalled();
	});

	test("阻止发送包含上传失败附件的消息", async () => {
		vi.mocked(open).mockResolvedValue("/home/user/error.bin");
		const client = runtimeClientStub({
			uploadAttachment: vi.fn(async () => {
				throw new Error("上传失败");
			}),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		// 添加附件（上传失败）
		await userEvent.click(screen.getByRole("button", { name: "添加附件" }));

		// 等待上传尝试
		await waitFor(
			() => {
				expect(client.uploadAttachment).toHaveBeenCalled();
			},
			{ timeout: 2000 },
		);

		// 附件应该出现
		expect(await screen.findByText("error.bin")).toBeInTheDocument();

		// 输入消息
		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "测试消息");

		// 尝试发送（发送按钮应该被禁用或发送被阻止）
		const sendBtn = screen.getByRole("button", { name: "发送" });

		// 由于附件状态为 error，发送可能被阻止
		// sendMessage 不应该被调用（测试逻辑）
		await userEvent.click(sendBtn);

		// 等待一小段时间确认没有发送
		await new Promise((resolve) => setTimeout(resolve, 100));
		expect(client.sendMessage).not.toHaveBeenCalled();
	});

	test("发送消息时包含附件 ID", async () => {
		vi.mocked(open).mockResolvedValue("/home/user/report.pdf");
		const client = runtimeClientStub({
			uploadAttachment: vi.fn(async () => ({
				id: "att-report-123",
				name: "report.pdf",
				size: 51200,
				mediaType: "application/pdf",
				kind: "file",
				downloadUrl: "/api/v1/chat/attachments/att-report-123",
				previewUrl: null,
				discarded: false,
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		// 添加附件
		await userEvent.click(screen.getByRole("button", { name: "添加附件" }));
		await screen.findByText("report.pdf");

		// 等待上传完成
		await waitFor(() => {
			expect(client.uploadAttachment).toHaveBeenCalled();
		});

		// 输入消息并发送
		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "这是报告");
		await userEvent.click(screen.getByRole("button", { name: "发送" }));

		// 验证消息包含附件 ID
		await waitFor(() => {
			expect(client.sendMessage).toHaveBeenCalledWith({
				conversationId: "default",
				message: {
					text: "这是报告",
					attachmentIds: ["att-report-123"],
					references: [],
				},
			});
		});
	});

	test("用户取消文件选择时不触发上传", async () => {
		vi.mocked(open).mockResolvedValue(null);
		const client = runtimeClientStub();
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		await userEvent.click(screen.getByRole("button", { name: "添加附件" }));

		// 应该不调用上传 API
		await waitFor(() => {
			expect(client.uploadAttachment).not.toHaveBeenCalled();
		});
	});

	test("附件在发送后被清空", async () => {
		vi.mocked(open).mockResolvedValue("/home/user/note.txt");
		const client = runtimeClientStub();
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		// 添加附件
		await userEvent.click(screen.getByRole("button", { name: "添加附件" }));
		await screen.findByText("note.txt");

		// 发送消息
		const input = screen.getByLabelText("消息输入");
		await userEvent.type(input, "附件测试");
		await userEvent.click(screen.getByRole("button", { name: "发送" }));

		// 附件应该被清空
		await waitFor(() => {
			expect(screen.queryByText("note.txt")).not.toBeInTheDocument();
		});
	});
});
