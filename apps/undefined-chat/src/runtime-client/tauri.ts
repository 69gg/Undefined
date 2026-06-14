import { invoke as originalInvoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

function invoke<T>(cmd: string, args?: unknown): Promise<T> {
	if (
		typeof window === "undefined" ||
		!("__TAURI_INTERNALS__" in (window as unknown as Record<string, unknown>))
	) {
		const isTest =
			typeof globalThis !== "undefined" &&
			(globalThis as unknown as Record<string, { env?: { NODE_ENV?: string } }>)
				?.process?.env?.NODE_ENV === "test";
		if (!isTest) {
			throw new Error(
				"请使用 Tauri 启动客户端（在终端运行 npm run tauri:dev）。当前运行在普通浏览器中，无法调用底层 Rust 原生接口。",
			);
		}
	}
	return args === undefined
		? originalInvoke(cmd)
		: // biome-ignore lint/suspicious/noExplicitAny: match original invoke args signature
			originalInvoke(cmd, args as any);
}
import type {
	ActiveJobsResponse,
	AgentStageSnapshot,
	ApiKeyStatus,
	Attachment,
	AttachmentDownloadInput,
	AttachmentDownloadResult,
	AttachmentPreviewInput,
	AttachmentPreviewResult,
	ChatEvent,
	ChatJob,
	CommandInfo,
	CommandsResponse,
	Conversation,
	ConversationsResponse,
	EventStreamSubscription,
	HistoryItem,
	HistoryPageResponse,
	HistoryResponse,
	HistoryWebchat,
	HtmlPreviewInput,
	JobEventsJsonResponse,
	MessageReference,
	RuntimeClient,
	RuntimeConfig,
	RuntimeHealth,
	RuntimeSseEvent,
	RuntimeSseStatus,
	SendMessageInput,
	SubcommandInfo,
	ToolCallSnapshot,
	UploadAttachmentInput,
} from "./types";

type RawRecord = Record<string, unknown>;

function record(value: unknown): RawRecord {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as RawRecord)
		: {};
}

function text(value: unknown, fallback = ""): string {
	return typeof value === "string" ? value : fallback;
}

