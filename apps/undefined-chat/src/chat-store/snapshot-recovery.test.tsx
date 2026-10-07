import { invoke } from "@tauri-apps/api/core";
import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { MessageTimeline } from "../message-timeline/MessageTimeline";
import { createTauriRuntimeClient } from "../runtime-client/tauri";
import type { ChatJob } from "../runtime-client/types";
import { event, job, runtimeClientStub } from "../test-fixtures";
import { renderWithProviders } from "../test-utils";
import { createChatStore } from "./store";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn() }));

function renderJob(activeJob: ChatJob) {
	return renderWithProviders(
		<MessageTimeline
			items={[]}
			activeJob={activeJob}
			connectionState="streaming"
			hasMoreHistory={false}
			onLoadMoreHistory={vi.fn()}
			onPreviewAttachment={vi.fn()}
			onPreviewHtml={vi.fn()}
			onSaveAttachment={vi.fn()}
		/>,
	);
}

function nativeSnapshot(lastSeq: number) {
	return {
		job_id: "job-1",
		conversation_id: "default",
		status: "running",
		last_seq: lastSeq,
		reply: "Agent before\n\nAgent after\n\nMain answer",
		history_finalized: false,
		current_tool_calls: [
			{
				webchat_call_id: "agent",
				name: "research",
				is_agent: true,
				status: "running",
				current_stage: "thinking",
				current_stage_detail: "Model detail",
				elapsed_ms: 1000,
			},
		],
		current_timeline: [
			{
				type: "call",
				seq: 1,
				call: {
					id: "agent",
					name: "research",
					status: "running",
					is_agent: true,
					children: [{ id: "nested", name: "search", status: "done" }],
					timeline: [
						{ type: "message", seq: 2, content: "Agent before" },
						{
							type: "call",
							seq: 3,
							call: { id: "nested", name: "search", status: "done" },
						},
						{ type: "message", seq: 4, content: "Agent after" },
					],
				},
			},
			{ type: "message", seq: 5, content: "Main answer" },
		],
	};
}

