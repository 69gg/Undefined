import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LOCALE_STORAGE_KEY, LanguageProvider } from "../i18n";
import { ConnectionSetup } from "./ConnectionSetup";

/** 在 LanguageProvider 下渲染（组件依赖 useTranslation） */
function renderWithI18n(ui: ReactElement) {
	return render(<LanguageProvider>{ui}</LanguageProvider>);
}

describe("ConnectionSetup", () => {
	beforeEach(() => {
		// 固定 locale 为 zh-CN，避免随测试环境 navigator.language 漂移
		localStorage.setItem(LOCALE_STORAGE_KEY, "zh-CN");
	});

	afterEach(() => {
		localStorage.clear();
	});

	it("renders connection form in setup mode", () => {
		const onConnect = vi.fn();
		renderWithI18n(<ConnectionSetup mode="setup" onConnect={onConnect} />);

		expect(screen.getByText("连接到 Runtime")).toBeInTheDocument();
		expect(screen.getByLabelText("Runtime URL")).toBeInTheDocument();
		expect(screen.getByLabelText("API Key")).toBeInTheDocument();
		expect(
			screen.getByRole("button", { name: "保存并连接" }),
		).toBeInTheDocument();
	});

	it("submits connection with valid inputs (url, key, allowInsecure)", async () => {
		const onConnect = vi.fn();
		renderWithI18n(<ConnectionSetup mode="setup" onConnect={onConnect} />);

		const urlInput = screen.getByLabelText("Runtime URL");
		const keyInput = screen.getByLabelText("API Key");
		const submitButton = screen.getByRole("button", { name: "保存并连接" });

		fireEvent.change(urlInput, {
			target: { value: "http://192.168.1.100:8788" },
		});
		fireEvent.change(keyInput, { target: { value: "test-api-key" } });
		fireEvent.click(submitButton);

		await waitFor(() => {
			expect(onConnect).toHaveBeenCalledWith(
				"http://192.168.1.100:8788",
				"test-api-key",
				false,
			);
		});
	});

	it("validates URL format", async () => {
		const onConnect = vi.fn();
		renderWithI18n(<ConnectionSetup mode="setup" onConnect={onConnect} />);

		const urlInput = screen.getByLabelText("Runtime URL");
		const keyInput = screen.getByLabelText("API Key");
		const submitButton = screen.getByRole("button", { name: "保存并连接" });

		// type="url" + required 会触发浏览器原生校验，jsdom 下不阻断提交逻辑，
		// 这里直接验证组件内的 URL 解析校验分支
		fireEvent.change(urlInput, { target: { value: "not-a-valid-url" } });
		fireEvent.change(keyInput, { target: { value: "test-key" } });
		fireEvent.click(submitButton);

		await waitFor(() => {
			expect(screen.getByText("URL 格式不正确")).toBeInTheDocument();
			expect(onConnect).not.toHaveBeenCalled();
		});
	});

	it("requires API key in setup mode", async () => {
		const onConnect = vi.fn();
		renderWithI18n(<ConnectionSetup mode="setup" onConnect={onConnect} />);

		const urlInput = screen.getByLabelText("Runtime URL");
		const submitButton = screen.getByRole("button", { name: "保存并连接" });

		fireEvent.change(urlInput, {
			target: { value: "http://192.168.1.100:8788" },
		});
		fireEvent.click(submitButton);

		await waitFor(() => {
			expect(screen.getByText("请输入 API Key")).toBeInTheDocument();
			expect(onConnect).not.toHaveBeenCalled();
		});
	});

	it("allows empty API key in settings mode (keeps existing key)", async () => {
		const onConnect = vi.fn();
		renderWithI18n(
			<ConnectionSetup
				currentUrl="http://192.168.1.100:8788"
				mode="settings"
				onConnect={onConnect}
			/>,
		);

		const submitButton = screen.getByRole("button", { name: "保存并连接" });
		fireEvent.click(submitButton);

		await waitFor(() => {
			expect(onConnect).toHaveBeenCalledWith(
				"http://192.168.1.100:8788",
				"",
				false,
			);
		});
	});

	it("forwards allowInsecure when checkbox is checked", async () => {
		const onConnect = vi.fn();
		renderWithI18n(<ConnectionSetup mode="setup" onConnect={onConnect} />);

		const urlInput = screen.getByLabelText("Runtime URL");
		const keyInput = screen.getByLabelText("API Key");
		const checkbox = screen.getByRole("checkbox");
		const submitButton = screen.getByRole("button", { name: "保存并连接" });

		fireEvent.change(urlInput, {
			target: { value: "http://192.168.1.100:8788" },
		});
		fireEvent.change(keyInput, { target: { value: "k" } });
		fireEvent.click(checkbox);
		fireEvent.click(submitButton);

		await waitFor(() => {
			expect(onConnect).toHaveBeenCalledWith(
				"http://192.168.1.100:8788",
				"k",
				true,
			);
		});
	});

	it("shows close button only in settings mode", () => {
		const onConnect = vi.fn();
		const onClose = vi.fn();
		const { rerender } = renderWithI18n(
			<ConnectionSetup mode="setup" onClose={onClose} onConnect={onConnect} />,
		);
		expect(
			screen.queryByRole("button", { name: "关闭" }),
		).not.toBeInTheDocument();

		rerender(
			<LanguageProvider>
				<ConnectionSetup
					mode="settings"
					onClose={onClose}
					onConnect={onConnect}
				/>
			</LanguageProvider>,
		);
		const closeButton = screen.getByRole("button", { name: "关闭" });
		fireEvent.click(closeButton);
		expect(onClose).toHaveBeenCalled();
	});

	it("loads and displays saved configs", async () => {
		const mockConfigs = [
			{ runtimeUrl: "http://192.168.1.100:8788", usedAt: Date.now() },
			{ runtimeUrl: "http://192.168.1.101:8788", usedAt: Date.now() - 1000 },
		];
		localStorage.setItem(
			"undefined-runtime-history",
			JSON.stringify(mockConfigs),
		);

		const onConnect = vi.fn();
		renderWithI18n(<ConnectionSetup mode="setup" onConnect={onConnect} />);

		await waitFor(() => {
			expect(screen.getByText("最近使用")).toBeInTheDocument();
			expect(screen.getByText("http://192.168.1.100:8788")).toBeInTheDocument();
			expect(screen.getByText("http://192.168.1.101:8788")).toBeInTheDocument();
		});
	});

	it("selects config from recent list", async () => {
		const mockConfigs = [
			{ runtimeUrl: "http://192.168.1.100:8788", usedAt: Date.now() },
		];
		localStorage.setItem(
			"undefined-runtime-history",
			JSON.stringify(mockConfigs),
		);

		const onConnect = vi.fn();
		renderWithI18n(<ConnectionSetup mode="setup" onConnect={onConnect} />);

		await waitFor(() => {
			expect(screen.getByText("http://192.168.1.100:8788")).toBeInTheDocument();
		});

		const configButton = screen.getByText("http://192.168.1.100:8788");
		fireEvent.click(configButton);

		const urlInput = screen.getByLabelText("Runtime URL") as HTMLInputElement;
		expect(urlInput.value).toBe("http://192.168.1.100:8788");
	});

	it("uses currentUrl prop as default", () => {
		const onConnect = vi.fn();
		renderWithI18n(
			<ConnectionSetup
				currentUrl="http://custom.example.com:8788"
				mode="setup"
				onConnect={onConnect}
			/>,
		);

		const urlInput = screen.getByLabelText("Runtime URL") as HTMLInputElement;
		expect(urlInput.value).toBe("http://custom.example.com:8788");
	});
});