function numberValue(value: unknown, fallback = 0): number {
	return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function nullableNumber(value: unknown): number | null {
	return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function bool(value: unknown, fallback = false): boolean {
	return typeof value === "boolean" ? value : fallback;
}

function arrayRecords(value: unknown): RawRecord[] {
	return Array.isArray(value)
		? value.filter(
				(item): item is RawRecord =>
					Boolean(item) && typeof item === "object" && !Array.isArray(item),
			)
		: [];
}

function arrayStrings(value: unknown): string[] {
	return Array.isArray(value)
		? value.filter((item): item is string => typeof item === "string")
		: [];
}

function field(raw: RawRecord, camel: string, snake: string): unknown {
	return raw[camel] ?? raw[snake];
}

function parseJsonRecord(textValue: string): RawRecord {
	try {
		return record(JSON.parse(textValue));
	} catch {
		return {};
	}
}

function runtimeErrorMessage(body: unknown, status: number): string {
	const raw = record(body);
	return (
		text(raw.error) ||
		text(raw.message) ||
		text(raw.text) ||
		`Runtime request failed with status ${status}`
	);
}

function unwrapRuntimeBody(value: unknown): unknown {
	const raw = record(value);
	if ("status" in raw && "ok" in raw && "body" in raw) {
		const status = numberValue(raw.status);
		if (!bool(raw.ok)) {
			throw new Error(runtimeErrorMessage(raw.body, status));
		}
		return raw.body;
	}
	return value;
}

function normalizeRuntimeConfig(
	value: unknown,
	apiKeyStatus: ApiKeyStatus,
): RuntimeConfig | null {
	if (value === null || value === undefined) {
		return null;
	}
	const raw = record(value);
	const runtimeUrl = text(field(raw, "runtimeUrl", "runtime_url"));
	if (!runtimeUrl) {
		return null;
	}
	return {
		runtimeUrl,
		hasApiKey: apiKeyStatus.available,
	};
}

function normalizeApiKeyStatus(value: unknown): ApiKeyStatus {
	const raw = record(value);
	return {
		available: bool(raw.available),
		storage: text(raw.storage, "system-keyring"),
		degraded: bool(raw.degraded),
		keyPreview:
			text(field(raw, "keyPreview", "key_preview")) ||
			(text(raw.key_preview) ? text(raw.key_preview) : null),
		detail: text(raw.detail),
	};
}

function normalizeAttachment(value: unknown): Attachment {
	const raw = record(value);
	const id =
		text(raw.id) ||
		text(raw.uid) ||
		text(raw.attachment_id) ||
		text(raw.attachmentId);
	return {
		id,
		name:
			text(raw.name) ||
			text(raw.display_name) ||
			text(raw.displayName) ||
			id ||
			"attachment",
		size: numberValue(raw.size),
		mediaType: text(
			field(raw, "mediaType", "media_type"),
			"application/octet-stream",
		),
		kind: text(raw.kind, "file"),
		downloadUrl: text(field(raw, "downloadUrl", "download_url")) || null,
		previewUrl: text(field(raw, "previewUrl", "preview_url")) || null,
		discarded: bool(raw.discarded),
	};
}

function normalizeReference(value: unknown): MessageReference {
	const raw = record(value);
	return {
		messageId:
			text(field(raw, "messageId", "message_id")) ||
			text(field(raw, "sourceMessageId", "source_message_id")),
		quote: text(raw.quote) || text(field(raw, "selectedText", "selected_text")),
	};
}

function runtimeMessagePayload(input: SendMessageInput): RawRecord {
	return {
		text: input.message.text,
		attachment_ids: input.message.attachmentIds,
		references: input.message.references.map((reference) => ({
			source_message_id: reference.messageId,
			selected_text: reference.quote,
		})),
	};
}

function normalizeEvent(value: unknown): ChatEvent {
	const raw = record(value);
	return {
		seq: numberValue(raw.seq),
		event: text(raw.event, "message"),
		payload: record(raw.payload),
	};
}

function normalizeToolCall(value: unknown): ToolCallSnapshot {
	const raw = record(value);
	return {
		id:
			text(raw.id) ||
			text(raw.webchat_call_id) ||
			text(raw.webchatCallId) ||
			text(raw.name, "tool"),
		name: text(raw.name) || text(raw.api_name) || text(raw.apiName, "tool"),
		status: text(raw.status, "running"),
		elapsedMs: nullableNumber(field(raw, "elapsedMs", "elapsed_ms")),
		durationMs: nullableNumber(field(raw, "durationMs", "duration_ms")),
		detail: text(raw.detail) || text(raw.result_preview) || undefined,
		argumentsPreview:
			text(raw.argumentsPreview) ||
			text(raw.arguments_preview) ||
			text(raw.input) ||
			undefined,
		resultPreview:
			text(raw.resultPreview) ||
			text(raw.result_preview) ||
			text(raw.output) ||
			undefined,
		uiHint: text(raw.uiHint) || text(raw.ui_hint) || undefined,
		currentStage:
			text(raw.currentStage) || text(raw.current_stage) || undefined,
		isAgent: bool(raw.isAgent) || bool(raw.is_agent) || undefined,
		children: arrayRecords(raw.children).map(normalizeToolCall),
		timeline: Array.isArray(raw.timeline) ? raw.timeline : undefined,
	};
}

function normalizeAgentStage(value: unknown): AgentStageSnapshot {
	const raw = record(value);
	return {
		id:
			text(raw.id) ||
			text(raw.webchat_call_id) ||
			text(raw.webchatCallId) ||
			text(raw.agent_name) ||
			text(raw.agentName, "agent"),
		name:
			text(raw.name) || text(raw.agent_name) || text(raw.agentName, "agent"),
		stage: text(raw.stage, "running"),
		status: text(raw.status, "running"),
		elapsedMs: nullableNumber(field(raw, "elapsedMs", "elapsed_ms")),
		detail: text(raw.detail) || undefined,
	};
}

function normalizeJob(value: unknown): ChatJob | null {
	const raw = record(value);
	const jobId = text(field(raw, "jobId", "job_id"));
	if (!jobId) {
		return null;
	}
	return {
		jobId,
		conversationId: text(field(raw, "conversationId", "conversation_id")),
		status: text(raw.status, "queued"),
		mode: text(raw.mode, "chat"),
		createdAt: numberValue(field(raw, "createdAt", "created_at")),
		updatedAt: numberValue(field(raw, "updatedAt", "updated_at")),
		finishedAt: nullableNumber(field(raw, "finishedAt", "finished_at")),
		elapsedMs: numberValue(field(raw, "elapsedMs", "elapsed_ms")),
		durationMs: nullableNumber(field(raw, "durationMs", "duration_ms")),
		currentStage: text(field(raw, "currentStage", "current_stage"), "queued"),
		currentStageDetail:
			text(field(raw, "currentStageDetail", "current_stage_detail")) || null,
		currentStageStartedAt: nullableNumber(
			field(raw, "currentStageStartedAt", "current_stage_started_at"),
		),
		currentStageElapsedMs: nullableNumber(
			field(raw, "currentStageElapsedMs", "current_stage_elapsed_ms"),
		),
		lastSeq: numberValue(field(raw, "lastSeq", "last_seq")),
		error: text(raw.error) || null,
		reply: text(raw.reply),
		messages: arrayStrings(raw.messages),
		currentAgentStages: arrayRecords(
			field(raw, "currentAgentStages", "current_agent_stages"),
		).map(normalizeAgentStage),
		currentToolCalls: arrayRecords(
			field(raw, "currentToolCalls", "current_tool_calls"),
		).map(normalizeToolCall),
		historyFinalized: bool(field(raw, "historyFinalized", "history_finalized")),
		currentTimeline: [],
		waitingInput: field(raw, "waitingInput", "waiting_input") ?? null,
	};
}

function normalizeConversation(value: unknown): Conversation {
	const raw = record(value);
	return {
		id: text(raw.id),
		title: text(raw.title, "默认会话"),
		titleSource: text(field(raw, "titleSource", "title_source")),
		titleStatus: text(field(raw, "titleStatus", "title_status")),
		createdAt: text(field(raw, "createdAt", "created_at")),
		updatedAt: text(field(raw, "updatedAt", "updated_at")),
		virtualUserId: text(field(raw, "virtualUserId", "virtual_user_id")),
		messageCount: numberValue(field(raw, "messageCount", "message_count")),
		isRunning: bool(field(raw, "isRunning", "is_running")),
	};
}

function normalizeWebchat(value: unknown): HistoryWebchat | undefined {
	const raw = record(value);
	if (Object.keys(raw).length === 0) {
		return undefined;
	}
	return {
		displayOnly: bool(field(raw, "displayOnly", "display_only")),
		jobId: text(field(raw, "jobId", "job_id")),
		mode: text(raw.mode),
		status: text(raw.status),
		createdAt:
			(field(raw, "createdAt", "created_at") as number | string | null) ?? null,
		finishedAt:
			(field(raw, "finishedAt", "finished_at") as number | string | null) ??
			null,
		durationMs: nullableNumber(field(raw, "durationMs", "duration_ms")),
		events: arrayRecords(raw.events).map(normalizeEvent),
		calls: Array.isArray(raw.calls) ? raw.calls : [],
		timeline: Array.isArray(raw.timeline) ? raw.timeline : [],
	};
}

function normalizeHistoryItem(value: unknown): HistoryItem {
	const raw = record(value);
	const role = text(raw.role, "user");
	const normalizedRole: HistoryItem["role"] =
		role === "bot" || role === "system" ? role : "user";
	const webchat = normalizeWebchat(raw.webchat);
	return {
		messageId:
			text(field(raw, "messageId", "message_id")) ||
			`${normalizedRole}-${text(raw.timestamp)}-${text(raw.content).length}`,
		role: normalizedRole,
		content: text(raw.content),
		timestamp: text(raw.timestamp),
		attachments: arrayRecords(raw.attachments).map(normalizeAttachment),
		references: arrayRecords(raw.references).map(normalizeReference),
		...(webchat ? { webchat } : {}),
	};
}

function normalizeSubcommand(value: unknown): SubcommandInfo {
	const raw = record(value);
	return {
		name: text(raw.name),
		trigger: text(raw.trigger),
		description: text(raw.description),
		args: text(raw.args),
		usage: text(raw.usage),
		available: bool(raw.available, true),
	};
}

function normalizeCommand(value: unknown): CommandInfo {
	const raw = record(value);
	const name = text(raw.name);
	return {
		name,
		trigger: text(raw.trigger) || `/${name}`,
		description: text(raw.description),
		usage: text(raw.usage),
		example: text(raw.example),
		aliases: arrayStrings(raw.aliases),
		aliasTriggers: arrayStrings(field(raw, "aliasTriggers", "alias_triggers")),
		subcommands: arrayRecords(raw.subcommands).map(normalizeSubcommand),
		available: bool(raw.available, true),
	};
}

function requireJob(value: unknown): ChatJob {
	const normalized = normalizeJob(value);
	if (!normalized) {
		throw new Error("Runtime response did not include a job");
	}
	return normalized;
}

function requireAttachmentFromUpload(value: unknown): Attachment {
	const raw = record(value);
	const status = numberValue(raw.status, 200);
	const body =
		typeof raw.body === "string" ? parseJsonRecord(raw.body) : record(raw.body);
	if (status < 200 || status >= 300) {
		throw new Error(runtimeErrorMessage(body, status));
	}
	const attachment = normalizeAttachment(body.attachment ?? body);
	if (!attachment.id) {
		throw new Error("Runtime upload response did not include an attachment");
	}
	return attachment;
}

function normalizeDownloadResult(value: unknown): AttachmentDownloadResult {
	const raw = record(value);
	return {
		status: numberValue(raw.status),
		ok: bool(raw.ok),
		savedFileName: text(field(raw, "savedFileName", "saved_file_name")) || null,
		bytesWritten: numberValue(field(raw, "bytesWritten", "bytes_written")),
		mediaType: text(field(raw, "mediaType", "media_type")) || null,
		body: text(raw.body) || null,
	};
}

function normalizePreviewResult(value: unknown): AttachmentPreviewResult {
	const raw = record(value);
	return {
		status: numberValue(raw.status),
		ok: bool(raw.ok),
		mediaType: text(field(raw, "mediaType", "media_type")) || null,
		bytes: Array.isArray(raw.bytes)
			? raw.bytes.filter(
					(item): item is number =>
						typeof item === "number" && Number.isInteger(item),
				)
			: [],
		body: text(raw.body) || null,
	};
}

function normalizeSubscription(value: unknown): EventStreamSubscription {
	const raw = record(value);
	return {
		subscriptionId: text(field(raw, "subscriptionId", "subscription_id")),
		jobId: text(field(raw, "jobId", "job_id")),
		afterSeq: numberValue(field(raw, "afterSeq", "after_seq")),
	};
}

export function createTauriRuntimeClient(): RuntimeClient {
	return {
		async getRuntimeConfig(): Promise<RuntimeConfig | null> {
			const [config, apiKeyStatus] = await Promise.all([
				invoke("get_runtime_config"),
				this.loadApiKeyStatus(),
			]);
			return normalizeRuntimeConfig(config, apiKeyStatus);
		},

		async saveRuntimeConfig(runtimeUrl: string): Promise<RuntimeConfig> {
			const [config, apiKeyStatus] = await Promise.all([
				invoke("save_runtime_config", {
					input: { runtimeUrl },
				}),
				this.loadApiKeyStatus(),
			]);
			const normalized = normalizeRuntimeConfig(config, apiKeyStatus);
			if (!normalized) {
				throw new Error("Runtime config response did not include runtimeUrl");
			}
			return normalized;
		},

		async saveApiKey(apiKey: string): Promise<ApiKeyStatus> {
			return normalizeApiKeyStatus(await invoke("save_api_key", { apiKey }));
		},

		async confirmInsecureStorageFallback(): Promise<ApiKeyStatus> {
			return normalizeApiKeyStatus(
				await invoke("confirm_insecure_storage_fallback"),
			);
		},

		async loadApiKeyStatus(): Promise<ApiKeyStatus> {
			return normalizeApiKeyStatus(await invoke("load_api_key_status"));
		},

		async probeRuntime(): Promise<RuntimeHealth> {
			const raw = record(await invoke("probe_runtime"));
			return {
				ok: bool(raw.ok),
				status: numberValue(raw.status),
				body: text(raw.body),
			};
		},

		async listConversations(): Promise<ConversationsResponse> {
			const raw = record(unwrapRuntimeBody(await invoke("list_conversations")));
			return {
				conversations: arrayRecords(raw.conversations).map(
					normalizeConversation,
				),
				activeJob: normalizeJob(field(raw, "activeJob", "active_job")),
				defaultConversationId: text(
					field(raw, "defaultConversationId", "default_conversation_id"),
				),
				virtualUserId: text(field(raw, "virtualUserId", "virtual_user_id")),
			};
		},

		async getHistory(input): Promise<HistoryResponse> {
			const raw = record(
				unwrapRuntimeBody(await invoke("get_history", { input })),
			);
			return {
				conversationId: text(field(raw, "conversationId", "conversation_id")),
				virtualUserId: text(field(raw, "virtualUserId", "virtual_user_id")),
				permission: text(raw.permission),
				count: numberValue(raw.count),
				items: arrayRecords(raw.items).map(normalizeHistoryItem),
				limit: numberValue(raw.limit, input.limit),
				before: nullableNumber(raw.before),
				hasMore: bool(field(raw, "hasMore", "has_more")),
				nextBefore: nullableNumber(field(raw, "nextBefore", "next_before")),
				total: numberValue(raw.total),
			};
		},

		async getHistoryPage(
			conversationId: string,
			before?: number | null,
			limit = 50,
		): Promise<HistoryPageResponse> {
			const input = {
				conversationId,
				limit,
				...(before !== undefined && before !== null ? { before } : {}),
			};
			const raw = record(
				unwrapRuntimeBody(await invoke("get_history", { input })),
			);
			return {
				conversationId: text(field(raw, "conversationId", "conversation_id")),
				virtualUserId: text(field(raw, "virtualUserId", "virtual_user_id")),
				permission: text(raw.permission),
				count: numberValue(raw.count),
				items: arrayRecords(raw.items).map(normalizeHistoryItem),
				limit: numberValue(raw.limit, limit),
				before: nullableNumber(raw.before),
				hasMore: bool(field(raw, "hasMore", "has_more")),
				nextBefore: nullableNumber(field(raw, "nextBefore", "next_before")),
				cursor: nullableNumber(field(raw, "nextBefore", "next_before")),
				total: numberValue(raw.total),
			};
		},

		async getActiveJobs(input = {}): Promise<ActiveJobsResponse> {
			const raw = record(
				unwrapRuntimeBody(await invoke("get_active_jobs", { input })),
			);
			const legacyJob = normalizeJob(raw.job);
			const jobs = arrayRecords(raw.jobs)
				.map(normalizeJob)
				.filter((item): item is ChatJob => item !== null);
			return {
				job: legacyJob,
				jobs: jobs.length > 0 ? jobs : legacyJob ? [legacyJob] : [],
			};
		},

		async sendMessage(input: SendMessageInput): Promise<ChatJob> {
			return requireJob(
				unwrapRuntimeBody(
					await invoke("send_message", {
						input: {
							conversationId: input.conversationId,
							message: runtimeMessagePayload(input),
						},
					}),
				),
			);
		},

		async createConversation(title?: string): Promise<Conversation> {
			const body = title?.trim() ? { title: title.trim() } : {};
			const raw = record(
				unwrapRuntimeBody(
					await invoke("runtime_request", {
						input: {
							method: "POST",
							path: "/api/v1/chat/conversations",
							body,
							headers: [],
						},
					}),
				),
			);
			const conversation = normalizeConversation(raw.conversation ?? raw);
			if (!conversation.id) {
				throw new Error("Runtime response did not include a conversation");
			}
			return conversation;
		},

		async deleteConversation(conversationId: string): Promise<void> {
			// DELETE 不带请求体：Tauri runtime 桥接层仅允许 POST/PATCH 携带 body
			await invoke("runtime_request", {
				input: {
					method: "DELETE",
					path: `/api/v1/chat/conversations/${conversationId}`,
					body: null,
					headers: [],
				},
			});
		},

		async renameConversation(
			conversationId: string,
			title: string,
		): Promise<{ ok: boolean }> {
			const raw = record(
				unwrapRuntimeBody(
					await invoke("runtime_request", {
						input: {
							method: "PATCH",
							path: `/api/v1/chat/conversations/${conversationId}`,
							body: { title },
							headers: [],
						},
					}),
				),
			);
			return { ok: bool(raw.ok, true) };
		},

		async cancelJob(jobId: string): Promise<ChatJob> {
			return requireJob(
				unwrapRuntimeBody(await invoke("cancel_job", { input: { jobId } })),
			);
		},

		async listCommands(): Promise<CommandsResponse> {
			const raw = record(unwrapRuntimeBody(await invoke("list_commands")));
			return {
				commands: arrayRecords(raw.commands).map(normalizeCommand),
			};
		},

		async fetchJobEventsJson(input): Promise<JobEventsJsonResponse> {
			const raw = record(
				unwrapRuntimeBody(await invoke("fetch_job_events_json", { input })),
			);
			return {
				job: requireJob(raw.job),
				after: numberValue(raw.after, input.afterSeq),
				lastSeq: numberValue(field(raw, "lastSeq", "last_seq")),
				events: arrayRecords(raw.events).map(normalizeEvent),
			};
		},

		async startJobEventStream(input): Promise<EventStreamSubscription> {
			return normalizeSubscription(
				await invoke("start_job_event_stream", {
					input: {
						jobId: input.jobId,
						afterSeq: input.afterSeq,
					},
				}),
			);
		},

		async stopJobEventStream(subscriptionId: string): Promise<void> {
			await invoke("stop_job_event_stream", { subscriptionId });
		},

		async uploadAttachment(input: UploadAttachmentInput): Promise<Attachment> {
			return requireAttachmentFromUpload(
				await invoke("upload_attachment_streaming", { input }),
			);
		},

		async saveAttachment(
			input: AttachmentDownloadInput,
		): Promise<AttachmentDownloadResult> {
			return normalizeDownloadResult(
				await invoke("save_attachment", { input }),
			);
		},

		async previewAttachment(
			input: AttachmentPreviewInput,
		): Promise<AttachmentPreviewResult> {
			return normalizePreviewResult(
				await invoke("preview_attachment_bytes", { input }),
			);
		},

		async openHtmlPreview(input: HtmlPreviewInput): Promise<void> {
			await invoke("open_html_preview", { input });
		},

		async listenRuntimeSse(onEvent, onStatus): Promise<() => void> {
			const unlistenEvent = await listen<RuntimeSseEvent>(
				"runtime-sse-event",
				(event) => {
					onEvent(event.payload);
				},
			);
			const unlistenStatus = await listen<RuntimeSseStatus>(
				"runtime-sse-status",
				(event) => {
					onStatus(event.payload);
				},
			);
			return () => {
				unlistenEvent();
				unlistenStatus();
			};
		},
	};
}
