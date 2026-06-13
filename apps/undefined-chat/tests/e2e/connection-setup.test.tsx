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

describe("E2E: Connection Setup Flow", () => {
	beforeEach(() => {
		vi.resetAllMocks();
	});

	test("显示连接配置界面当没有配置时", async () => {
		const client = runtimeClientStub({
			getRuntimeConfig: vi.fn(async () => null),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		expect(await screen.findByText("连接到 Runtime")).toBeInTheDocument();
		expect(screen.getByLabelText("Runtime URL")).toBeInTheDocument();
		expect(screen.getByLabelText("API Key")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "保存并连接" })).toBeInTheDocument();
	});

	test("使用默认 URL 预填充输入框", async () => {
		const client = runtimeClientStub({
			getRuntimeConfig: vi.fn(async () => null),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		const urlInput = (await screen.findByLabelText(
			"Runtime URL",
		)) as HTMLInputElement;
		expect(urlInput.value).toBe("http://127.0.0.1:8788");
	});

	test("保存配置并在连接后引导应用", async () => {
		const client = runtimeClientStub({
			getRuntimeConfig: vi
				.fn()
				.mockResolvedValueOnce(null)
				.mockResolvedValueOnce({
					runtimeUrl: "http://localhost:8788",
					hasApiKey: true,
				}),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		const urlInput = await screen.findByLabelText("Runtime URL");
		const keyInput = screen.getByLabelText("API Key");
		const connectBtn = screen.getByRole("button", { name: "保存并连接" });

		await userEvent.clear(urlInput);
		await userEvent.type(urlInput, "http://localhost:8788");
		await userEvent.type(keyInput, "sk-test-key-12345");
		await userEvent.click(connectBtn);

		await waitFor(() => {
			expect(client.saveRuntimeConfig).toHaveBeenCalledWith(
				"http://localhost:8788",
			);
			expect(client.saveApiKey).toHaveBeenCalledWith("sk-test-key-12345");
		});

		// 验证引导流程
		expect(client.probeRuntime).toHaveBeenCalled();
		expect(client.listConversations).toHaveBeenCalled();
		expect(client.getActiveJobs).toHaveBeenCalled();
		expect(client.listCommands).toHaveBeenCalled();

		// 验证进入主界面
		expect(await screen.findByRole("log", { name: "消息" })).toBeInTheDocument();
	});

	test("在 URL 和 API Key 都必填时阻止提交", async () => {
		const client = runtimeClientStub({
			getRuntimeConfig: vi.fn(async () => null),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		const keyInput = await screen.findByLabelText("API Key");
		const connectBtn = screen.getByRole("button", { name: "保存并连接" });

		// 清空 URL，尝试提交
		const urlInput = screen.getByLabelText("Runtime URL");
		await userEvent.clear(urlInput);

		await userEvent.click(connectBtn);

		// 表单应该被验证阻止，不会调用 API
		expect(client.saveRuntimeConfig).not.toHaveBeenCalled();

		// 输入 URL 但不输入 Key
		await userEvent.type(urlInput, "http://localhost:8788");
		await userEvent.click(connectBtn);

		// API Key 也是必填的
		expect(client.saveApiKey).not.toHaveBeenCalled();
	});

	test("支持不安全存储降级选项", async () => {
		const client = runtimeClientStub({
			getRuntimeConfig: vi
				.fn()
				.mockResolvedValueOnce(null)
				.mockResolvedValueOnce({
					runtimeUrl: "http://localhost:8788",
					hasApiKey: true,
				}),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByText("连接到 Runtime");

		const urlInput = screen.getByLabelText("Runtime URL");
		const keyInput = screen.getByLabelText("API Key");
		const fallbackCheckbox = screen.getByLabelText("允许不安全存储降级");
		const connectBtn = screen.getByRole("button", { name: "保存并连接" });

		await userEvent.clear(urlInput);
		await userEvent.type(urlInput, "http://localhost:8788");
		await userEvent.type(keyInput, "sk-test");
		await userEvent.click(fallbackCheckbox);
		await userEvent.click(connectBtn);

		await waitFor(() => {
			expect(client.confirmInsecureStorageFallback).toHaveBeenCalledOnce();
			expect(client.saveApiKey).toHaveBeenCalledWith("sk-test");
		});
	});

	test("显示配置保存错误", async () => {
		const client = runtimeClientStub({
			getRuntimeConfig: vi.fn(async () => null),
			saveRuntimeConfig: vi.fn(async () => {
				throw new Error("网络连接失败");
			}),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		const urlInput = await screen.findByLabelText("Runtime URL");
		const keyInput = screen.getByLabelText("API Key");
		const connectBtn = screen.getByRole("button", { name: "保存并连接" });

		await userEvent.clear(urlInput);
		await userEvent.type(urlInput, "http://invalid-url:9999");
		await userEvent.type(keyInput, "sk-test");
		await userEvent.click(connectBtn);

		expect(await screen.findByText("网络连接失败")).toBeInTheDocument();
	});

	test("已有配置时可以通过设置按钮重新打开配置面板", async () => {
		const client = runtimeClientStub({
			getRuntimeConfig: vi.fn(async () => ({
				runtimeUrl: "http://127.0.0.1:8788",
				hasApiKey: true,
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		// 等待应用加载完成
		await screen.findByRole("navigation", { name: "会话" });

		// 点击设置按钮（使用更具体的选择器）
		const settingsBtn = screen
			.getAllByTitle("配置 Runtime")
			.find((el) => el.tagName === "BUTTON") as HTMLElement;
		expect(settingsBtn).toBeDefined();
		await userEvent.click(settingsBtn);

		// 配置面板应该打开，标题不同
		expect(await screen.findByText("Runtime 配置")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "保存并连接" })).toBeInTheDocument();

		// 应该有关闭按钮（按 title 查找）
		const closeBtn = screen
			.getAllByTitle("关闭")
			.find((el) => el.tagName === "BUTTON") as HTMLElement;
		expect(closeBtn).toBeDefined();
		await userEvent.click(closeBtn);

		// 面板关闭
		await waitFor(() => {
			expect(screen.queryByText("Runtime 配置")).not.toBeInTheDocument();
		});
	});

	test("配置面板中 API Key 输入框对已有配置显示占位符", async () => {
		const client = runtimeClientStub({
			getRuntimeConfig: vi.fn(async () => ({
				runtimeUrl: "http://127.0.0.1:8788",
				hasApiKey: true,
			})),
		});
		vi.mocked(createTauriRuntimeClient).mockReturnValue(client);

		render(<App />);

		await screen.findByRole("navigation", { name: "会话" });

		// 打开设置（使用更具体的选择器）
		const settingsBtn = screen
			.getAllByTitle("配置 Runtime")
			.find((el) => el.tagName === "BUTTON") as HTMLElement;
		expect(settingsBtn).toBeDefined();
		await userEvent.click(settingsBtn);

		const keyInput = (await screen.findByLabelText(
			"API Key",
		)) as HTMLInputElement;

		// 已有配置时显示占位符而不是要求必填
		expect(keyInput.placeholder).toContain("••••");
		expect(keyInput.required).toBe(false);
	});
});
