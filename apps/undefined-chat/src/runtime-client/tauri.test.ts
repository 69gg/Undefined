import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { createTauriRuntimeClient } from "./tauri";
import type { RuntimeSseEvent, RuntimeSseStatus } from "./types";

vi.mock("@tauri-apps/api/core", () => ({
	invoke: vi.fn(),
}));

vi.mock("@tauri-apps/api/event", () => ({
	listen: vi.fn(),
}));

describe("createTauriRuntimeClient", () => {
	beforeEach(() => {
		vi.resetAllMocks();
	});

	test("normalizes conversation and active job responses from Tauri commands", async () => {
		vi.mocked(invoke).mockResolvedValueOnce({
			status: 200,
			ok: true,
			body: {
				conversations: [
					{
						id: "default",
						title: "默认会话",
						title_source: "temporary",
						title_status: "temporary",
						created_at: "2026-06-08T10:00:00",
						updated_at: "2026-06-08T10:01:00",
						virtual_user_id: "webchat",
						message_count: 2,
						is_running: true,
					},
				],
				active_job: {
					job_id: "job-1",
					conversation_id: "default",
					status: "running",
					mode: "chat",
					created_at: 1770000000,
					updated_at: 1770000001,
					finished_at: null,
					elapsed_ms: 1000,
					duration_ms: null,
					current_stage: "thinking",
					current_stage_detail: "正在处理",
					current_stage_started_at: 1770000000,
					current_stage_elapsed_ms: 1000,
					last_seq: 3,
					error: null,
					reply: "",
					messages: [],
					current_agent_stages: [],
					current_tool_calls: [],
					history_finalized: false,
					waiting_input: null,
				},
				default_conversation_id: "default",
				virtual_user_id: "webchat",
			},
		});

		const client = createTauriRuntimeClient();
		const response = await client.listConversations();

		expect(invoke).toHaveBeenCalledWith("list_conversations");
		expect(response.conversations[0]).toMatchObject({
			id: "default",
			isRunning: true,
			messageCount: 2,
			titleSource: "temporary",
		});
		expect(response.activeJob?.jobId).toBe("job-1");
		expect(response.activeJob?.conversationId).toBe("default");
		expect(response.defaultConversationId).toBe("default");
	});

	test("creates conversations through the generic Runtime request bridge", async () => {
		vi.mocked(invoke).mockResolvedValueOnce({
			status: 201,
			ok: true,
			body: {
				conversation: {
					id: "conv-new",
					title: "排障",
					title_source: "manual",
					title_status: "ready",
					created_at: "2026-06-08T10:00:00",
					updated_at: "2026-06-08T10:00:00",
					virtual_user_id: "webchat",
					message_count: 0,
					is_running: false,
				},
			},
		});

		const client = createTauriRuntimeClient();
		const response = await client.createConversation("排障");

		expect(invoke).toHaveBeenCalledWith("runtime_request", {
			input: {
				method: "POST",
				path: "/api/v1/chat/conversations",
				body: { title: "排障" },
				headers: [],
			},
		});
		expect(response).toMatchObject({
			id: "conv-new",
			title: "排障",
			messageCount: 0,
		});
	});

	test("maps structured messages to the Runtime API payload contract", async () => {
		vi.mocked(invoke).mockResolvedValueOnce({
			status: 202,
			ok: true,
			body: {
				job_id: "job-2",
				conversation_id: "conv-2",
				status: "queued",
				mode: "chat",
				created_at: 1770000002,
				updated_at: 1770000002,
				finished_at: null,
				elapsed_ms: 0,
				duration_ms: null,
				current_stage: "queued",
				current_stage_detail: null,
				current_stage_started_at: null,
				current_stage_elapsed_ms: null,
				last_seq: 0,
				error: null,
				reply: "",
				messages: [],
				current_agent_stages: [],
				current_tool_calls: [],
				history_finalized: false,
				waiting_input: null,
			},
		});

		const client = createTauriRuntimeClient();
		const response = await client.sendMessage({
			conversationId: "conv-2",
			message: {
				text: "解释这段日志",
				attachmentIds: ["att-1"],
				references: [{ messageId: "msg-1", quote: "报错片段" }],
			},
		});

		expect(invoke).toHaveBeenCalledWith("send_message", {
			input: {
				conversationId: "conv-2",
				message: {
					text: "解释这段日志",
					attachment_ids: ["att-1"],
					references: [
						{
							source_message_id: "msg-1",
							selected_text: "报错片段",
						},
					],
				},
			},
		});
		expect(response.jobId).toBe("job-2");
	});

	test("normalizes Runtime history references into UI references", async () => {
		vi.mocked(invoke).mockResolvedValueOnce({
			status: 200,
			ok: true,
			body: {
				conversation_id: "default",
				virtual_user_id: "webchat",
				permission: "superadmin",
				count: 1,
				items: [
					{
						message_id: "msg-2",
						role: "user",
						content: "继续解释",
						timestamp: "2026-06-08T10:00:00+08:00",
						attachments: [],
						references: [
							{
								source_message_id: "msg-1",
								selected_text: "报错片段",
							},
						],
					},
				],
				limit: 50,
				before: null,
				has_more: false,
				next_before: null,
				total: 1,
			},
		});

		const client = createTauriRuntimeClient();
		const response = await client.getHistory({
			conversationId: "default",
			limit: 50,
		});

		expect(response.items[0]?.references).toEqual([
			{
				messageId: "msg-1",
				quote: "报错片段",
			},
		]);
	});

	test("listens for typed runtime SSE events and statuses", async () => {
		const unlistenEvent = vi.fn();
		const unlistenStatus = vi.fn();
		let eventCallback = (_event: { payload: RuntimeSseEvent }): void => {
			throw new Error("event listener was not registered");
		};
		let statusCallback = (_event: { payload: RuntimeSseStatus }): void => {
			throw new Error("status listener was not registered");
		};
		vi.mocked(listen).mockImplementation(async (eventName, handler) => {
			if (eventName === "runtime-sse-event") {
				eventCallback = handler as (event: {
					payload: RuntimeSseEvent;
				}) => void;
				return unlistenEvent;
			}
			statusCallback = handler as (event: {
				payload: RuntimeSseStatus;
			}) => void;
			return unlistenStatus;
		});
		const onEvent = vi.fn();
		const onStatus = vi.fn();

		const client = createTauriRuntimeClient();
		const stop = await client.listenRuntimeSse(onEvent, onStatus);
		eventCallback({
			payload: {
				jobId: "job-1",
				seq: 1,
				eventType: "stage",
				payload: { stage: "thinking" },
				subscriptionId: "sub-1",
			},
		});
		statusCallback({
			payload: {
				jobId: "job-1",
				status: "connected",
				detail: null,
				subscriptionId: "sub-1",
			},
		});
		stop();

		expect(listen).toHaveBeenCalledWith(
			"runtime-sse-event",
			expect.any(Function),
		);
		expect(listen).toHaveBeenCalledWith(
			"runtime-sse-status",
			expect.any(Function),
		);
		expect(onEvent).toHaveBeenCalledWith({
			jobId: "job-1",
			seq: 1,
			eventType: "stage",
			payload: { stage: "thinking" },
			subscriptionId: "sub-1",
		});
		expect(onStatus).toHaveBeenCalledWith({
			jobId: "job-1",
			status: "connected",
			detail: null,
			subscriptionId: "sub-1",
		});
		expect(unlistenEvent).toHaveBeenCalledOnce();
		expect(unlistenStatus).toHaveBeenCalledOnce();
	});
});
