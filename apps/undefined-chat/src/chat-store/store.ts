import type {
	HistoryItem,
	RuntimeClient,
	RuntimeSseEvent,
	RuntimeSseStatus,
	SendMessageInput,
	ToolCallSnapshot,
} from "../runtime-client/types";
import type {
	ChatAction,
	ChatEvent,
	ChatJob,
	ChatState,
	MessageReference,
} from "./types";

export type {
	AttachmentDraft,
	ChatAction,
	ChatEvent,
	ChatJob,
	ChatState,
	MessageReference,
	ToolBlock,
} from "./types";

export type ChatStore = {
	bootstrap: () => Promise<void>;
	createConversation: (title?: string) => Promise<void>;
	deleteConversation: (conversationId: string) => Promise<void>;
	renameConversation: (
		conversationId: string,
		newTitle: string,
	) => Promise<void>;
	selectConversation: (conversationId: string) => Promise<void>;
	updateDraft: (conversationId: string, draft: string) => void;
	sendSelectedMessage: () => Promise<void>;
	addAttachmentPath: (
		conversationId: string,
		filePath: string,
	) => Promise<void>;
	addReference: (conversationId: string, reference: MessageReference) => void;
	addReferenceFromMessageId: (
		conversationId: string,
		messageId: string,
	) => void;
	clearReference: (conversationId: string, messageId: string) => void;
	clearAttachment: (conversationId: string, attachmentId: string) => void;
	loadMoreHistory: (conversationId: string) => Promise<void>;
	reloadHistory: (conversationId: string) => Promise<void>;
	applyRuntimeEvents: (jobId: string, events: ChatEvent[]) => void;
	handleRuntimeEvent: (event: RuntimeSseEvent) => void;
	handleRuntimeStatus: (status: RuntimeSseStatus) => void;
	dispatch: (action: ChatAction) => void;
	getSnapshot: () => ChatState;
	subscribe: (listener: () => void) => () => void;
};

const HISTORY_LIMIT = 50;
const JSON_FALLBACK_POLL_MS = 1000;
const TERMINAL_EVENTS = new Set(["done", "error", "cancelled"]);

export function createInitialChatState(): ChatState {
	return {
		connectionState: "idle",
		runtimeConfig: null,
		health: null,
		conversations: [],
		selectedConversationId: null,
		historyByConversation: {},
		creatingConversation: false,
		activeJobsByConversation: {},
		eventsByJob: {},
		eventCursorByJob: {},
		jobConversationById: {},
		toolBlocksByJob: {},
		draftsByConversation: {},
		attachmentsByConversation: {},
		referencesByConversation: {},
		commands: [],
		commandPaletteOpen: false,
		commandPaletteQuery: "",
		commandPaletteActiveIndex: 0,
		imageViewer: null,
		htmlPreview: null,
		autoScrollEnabled: true,
		topLoadSuppressedUntil: 0,
		platform: null,
		settings: {
			locale: "zh-CN",
			mobilePanel: "chat",
		},
		bootstrapping: false,
		error: null,
		sendError: null,
	};
}

function activeJobsByConversation(jobs: ChatJob[]): Record<string, ChatJob> {
	return Object.fromEntries(
		jobs
			.filter((item) => isJobRunning(item))
			.map((item) => [item.conversationId, item]),
	);
}

function jobConversationById(jobs: ChatJob[]): Record<string, string> {
	return Object.fromEntries(
		jobs.map((item) => [item.jobId, item.conversationId]),
	);
}

function withoutConversationJob(
	state: ChatState,
	conversationId: string,
	jobId: string,
): Pick<ChatState, "activeJobsByConversation" | "jobConversationById"> {
	const activeJobs = { ...state.activeJobsByConversation };
	const jobConversations = { ...state.jobConversationById };
	if (activeJobs[conversationId]?.jobId === jobId) {
		delete activeJobs[conversationId];
	}
	delete jobConversations[jobId];
	return {
		activeJobsByConversation: activeJobs,
		jobConversationById: jobConversations,
	};
}

