import { describe, expect, test, vi } from "vitest";
import {
	conversation,
	event,
	historyItem,
	job,
	runtimeClientStub,
} from "../test-fixtures";
import {
	chatReducer,
	createChatStore,
	createInitialChatState,
	parseSseChunk,
} from "./store";

describe("chat store", () => {
	afterEach(() => {
		vi.useRealTimers();
	});

	test("bootstraps config, health, conversations, active jobs, commands, and selected history", async () => {
		const activeJob = job({ jobId: "job-running", conversationId: "default" });
		const client = runtimeClientStub({
			listConversations: vi.fn(async () => ({
				conversations: [
					conversation({ id: "default", title: "默认会话" }),
					conversation({ id: "ops", title: "运维", messageCount: 4 }),
				],
				activeJob,
				defaultConversationId: "default",
				virtualUserId: "webchat",
			})),
			getActiveJobs: vi.fn(async () => ({
				job: activeJob,
				jobs: [activeJob],
			})),
			getHistory: vi.fn(async () => ({
				conversationId: "default",
				virtualUserId: "webchat",
				permission: "superadmin",
				count: 2,
				items: [
					historyItem({
						messageId: "u-1",
						role: "user",
						content: "帮我总结",
					}),
					historyItem({
						messageId: "b-1",
						role: "bot",
						content: "可以。",
					}),
				],
				limit: 50,
				before: null,
				hasMore: false,
				nextBefore: null,
				total: 2,
			})),
		});

		const store = createChatStore({ client });
		await store.bootstrap();
		const state = store.getSnapshot();

		expect(state.runtimeConfig?.runtimeUrl).toBe("http://127.0.0.1:8788");
		expect(state.health?.ok).toBe(true);
		expect(state.connectionState).toBe("streaming");
		expect(state.conversations.map((item) => item.id)).toEqual([
			"default",
			"ops",
		]);
		expect(state.selectedConversationId).toBe("default");
		expect(state.activeJobsByConversation.default?.jobId).toBe("job-running");
		expect(state.historyByConversation.default?.items).toHaveLength(2);
		expect(state.commands[0]?.name).toBe("help");
		expect(state.commands[1]?.subcommands.map((item) => item.name)).toEqual([
			"new",
			"list",
		]);
		expect(client.getHistory).toHaveBeenCalledWith({
			conversationId: "default",
			limit: 50,
		});
	});

	test("blocks send only for the selected conversation when that conversation is running", async () => {
		const opsJob = job({ jobId: "job-ops", conversationId: "ops" });
		const client = runtimeClientStub({
			listConversations: vi.fn(async () => ({
				conversations: [
					conversation({ id: "default", title: "默认会话" }),
					conversation({ id: "ops", title: "运维" }),
				],
				activeJob: opsJob,
				defaultConversationId: "default",
				virtualUserId: "webchat",
			})),
			getActiveJobs: vi.fn(async () => ({
				job: opsJob,
				jobs: [opsJob],
			})),
		});
		const store = createChatStore({ client });
		await store.bootstrap();

		store.updateDraft("default", "默认会话可以发送");
		await store.sendSelectedMessage();
		expect(client.sendMessage).toHaveBeenCalledWith({
			conversationId: "default",
			message: {
				text: "默认会话可以发送",
				attachmentIds: [],
				references: [],
			},
		});

		await store.selectConversation("ops");
		store.updateDraft("ops", "这条应该被锁住");
		await store.sendSelectedMessage();

		expect(client.sendMessage).toHaveBeenCalledTimes(1);
		expect(store.getSnapshot().sendError).toBe("当前会话仍在运行");
	});

	test("handles connection states through reducer actions", () => {
		let state = createInitialChatState();

		for (const status of [
			"connecting",
			"connected",
			"streaming",
			"resuming",
			"json_fallback",
			"disconnected",
		] as const) {
			state = chatReducer(state, {
				type: "connection/set",
				connectionState: status,
			});
			expect(state.connectionState).toBe(status);
		}
	});

	test("parses SSE chunks and applies job events by seq without duplicating after reconnect", async () => {
		expect(
			parseSseChunk(
				'event: stage\nid: 7\ndata: {"job_id":"job-1","stage":"thinking"}\n\n',
			),
		).toEqual([
			{
				seq: 7,
				event: "stage",
				payload: {
					job_id: "job-1",
					stage: "thinking",
				},
			},
		]);

		const runningJob = job({ jobId: "job-1", conversationId: "default" });
		const client = runtimeClientStub({
			getActiveJobs: vi.fn(async () => ({
				job: runningJob,
				jobs: [runningJob],
			})),
		});
		const store = createChatStore({ client });
		await store.bootstrap();

		store.applyRuntimeEvents("job-1", [
			event({
				seq: 1,
				event: "stage",
				payload: { job_id: "job-1", stage: "thinking" },
			}),
			event({
				seq: 1,
				event: "stage",
				payload: { job_id: "job-1", stage: "thinking" },
			}),
			event({
				seq: 2,
				event: "tool_start",
				payload: { job_id: "job-1", name: "group.get_member_info" },
			}),
		]);

		const state = store.getSnapshot();
		expect(state.eventCursorByJob["job-1"]).toBe(2);
		expect(state.eventsByJob["job-1"]).toHaveLength(2);
		expect(state.eventsByJob["job-1"]?.map((item) => item.event)).toEqual([
			"stage",
			"tool_start",
		]);
	});

	test("applyRuntimeEvents consumes tool_start/tool_end to update currentToolCalls in real time", async () => {
		const runningJob = job({ jobId: "job-1", conversationId: "default" });
		const client = runtimeClientStub({
			getActiveJobs: vi.fn(async () => ({
				job: runningJob,
				jobs: [runningJob],
			})),
		});
		const store = createChatStore({ client });
		await store.bootstrap();

		store.applyRuntimeEvents("job-1", [
			event({
				seq: 1,
				event: "tool_start",
				payload: {
					job_id: "job-1",
					webchat_call_id: "call-1",
					name: "search",
					arguments_preview: '{"q":"新闻"}',
				},
			}),
			event({
				seq: 2,
				event: "tool_end",
				payload: {
					job_id: "job-1",
					webchat_call_id: "call-1",
					ok: true,
					result_preview: "搜索结果",
				},
			}),
		]);

		const state = store.getSnapshot();
		const activeJob = state.activeJobsByConversation.default;
		expect(activeJob).toBeTruthy();
		expect(activeJob?.currentToolCalls).toHaveLength(1);
		expect(activeJob?.currentToolCalls[0]?.name).toBe("search");
		expect(activeJob?.currentToolCalls[0]?.status).toBe("done");
		expect(activeJob?.currentToolCalls[0]?.argumentsPreview).toBe(
			'{"q":"新闻"}',
		);
		expect(activeJob?.currentToolCalls[0]?.resultPreview).toBe("搜索结果");
	});

	test("applyRuntimeEvents maintains currentTimeline in event-arrival order (message/call interleaved)", async () => {
		const runningJob = job({ jobId: "job-1", conversationId: "default" });
		const client = runtimeClientStub({
			getActiveJobs: vi.fn(async () => ({
				job: runningJob,
				jobs: [runningJob],
			})),
		});
		const store = createChatStore({ client });
		await store.bootstrap();

		store.applyRuntimeEvents("job-1", [
			event({
				seq: 1,
				event: "message",
				payload: { job_id: "job-1", content: "先说一句" },
			}),
			event({
				seq: 2,
				event: "tool_start",
				payload: {
					job_id: "job-1",
					webchat_call_id: "call-1",
					name: "search",
				},
			}),
			event({
				seq: 3,
				event: "message",
				payload: { job_id: "job-1", content: "再说一句" },
			}),
			event({
				seq: 4,
				event: "tool_end",
				payload: {
					job_id: "job-1",
					webchat_call_id: "call-1",
					ok: true,
					result_preview: "结果",
				},
			}),
		]);

		const state = store.getSnapshot();
		const activeJob = state.activeJobsByConversation.default;
		// currentTimeline 按事件到达顺序交错：message → call → message（tool_end 不再 push）
		expect(activeJob?.currentTimeline).toEqual([
			{ type: "message", seq: 1, content: "先说一句" },
			{ type: "call", seq: 2, callId: "call-1" },
			{ type: "message", seq: 3, content: "再说一句" },
		]);
	});

	test("applyRuntimeEvents dedupes events by seq (no duplicate accumulation on fallback/reconnect)", async () => {
		const runningJob = job({ jobId: "job-1", conversationId: "default" });
		const client = runtimeClientStub({
			getActiveJobs: vi.fn(async () => ({
				job: runningJob,
				jobs: [runningJob],
			})),
		});
		const store = createChatStore({ client });
		await store.bootstrap();

		// 第一次：处理 message seq 1
		store.applyRuntimeEvents("job-1", [
			event({
				seq: 1,
				event: "message",
				payload: { job_id: "job-1", content: "你好" },
			}),
		]);
		// 第二次（模拟 JSON fallback / SSE 重连重发）：含已处理的 seq 1 + 新 seq 2
		store.applyRuntimeEvents("job-1", [
			event({
				seq: 1,
				event: "message",
				payload: { job_id: "job-1", content: "你好" },
			}),
			event({
				seq: 2,
				event: "message",
				payload: { job_id: "job-1", content: "世界" },
			}),
		]);

		const state = store.getSnapshot();
		const activeJob = state.activeJobsByConversation.default;
		// seq 1 不重复累积；currentTimeline 与 reply 仅各含一次
		expect(activeJob?.currentTimeline).toEqual([
			{ type: "message", seq: 1, content: "你好" },
			{ type: "message", seq: 2, content: "世界" },
		]);
		expect(activeJob?.reply).toBe("你好世界");
	});

	test("continues JSON fallback polling until an SSE-broken job reaches terminal state", async () => {
		vi.useFakeTimers();
		const runningJob = job({ jobId: "job-1", conversationId: "default" });
		const doneJob = job({
			jobId: "job-1",
			conversationId: "default",
			status: "done",
			lastSeq: 2,
		});
		const client = runtimeClientStub({
			getActiveJobs: vi.fn(async () => ({
				job: runningJob,
				jobs: [runningJob],
			})),
			fetchJobEventsJson: vi
				.fn()
				.mockResolvedValueOnce({
					job: runningJob,
					after: 0,
					lastSeq: 1,
					events: [
						event({
							seq: 1,
							event: "stage",
							payload: { job_id: "job-1", stage: "thinking" },
						}),
					],
				})
				.mockResolvedValueOnce({
					job: doneJob,
					after: 1,
					lastSeq: 2,
					events: [
						event({
							seq: 2,
							event: "done",
							payload: {
								job_id: "job-1",
								conversation_id: "default",
							},
						}),
					],
				}),
		});
		const store = createChatStore({ client });
		await store.bootstrap();

		store.handleRuntimeStatus({
			subscriptionId: "sub-1",
			jobId: "job-1",
			status: "error",
			detail: "stream closed",
		});
		await vi.waitFor(() => {
			expect(client.fetchJobEventsJson).toHaveBeenCalledTimes(1);
		});
		expect(store.getSnapshot().connectionState).toBe("json_fallback");

		await vi.advanceTimersByTimeAsync(1200);
		await vi.waitFor(() => {
			expect(client.fetchJobEventsJson).toHaveBeenCalledTimes(2);
		});

		expect(
			store.getSnapshot().activeJobsByConversation.default,
		).toBeUndefined();
		expect(store.getSnapshot().connectionState).toBe("connected");
		expect(client.getHistory).toHaveBeenLastCalledWith({
			conversationId: "default",
			limit: 50,
		});
	});

	test("deleteConversation removes the conversation and selects the next one", async () => {
		const client = runtimeClientStub({
			listConversations: vi.fn(async () => ({
				conversations: [
					conversation({ id: "default", title: "默认会话" }),
					conversation({ id: "ops", title: "运维" }),
				],
				activeJob: null,
				defaultConversationId: "default",
				virtualUserId: "webchat",
			})),
		});
		const store = createChatStore({ client });
		await store.bootstrap();
		expect(store.getSnapshot().selectedConversationId).toBe("default");

		await store.deleteConversation("default");

		expect(client.deleteConversation).toHaveBeenCalledWith("default");
		const state = store.getSnapshot();
		expect(state.conversations.map((item) => item.id)).toEqual(["ops"]);
		expect(state.selectedConversationId).toBe("ops");
		expect(state.historyByConversation.default).toBeUndefined();
	});

	test("createConversation toggles creatingConversation around the request", async () => {
		let resolveCreate!: (value: ReturnType<typeof conversation>) => void;
		const client = runtimeClientStub({
			createConversation: vi.fn(
				() =>
					new Promise<ReturnType<typeof conversation>>((resolve) => {
						resolveCreate = resolve;
					}),
			),
		});
		const store = createChatStore({ client });
		await store.bootstrap();

		const pending = store.createConversation();
		expect(store.getSnapshot().creatingConversation).toBe(true);

		resolveCreate(
			conversation({ id: "new", title: "新会话", messageCount: 0 }),
		);
		await pending;
		expect(store.getSnapshot().creatingConversation).toBe(false);
		expect(store.getSnapshot().selectedConversationId).toBe("new");
	});

	test("history/loading then history/set toggles the loading flag", () => {
		let state = createInitialChatState();
		state = chatReducer(state, {
			type: "history/loading",
			conversationId: "c1",
		});
		expect(state.historyByConversation.c1?.loading).toBe(true);
		state = chatReducer(state, {
			type: "history/set",
			conversationId: "c1",
			items: [],
			hasMore: false,
			nextBefore: null,
			total: 0,
		});
		expect(state.historyByConversation.c1?.loading).toBe(false);
	});

	test("sendSelectedMessage 立即乐观显示用户消息并清空草稿、出现 AI 任务", async () => {
		const client = runtimeClientStub();
		const store = createChatStore({ client });
		await store.bootstrap();

		store.updateDraft("default", "你好，实时显示");
		await store.sendSelectedMessage();

		const state = store.getSnapshot();
		const items = state.historyByConversation.default?.items ?? [];
		// 用户消息立即出现在历史中（乐观渲染）
		expect(
			items.some(
				(item) => item.role === "user" && item.content === "你好，实时显示",
			),
		).toBe(true);
		// 草稿被清空
		expect(state.draftsByConversation.default).toBe("");
		// 出现进行中的 AI 任务（驱动实时任务框）
		expect(state.activeJobsByConversation.default).toBeDefined();
		expect(client.sendMessage).toHaveBeenCalledWith({
			conversationId: "default",
			message: { text: "你好，实时显示", attachmentIds: [], references: [] },
		});
	});

	test("sendSelectedMessage 发送失败时回滚乐观消息并恢复草稿", async () => {
		const client = runtimeClientStub({
			sendMessage: vi.fn(async () => {
				throw new Error("发送失败");
			}),
		});
		const store = createChatStore({ client });
		await store.bootstrap();

		store.updateDraft("default", "会失败的消息");
		await store.sendSelectedMessage();

		const state = store.getSnapshot();
		const items = state.historyByConversation.default?.items ?? [];
		// 乐观消息已移除
		expect(items.some((item) => item.content === "会失败的消息")).toBe(false);
		// 草稿恢复
		expect(state.draftsByConversation.default).toBe("会失败的消息");
		expect(state.sendError).toBe("发送失败");
	});
});
