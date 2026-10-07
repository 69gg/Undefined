import { describe, expect, test, vi } from "vitest";
import type {
	ActiveJobsResponse,
	HistoryResponse,
	JobEventsJsonResponse,
} from "../runtime-client/types";
import {
	conversation,
	historyItem,
	job,
	runtimeClientStub,
} from "../test-fixtures";
import { createChatStore } from "./store";

function deferred<T>() {
	let resolve!: (value: T) => void;
	const promise = new Promise<T>((resolvePromise) => {
		resolve = resolvePromise;
	});
	return { promise, resolve };
}

function resumeFixture() {
	let active: ActiveJobsResponse = { job: null, jobs: [] };
	let completed = false;
	const client = runtimeClientStub({
		listConversations: vi.fn(async () => ({
			conversations: [conversation({ id: "A" }), conversation({ id: "B" })],
			activeJob: null,
			defaultConversationId: "A",
			virtualUserId: "webchat",
		})),
		getActiveJobs: vi.fn(async () => active),
		sendMessage: vi.fn(async () =>
			job({ jobId: "job-A", conversationId: "A", hasTimelineSnapshot: true }),
		),
		getHistory: vi.fn(async ({ conversationId }): Promise<HistoryResponse> => {
			const items =
				completed && conversationId === "A"
					? [
							historyItem({ messageId: "user-A", content: "question-A" }),
							historyItem({
								messageId: "bot-A",
								role: "bot",
								content: "completed-in-background",
							}),
						]
					: [];
			return {
				conversationId,
				virtualUserId: "webchat",
				permission: "superadmin",
				count: items.length,
				items,
				limit: 50,
				before: null,
				hasMore: false,
				nextBefore: null,
				total: items.length,
			};
		}),
	});
	const store = createChatStore({ client });
	return {
		client,
		store,
		complete() {
			completed = true;
		},
		setActive(response: ActiveJobsResponse) {
			active = response;
		},
		async start() {
			await store.bootstrap();
			store.updateDraft("A", "question-A");
			await store.sendSelectedMessage();
			await store.selectConversation("B");
		},
	};
}

