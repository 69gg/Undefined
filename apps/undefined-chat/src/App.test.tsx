import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { App } from "./App";
import { probeRuntime, probeSecretStorage } from "./runtime";

vi.mock("./runtime", () => ({
	probeRuntime: vi.fn(),
	probeSecretStorage: vi.fn(),
}));

const mockProbeRuntime = vi.mocked(probeRuntime);
const mockProbeSecretStorage = vi.mocked(probeSecretStorage);

describe("App", () => {
	beforeEach(() => {
		vi.resetAllMocks();
	});

	test("renders the default runtime connection state", () => {
		render(<App />);

		const runtimeInput = screen.getByLabelText(
			"Runtime URL",
		) as HTMLInputElement;

		expect(
			screen.getByRole("heading", {
				name: "原生优先 WebChat 客户端验证",
			}),
		).toBeTruthy();
		expect(runtimeInput.value).toBe("http://127.0.0.1:8788");
		expect(screen.getByText("待连接")).toBeTruthy();
	});

	test("shows runtime probe results", async () => {
		mockProbeRuntime.mockResolvedValue({
			ok: true,
			status: 200,
			body: "ok",
		});

		render(<App />);
		await userEvent.click(screen.getByRole("button", { name: "测试连接" }));

		expect(mockProbeRuntime).toHaveBeenCalledWith("http://127.0.0.1:8788");
		expect(await screen.findByText("已连接")).toBeTruthy();
		expect(screen.getByText(/"status": 200/)).toBeTruthy();
	});

	test("clears stale runtime results when a later probe fails", async () => {
		mockProbeRuntime
			.mockResolvedValueOnce({
				ok: true,
				status: 200,
				body: "ok",
			})
			.mockRejectedValueOnce(new Error("runtime offline"));

		render(<App />);
		await userEvent.click(screen.getByRole("button", { name: "测试连接" }));
		expect(await screen.findByText(/"status": 200/)).toBeTruthy();

		await userEvent.click(screen.getByRole("button", { name: "测试连接" }));

		expect(await screen.findByText("Error: runtime offline")).toBeTruthy();
		expect(screen.queryByText(/"status": 200/)).toBeNull();
	});

	test("shows secret storage probe results", async () => {
		mockProbeSecretStorage.mockResolvedValue({
			available: true,
			degraded: false,
			detail: "stronghold ready",
		});

		render(<App />);
		await userEvent.click(screen.getByRole("button", { name: "探测" }));

		expect(mockProbeSecretStorage).toHaveBeenCalledOnce();
		expect(screen.getByText(/stronghold ready/)).toBeTruthy();
	});

	test("shows secret storage probe errors", async () => {
		mockProbeSecretStorage.mockRejectedValue(new Error("command unavailable"));

		render(<App />);
		await userEvent.click(screen.getByRole("button", { name: "探测" }));

		expect(mockProbeSecretStorage).toHaveBeenCalledOnce();
		expect(await screen.findByText("Error: command unavailable")).toBeTruthy();
	});

	test("clears stale secret storage results when a later probe fails", async () => {
		mockProbeSecretStorage
			.mockResolvedValueOnce({
				available: true,
				degraded: false,
				detail: "stronghold ready",
			})
			.mockRejectedValueOnce(new Error("stronghold locked"));

		render(<App />);
		await userEvent.click(screen.getByRole("button", { name: "探测" }));
		expect(await screen.findByText(/stronghold ready/)).toBeTruthy();

		await userEvent.click(screen.getByRole("button", { name: "探测" }));

		expect(await screen.findByText("Error: stronghold locked")).toBeTruthy();
		expect(screen.queryByText(/stronghold ready/)).toBeNull();
	});
});
