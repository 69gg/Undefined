import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConnectionSetup } from "./ConnectionSetup";

describe("ConnectionSetup", () => {
	it("renders connection form", () => {
		const onConnect = vi.fn();
		render(<ConnectionSetup onConnect={onConnect} />);

		expect(screen.getByText("连接到 Undefined Runtime")).toBeInTheDocument();
		expect(screen.getByLabelText("Runtime URL")).toBeInTheDocument();
		expect(screen.getByLabelText("API Key")).toBeInTheDocument();
		expect(screen.getByRole("button", { name: "连接" })).toBeInTheDocument();
	});

	it("submits connection with valid inputs", async () => {
		const onConnect = vi.fn();
		render(<ConnectionSetup onConnect={onConnect} />);

		const urlInput = screen.getByLabelText("Runtime URL");
		const keyInput = screen.getByLabelText("API Key");
		const submitButton = screen.getByRole("button", { name: "连接" });

		fireEvent.change(urlInput, {
			target: { value: "http://192.168.1.100:8788" },
		});
		fireEvent.change(keyInput, { target: { value: "test-api-key" } });
		fireEvent.click(submitButton);

		await waitFor(() => {
			expect(onConnect).toHaveBeenCalledWith(
				"http://192.168.1.100:8788",
				"test-api-key",
			);
		});
	});

	it("validates URL format", async () => {
		const onConnect = vi.fn();
		render(<ConnectionSetup onConnect={onConnect} />);

		const urlInput = screen.getByLabelText("Runtime URL");
		const keyInput = screen.getByLabelText("API Key");
		const submitButton = screen.getByRole("button", { name: "连接" });

		fireEvent.change(urlInput, { target: { value: "not-a-valid-url" } });
		fireEvent.change(keyInput, { target: { value: "test-key" } });
		fireEvent.click(submitButton);

		await waitFor(() => {
			expect(screen.getByText("URL 格式不正确")).toBeInTheDocument();
			expect(onConnect).not.toHaveBeenCalled();
		});
	});

	it("requires both URL and API key", async () => {
		const onConnect = vi.fn();
		render(<ConnectionSetup onConnect={onConnect} />);

		const urlInput = screen.getByLabelText("Runtime URL");
		const submitButton = screen.getByRole("button", { name: "连接" });

		fireEvent.change(urlInput, {
			target: { value: "http://192.168.1.100:8788" },
		});
		fireEvent.click(submitButton);

		await waitFor(() => {
			expect(screen.getByText("请输入 API Key")).toBeInTheDocument();
			expect(onConnect).not.toHaveBeenCalled();
		});
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
		render(<ConnectionSetup onConnect={onConnect} />);

		await waitFor(() => {
			expect(screen.getByText("最近使用")).toBeInTheDocument();
			expect(screen.getByText("http://192.168.1.100:8788")).toBeInTheDocument();
			expect(screen.getByText("http://192.168.1.101:8788")).toBeInTheDocument();
		});

		localStorage.clear();
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
		render(<ConnectionSetup onConnect={onConnect} />);

		await waitFor(() => {
			expect(screen.getByText("http://192.168.1.100:8788")).toBeInTheDocument();
		});

		const configButton = screen.getByText("http://192.168.1.100:8788");
		fireEvent.click(configButton);

		const urlInput = screen.getByLabelText("Runtime URL") as HTMLInputElement;
		expect(urlInput.value).toBe("http://192.168.1.100:8788");

		localStorage.clear();
	});

	it("uses currentUrl prop as default", () => {
		const onConnect = vi.fn();
		render(
			<ConnectionSetup
				currentUrl="http://custom.example.com:8788"
				onConnect={onConnect}
			/>,
		);

		const urlInput = screen.getByLabelText("Runtime URL") as HTMLInputElement;
		expect(urlInput.value).toBe("http://custom.example.com:8788");
	});
});
