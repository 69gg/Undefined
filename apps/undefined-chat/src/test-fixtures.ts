import { vi } from "vitest";
import type {
	ApiKeyStatus,
	AttachmentDownloadResult,
	AttachmentPreviewResult,
	ChatEvent,
	ChatJob,
	CommandInfo,
	Conversation,
	EventStreamSubscription,
	HistoryItem,
	RuntimeClient,
	SubcommandInfo,
} from "./runtime-client/types";

export function subcommandInfo(
	overrides: Partial<SubcommandInfo> = {},
): SubcommandInfo {
	return {
		name: "new",
		trigger: "/conv new",
		description: "新建会话",
		args: "[标题]",
		usage: "/conv new [标题]",
		available: true,
		...overrides,
	};
}

export function commandInfo(overrides: Partial<CommandInfo> = {}): CommandInfo {
	// trigger / usage / example 默认按 name 派生，避免遗漏导致搜索文本被默认值污染
	const name = overrides.name ?? "help";
	return {
		name,
		trigger: `/${name}`,
		description: "显示帮助",
		usage: `/${name}`,
		example: `/${name}`,
		aliases: [],
		aliasTriggers: [],
		subcommands: [],
		available: true,
		...overrides,
	};
}

export function conversation(
	overrides: Partial<Conversation> = {},
): Conversation {
	return {
		id: "default",
		title: "默认会话",
		titleSource: "temporary",
		titleStatus: "temporary",
		createdAt: "2026-06-08T10:00:00",
		updatedAt: "2026-06-08T10:00:00",
		virtualUserId: "webchat",
		messageCount: 2,
		isRunning: false,
		...overrides,
	};
}

export function historyItem(overrides: Partial<HistoryItem> = {}): HistoryItem {
	return {
		messageId: `msg-${overrides.role ?? "user"}`,
		role: "user",
		content: "你好",
		timestamp: "2026-06-08T10:00:00",
		attachments: [],
		references: [],
		...overrides,
	};
}

export function job(overrides: Partial<ChatJob> = {}): ChatJob {
	return {
		jobId: "job-1",
		conversationId: "default",
		status: "running",
		mode: "chat",
		createdAt: 1770000000,
		updatedAt: 1770000001,
		finishedAt: null,
		elapsedMs: 1000,
		durationMs: null,
		currentStage: "thinking",
		currentStageDetail: "正在处理",
		currentStageStartedAt: 1770000000,
		currentStageElapsedMs: 1000,
		lastSeq: 0,
		error: null,
		reply: "",
		messages: [],
		currentAgentStages: [],
		currentToolCalls: [],
		historyFinalized: false,
		currentTimeline: [],
		waitingInput: null,
		...overrides,
	};
}

export function event(overrides: Partial<ChatEvent> = {}): ChatEvent {
	return {
		seq: 1,
		event: "stage",
		payload: {
			job_id: "job-1",
			conversation_id: "default",
			stage: "thinking",
		},
		...overrides,
	};
}

export function runtimeClientStub(
	overrides: Partial<RuntimeClient> = {},
): RuntimeClient {
	const apiKeyStatus: ApiKeyStatus = {
		available: true,
		storage: "system-keyring",
		degraded: false,
		keyPreview: "sk-...test",
		detail: "",
	};
	const streamSubscription: EventStreamSubscription = {
		subscriptionId: "sub-1",
		jobId: "job-1",
		afterSeq: 0,
	};
	const downloadResult: AttachmentDownloadResult = {
		status: 200,
		ok: true,
		savedFileName: "note.txt",
		bytesWritten: 12,
		mediaType: "text/plain",
		body: null,
	};
	const previewResult: AttachmentPreviewResult = {
		status: 200,
		ok: true,
		mediaType: "image/png",
		bytes: [137, 80, 78, 71],
		body: null,
	};
	return {
		getRuntimeConfig: vi.fn(async () => ({
			runtimeUrl: "http://127.0.0.1:8788",
			hasApiKey: true,
		})),
		saveRuntimeConfig: vi.fn(async (runtimeUrl: string) => ({
			runtimeUrl,
			hasApiKey: true,
		})),
		saveApiKey: vi.fn(async () => apiKeyStatus),
		confirmInsecureStorageFallback: vi.fn(async () => ({
			...apiKeyStatus,
			storage: "insecure-file",
			degraded: true,
			detail: "Insecure storage fallback confirmed for this app session",
		})),
		loadApiKeyStatus: vi.fn(async () => apiKeyStatus),
		probeRuntime: vi.fn(async () => ({
			ok: true,
			status: 200,
			body: "ok",
		})),
		listConversations: vi.fn(async () => ({
			conversations: [conversation()],
			activeJob: null,
			defaultConversationId: "default",
			virtualUserId: "webchat",
		})),
		createConversation: vi.fn(async (title?: string) =>
			conversation({
				id: title ? "custom" : "new",
				title: title || "新会话",
				messageCount: 0,
			}),
		),
		deleteConversation: vi.fn(async () => undefined),
		renameConversation: vi.fn(async () => ({ ok: true })),
		getHistory: vi.fn(async () => ({
			conversationId: "default",
			virtualUserId: "webchat",
			permission: "superadmin",
			count: 0,
			items: [],
			limit: 50,
			before: null,
			hasMore: false,
			nextBefore: null,
			total: 0,
		})),
		getHistoryPage: vi.fn(async () => ({
			conversationId: "default",
			virtualUserId: "webchat",
			permission: "superadmin",
			count: 0,
			items: [],
			limit: 50,
			before: null,
			hasMore: false,
			nextBefore: null,
			cursor: null,
			total: 0,
		})),
		getActiveJobs: vi.fn(async () => ({
			job: null,
			jobs: [],
		})),
		sendMessage: vi.fn(async () => job()),
		cancelJob: vi.fn(async () => job({ status: "cancelled" })),
		listCommands: vi.fn(async () => ({
			commands: [
				{
					name: "help",
					trigger: "/help",
					description: "显示帮助",
					usage: "/help",
					example: "/help",
					aliases: ["h"],
					aliasTriggers: ["/h"],
					subcommands: [],
					available: true,
				},
				{
					name: "conv",
					trigger: "/conv",
					description: "管理会话",
					usage: "/conv <子命令>",
					example: "/conv new 调试",
					aliases: [],
					aliasTriggers: [],
					available: true,
					subcommands: [
						{
							name: "new",
							trigger: "/conv new",
							description: "新建会话",
							args: "[标题]",
							usage: "/conv new [标题]",
							available: true,
						},
						{
							name: "list",
							trigger: "/conv list",
							description: "列出会话",
							args: "",
							usage: "/conv list",
							available: true,
						},
					],
				},
			],
		})),
		fetchJobEventsJson: vi.fn(async () => ({
			job: job(),
			after: 0,
			lastSeq: 0,
			events: [],
		})),
		startJobEventStream: vi.fn(async () => streamSubscription),
		stopJobEventStream: vi.fn(async () => undefined),
		uploadAttachment: vi.fn(async () => ({
			id: "att-1",
			name: "note.txt",
			size: 12,
			mediaType: "text/plain",
			kind: "file",
			downloadUrl: "/api/v1/chat/attachments/att-1",
			previewUrl: null,
			discarded: false,
		})),
		saveAttachment: vi.fn(async () => downloadResult),
		previewAttachment: vi.fn(async () => previewResult),
		openHtmlPreview: vi.fn(async () => undefined),
		listenRuntimeSse: vi.fn(async () => () => undefined),
		...overrides,
	};
}
