import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { App } from "./App";
import { LanguageProvider, LOCALE_STORAGE_KEY } from "./i18n";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));

describe("connection recovery through the real Tauri client and store", () => {
	beforeEach(() => {
		vi.resetAllMocks();
		localStorage.clear();
		localStorage.setItem(LOCALE_STORAGE_KEY, "zh-CN");
		vi.mocked(listen).mockResolvedValue(() => undefined);
	});

	test.each([false, true])(
		"key failure with rollback failure=%s keeps UI and Native target consistent and prevents Runtime requests",
		async (rollbackFails) => {
			let nativeUrl = "http://runtime-a.test";
			const runtimeCalls: Array<{ command: string; origin: string }> = [];
			vi.mocked(invoke).mockImplementation(async (command, args) => {
				switch (command) {
					case "get_runtime_config":
						return { runtimeUrl: nativeUrl };
					case "load_api_key_status":
						return { available: true, storage: "system-keyring" };
					case "save_runtime_config": {
						const { input } = args as { input: { runtimeUrl: string } };
						if (rollbackFails && input.runtimeUrl === "http://runtime-a.test") {
							throw new Error("rollback denied");
						}
						nativeUrl = input.runtimeUrl;
						return { runtimeUrl: nativeUrl };
					}
					case "save_api_key":
						throw new Error("keyring denied");
				}
				runtimeCalls.push({ command, origin: nativeUrl });
				switch (command) {
					case "probe_runtime":
						return { status: 200, ok: true, body: "ok" };
					case "list_conversations":
						return {
							conversations: [
								{ id: "legacy-system-42", title: "A conversation" },
							],
							default_conversation_id: "legacy-system-42",
						};
					case "get_history":
						return {
							conversation_id: "legacy-system-42",
							items: [
								{ message_id: "a-history", role: "user", content: "A history" },
							],
						};
					case "get_active_jobs":
						return { jobs: [] };
					case "list_commands":
						return { commands: [] };
					default:
						throw new Error(`Unexpected Native command: ${command}`);
				}
			});
			render(
				<LanguageProvider>
					<App />
				</LanguageProvider>,
			);
			await screen.findByText("A history");
			await userEvent.type(
				screen.getByLabelText("消息输入"),
				"A private draft",
			);
			fireEvent.keyDown(window, { key: ",", ctrlKey: true });
			await userEvent.clear(screen.getByLabelText("Runtime URL"));
			await userEvent.type(
				screen.getByLabelText("Runtime URL"),
				"http://runtime-b.test",
			);
			await userEvent.type(screen.getByLabelText("API Key"), "B-key");
			await userEvent.click(screen.getByRole("button", { name: "保存并连接" }));
			await screen.findByText(/keyring denied/);
			expect(nativeUrl).toBe(
				rollbackFails ? "http://runtime-b.test" : "http://runtime-a.test",
			);
			expect(screen.getByLabelText("Runtime URL")).toHaveValue(nativeUrl);
			expect(screen.getByLabelText("消息输入")).toBeDisabled();
			expect(screen.getByLabelText("消息输入")).toHaveValue(
				rollbackFails ? "" : "A private draft",
			);
			fireEvent.keyDown(window, { key: "Escape" });
			expect(screen.getByLabelText("Runtime URL")).toBeInTheDocument();
			fireEvent.keyDown(window, { key: "Enter", ctrlKey: true });
			expect(runtimeCalls.map(({ origin }) => origin)).toEqual(
				Array(5).fill("http://runtime-a.test"),
			);
			expect(
				vi
					.mocked(invoke)
					.mock.calls.filter(([command]) => command === "send_message"),
			).toEqual([]);
		},
	);
});