export function isJobRunning(job: ChatJob | null | undefined): boolean {
	return Boolean(
		job && !["done", "error", "cancelled"].includes(job.status.toLowerCase()),
	);
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
	switch (action.type) {
		case "connection/set":
			return { ...state, connectionState: action.connectionState };
		case "bootstrap/start":
			return {
				...state,
				bootstrapping: true,
				connectionState: "connecting",
				error: null,
			};
		case "bootstrap/success": {
			const activeJobs = activeJobsByConversation(action.activeJobs);
			return {
				...state,
				bootstrapping: false,
				connectionState:
					action.activeJobs.length > 0 ? "streaming" : "connected",
				runtimeConfig: action.runtimeConfig,
				health: action.health,
				conversations: action.conversations.map((item) => ({
					...item,
					isRunning: Boolean(activeJobs[item.id]),
				})),
				selectedConversationId: action.selectedConversationId,
				activeJobsByConversation: activeJobs,
				jobConversationById: jobConversationById(action.activeJobs),
				commands: action.commands,
				error: null,
			};
		}
		case "bootstrap/error":
			return {
				...state,
				bootstrapping: false,
				connectionState: "disconnected",
				runtimeConfig: action.runtimeConfig ?? state.runtimeConfig,
				error: action.error,
			};
		case "history/loading": {
			const existing = state.historyByConversation[action.conversationId];
			return {
				...state,
				historyByConversation: {
					...state.historyByConversation,
					[action.conversationId]: {
						items: existing?.items ?? [],
						hasMore: existing?.hasMore ?? false,
						nextBefore: existing?.nextBefore ?? null,
						total: existing?.total ?? 0,
						loading: true,
						error: null,
					},
				},
			};
		}
		case "history/error": {
			const existing = state.historyByConversation[action.conversationId];
			return {
				...state,
				historyByConversation: {
					...state.historyByConversation,
					[action.conversationId]: {
						items: existing?.items ?? [],
						hasMore: existing?.hasMore ?? false,
						nextBefore: existing?.nextBefore ?? null,
						total: existing?.total ?? 0,
						loading: false,
						error: action.error,
					},
				},
			};
		}
		case "history/set":
			return {
				...state,
				historyByConversation: {
					...state.historyByConversation,
					[action.conversationId]: {
						items: action.items,
						hasMore: action.hasMore,
						nextBefore: action.nextBefore,
						total: action.total,
						loading: false,
						error: null,
					},
				},
			};
		case "message/optimisticUser": {
			const existing = state.historyByConversation[action.conversationId];
			return {
				...state,
				historyByConversation: {
					...state.historyByConversation,
					[action.conversationId]: {
						items: [...(existing?.items ?? []), action.item],
						hasMore: existing?.hasMore ?? false,
						nextBefore: existing?.nextBefore ?? null,
						total: (existing?.total ?? 0) + 1,
						loading: false,
						error: null,
					},
				},
			};
		}
		case "conversation/select":
			return {
				...state,
				selectedConversationId: action.conversationId,
				settings: { ...state.settings, mobilePanel: "chat" },
				sendError: null,
			};
		case "conversation/upsert": {
			const exists = state.conversations.some(
				(item) => item.id === action.conversation.id,
			);
			return {
				...state,
				conversations: exists
					? state.conversations.map((item) =>
							item.id === action.conversation.id ? action.conversation : item,
						)
					: [action.conversation, ...state.conversations],
				selectedConversationId: action.conversation.id,
				settings: { ...state.settings, mobilePanel: "chat" },
			};
		}
		case "conversation/creating":
			return { ...state, creatingConversation: action.creating };
		case "conversation/remove": {
			const conversations = state.conversations.filter(
				(item) => item.id !== action.conversationId,
			);
			const historyByConversation = { ...state.historyByConversation };
			delete historyByConversation[action.conversationId];
			const draftsByConversation = { ...state.draftsByConversation };
			delete draftsByConversation[action.conversationId];
			const attachmentsByConversation = {
				...state.attachmentsByConversation,
			};
			delete attachmentsByConversation[action.conversationId];
			const referencesByConversation = {
				...state.referencesByConversation,
			};
			delete referencesByConversation[action.conversationId];
			return {
				...state,
				conversations,
				historyByConversation,
				draftsByConversation,
				attachmentsByConversation,
				referencesByConversation,
				selectedConversationId:
					state.selectedConversationId === action.conversationId
						? action.nextSelectedId
						: state.selectedConversationId,
			};
		}
		case "draft/set":
			return {
				...state,
				draftsByConversation: {
					...state.draftsByConversation,
					[action.conversationId]: action.draft,
				},
			};
		case "send/error":
			return { ...state, sendError: action.error };
		case "job/upsert": {
			const activeJobs = { ...state.activeJobsByConversation };
			const jobConversations = {
				...state.jobConversationById,
				[action.job.jobId]: action.job.conversationId,
			};
			if (isJobRunning(action.job)) {
				activeJobs[action.job.conversationId] = action.job;
			} else {
				delete activeJobs[action.job.conversationId];
				delete jobConversations[action.job.jobId];
			}
			return {
				...state,
				activeJobsByConversation: activeJobs,
				jobConversationById: jobConversations,
				conversations: state.conversations.map((item) =>
					item.id === action.job.conversationId
						? { ...item, isRunning: isJobRunning(action.job) }
						: item,
				),
			};
		}
		case "job/remove": {
			const removed = withoutConversationJob(
				state,
				action.conversationId,
				action.jobId,
			);
			return {
				...state,
				...removed,
				conversations: state.conversations.map((item) =>
					item.id === action.conversationId
						? { ...item, isRunning: false }
						: item,
				),
			};
		}
		case "events/apply": {
			const cursor = state.eventCursorByJob[action.jobId] ?? 0;
			const seenSeqs = new Set<number>();
			const nextEvents = action.events
				.filter((item) => {
					if (item.seq <= cursor || seenSeqs.has(item.seq)) {
						return false;
					}
					seenSeqs.add(item.seq);
					return true;
				})
				.sort((left, right) => left.seq - right.seq);
			if (nextEvents.length === 0) {
				return state;
			}
			const lastSeq = nextEvents[nextEvents.length - 1]?.seq ?? cursor;
			return {
				...state,
				eventCursorByJob: {
					...state.eventCursorByJob,
					[action.jobId]: lastSeq,
				},
				eventsByJob: {
					...state.eventsByJob,
					[action.jobId]: [
						...(state.eventsByJob[action.jobId] ?? []),
						...nextEvents,
					],
				},
			};
		}
		case "attachments/set":
			return {
				...state,
				attachmentsByConversation: {
					...state.attachmentsByConversation,
					[action.conversationId]: action.attachments,
				},
			};
		case "references/set":
			return {
				...state,
				referencesByConversation: {
					...state.referencesByConversation,
					[action.conversationId]: action.references,
				},
			};
		case "mobile-panel/set":
			return {
				...state,
				settings: { ...state.settings, mobilePanel: action.panel },
			};
		case "toolBlock/upsert": {
			const blockMap = state.toolBlocksByJob[action.jobId] || new Map();
			const updatedMap = new Map(blockMap);
			updatedMap.set(action.toolBlock.webchatCallId, action.toolBlock);
			return {
				...state,
				toolBlocksByJob: {
					...state.toolBlocksByJob,
					[action.jobId]: updatedMap,
				},
			};
		}
		case "toolBlock/clear": {
			const { [action.jobId]: _, ...remaining } = state.toolBlocksByJob;
			return {
				...state,
				toolBlocksByJob: remaining,
			};
		}
		case "commandPalette/open":
			return {
				...state,
				commandPaletteOpen: true,
				commandPaletteQuery: action.query ?? "",
				commandPaletteActiveIndex: 0,
			};
		case "commandPalette/close":
			return {
				...state,
				commandPaletteOpen: false,
				commandPaletteQuery: "",
				commandPaletteActiveIndex: 0,
			};
		case "commandPalette/setQuery":
			return {
				...state,
				commandPaletteQuery: action.query,
				commandPaletteActiveIndex: 0,
			};
		case "commandPalette/navigate": {
			const commandCount = state.commands.length;
			if (commandCount === 0) {
				return state;
			}
			const nextIndex = state.commandPaletteActiveIndex + action.delta;
			return {
				...state,
				commandPaletteActiveIndex: Math.max(
					0,
					Math.min(nextIndex, commandCount - 1),
				),
			};
		}
		case "imageViewer/open":
			return {
				...state,
				imageViewer: {
					open: true,
					src: action.src,
					alt: action.alt,
				},
			};
		case "imageViewer/close":
			return {
				...state,
				imageViewer: null,
			};
		case "htmlPreview/open":
			return {
				...state,
				htmlPreview: {
					open: true,
					source: action.source,
					windowId: action.windowId,
				},
			};
		case "htmlPreview/close":
			return {
				...state,
				htmlPreview: null,
			};
		case "autoScroll/set":
			return {
				...state,
				autoScrollEnabled: action.enabled,
			};
		case "platform/set":
			return {
				...state,
				platform: action.platform,
			};
		default:
			return state;
	}
}