describe("completed jobs omitted from a reconnect snapshot", () => {
	test("refreshes a nonselected conversation even when its old JSON response arrives after resume", async () => {
		const { client, store, start, complete } = resumeFixture();
		const terminal = deferred<JobEventsJsonResponse>();
		vi.mocked(client.fetchJobEventsJson).mockImplementationOnce(
			() => terminal.promise,
		);
		await start();
		store.handleRuntimeStatus({
			jobId: "job-A",
			subscriptionId: "sub-1",
			status: "error",
			detail: "offline",
		});
		complete();
		await store.bootstrap({ preserveSelectionId: "B", resuming: true });
		terminal.resolve({
			job: job({
				jobId: "job-A",
				conversationId: "A",
				status: "done",
				historyFinalized: true,
				lastSeq: 3,
			}),
			events: [],
			after: 0,
			lastSeq: 3,
		});
		await Promise.resolve();
		await store.selectConversation("A");
		expect(store.getSnapshot().historyByConversation.A.items[1].content).toBe(
			"completed-in-background",
		);
		expect(client.getHistory).toHaveBeenCalledTimes(4);
		const lateTerminal = {
			jobId: "job-A",
			subscriptionId: "sub-1",
			seq: 3,
			eventType: "done",
			payload: { conversation_id: "A" },
		};
		store.handleRuntimeEvent(lateTerminal);
		store.handleRuntimeEvent(lateTerminal);
		await vi.waitFor(() => expect(client.getHistory).toHaveBeenCalledTimes(5));
		expect(store.getSnapshot().historyByConversation.A.items).toHaveLength(2);
	});

	test("deduplicates the selected conversation and retains terminal jobs still finalizing history", async () => {
		const { client, store, start, complete, setActive } = resumeFixture();
		await start();
		await store.selectConversation("A");
		setActive({
			job: null,
			jobs: [
				job({
					jobId: "job-A",
					conversationId: "A",
					status: "done",
					historyFinalized: false,
					hasTimelineSnapshot: true,
				}),
			],
		});
		await store.bootstrap({ preserveSelectionId: "B", resuming: true });
		expect(client.getHistory).toHaveBeenCalledTimes(3);
		expect(store.getSnapshot().activeJobsByConversation.A).toBeDefined();
		setActive({ job: null, jobs: [] });
		complete();
		await store.bootstrap({ preserveSelectionId: "A", resuming: true });
		expect(client.getHistory).toHaveBeenCalledTimes(4);
		expect(store.getSnapshot().activeJobsByConversation.A).toBeUndefined();
	});

	test("does not reload a conversation deleted while offline", async () => {
		const { client, store, start } = resumeFixture();
		await start();
		vi.mocked(client.listConversations).mockResolvedValue({
			conversations: [conversation({ id: "B" })],
			activeJob: null,
			defaultConversationId: "B",
			virtualUserId: "webchat",
		});
		await store.bootstrap({ preserveSelectionId: "B", resuming: true });
		expect(
			vi
				.mocked(client.getHistory)
				.mock.calls.map(([input]) => input.conversationId),
		).toEqual(["A", "B", "B"]);
	});

	test("preserves the history request started by a terminal response during bootstrap", async () => {
		const { client, store, start, complete } = resumeFixture();
		await start();
		const snapshot = deferred<ActiveJobsResponse>();
		vi.mocked(client.getActiveJobs).mockImplementationOnce(
			() => snapshot.promise,
		);
		const terminalHistory = deferred<HistoryResponse>();
		const getHistory = client.getHistory;
		vi.mocked(client.getHistory).mockImplementationOnce(
			() => terminalHistory.promise,
		);
		const resuming = store.bootstrap({
			preserveSelectionId: "B",
			resuming: true,
		});
		await vi.waitFor(() =>
			expect(client.getActiveJobs).toHaveBeenCalledTimes(2),
		);
		vi.mocked(client.fetchJobEventsJson).mockResolvedValue({
			job: job({
				jobId: "job-A",
				conversationId: "A",
				status: "done",
				historyFinalized: true,
				hasTimelineSnapshot: true,
			}),
			events: [],
			after: 0,
			lastSeq: 0,
		});
		store.handleRuntimeStatus({
			jobId: "job-A",
			subscriptionId: "sub-1",
			status: "closed",
			detail: "done",
		});
		await vi.waitFor(() => expect(client.getHistory).toHaveBeenCalledTimes(3));
		snapshot.resolve({ job: null, jobs: [] });
		await resuming;
		complete();
		// 获取 fixture 的权威历史结果，但不发起新的 store history 请求。
		terminalHistory.resolve(
			await getHistory({ conversationId: "A", limit: 50 }),
		);
		await vi.waitFor(() =>
			expect(store.getSnapshot().historyByConversation.A.items).toHaveLength(2),
		);
		expect(store.getSnapshot().historyByConversation.A.items[1].content).toBe(
			"completed-in-background",
		);
	});

	test("retries a terminal history refresh invalidated by same-Runtime suspension", async () => {
		const { client, store, start, complete } = resumeFixture();
		await start();
		const pendingHistory = deferred<HistoryResponse>();
		vi.mocked(client.getHistory).mockImplementationOnce(
			() => pendingHistory.promise,
		);
		vi.mocked(client.fetchJobEventsJson).mockResolvedValue({
			job: job({
				jobId: "job-A",
				conversationId: "A",
				status: "done",
				historyFinalized: true,
				hasTimelineSnapshot: true,
			}),
			events: [],
			after: 0,
			lastSeq: 0,
		});
		store.handleRuntimeStatus({
			jobId: "job-A",
			subscriptionId: "sub-1",
			status: "closed",
			detail: "done",
		});
		await vi.waitFor(() => expect(client.getHistory).toHaveBeenCalledTimes(3));
		expect(store.getSnapshot().activeJobsByConversation.A).toBeUndefined();
		expect(store.getSnapshot().historyByConversation.A.loading).toBe(true);
		store.suspendRuntime();
		complete();
		await store.bootstrap({ preserveSelectionId: "B", resumeSuspended: true });
		expect(client.getHistory).toHaveBeenCalledTimes(5);
		const finalHistory = store.getSnapshot().historyByConversation.A;
		pendingHistory.resolve({
			conversationId: "A",
			virtualUserId: "webchat",
			permission: "superadmin",
			count: 1,
			limit: 50,
			before: null,
			hasMore: false,
			nextBefore: null,
			total: 1,
			items: [historyItem({ content: "obsolete" })],
		});
		await Promise.resolve();
		await store.selectConversation("A");
		expect(store.getSnapshot().historyByConversation.A).toEqual(finalHistory);
		expect(finalHistory.items[1].content).toBe("completed-in-background");
	});

	test("retries a failed background completion refresh when selecting its conversation", async () => {
		const { client, store, start, complete } = resumeFixture();
		await start();
		complete();
		const getHistory = vi.mocked(client.getHistory).getMockImplementation();
		if (!getHistory) throw new Error("missing fixture history implementation");
		let failA = true;
		vi.mocked(client.getHistory).mockImplementation(async (input) => {
			if (input.conversationId === "A" && failA)
				throw new Error("temporary history failure");
			return getHistory(input);
		});
		await store.bootstrap({ preserveSelectionId: "B", resuming: true });
		expect(store.getSnapshot().historyByConversation.A.error).toBe(
			"temporary history failure",
		);
		failA = false;
		await store.selectConversation("A");
		expect(store.getSnapshot().historyByConversation.A.error).toBeNull();
		expect(store.getSnapshot().historyByConversation.A.items[1].content).toBe(
			"completed-in-background",
		);
	});
});
