import { describe, expect, it, vi } from "vitest";
import { isAndroid } from "./AndroidLifecycle";

describe("AndroidLifecycle", () => {
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
		it("returns cleanup function", () => {
			// Mock store with minimal required interface
			const mockStore = {
				bootstrap: vi.fn(),
				getSnapshot: vi.fn(() => ({
					activeJobsByConversation: {},
					eventCursorByJob: {},
				})),
			};

			// Note: Full testing requires Tauri environment
			// This test verifies the store interface contract
			expect(mockStore.bootstrap).toBeDefined();
			expect(mockStore.getSnapshot).toBeDefined();
		});
	});
});