function errorMessage(err: unknown): string {
	return err instanceof Error ? err.message : String(err);
}

function selectedConversation(state: ChatState): string | null {
	return state.selectedConversationId ?? state.conversations[0]?.id ?? null;
}

function fileNameFromPath(filePath: string): string {
	return filePath.split(/[\\/]/).filter(Boolean).pop() || "attachment";
}

function normalizeRawSseEvent(
	eventName: string,
	eventId: number | null,
	dataLines: string[],
): ChatEvent | null {
	const data = dataLines.join("\n").trim();
	if (!data) {
		return null;
	}
	const payload = JSON.parse(data) as Record<string, unknown>;
	const seq =
		typeof payload.seq === "number"
			? payload.seq
			: eventId !== null
				? eventId
				: 0;
	return {
		seq,
		event: eventName || "message",
		payload,
	};
}

export function parseSseChunk(raw: string): ChatEvent[] {
	const events: ChatEvent[] = [];
	for (const block of raw.split(/\n\n+/)) {
		const lines = block.split(/\r?\n/);
		let eventName = "message";
		let eventId: number | null = null;
		const dataLines: string[] = [];
		for (const line of lines) {
			if (!line || line.startsWith(":")) {
				continue;
			}
			const separatorIndex = line.indexOf(":");
			const key = separatorIndex >= 0 ? line.slice(0, separatorIndex) : line;
			const value =
				separatorIndex >= 0 ? line.slice(separatorIndex + 1).trimStart() : "";
			if (key === "event") {
				eventName = value;
			} else if (key === "id") {
				const parsed = Number.parseInt(value, 10);
				eventId = Number.isFinite(parsed) ? parsed : null;
			} else if (key === "data") {
				dataLines.push(value);
			}
		}
		const event = normalizeRawSseEvent(eventName, eventId, dataLines);
		if (event) {
			events.push(event);
		}
	}
	return events;
}

