import { invoke } from "@tauri-apps/api/core";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { createTauriRuntimeClient } from "../runtime-client/tauri";
import { event, historyItem, job, runtimeClientStub } from "../test-fixtures";
import { createChatStore } from "./store";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));

function runtimeJob(overrides: Record<string, unknown> = {}) {
	return {
		job_id: "job-1",
		conversation_id: "default",
		status: "running",
		reply: "",
		messages: [],
		last_seq: 0,
		current_tool_calls: [],
		history_finalized: false,
		...overrides,
	};
}

describe("Runtime job contract through the native client", () => {
	beforeEach(() => {
		vi.resetAllMocks();
		vi.useFakeTimers();
	});
	afterEach(() => {
		vi.clearAllTimers();
		vi.useRealTimers();
	});

	test("fallback preserves the timeline and completed calls without double counting snapshot text", async () => {
		const nativeClient = createTauriRuntimeClient();
		const running = job();
		vi.mocked(invoke).mockResolvedValue({
			status: 200,
			ok: true,
			body: {
				job: runtimeJob({
					reply: "你好\n\n世界",
					messages: ["你好", "世界"],
					last_seq: 4,
				}),
				after: 3,
				last_seq: 4,
				events: [
					{
						seq: 4,
						event: "message",
						payload: {
							job_id: "job-1",
							conversation_id: "default",
							content: "世界",
						},
					},
				],
			},
		});
		const client = runtimeClientStub({
			getActiveJobs: vi.fn(async () => ({ job: running, jobs: [running] })),
			fetchJobEventsJson: nativeClient.fetchJobEventsJson,
		});
		const store = createChatStore({ client });
		await store.bootstrap();
		store.applyRuntimeEvents("job-1", [
			event({ seq: 1, event: "message", payload: { content: "你好" } }),
			event({
				seq: 2,
				event: "tool_start",
				payload: { webchat_call_id: "search-1", name: "search" },
			}),
			event({
				seq: 3,
				event: "tool_end",
				payload: {
					webchat_call_id: "search-1",
					ok: true,
					result_preview: "结果",
				},
			}),
		]);
		store.handleRuntimeStatus({
			subscriptionId: "sub-1",
			jobId: "job-1",
			status: "error",
			detail: "SSE disconnected",
		});
		await vi.waitFor(() => {
			expect(store.getSnapshot().activeJobsByConversation.default?.reply).toBe(
				"你好\n\n世界",
			);
		});
		const active = store.getSnapshot().activeJobsByConversation.default;
		expect(active?.currentTimeline).toEqual([
			{ type: "message", seq: 1, content: "你好" },
			{ type: "call", seq: 2, callId: "search-1" },
			{ type: "message", seq: 4, content: "世界" },
		]);
		expect(active?.currentToolCalls[0]).toMatchObject({
			id: "search-1",
			status: "done",
			resultPreview: "结果",
		});
		expect(invoke).toHaveBeenCalledWith("fetch_job_events_json", {
			input: { jobId: "job-1", afterSeq: 3, conversationId: "default" },
		});
		await vi.advanceTimersByTimeAsync(1000);
		expect(store.getSnapshot().activeJobsByConversation.default?.reply).toBe(
			"你好\n\n世界",
		);
		expect(
			store.getSnapshot().activeJobsByConversation.default?.currentTimeline,
		).toEqual(active?.currentTimeline);
	});

	test.each(["sse", "json"])(
		"%s terminal delivery waits for history_finalized before releasing the job and reloading history",
		async (transport) => {
			const nativeClient = createTauriRuntimeClient();
			const running = job();
			const terminalEvent = {
				seq: 1,
				event: "done",
				payload: {
					job_id: "job-1",
					conversation_id: "default",
					status: "done",
				},
			};
			vi.mocked(invoke)
				.mockResolvedValueOnce({
					status: 200,
					ok: true,
					body: {
						job: runtimeJob({ status: "done", last_seq: 1 }),
						events: [terminalEvent],
					},
				})
				.mockResolvedValueOnce({
					status: 200,
					ok: true,
					body: {
						job: runtimeJob({
							status: "done",
							last_seq: 1,
							history_finalized: true,
						}),
						events: [],
					},
				});
			const client = runtimeClientStub({
				getActiveJobs: vi.fn(async () => ({ job: running, jobs: [running] })),
				fetchJobEventsJson: nativeClient.fetchJobEventsJson,
			});
			const store = createChatStore({ client });
			await store.bootstrap();
			if (transport === "sse") {
				store.applyRuntimeEvents("job-1", [terminalEvent]);
				await vi.advanceTimersByTimeAsync(1000);
			} else {
				store.handleRuntimeStatus({
					subscriptionId: "sub-1",
					jobId: "job-1",
					status: "error",
					detail: "closed",
				});
				await vi.waitFor(() => expect(invoke).toHaveBeenCalledTimes(1));
			}
			expect(client.getHistory).toHaveBeenCalledTimes(1);
			expect(store.getSnapshot().jobConversationById["job-1"]).toBe("default");
			expect(
				store.getSnapshot().activeJobsByConversation.default?.historyFinalized,
			).toBe(false);
			store.updateDraft("default", "下一条");
			await store.sendSelectedMessage();
			expect(client.sendMessage).not.toHaveBeenCalled();
			await vi.advanceTimersByTimeAsync(1000);
			expect(client.getHistory).toHaveBeenCalledTimes(2);
			expect(client.stopJobEventStream).toHaveBeenCalledWith("sub-1");
			expect(
				store.getSnapshot().activeJobsByConversation.default,
			).toBeUndefined();
			expect(store.getSnapshot().jobConversationById["job-1"]).toBeUndefined();
			expect(store.getSnapshot().connectionState).toBe("connected");
		},
	);

	test("an accepted message keeps its history and empty draft when native SSE startup rejects", async () => {
		const nativeClient = createTauriRuntimeClient();
		vi.mocked(invoke).mockImplementation(async (command) => {
			if (command === "start_job_event_stream") {
				throw new Error("native subscription failed");
			}
			return {
				status: command === "send_message" ? 202 : 200,
				ok: true,
				body:
					command === "send_message"
						? runtimeJob()
						: { job: runtimeJob(), events: [] },
			};
		});
		const client = runtimeClientStub({
			sendMessage: nativeClient.sendMessage,
			startJobEventStream: nativeClient.startJobEventStream,
			fetchJobEventsJson: nativeClient.fetchJobEventsJson,
		});
		const store = createChatStore({ client });
		await store.bootstrap();
		store.updateDraft("default", "已经发送");
		await store.sendSelectedMessage();
		await vi.waitFor(() =>
			expect(invoke).toHaveBeenCalledWith("fetch_job_events_json", {
				input: { jobId: "job-1", afterSeq: 0, conversationId: "default" },
			}),
		);
		expect(store.getSnapshot().draftsByConversation.default).toBe("");
		expect(store.getSnapshot().sendError).toBeNull();
		expect(store.getSnapshot().connectionState).toBe("json_fallback");
		expect(store.getSnapshot().historyByConversation.default?.items).toEqual([
			expect.objectContaining(
				historyItem({
					content: "已经发送",
					timestamp: expect.any(String),
					messageId: expect.any(String),
				}),
			),
		]);
		expect(store.getSnapshot().activeJobsByConversation.default?.jobId).toBe(
			"job-1",
		);
	});

	test.each(["response", "error"])(
		"ignores a late old-job %s after finalization and a new send",
		async (completion) => {
			const nativeClient = createTauriRuntimeClient();
			let resolveOld!: (value: unknown) => void;
			let rejectOld!: (reason: Error) => void;
			const pending = new Promise((resolve, reject) => {
				resolveOld = resolve;
				rejectOld = reject;
			});
			vi.mocked(invoke)
				.mockReturnValueOnce(pending)
				.mockResolvedValueOnce({
					status: 200,
					ok: true,
					body: {
						job: runtimeJob({
							status: "done",
							last_seq: 1,
							history_finalized: true,
						}),
						events: [],
					},
				});
			const running = job();
			const client = runtimeClientStub({
				getActiveJobs: vi.fn(async () => ({ job: running, jobs: [running] })),
				fetchJobEventsJson: nativeClient.fetchJobEventsJson,
				sendMessage: vi.fn(async () => job({ jobId: "job-new" })),
			});
			const store = createChatStore({ client });
			await store.bootstrap();
			const broken = {
				subscriptionId: "sub-1",
				jobId: "job-1",
				status: "error",
				detail: "closed",
			};
			store.handleRuntimeStatus(broken);
			store.handleRuntimeStatus(broken);
			await vi.waitFor(() =>
				expect(
					store.getSnapshot().activeJobsByConversation.default,
				).toBeUndefined(),
			);
			store.updateDraft("default", "新任务");
			await store.sendSelectedMessage();
			if (completion === "response") {
				resolveOld({
					status: 200,
					ok: true,
					body: { job: runtimeJob(), events: [] },
				});
			} else {
				rejectOld(new Error("old request failed"));
			}
			await vi.advanceTimersByTimeAsync(0);
			expect(store.getSnapshot().activeJobsByConversation.default?.jobId).toBe(
				"job-new",
			);
			expect(store.getSnapshot().jobConversationById["job-1"]).toBeUndefined();
			expect(store.getSnapshot().connectionState).toBe("streaming");
			store.applyRuntimeEvents("job-1", [
				{ seq: 2, event: "done", payload: { conversation_id: "default" } },
			]);
			expect(store.getSnapshot().activeJobsByConversation.default?.jobId).toBe(
				"job-new",
			);
		},
	);

	test("an older concurrent response cannot replace the latest same-job snapshot", async () => {
		const nativeClient = createTauriRuntimeClient();
		let resolveOld!: (value: unknown) => void;
		const pending = new Promise((resolve) => {
			resolveOld = resolve;
		});
		vi.mocked(invoke)
			.mockReturnValueOnce(pending)
			.mockResolvedValueOnce({
				status: 200,
				ok: true,
				body: {
					job: runtimeJob({ reply: "已有\n\n新增", last_seq: 2 }),
					events: [{ seq: 2, event: "message", payload: { content: "新增" } }],
				},
			});
		const running = job();
		const client = runtimeClientStub({
			getActiveJobs: vi.fn(async () => ({ job: running, jobs: [running] })),
			fetchJobEventsJson: nativeClient.fetchJobEventsJson,
		});
		const store = createChatStore({ client });
		await store.bootstrap();
		store.applyRuntimeEvents("job-1", [
			{ seq: 1, event: "message", payload: { content: "已有" } },
		]);
		const broken = {
			subscriptionId: "sub-1",
			jobId: "job-1",
			status: "error",
			detail: "closed",
		};
		store.handleRuntimeStatus(broken);
		store.handleRuntimeStatus(broken);
		await vi.waitFor(() =>
			expect(store.getSnapshot().eventCursorByJob["job-1"]).toBe(2),
		);
		const latest = store.getSnapshot().activeJobsByConversation.default;
		resolveOld({
			status: 200,
			ok: true,
			body: { job: runtimeJob({ reply: "已有", last_seq: 1 }), events: [] },
		});
		await vi.advanceTimersByTimeAsync(0);
		expect(store.getSnapshot().activeJobsByConversation.default).toEqual(
			latest,
		);
		expect(store.getSnapshot().eventCursorByJob["job-1"]).toBe(2);
	});

	test("a snapshot overtaken by SSE keeps the consumed cursor and polls again", async () => {
		const nativeClient = createTauriRuntimeClient();
		let resolveOld!: (value: unknown) => void;
		const pending = new Promise((resolve) => {
			resolveOld = resolve;
		});
		vi.mocked(invoke)
			.mockReturnValueOnce(pending)
			.mockResolvedValueOnce({
				status: 200,
				ok: true,
				body: {
					job: runtimeJob({ reply: "已有\n\n新增", last_seq: 2 }),
					events: [],
				},
			});
		const running = job();
		const client = runtimeClientStub({
			getActiveJobs: vi.fn(async () => ({ job: running, jobs: [running] })),
			fetchJobEventsJson: nativeClient.fetchJobEventsJson,
		});
		const store = createChatStore({ client });
		await store.bootstrap();
		store.applyRuntimeEvents("job-1", [
			{ seq: 1, event: "message", payload: { content: "已有" } },
		]);
		store.handleRuntimeStatus({
			subscriptionId: "sub-1",
			jobId: "job-1",
			status: "error",
			detail: "closed",
		});
		store.applyRuntimeEvents("job-1", [
			{ seq: 2, event: "message", payload: { content: "新增" } },
		]);
		const latest = store.getSnapshot().activeJobsByConversation.default;
		resolveOld({
			status: 200,
			ok: true,
			body: { job: runtimeJob({ reply: "已有", last_seq: 1 }), events: [] },
		});
		await vi.advanceTimersByTimeAsync(0);
		expect(store.getSnapshot().activeJobsByConversation.default).toEqual(
			latest,
		);
		expect(store.getSnapshot().eventCursorByJob["job-1"]).toBe(2);
		await vi.advanceTimersByTimeAsync(1000);
		expect(invoke).toHaveBeenLastCalledWith("fetch_job_events_json", {
			input: { jobId: "job-1", afterSeq: 2, conversationId: "default" },
		});
		expect(store.getSnapshot().activeJobsByConversation.default?.reply).toBe(
			"已有\n\n新增",
		);
		expect(
			store.getSnapshot().activeJobsByConversation.default?.currentTimeline,
		).toEqual(latest?.currentTimeline);
	});

	test("cancellation keeps the real event cursor so its finalized snapshot can finish", async () => {
		const nativeClient = createTauriRuntimeClient();
		vi.mocked(invoke)
			.mockResolvedValueOnce({
				status: 200,
				ok: true,
				body: runtimeJob({ status: "cancelled", last_seq: 4 }),
			})
			.mockResolvedValueOnce({
				status: 200,
				ok: true,
				body: {
					job: runtimeJob({
						status: "cancelled",
						last_seq: 4,
						history_finalized: true,
					}),
					events: [
						{
							seq: 4,
							event: "error",
							payload: {
								job_id: "job-1",
								conversation_id: "default",
								error: "cancelled",
							},
						},
					],
				},
			});
		const running = job();
		const client = runtimeClientStub({
			getActiveJobs: vi.fn(async () => ({ job: running, jobs: [running] })),
			cancelJob: nativeClient.cancelJob,
			fetchJobEventsJson: nativeClient.fetchJobEventsJson,
		});
		const store = createChatStore({ client });
		await store.bootstrap();
		store.applyRuntimeEvents("job-1", [
			{ seq: 3, event: "message", payload: { content: "取消前回复" } },
		]);
		await store.cancelJob("job-1");
		expect(store.getSnapshot().eventCursorByJob["job-1"]).toBe(3);
		expect(store.getSnapshot().activeJobsByConversation.default?.status).toBe(
			"cancelled",
		);
		expect(client.getHistory).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(1000);
		expect(invoke).toHaveBeenLastCalledWith("fetch_job_events_json", {
			input: { jobId: "job-1", afterSeq: 3, conversationId: "default" },
		});
		expect(
			store.getSnapshot().activeJobsByConversation.default,
		).toBeUndefined();
		expect(store.getSnapshot().eventCursorByJob["job-1"]).toBe(4);
		expect(client.getHistory).toHaveBeenCalledTimes(2);
	});
});
