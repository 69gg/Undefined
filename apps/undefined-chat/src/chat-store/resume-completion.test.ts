import { describe, expect, test, vi } from "vitest";
import type {
	ActiveJobsResponse,
	ChatJob,
	EventStreamSubscription,
	HistoryResponse,
	JobEventsJsonResponse,
	RuntimeHealth,
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
	let reject!: (reason: Error) => void;
	const promise = new Promise<T>((resolvePromise, rejectPromise) => {
		resolve = resolvePromise;
		reject = rejectPromise;
	});
	return { promise, resolve, reject };
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
	test("deduplicates a send ACK subscription while resume is still installing its listener", async () => {
		const sending = deferred<ChatJob>();
		const listener = deferred<() => void>();
		const stream = deferred<EventStreamSubscription>();
		const accepted = job({ hasTimelineSnapshot: true });
		const client = runtimeClientStub({
			sendMessage: vi.fn(() => sending.promise),
			startJobEventStream: vi
				.fn()
				.mockImplementationOnce(() => stream.promise)
				.mockResolvedValue({
					subscriptionId: "duplicate-subscription",
					jobId: accepted.jobId,
					afterSeq: 0,
				}),
			cancelJob: vi.fn(async () =>
				job({ status: "cancelled", historyFinalized: true }),
			),
		});
		const store = createChatStore({ client });
		await store.bootstrap();
		store.updateDraft("default", "question");
		const sendRequest = store.sendSelectedMessage();
		vi.mocked(client.getActiveJobs).mockResolvedValueOnce({
			job: accepted,
			jobs: [accepted],
		});
		vi.mocked(client.listenRuntimeSse).mockImplementationOnce(
			() => listener.promise,
		);
		const resuming = store.bootstrap({ resuming: true });
		await vi.waitFor(() =>
			expect(client.listenRuntimeSse).toHaveBeenCalledTimes(2),
		);
		sending.resolve(accepted);
		await vi.waitFor(() =>
			expect(client.startJobEventStream).toHaveBeenCalledTimes(1),
		);
		listener.resolve(() => {});
		await resuming;
		stream.resolve({
			subscriptionId: "single-subscription",
			jobId: accepted.jobId,
			afterSeq: 0,
		});
		await sendRequest;
		expect(client.startJobEventStream).toHaveBeenCalledTimes(1);
		await store.cancelJob(accepted.jobId);
		expect(client.stopJobEventStream).toHaveBeenCalledExactlyOnceWith(
			"single-subscription",
		);
	});

	test.each(["success", "failure"])(
		"ignores late pre-resume stream %s without replacing the recovered subscription",
		async (outcome) => {
			const sending = deferred<ChatJob>();
			const health = deferred<RuntimeHealth>();
			const oldStream = deferred<EventStreamSubscription>();
			const accepted = job({ hasTimelineSnapshot: true });
			const client = runtimeClientStub({
				sendMessage: vi.fn(() => sending.promise),
				startJobEventStream: vi
					.fn()
					.mockImplementationOnce(() => oldStream.promise)
					.mockResolvedValueOnce({
						subscriptionId: "recovered-subscription",
						jobId: accepted.jobId,
						afterSeq: 0,
					}),
				cancelJob: vi.fn(async () =>
					job({ status: "cancelled", historyFinalized: true }),
				),
			});
			const store = createChatStore({ client });
			await store.bootstrap();
			store.updateDraft("default", "question");
			const sendRequest = store.sendSelectedMessage();
			vi.mocked(client.probeRuntime).mockImplementationOnce(
				() => health.promise,
			);
			const resuming = store.bootstrap({ resuming: true });
			await vi.waitFor(() =>
				expect(client.getActiveJobs).toHaveBeenCalledTimes(2),
			);
			sending.resolve(accepted);
			await vi.waitFor(() =>
				expect(client.startJobEventStream).toHaveBeenCalledTimes(1),
			);
			health.resolve({ ok: true, status: 200, body: "ok" });
			await resuming;
			expect(client.startJobEventStream).toHaveBeenCalledTimes(2);
			if (outcome === "success") {
				oldStream.resolve({
					subscriptionId: "obsolete-subscription",
					jobId: accepted.jobId,
					afterSeq: 0,
				});
			} else {
				oldStream.reject(new Error("obsolete stream start failed"));
			}
			await sendRequest;
			if (outcome === "success") {
				expect(client.stopJobEventStream).toHaveBeenCalledWith(
					"obsolete-subscription",
				);
			} else {
				expect(client.stopJobEventStream).not.toHaveBeenCalled();
			}
			expect(client.fetchJobEventsJson).not.toHaveBeenCalled();
			await store.cancelJob(accepted.jobId);
			expect(client.stopJobEventStream).toHaveBeenLastCalledWith(
				"recovered-subscription",
			);
		},
	);

	test.each([false, true])(
		"retains a send accepted during resume without retaining a completed job (snapshot includes send: %s)",
		async (snapshotIncludesSend) => {
			const sending = deferred<ChatJob>();
			const health = deferred<RuntimeHealth>();
			const previous = job({ jobId: "completed-B", conversationId: "B" });
			const accepted = job({
				jobId: "new-A",
				conversationId: "A",
				hasTimelineSnapshot: true,
			});
			const snapshot = { ...accepted, lastSeq: 3, reply: "newer reply" };
			const client = runtimeClientStub({
				listConversations: vi.fn(async () => ({
					conversations: [conversation({ id: "A" }), conversation({ id: "B" })],
					activeJob: null,
					defaultConversationId: "A",
					virtualUserId: "webchat",
				})),
				getActiveJobs: vi
					.fn()
					.mockResolvedValueOnce({ job: previous, jobs: [previous] })
					.mockResolvedValueOnce({
						job: snapshotIncludesSend ? snapshot : null,
						jobs: snapshotIncludesSend ? [snapshot] : [],
					}),
				sendMessage: vi.fn(() => sending.promise),
			});
			const store = createChatStore({ client });
			await store.bootstrap();
			store.updateDraft("A", "question-A");
			const sendRequest = store.sendSelectedMessage();
			vi.mocked(client.probeRuntime).mockImplementationOnce(
				() => health.promise,
			);
			const resuming = store.bootstrap({
				preserveSelectionId: "A",
				resuming: true,
			});
			await vi.waitFor(() =>
				expect(client.getActiveJobs).toHaveBeenCalledTimes(2),
			);
			sending.resolve(accepted);
			await sendRequest;
			expect(store.getSnapshot().activeJobsByConversation.A?.jobId).toBe(
				"new-A",
			);
			health.resolve({ ok: true, status: 200, body: "ok" });
			await resuming;
			expect(store.getSnapshot().activeJobsByConversation.A).toEqual(
				snapshotIncludesSend ? snapshot : accepted,
			);
			expect(store.getSnapshot().activeJobsByConversation.B).toBeUndefined();
			expect(store.getSnapshot().jobConversationById).toEqual({ "new-A": "A" });
			expect(store.getSnapshot().connectionState).toBe("streaming");
			expect(client.startJobEventStream).toHaveBeenLastCalledWith({
				jobId: "new-A",
				conversationId: "A",
				afterSeq: snapshotIncludesSend ? 3 : 0,
			});
			expect(client.startJobEventStream).toHaveBeenCalledTimes(3);
		},
	);

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