function chatEventFromRuntimeEvent(event: RuntimeSseEvent): ChatEvent {
	return {
		seq: event.seq,
		event: event.eventType ?? "message",
		payload: event.payload,
	};
}

/**
 * 按 callId 在工具调用列表（含嵌套 children）中 upsert 一个 ToolCallSnapshot。
 * 对齐 WebUI upsertTimelineToolBlock 的 key 策略（webchat_call_id || tool_call_id）。
 * 有 parentCallId 时在匹配父块的 children 里递归 upsert；否则在顶层 upsert。
 */
function upsertToolCall(
	list: ToolCallSnapshot[],
	callId: string,
	parentCallId: string | undefined,
	patch: (existing: ToolCallSnapshot | undefined) => ToolCallSnapshot,
): ToolCallSnapshot[] {
	const matches = (item: ToolCallSnapshot, id: string): boolean =>
		item.id === id || (!item.id && item.name === id);

	if (parentCallId) {
		return list.map((item) => {
			if (matches(item, parentCallId)) {
				return {
					...item,
					children: upsertToolCall(
						item.children ?? [],
						callId,
						undefined,
						patch,
					),
				};
			}
			if (item.children && item.children.length > 0) {
				return {
					...item,
					children: upsertToolCall(item.children, callId, parentCallId, patch),
				};
			}
			return item;
		});
	}

	const idx = list.findIndex((item) => matches(item, callId));
	if (idx >= 0) {
		const next = list.slice();
		next[idx] = patch(list[idx]);
		return next;
	}
	return [...list, patch(undefined)];
}

