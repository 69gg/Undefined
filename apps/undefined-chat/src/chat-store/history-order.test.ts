import { describe, expect, test, vi } from "vitest";
import type {
	HistoryPageResponse,
	HistoryResponse,
} from "../runtime-client/types";
import { historyItem, job, runtimeClientStub } from "../test-fixtures";
import { createChatStore } from "./store";

function deferred<T>() {
	let resolve!: (value: T) => void;
	let reject!: (reason: Error) => void;
	const promise = new Promise<T>((resolvePromise, rejectPromise) => {
		resolve = resolvePromise;
		reject = rejectPromise;
	});
	return { promise, resolve, reject };
}

function history(start: number, end: number, total = end): HistoryResponse {
	return {
		conversationId: "default",
		virtualUserId: "webchat",
		permission: "superadmin",
		count: end - start,
		items: Array.from({ length: end - start }, (_, index) =>
			historyItem({
				messageId: `message-${start + index}`,
				content: `正文 ${start + index}`,
			}),
		),
		limit: 50,
		before: null,
		hasMore: start > 0,
		nextBefore: start > 0 ? start : null,
		total,
	};
}

describe("history request ordering within one Runtime", () => {
	test("a late page cannot replace the final history after sending and cancelling a job", async () => {
		const oldPage = deferred<HistoryPageResponse>();
		const finalHistory = history(72, 122);
		finalHistory.items.splice(
			-2,
			2,
			historyItem({ messageId: "new-user", content: "新问题" }),
			historyItem({
				messageId: "new-bot",
				role: "bot",
				content: "新回复",
			}),
		);
		const client = runtimeClientStub({
			getHistory: vi
				.fn()
				.mockResolvedValueOnce(history(70, 120))
				.mockResolvedValueOnce(finalHistory),
			getHistoryPage: vi.fn(() => oldPage.promise),
			cancelJob: vi.fn(async () =>
				job({ status: "cancelled", historyFinalized: true }),
			),
		});
		const store = createChatStore({ client });
		await store.bootstrap();
		const pendingPage = store.loadMoreHistory("default");
		store.updateDraft("default", "新问题");
		await store.sendSelectedMessage();
		await store.cancelJob("job-1");
		await vi.waitFor(() => {
			expect(store.getSnapshot().historyByConversation.default.items).toEqual(
				finalHistory.items,
			);
		});
		oldPage.resolve({ ...history(20, 70, 120), before: 70, cursor: 20 });
		await pendingPage;
		expect(store.getSnapshot().historyByConversation.default).toEqual({
			items: finalHistory.items,
			hasMore: true,
			nextBefore: 72,
			total: 122,
			loading: false,
			error: null,
		});
	});

	test.each(["success", "error"])(
		"a superseded reload %s cannot replace a newer reload",
		async (outcome) => {
			const oldReload = deferred<HistoryResponse>();
			const newer = history(72, 122);
			const client = runtimeClientStub();
			const store = createChatStore({ client });
			await store.bootstrap();
			vi.mocked(client.getHistory)
				.mockImplementationOnce(() => oldReload.promise)
				.mockResolvedValueOnce(newer);
			const pending = store.reloadHistory("default");
			await store.reloadHistory("default");
			if (outcome === "success") oldReload.resolve(history(70, 120));
			else oldReload.reject(new Error("旧请求失败"));
			await pending;
			expect(store.getSnapshot().historyByConversation.default).toEqual({
				items: newer.items,
				hasMore: true,
				nextBefore: 72,
				total: 122,
				loading: false,
				error: null,
			});
		},
	);

	test("an old page error cannot clear a newer reload's loading state", async () => {
		const page = deferred<HistoryPageResponse>();
		const reload = deferred<HistoryResponse>();
		const client = runtimeClientStub({
			getHistory: vi.fn(async () => history(70, 120)),
			getHistoryPage: vi.fn(() => page.promise),
		});
		const store = createChatStore({ client });
		await store.bootstrap();
		const pendingPage = store.loadMoreHistory("default");
		vi.mocked(client.getHistory).mockImplementationOnce(() => reload.promise);
		const pendingReload = store.reloadHistory("default");
		page.reject(new Error("迟到分页错误"));
		await pendingPage;
		expect(store.getSnapshot().historyByConversation.default.loading).toBe(
			true,
		);
		expect(store.getSnapshot().historyByConversation.default.error).toBeNull();
		reload.resolve(history(72, 122));
		await pendingReload;
		expect(store.getSnapshot().historyByConversation.default.loading).toBe(
			false,
		);
	});

	test.each(["page", "reload"])(
		"an in-flight %s cannot remove a newly sent optimistic message",
		async (kind) => {
			const response = deferred<HistoryPageResponse>();
			const client = runtimeClientStub({
				getHistory: vi.fn(async () => history(70, 120)),
				getHistoryPage: vi.fn(() => response.promise),
			});
			const store = createChatStore({ client });
			await store.bootstrap();
			vi.mocked(client.getHistory).mockImplementationOnce(
				() => response.promise,
			);
			const pending =
				kind === "page"
					? store.loadMoreHistory("default")
					: store.reloadHistory("default");
			store.updateDraft("default", "保留新问题");
			await store.sendSelectedMessage();
			response.resolve({ ...history(20, 70, 120), before: 70, cursor: 20 });
			await pending;
			const saved = store.getSnapshot().historyByConversation.default;
			expect(saved.items.at(-1)?.content).toBe("保留新问题");
			expect(saved.total).toBe(121);
			expect(saved.nextBefore).toBe(70);
			expect(saved.loading).toBe(false);
		},
	);

	test("a pending history response cannot recreate a deleted conversation's history", async () => {
		const response = deferred<HistoryResponse>();
		const client = runtimeClientStub();
		const store = createChatStore({ client });
		await store.bootstrap();
		vi.mocked(client.getHistory).mockImplementationOnce(() => response.promise);
		const pending = store.reloadHistory("default");
		await store.deleteConversation("default");
		response.resolve(history(70, 120));
		await pending;
		expect(store.getSnapshot().historyByConversation.default).toBeUndefined();
	});
});
