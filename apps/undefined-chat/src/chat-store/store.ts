import type {
	ChatEvent,
	ChatJob,
	CommandInfo,
	ConnectionState,
	Conversation,
	HistoryItem,
	MessageReference,
	RuntimeClient,
	RuntimeConfig,
	RuntimeHealth,
	RuntimeSseEvent,
	RuntimeSseStatus,
	SendMessageInput,
} from "../runtime-client/types";

export type AttachmentDraft = {
	id: string;
	name: string;
	size: number;
	status: "queued" | "uploading" | "ready" | "error";
	attachmentId: string | null;
	error?: string;
};

export type ConversationHistoryState = {
	items: HistoryItem[];
	hasMore: boolean;
	nextBefore: number | null;
	total: number;
	loading: boolean;
	error: string | null;
};

export type ChatState = {
	connectionState: ConnectionState;
	runtimeConfig: RuntimeConfig | null;
	health: RuntimeHealth | null;
	conversations: Conversation[];
	selectedConversationId: string | null;
	historyByConversation: Record<string, ConversationHistoryState>;
	activeJobsByConversation: Record<string, ChatJob>;
	eventsByJob: Record<string, ChatEvent[]>;
	eventCursorByJob: Record<string, number>;
	jobConversationById: Record<string, string>;
	draftsByConversation: Record<string, string>;
	attachmentsByConversation: Record<string, AttachmentDraft[]>;
	referencesByConversation: Record<string, MessageReference[]>;
	commands: CommandInfo[];
	settings: {
		locale: "zh-CN" | "en";
		mobilePanel: "chat" | "conversations" | "settings";
	};
	bootstrapping: boolean;
	error: string | null;
	sendError: string | null;
};

export type ChatAction =
	| { type: "connection/set"; connectionState: ConnectionState }
	| { type: "bootstrap/start" }
	| {
			type: "bootstrap/success";
			runtimeConfig: RuntimeConfig;
			health: RuntimeHealth;
			conversations: Conversation[];
			selectedConversationId: string;
			activeJobs: ChatJob[];
			commands: CommandInfo[];
	  }
	| {
			type: "bootstrap/error";
			error: string;
			runtimeConfig?: RuntimeConfig | null;
	  }
	| {
			type: "history/set";
			conversationId: string;
			items: HistoryItem[];
			hasMore: boolean;
			nextBefore: number | null;
			total: number;
	  }
	| { type: "conversation/select"; conversationId: string }
	| { type: "conversation/upsert"; conversation: Conversation }
	| { type: "draft/set"; conversationId: string; draft: string }
	| { type: "send/error"; error: string | null }
	| { type: "job/upsert"; job: ChatJob }
	| { type: "job/remove"; conversationId: string; jobId: string }
	| { type: "events/apply"; jobId: string; events: ChatEvent[] }
	| {
			type: "attachments/set";
			conversationId: string;
			attachments: AttachmentDraft[];
	  }
	| {
			type: "references/set";
			conversationId: string;
			references: MessageReference[];
	  }
	| { type: "mobile-panel/set"; panel: "chat" | "conversations" | "settings" };

export type ChatStore = {
	bootstrap: () => Promise<void>;
	createConversation: (title?: string) => Promise<void>;
	selectConversation: (conversationId: string) => Promise<void>;
	updateDraft: (conversationId: string, draft: string) => void;
	sendSelectedMessage: () => Promise<void>;
	addAttachmentPath: (
		conversationId: string,
		filePath: string,
	) => Promise<void>;
	addReference: (conversationId: string, reference: MessageReference) => void;
	clearReference: (conversationId: string, messageId: string) => void;
	clearAttachment: (conversationId: string, attachmentId: string) => void;
	applyRuntimeEvents: (jobId: string, events: ChatEvent[]) => void;
	handleRuntimeEvent: (event: RuntimeSseEvent) => void;
	handleRuntimeStatus: (status: RuntimeSseStatus) => void;
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
		activeJobsByConversation: {},
		eventsByJob: {},
		eventCursorByJob: {},
		jobConversationById: {},
		draftsByConversation: {},
		attachmentsByConversation: {},
		referencesByConversation: {},
		commands: [],
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
			const selected =
				conversationsResponse.defaultConversationId ||
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
		try {
			const conversation = await client.createConversation(title);
			dispatch({ type: "conversation/upsert", conversation });
			await loadHistory(conversation.id);
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
			dispatch({ type: "draft/set", conversationId, draft: "" });
			dispatch({ type: "attachments/set", conversationId, attachments: [] });
			dispatch({ type: "references/set", conversationId, references: [] });
			dispatch({ type: "connection/set", connectionState: "streaming" });
			await startStreamForJob(job);
		} catch (err) {
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
		const doneEvent = events.find((item) =>
			["done", "error", "cancelled"].includes(item.event),
		);
		const conversationId =
			state.jobConversationById[jobId] ||
			events
				.map((item) => item.payload.conversation_id)
				.find((item): item is string => typeof item === "string") ||
			"";
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

	return {
		bootstrap,
		createConversation,
		selectConversation,
		updateDraft,
		sendSelectedMessage,
		addAttachmentPath,
		addReference,
		clearReference,
		clearAttachment,
		applyRuntimeEvents,
		handleRuntimeEvent,
		handleRuntimeStatus,
		getSnapshot: () => state,
		subscribe(listener) {
			listeners.add(listener);
			return () => {
				listeners.delete(listener);
			};
		},
	};
}