export function createChatStore({
	client,
}: {
	client: RuntimeClient;
}): ChatStore {
	let state = createInitialChatState();
	const listeners = new Set<() => void>();
	const subscriptionsByJob = new Map<string, string>();
	const fallbackTimersByJob = new Map<string, ReturnType<typeof setTimeout>>();
	let unlistenRuntimeSse: (() => void) | null = null;

	function emit(): void {
		for (const listener of listeners) {
			listener();
		}
	}

	function dispatch(action: ChatAction): void {
		state = chatReducer(state, action);
		emit();
	}

	async function loadHistory(conversationId: string): Promise<void> {
		dispatch({ type: "history/loading", conversationId });
		try {
			const history = await client.getHistory({
				conversationId,
				limit: HISTORY_LIMIT,
			});
			dispatch({
				type: "history/set",
				conversationId,
				items: history.items,
				hasMore: history.hasMore,
				nextBefore: history.nextBefore,
				total: history.total,
			});
		} catch (err) {
			// 单会话历史加载失败降级为会话级错误，不升级为全局致命错误
			dispatch({
				type: "history/error",
				conversationId,
				error: errorMessage(err),
			});
		}
	}

	async function startStreamForJob(job: ChatJob): Promise<void> {
		if (subscriptionsByJob.has(job.jobId)) {
			return;
		}
		const subscription = await client.startJobEventStream({
			jobId: job.jobId,
			afterSeq: state.eventCursorByJob[job.jobId] ?? job.lastSeq,
			conversationId: job.conversationId,
		});
		if (subscription.subscriptionId) {
			subscriptionsByJob.set(job.jobId, subscription.subscriptionId);
		}
	}

	function stopFallbackPolling(jobId: string): void {
		const timer = fallbackTimersByJob.get(jobId);
		if (timer) {
			clearTimeout(timer);
			fallbackTimersByJob.delete(jobId);
		}
	}

	function scheduleFallbackPolling(jobId: string): void {
		if (fallbackTimersByJob.has(jobId)) {
			return;
		}
		const timer = setTimeout(() => {
			fallbackTimersByJob.delete(jobId);
			fetchJobEventsFallback(jobId);
		}, JSON_FALLBACK_POLL_MS);
		fallbackTimersByJob.set(jobId, timer);
	}

	function fetchJobEventsFallback(jobId: string): void {
		stopFallbackPolling(jobId);
		dispatch({ type: "connection/set", connectionState: "json_fallback" });
		void client
			.fetchJobEventsJson({
				jobId,
				afterSeq: state.eventCursorByJob[jobId] ?? 0,
				conversationId: state.jobConversationById[jobId],
			})
			.then((response) => {
				dispatch({ type: "job/upsert", job: response.job });
				applyRuntimeEvents(jobId, response.events);
				const hasTerminalEvent = response.events.some((item) =>
					TERMINAL_EVENTS.has(item.event),
				);
				if (isJobRunning(response.job)) {
					scheduleFallbackPolling(jobId);
				} else if (!hasTerminalEvent && response.job.conversationId) {
					void loadHistory(response.job.conversationId);
					dispatch({ type: "connection/set", connectionState: "connected" });
				}
			})
			.catch(() => {
				stopFallbackPolling(jobId);
				dispatch({ type: "connection/set", connectionState: "disconnected" });
			});
	}

	async function bootstrap(): Promise<void> {
		dispatch({ type: "bootstrap/start" });
		try {
			const runtimeConfig = await client.getRuntimeConfig();
			if (!runtimeConfig?.runtimeUrl || !runtimeConfig.hasApiKey) {
				dispatch({
					type: "bootstrap/error",
					runtimeConfig,
					error: "请先配置 Runtime URL 和 API Key",
				});
				return;
			}

			const [health, conversationsResponse, activeJobs, commands] =
				await Promise.all([
					client.probeRuntime(),
					client.listConversations(),
					client.getActiveJobs(),
					client.listCommands(),
				]);
			// 仅选取真实存在于会话列表中的会话：defaultConversationId 是后端常量
			// （legacy-system-42），未必对应已存在的会话，盲目用它会触发 getHistory 404
			const conversationIds = new Set(
				conversationsResponse.conversations.map((item) => item.id),
			);
			const preferredDefault = conversationsResponse.defaultConversationId;
			const selected =
				(preferredDefault && conversationIds.has(preferredDefault)
					? preferredDefault
					: "") ||
				conversationsResponse.conversations[0]?.id ||
				activeJobs.jobs[0]?.conversationId ||
				"";
			dispatch({
				type: "bootstrap/success",
				runtimeConfig,
				health,
				conversations: conversationsResponse.conversations,
				selectedConversationId: selected,
				activeJobs: activeJobs.jobs,
				commands: commands.commands,
			});
			unlistenRuntimeSse?.();
			unlistenRuntimeSse = await client.listenRuntimeSse(
				handleRuntimeEvent,
				handleRuntimeStatus,
			);
			for (const activeJob of activeJobs.jobs) {
				await startStreamForJob(activeJob);
			}
			if (selected) {
				await loadHistory(selected);
			}
			if (activeJobs.jobs.length > 0) {
				dispatch({ type: "connection/set", connectionState: "streaming" });
			}
		} catch (err) {
			dispatch({ type: "bootstrap/error", error: errorMessage(err) });
		}
	}

	async function createConversation(title?: string): Promise<void> {
		dispatch({ type: "conversation/creating", creating: true });
		try {
			const conversation = await client.createConversation(title);
			dispatch({ type: "conversation/upsert", conversation });
			await loadHistory(conversation.id);
		} catch (err) {
			dispatch({ type: "send/error", error: errorMessage(err) });
		} finally {
			dispatch({ type: "conversation/creating", creating: false });
		}
	}

	async function deleteConversation(conversationId: string): Promise<void> {
		const wasSelected = state.selectedConversationId === conversationId;
		const nextSelectedId = wasSelected
			? (state.conversations.find((item) => item.id !== conversationId)?.id ??
				null)
			: state.selectedConversationId;
		try {
			await client.deleteConversation(conversationId);
			dispatch({ type: "conversation/remove", conversationId, nextSelectedId });
			if (
				wasSelected &&
				nextSelectedId &&
				!state.historyByConversation[nextSelectedId]
			) {
				await loadHistory(nextSelectedId);
			}
		} catch (err) {
			dispatch({ type: "send/error", error: errorMessage(err) });
		}
	}

	async function renameConversation(
		conversationId: string,
		newTitle: string,
	): Promise<void> {
		try {
			await client.renameConversation(conversationId, newTitle);
			// 更新本地 state 中的会话标题
			const conversation = state.conversations.find(
				(item) => item.id === conversationId,
			);
			if (conversation) {
				dispatch({
					type: "conversation/upsert",
					conversation: { ...conversation, title: newTitle },
				});
			}
		} catch (err) {
			dispatch({ type: "send/error", error: errorMessage(err) });
		}
	}

	async function selectConversation(conversationId: string): Promise<void> {
		if (state.selectedConversationId === conversationId) {
			return;
		}
		dispatch({ type: "conversation/select", conversationId });
		if (!state.historyByConversation[conversationId]) {
			await loadHistory(conversationId);
		}
	}

	function updateDraft(conversationId: string, draft: string): void {
		dispatch({ type: "draft/set", conversationId, draft });
	}

	async function sendSelectedMessage(): Promise<void> {
		const conversationId = selectedConversation(state);
		if (!conversationId) {
			dispatch({ type: "send/error", error: "没有可用会话" });
			return;
		}
		if (isJobRunning(state.activeJobsByConversation[conversationId])) {
			dispatch({ type: "send/error", error: "当前会话仍在运行" });
			return;
		}
		const text = (state.draftsByConversation[conversationId] ?? "").trim();
		const attachments = state.attachmentsByConversation[conversationId] ?? [];
		if (
			attachments.some((item) => ["queued", "uploading"].includes(item.status))
		) {
			dispatch({ type: "send/error", error: "附件仍在上传" });
			return;
		}
		if (attachments.some((item) => item.status === "error")) {
			dispatch({ type: "send/error", error: "请先移除上传失败的附件" });
			return;
		}
		const attachmentIds = attachments
			.map((item) => item.attachmentId)
			.filter((item): item is string => Boolean(item));
		const references = state.referencesByConversation[conversationId] ?? [];
		if (!text && attachmentIds.length === 0) {
			return;
		}

		// 立即插入乐观用户消息并清空草稿/附件/引用（不等后端响应）
		const optimisticMessageId = `optimistic-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
		const optimisticTimestamp = new Date().toISOString();
		// 附件留空：上传附件的多媒体元信息（mediaType/previewUrl）此刻不全，
		// 待任务完成重载历史后随真实记录显示，避免乐观渲染出错误的附件卡片
		const optimisticItem: HistoryItem = {
			messageId: optimisticMessageId,
			role: "user",
			content: text,
			timestamp: optimisticTimestamp,
			attachments: [],
			references,
		};
		dispatch({
			type: "message/optimisticUser",
			conversationId,
			item: optimisticItem,
		});
		dispatch({ type: "draft/set", conversationId, draft: "" });
		dispatch({ type: "attachments/set", conversationId, attachments: [] });
		dispatch({ type: "references/set", conversationId, references: [] });

		const input: SendMessageInput = {
			conversationId,
			message: {
				text,
				attachmentIds,
				references,
			},
		};
		try {
			dispatch({ type: "send/error", error: null });
			const job = await client.sendMessage(input);
			dispatch({ type: "job/upsert", job });
			dispatch({ type: "connection/set", connectionState: "streaming" });
			await startStreamForJob(job);
		} catch (err) {
			// 发送失败：移除乐观用户消息并恢复草稿/附件/引用
			const currentHistory = state.historyByConversation[conversationId];
			if (currentHistory) {
				dispatch({
					type: "history/set",
					conversationId,
					items: currentHistory.items.filter(
						(item) => item.messageId !== optimisticMessageId,
					),
					hasMore: currentHistory.hasMore,
					nextBefore: currentHistory.nextBefore,
					total: Math.max(0, currentHistory.total - 1),
				});
			}
			dispatch({ type: "draft/set", conversationId, draft: text });
			dispatch({ type: "attachments/set", conversationId, attachments });
			dispatch({ type: "references/set", conversationId, references });
			dispatch({ type: "send/error", error: errorMessage(err) });
		}
	}

	async function addAttachmentPath(
		conversationId: string,
		filePath: string,
	): Promise<void> {
		const trimmed = filePath.trim();
		if (!trimmed) {
			return;
		}
		const localId = `local-${Date.now()}-${Math.random().toString(36).slice(2)}`;
		const queued = [
			...(state.attachmentsByConversation[conversationId] ?? []),
			{
				id: localId,
				name: fileNameFromPath(trimmed),
				size: 0,
				status: "uploading" as const,
				attachmentId: null,
			},
		];
		dispatch({ type: "attachments/set", conversationId, attachments: queued });
		try {
			const attachment = await client.uploadAttachment({ filePath: trimmed });
			const current = state.attachmentsByConversation[conversationId] ?? [];
			dispatch({
				type: "attachments/set",
				conversationId,
				attachments: current.map((item) =>
					item.id === localId
						? {
								id: localId,
								name: attachment.name,
								size: attachment.size,
								status: "ready",
								attachmentId: attachment.id,
							}
						: item,
				),
			});
		} catch (err) {
			const current = state.attachmentsByConversation[conversationId] ?? [];
			dispatch({
				type: "attachments/set",
				conversationId,
				attachments: current.map((item) =>
					item.id === localId
						? { ...item, status: "error", error: errorMessage(err) }
						: item,
				),
			});
		}
	}

	function addReference(
		conversationId: string,
		reference: MessageReference,
	): void {
		const references = state.referencesByConversation[conversationId] ?? [];
		dispatch({
			type: "references/set",
			conversationId,
			references: [
				...references.filter((item) => item.messageId !== reference.messageId),
				reference,
			],
		});
	}

	function addReferenceFromMessageId(
		conversationId: string,
		messageId: string,
	): void {
		const historyState = state.historyByConversation[conversationId];
		if (!historyState) {
			return;
		}
		const message = historyState.items.find(
			(item) => item.messageId === messageId,
		);
		if (!message) {
			return;
		}
		// 截取前 100 个字符作为引用预览
		const quote = message.content.slice(0, 100);
		addReference(conversationId, { messageId, quote });
	}

	function clearReference(conversationId: string, messageId: string): void {
		dispatch({
			type: "references/set",
			conversationId,
			references: (state.referencesByConversation[conversationId] ?? []).filter(
				(item) => item.messageId !== messageId,
			),
		});
	}

	function clearAttachment(conversationId: string, attachmentId: string): void {
		dispatch({
			type: "attachments/set",
			conversationId,
			attachments: (
				state.attachmentsByConversation[conversationId] ?? []
			).filter((item) => item.id !== attachmentId),
		});
	}

	function applyRuntimeEvents(jobId: string, events: ChatEvent[]): void {
		dispatch({ type: "events/apply", jobId, events });
		const conversationId =
			state.jobConversationById[jobId] ||
			events
				.map((item) => item.payload.conversation_id)
				.find((item): item is string => typeof item === "string") ||
			"";

		// 消费 stage/message 事件更新 activeJob（对齐 WebUI applyChatEventsPayload）
		const activeJob =
			conversationId && state.activeJobsByConversation[conversationId];
		if (activeJob && activeJob.jobId === jobId) {
			let updatedJob = activeJob;
			for (const event of events) {
				if (event.event === "stage" && event.payload) {
					// stage 事件：更新 currentStage/Detail/StartedAt（对齐 WebUI setChatStage）
					const stage = String(event.payload.stage ?? "").trim();
					const detail = String(event.payload.detail ?? "").trim() || null;
					const startedAt =
						typeof event.payload.started_at === "number"
							? event.payload.started_at
							: null;
					const elapsedMs =
						typeof event.payload.elapsed_ms === "number"
							? event.payload.elapsed_ms
							: null;
					if (stage) {
						updatedJob = {
							...updatedJob,
							currentStage: stage,
							currentStageDetail: detail,
							currentStageStartedAt: startedAt,
							currentStageElapsedMs: elapsedMs,
						};
					}
				} else if (event.event === "message" && event.payload) {
					// message 事件：追加文本到 reply（对齐 WebUI appendTimelineMessage）
					const content = String(
						event.payload.content ?? event.payload.message ?? "",
					);
					if (content) {
						updatedJob = {
							...updatedJob,
							reply: updatedJob.reply + content,
						};
					}
				} else if (
					event.event === "tool_start" ||
					event.event === "agent_start" ||
					event.event === "tool_end" ||
					event.event === "agent_end"
				) {
					// tool/agent 生命周期：upsert 工具块（对齐 WebUI upsertToolBlock）
					const payload = event.payload ?? {};
					const callId = String(
						payload.webchat_call_id ||
							payload.tool_call_id ||
							payload.name ||
							"",
					);
					if (callId) {
						const parentCallId =
							String(payload.parent_webchat_call_id || "") || undefined;
						const isStart =
							event.event === "tool_start" || event.event === "agent_start";
						updatedJob = {
							...updatedJob,
							currentToolCalls: upsertToolCall(
								updatedJob.currentToolCalls,
								callId,
								parentCallId,
								(existing) => ({
									id: callId,
									name: String(payload.name || existing?.name || ""),
									status: isStart
										? "running"
										: payload.ok === false
											? "error"
											: "done",
									isAgent:
										Boolean(payload.is_agent) || existing?.isAgent || false,
									argumentsPreview: isStart
										? String(payload.arguments_preview ?? "")
										: (existing?.argumentsPreview ?? ""),
									resultPreview: !isStart
										? String(payload.result_preview ?? "")
										: (existing?.resultPreview ?? ""),
									uiHint:
										String(payload.ui_hint ?? existing?.uiHint ?? "") ||
										undefined,
									currentStage: existing?.currentStage,
									elapsedMs: existing?.elapsedMs ?? null,
									durationMs:
										!isStart && typeof payload.duration_ms === "number"
											? payload.duration_ms
											: (existing?.durationMs ?? null),
									children: existing?.children ?? [],
									timeline: existing?.timeline,
								}),
							),
						};
					}
				} else if (event.event === "agent_stage") {
					// agent 阶段：更新 agent 块 currentStage（对齐 WebUI upsertAgentStageBlock）
					const payload = event.payload ?? {};
					const callId = String(payload.webchat_call_id || payload.name || "");
					if (callId) {
						const parentCallId =
							String(payload.parent_webchat_call_id || "") || undefined;
						updatedJob = {
							...updatedJob,
							currentToolCalls: upsertToolCall(
								updatedJob.currentToolCalls,
								callId,
								parentCallId,
								(existing) => ({
									id: callId,
									name: String(
										payload.agent_name || payload.name || existing?.name || "",
									),
									status: String(
										payload.status || existing?.status || "running",
									),
									isAgent: true,
									currentStage:
										String(payload.stage || "") || existing?.currentStage,
									argumentsPreview: existing?.argumentsPreview,
									resultPreview: existing?.resultPreview,
									uiHint: existing?.uiHint,
									elapsedMs: existing?.elapsedMs ?? null,
									durationMs: existing?.durationMs ?? null,
									children: existing?.children ?? [],
									timeline: existing?.timeline,
								}),
							),
						};
					}
				}
			}
			if (updatedJob !== activeJob) {
				dispatch({ type: "job/upsert", job: updatedJob });
			}
		}

		// 终态事件：清理 job 并重载历史
		const doneEvent = events.find((item) =>
			["done", "error", "cancelled"].includes(item.event),
		);
		if (doneEvent && conversationId) {
			stopFallbackPolling(jobId);
			const subscriptionId = subscriptionsByJob.get(jobId);
			if (subscriptionId) {
				subscriptionsByJob.delete(jobId);
				void client.stopJobEventStream(subscriptionId);
			}
			dispatch({ type: "job/remove", conversationId, jobId });
			if (Object.keys(state.activeJobsByConversation).length === 0) {
				dispatch({ type: "connection/set", connectionState: "connected" });
			}
			void loadHistory(conversationId);
		}
	}

	function handleRuntimeEvent(event: RuntimeSseEvent): void {
		applyRuntimeEvents(event.jobId, [chatEventFromRuntimeEvent(event)]);
	}

	function handleRuntimeStatus(status: RuntimeSseStatus): void {
		if (status.status === "connected") {
			dispatch({ type: "connection/set", connectionState: "streaming" });
			return;
		}
		if (status.status === "error") {
			fetchJobEventsFallback(status.jobId);
			return;
		}
		if (status.status === "closed") {
			const conversationId = state.jobConversationById[status.jobId];
			if (conversationId && state.activeJobsByConversation[conversationId]) {
				fetchJobEventsFallback(status.jobId);
				return;
			}
			dispatch({ type: "connection/set", connectionState: "connected" });
		}
	}

	async function loadMoreHistory(conversationId: string): Promise<void> {
		const historyState = state.historyByConversation[conversationId];
		if (!historyState || !historyState.hasMore || historyState.loading) {
			return;
		}

		dispatch({
			type: "history/set",
			conversationId,
			items: historyState.items,
			hasMore: historyState.hasMore,
			nextBefore: historyState.nextBefore,
			total: historyState.total,
		});

		try {
			const response = await client.getHistoryPage(
				conversationId,
				historyState.nextBefore ?? undefined,
				HISTORY_LIMIT,
			);

			const newItems = [...response.items.reverse(), ...historyState.items];

			dispatch({
				type: "history/set",
				conversationId,
				items: newItems,
				hasMore: response.hasMore,
				nextBefore: response.nextBefore,
				total: response.total,
			});
		} catch (error) {
			console.error("Failed to load more history:", error);
		}
	}

	return {
		bootstrap,
		createConversation,
		deleteConversation,
		renameConversation,
		selectConversation,
		updateDraft,
		sendSelectedMessage,
		addAttachmentPath,
		addReference,
		addReferenceFromMessageId,
		clearReference,
		clearAttachment,
		loadMoreHistory,
		reloadHistory: loadHistory,
		applyRuntimeEvents,
		handleRuntimeEvent,
		handleRuntimeStatus,
		dispatch,
		getSnapshot: () => state,
		subscribe(listener) {
			listeners.add(listener);
			return () => {
				listeners.delete(listener);
			};
		},
	};
}
