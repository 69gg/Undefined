import { describe, expect, it, vi } from "vitest";
import { createChatStore } from "../chat-store/store";
import {
	conversation,
	historyItem,
	job,
	runtimeClientStub,
} from "../test-fixtures";
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
		it("reloads a completed background conversation through the real resume listener", async () => {
			let completed = false;
			const client = runtimeClientStub({
				listConversations: vi.fn(async () => ({
					conversations: [conversation({ id: "A" }), conversation({ id: "B" })],
					activeJob: null,
					defaultConversationId: "A",
					virtualUserId: "webchat",
				})),
				sendMessage: vi.fn(async () => job({ conversationId: "A" })),
			});
			const getHistory = client.getHistory;
			client.getHistory = vi.fn(async (input) => {
				const history = await getHistory(input);
				const items =
					completed && input.conversationId === "A"
						? [historyItem({ role: "bot", content: "后台已完成" })]
						: [];
				return {
					...history,
					conversationId: input.conversationId,
					items,
					total: items.length,
				};
			});
			const store = createChatStore({ client });
			await store.bootstrap();
			store.updateDraft("A", "question");
			await store.sendSelectedMessage();
			await store.selectConversation("B");
			const cleanup = setupAndroidLifecycle(store);
			await vi.waitFor(() =>
				expect(listeners.has("tauri://resumed")).toBe(true),
			);
			completed = true;
			await listeners.get("tauri://resumed")?.();
			expect(store.getSnapshot().selectedConversationId).toBe("B");
			await store.selectConversation("A");
			expect(store.getSnapshot().historyByConversation.A.items[0].content).toBe(
				"后台已完成",
			);
			cleanup();
		});

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
