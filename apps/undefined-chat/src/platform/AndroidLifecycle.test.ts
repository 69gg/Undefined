import { describe, expect, it, vi } from "vitest";
import { isAndroid, setupAndroidLifecycle } from "./AndroidLifecycle";

const listeners = new Map<string, () => void | Promise<void>>();
const unlisten = vi.fn();

vi.mock("@tauri-apps/api/window", () => ({
	getCurrentWindow: () => ({
		listen: vi.fn(
			async (event: string, callback: () => void | Promise<void>) => {
				listeners.set(event, callback);
				return unlisten;
			},
		),
	}),
}));

vi.mock("@tauri-apps/api/event", () => ({
	TauriEvent: {
		WINDOW_RESUMED: "tauri://resumed",
		WINDOW_SUSPENDED: "tauri://suspended",
	},
}));

describe("AndroidLifecycle", () => {
	beforeEach(() => {
		listeners.clear();
		unlisten.mockClear();
	});

	describe("isAndroid", () => {
		it("detects Android platform from user agent", () => {
			const originalUserAgent = navigator.userAgent;

			// Mock Android user agent
			Object.defineProperty(navigator, "userAgent", {
				value:
					"Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36",
				configurable: true,
			});

			expect(isAndroid()).toBe(true);

			// Restore original user agent
			Object.defineProperty(navigator, "userAgent", {
				value: originalUserAgent,
				configurable: true,
			});
		});

		it("returns false for non-Android platforms", () => {
			const originalUserAgent = navigator.userAgent;

			// Mock desktop user agent
			Object.defineProperty(navigator, "userAgent", {
				value:
					"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
				configurable: true,
			});

			expect(isAndroid()).toBe(false);

			// Restore original user agent
			Object.defineProperty(navigator, "userAgent", {
				value: originalUserAgent,
				configurable: true,
			});
		});
	});

	describe("setupAndroidLifecycle", () => {
		it("re-bootstraps on android resume and cleans listeners", async () => {
			const mockStore = {
				bootstrap: vi.fn(async () => undefined),
				getSnapshot: vi.fn(() => ({
					activeJobsByConversation: {},
					eventCursorByJob: {},
				})),
			};

			const cleanup = setupAndroidLifecycle(
				mockStore as unknown as Parameters<typeof setupAndroidLifecycle>[0],
			);
			await vi.waitFor(() => {
				expect(listeners.has("tauri://suspended")).toBe(true);
				expect(listeners.has("tauri://resumed")).toBe(true);
			});

			await listeners.get("tauri://resumed")?.();

			expect(mockStore.bootstrap).toHaveBeenCalledOnce();
			cleanup();
			expect(unlisten).toHaveBeenCalledTimes(2);
		});
	});
});