describe("job snapshot recovery", () => {
	beforeEach(() => vi.resetAllMocks());

	test("keeps a legacy snapshot prefix when the next SSE message arrives", async () => {
		const active = job({ lastSeq: 6, reply: "Saved prefix" });
		const store = createChatStore({
			client: runtimeClientStub({
				getActiveJobs: vi.fn(async () => ({ job: active, jobs: [active] })),
			}),
		});
		await store.bootstrap();
		store.applyRuntimeEvents("job-1", [
			event({ seq: 7, event: "message", payload: { content: "Next message" } }),
		]);
		renderJob(store.getSnapshot().activeJobsByConversation.default);
		expect(screen.getByText("Saved prefix")).toBeTruthy();
		expect(screen.getByText("Next message")).toBeTruthy();
	});

	test("cold native snapshots preserve completed tools and nested message order", async () => {
		vi.mocked(invoke).mockResolvedValue({
			status: 200,
			ok: true,
			body: { job: nativeSnapshot(6), jobs: [nativeSnapshot(6)] },
		});
		const native = createTauriRuntimeClient();
		const store = createChatStore({
			client: runtimeClientStub({ getActiveJobs: native.getActiveJobs }),
		});
		await store.bootstrap();
		const active = store.getSnapshot().activeJobsByConversation.default;
		expect(active.currentToolCalls[0]?.children?.[0]?.status).toBe("done");
		expect(store.getSnapshot().eventCursorByJob["job-1"]).toBe(6);
		renderJob(active);
		const agent = screen.getByText("research").closest("details");
		expect(agent).not.toBeNull();
		expect(within(agent as HTMLElement).getByText("Agent before")).toBeTruthy();
		expect(within(agent as HTMLElement).getByText("Agent after")).toBeTruthy();
		expect(screen.getAllByText("Agent before")).toHaveLength(1);
		expect(screen.getByText(/Model detail/)).toBeTruthy();
		const before = screen.getByText("Agent before"),
			search = screen.getByText("search"),
			after = screen.getByText("Agent after");
		expect(
			before.compareDocumentPosition(search) & Node.DOCUMENT_POSITION_FOLLOWING,
		).toBeTruthy();
		expect(
			search.compareDocumentPosition(after) & Node.DOCUMENT_POSITION_FOLLOWING,
		).toBeTruthy();
		expect(agent?.contains(screen.getByText("Main answer"))).toBe(false);
	});

	test.each([false, true])(
		"resume advances the cursor with its accepted snapshot (legacy: %s)",
		async (legacy) => {
			const native = createTauriRuntimeClient();
			let snapshot = nativeSnapshot(6);
			vi.mocked(invoke).mockImplementation(async () => {
				const raw: Record<string, unknown> = { ...snapshot };
				if (legacy) delete raw.current_timeline;
				return { status: 200, ok: true, body: { job: raw, jobs: [raw] } };
			});
			const client = runtimeClientStub({ getActiveJobs: native.getActiveJobs });
			const store = createChatStore({ client });
			await store.bootstrap();
			snapshot = {
				...nativeSnapshot(7),
				reply:
					"Agent before\n\nAgent after\n\nMain answer\n\nSnapshot addition",
				current_timeline: [
					...nativeSnapshot(7).current_timeline,
					{ type: "message", seq: 7, content: "Snapshot addition" },
				],
			};
			await store.bootstrap({ resuming: true });
			expect(client.startJobEventStream).toHaveBeenLastCalledWith({
				jobId: "job-1",
				conversationId: "default",
				afterSeq: 7,
			});
			store.applyRuntimeEvents("job-1", [
				event({
					seq: 7,
					event: "message",
					payload: { content: "Snapshot addition" },
				}),
			]);
			expect(
				store
					.getSnapshot()
					.activeJobsByConversation.default.reply.match(/Snapshot addition/g),
			).toHaveLength(1);
			renderJob(store.getSnapshot().activeJobsByConversation.default);
			expect(screen.getAllByText(/Snapshot addition/)).toHaveLength(1);
		},
	);

	test("streamed agent messages stay in their parent without a duplicated reply fallback", async () => {
		const active = job();
		const store = createChatStore({
			client: runtimeClientStub({
				getActiveJobs: vi.fn(async () => ({ job: active, jobs: [active] })),
			}),
		});
		await store.bootstrap();
		store.applyRuntimeEvents("job-1", [
			event({
				seq: 1,
				event: "agent_start",
				payload: { webchat_call_id: "agent", name: "research", is_agent: true },
			}),
			event({
				seq: 2,
				event: "message",
				payload: {
					content: "Only inside agent",
					parent_webchat_call_id: "agent",
				},
			}),
		]);
		renderJob(store.getSnapshot().activeJobsByConversation.default);
		const agent = screen.getByText("research").closest("details");
		expect(
			within(agent as HTMLElement).getByText("Only inside agent"),
		).toBeTruthy();
		expect(screen.getAllByText("Only inside agent")).toHaveLength(1);
	});

	test("nested streamed agents retain message/call order and do not leak a fallback at the root", async () => {
		const active = job();
		const store = createChatStore({
			client: runtimeClientStub({
				getActiveJobs: vi.fn(async () => ({ job: active, jobs: [active] })),
			}),
		});
		await store.bootstrap();
		store.applyRuntimeEvents("job-1", [
			event({
				seq: 1,
				event: "agent_start",
				payload: { webchat_call_id: "outer", name: "outer", is_agent: true },
			}),
			event({
				seq: 2,
				event: "agent_start",
				payload: {
					webchat_call_id: "inner",
					name: "inner",
					is_agent: true,
					parent_webchat_call_id: "outer",
				},
			}),
			event({
				seq: 3,
				event: "message",
				payload: { content: "Before search", parent_webchat_call_id: "inner" },
			}),
			event({
				seq: 4,
				event: "tool_start",
				payload: {
					webchat_call_id: "search",
					name: "search",
					parent_webchat_call_id: "inner",
				},
			}),
			event({
				seq: 5,
				event: "tool_end",
				payload: {
					webchat_call_id: "search",
					name: "search",
					parent_webchat_call_id: "inner",
					ok: true,
				},
			}),
			event({
				seq: 6,
				event: "message",
				payload: { content: "After search", parent_webchat_call_id: "inner" },
			}),
		]);
		renderJob(store.getSnapshot().activeJobsByConversation.default);
		const inner = screen.getByText("inner").closest("details");
		expect(inner?.contains(screen.getByText("Before search"))).toBe(true);
		expect(inner?.contains(screen.getByText("After search"))).toBe(true);
		expect(screen.getAllByText("Before search")).toHaveLength(1);
		expect(screen.getAllByText("search")).toHaveLength(1);
		expect(
			screen
				.getByText("Before search")
				.compareDocumentPosition(screen.getByText("search")) &
				Node.DOCUMENT_POSITION_FOLLOWING,
		).toBeTruthy();
		expect(
			screen
				.getByText("search")
				.compareDocumentPosition(screen.getByText("After search")) &
				Node.DOCUMENT_POSITION_FOLLOWING,
		).toBeTruthy();
	});

	test("JSON recovery applies the complete snapshot and rejects its duplicated event", async () => {
		vi.mocked(invoke).mockResolvedValue({
			status: 200,
			ok: true,
			body: {
				job: nativeSnapshot(6),
				events: [
					{ seq: 5, event: "message", payload: { content: "Main answer" } },
				],
			},
		});
		const native = createTauriRuntimeClient();
		const active = job();
		const store = createChatStore({
			client: runtimeClientStub({
				getActiveJobs: vi.fn(async () => ({ job: active, jobs: [active] })),
				fetchJobEventsJson: native.fetchJobEventsJson,
			}),
		});
		await store.bootstrap();
		store.handleRuntimeStatus({
			jobId: "job-1",
			subscriptionId: "sub-1",
			status: "error",
			detail: "disconnected",
		});
		await vi.waitFor(() =>
			expect(store.getSnapshot().eventCursorByJob["job-1"]).toBe(6),
		);
		store.applyRuntimeEvents("job-1", [
			event({ seq: 5, event: "message", payload: { content: "Main answer" } }),
		]);
		renderJob(store.getSnapshot().activeJobsByConversation.default);
		expect(screen.getAllByText("Main answer")).toHaveLength(1);
		expect(screen.getAllByText("Agent before")).toHaveLength(1);
		store.suspendRuntime();
	});

	test("legacy JSON snapshots recover message gaps outside the replay buffer", async () => {
		const active = job({ lastSeq: 6, reply: "Prefix", messages: ["Prefix"] });
		const store = createChatStore({
			client: runtimeClientStub({
				getActiveJobs: vi.fn(async () => ({ job: active, jobs: [active] })),
				fetchJobEventsJson: vi.fn(async () => ({
					job: job({
						lastSeq: 9,
						reply: "Prefix\n\nMissing buffered message\n\nLatest",
						messages: ["Prefix", "Missing buffered message", "Latest"],
					}),
					events: [
						event({ seq: 9, event: "message", payload: { content: "Latest" } }),
					],
					after: 6,
					lastSeq: 9,
				})),
			}),
		});
		await store.bootstrap();
		store.handleRuntimeStatus({
			jobId: "job-1",
			subscriptionId: "sub-1",
			status: "error",
			detail: "disconnected",
		});
		await vi.waitFor(() =>
			expect(store.getSnapshot().eventCursorByJob["job-1"]).toBe(9),
		);
		renderJob(store.getSnapshot().activeJobsByConversation.default);
		expect(screen.getByText("Prefix")).toBeTruthy();
		expect(screen.getByText("Missing buffered message")).toBeTruthy();
		expect(screen.getAllByText("Latest")).toHaveLength(1);
		store.suspendRuntime();
	});

	test("a late bootstrap snapshot cannot roll back events consumed while it was loading", async () => {
		const active = job({ lastSeq: 6, reply: "Prefix" });
		let resolveSnapshot!: (value: { job: ChatJob; jobs: ChatJob[] }) => void;
		const client = runtimeClientStub({
			getActiveJobs: vi.fn(async () => ({ job: active, jobs: [active] })),
		});
		const store = createChatStore({ client });
		await store.bootstrap();
		vi.mocked(client.getActiveJobs).mockImplementationOnce(
			() =>
				new Promise((resolve) => {
					resolveSnapshot = resolve;
				}),
		);
		const bootstrap = store.bootstrap({ resuming: true });
		await vi.waitFor(() => expect(resolveSnapshot).toBeDefined());
		store.applyRuntimeEvents("job-1", [
			event({ seq: 8, event: "message", payload: { content: "Newer event" } }),
		]);
		resolveSnapshot({ job: active, jobs: [active] });
		await bootstrap;
		expect(store.getSnapshot().eventCursorByJob["job-1"]).toBe(8);
		expect(client.startJobEventStream).toHaveBeenLastCalledWith({
			jobId: "job-1",
			conversationId: "default",
			afterSeq: 8,
		});
		renderJob(store.getSnapshot().activeJobsByConversation.default);
		expect(screen.getByText("Newer event")).toBeTruthy();
	});

	test("a tool recovered inside a snapshot uses its later streamed completion", async () => {
		const snapshot = nativeSnapshot(6);
		const agent = snapshot.current_timeline[0].call;
		if (!agent) throw new Error("fixture must contain the agent");
		agent.children[0].status = "running";
		const child = agent.timeline[1].call;
		if (!child) throw new Error("fixture must contain the child");
		child.status = "running";
		vi.mocked(invoke).mockResolvedValue({
			status: 200,
			ok: true,
			body: { job: snapshot, jobs: [snapshot] },
		});
		const native = createTauriRuntimeClient();
		const store = createChatStore({
			client: runtimeClientStub({ getActiveJobs: native.getActiveJobs }),
		});
		await store.bootstrap();
		store.applyRuntimeEvents("job-1", [
			event({
				seq: 7,
				event: "tool_end",
				payload: {
					webchat_call_id: "nested",
					parent_webchat_call_id: "agent",
					name: "search",
					ok: true,
					result_preview: "Latest completed result",
				},
			}),
		]);
		renderJob(store.getSnapshot().activeJobsByConversation.default);
		expect(
			screen.getByText("search").closest("details")?.classList.contains("done"),
		).toBe(true);
		expect(screen.getByText("Latest completed result")).toBeTruthy();
		expect(screen.getAllByText("search")).toHaveLength(1);
	});

	test.each([false, true])(
		"an in-flight JSON snapshot cannot overwrite later SSE (complete timeline: %s)",
		async (complete) => {
			let resolveSnapshot!: (value: unknown) => void;
			vi.mocked(invoke).mockImplementation(
				() =>
					new Promise((resolve) => {
						resolveSnapshot = resolve;
					}),
			);
			const native = createTauriRuntimeClient();
			const active = job();
			const store = createChatStore({
				client: runtimeClientStub({
					getActiveJobs: vi.fn(async () => ({ job: active, jobs: [active] })),
					fetchJobEventsJson: native.fetchJobEventsJson,
				}),
			});
			await store.bootstrap();
			store.handleRuntimeStatus({
				jobId: "job-1",
				subscriptionId: "sub-1",
				status: "error",
				detail: "disconnected",
			});
			store.applyRuntimeEvents("job-1", [
				event({
					seq: 8,
					event: "message",
					payload: { content: "Newer SSE message" },
				}),
			]);
			const latest = store.getSnapshot().activeJobsByConversation.default;
			const snapshot: Record<string, unknown> = nativeSnapshot(6);
			if (!complete) delete snapshot.current_timeline;
			resolveSnapshot({
				status: 200,
				ok: true,
				body: { job: snapshot, events: [] },
			});
			await new Promise((resolve) => setTimeout(resolve, 0));
			expect(store.getSnapshot().activeJobsByConversation.default).toEqual(
				latest,
			);
			expect(store.getSnapshot().eventCursorByJob["job-1"]).toBe(8);
			store.suspendRuntime();
		},
	);
});
