export type ConnectionState =
	| "idle"
	| "connecting"
	| "connected"
	| "streaming"
	| "resuming"
	| "json_fallback"
	| "disconnected";

export type RuntimeConfig = {
	runtimeUrl: string;
	hasApiKey: boolean;
};

export type ApiKeyStatus = {
	available: boolean;
	storage: string;
	degraded: boolean;
	keyPreview: string | null;
	detail: string;
};

export type RuntimeHealth = {
	ok: boolean;
	status: number;
	body: string;
};

export type Conversation = {
	id: string;
	title: string;
	titleSource: string;
	titleStatus: string;
	createdAt: string;
	updatedAt: string;
	virtualUserId: string;
	messageCount: number;
	isRunning: boolean;
};

export type Attachment = {
	id: string;
	name: string;
	size: number;
	mediaType: string;
	kind: string;
	downloadUrl: string | null;
	previewUrl: string | null;
	discarded: boolean;
};

export type MessageReference = {
	messageId: string;
	quote: string;
};

export type HistoryWebchat = {
	displayOnly: boolean;
	jobId: string;
	mode: string;
	status: string;
	createdAt: number | string | null;
	finishedAt: number | string | null;
	durationMs: number | null;
	events: ChatEvent[];
	calls: unknown[];
	timeline: unknown[];
};

export type HistoryItem = {
	messageId: string;
	role: "user" | "bot" | "system";
	content: string;
	timestamp: string;
	attachments: Attachment[];
	references: MessageReference[];
	webchat?: HistoryWebchat;
};

export type ToolCallSnapshot = {
	id: string;
	name: string;
	status: string;
	elapsedMs: number | null;
	detail?: string;
};

export type AgentStageSnapshot = {
	id: string;
	name: string;
	stage: string;
	status: string;
	elapsedMs: number | null;
	detail?: string;
};

export type ChatJob = {
	jobId: string;
	conversationId: string;
	status: string;
	mode: string;
	createdAt: number;
	updatedAt: number;
	finishedAt: number | null;
	elapsedMs: number;
	durationMs: number | null;
	currentStage: string;
	currentStageDetail: string | null;
	currentStageStartedAt: number | null;
	currentStageElapsedMs: number | null;
	lastSeq: number;
	error: string | null;
	reply: string;
	messages: string[];
	currentAgentStages: AgentStageSnapshot[];
	currentToolCalls: ToolCallSnapshot[];
	historyFinalized: boolean;
	waitingInput: unknown | null;
};

export type ChatEvent = {
	seq: number;
	event: string;
	payload: Record<string, unknown>;
};

export type CommandInfo = {
	name: string;
	description: string;
};

export type SendMessageInput = {
	conversationId: string;
	message: {
		text: string;
		attachmentIds: string[];
		references: MessageReference[];
	};
};

export type RuntimeSseEvent = {
	subscriptionId: string;
	jobId: string;
	seq: number;
	eventType: string | null;
	payload: Record<string, unknown>;
};

export type RuntimeSseStatus = {
	subscriptionId: string;
	jobId: string;
	status: "connected" | "closed" | "error" | string;
	detail: string | null;
};

export type HtmlPreviewInput = {
	title: string;
	html: string;
};

export type ConversationsResponse = {
	conversations: Conversation[];
	activeJob: ChatJob | null;
	defaultConversationId: string;
	virtualUserId: string;
};

export type HistoryResponse = {
	conversationId: string;
	virtualUserId: string;
	permission: string;
	count: number;
	items: HistoryItem[];
	limit: number;
	before: number | null;
	hasMore: boolean;
	nextBefore: number | null;
	total: number;
};

export type ActiveJobsResponse = {
	job: ChatJob | null;
	jobs: ChatJob[];
};

export type CommandsResponse = {
	commands: CommandInfo[];
};

export type JobEventsJsonResponse = {
	job: ChatJob;
	after: number;
	lastSeq: number;
	events: ChatEvent[];
};

export type UploadAttachmentInput = {
	filePath: string;
};

export type AttachmentDownloadInput = {
	attachmentId: string;
	fileName?: string | null;
};

export type AttachmentDownloadResult = {
	status: number;
	ok: boolean;
	savedFileName: string | null;
	bytesWritten: number;
	mediaType: string | null;
	body: string | null;
};

export type AttachmentPreviewInput = {
	attachmentId: string;
};

export type AttachmentPreviewResult = {
	status: number;
	ok: boolean;
	mediaType: string | null;
	bytes: number[];
	body: string | null;
};

export type EventStreamSubscription = {
	subscriptionId: string;
	jobId: string;
	afterSeq: number;
};

export type RuntimeClient = {
	getRuntimeConfig: () => Promise<RuntimeConfig | null>;
	saveRuntimeConfig: (runtimeUrl: string) => Promise<RuntimeConfig>;
	saveApiKey: (apiKey: string) => Promise<ApiKeyStatus>;
	confirmInsecureStorageFallback: () => Promise<ApiKeyStatus>;
	loadApiKeyStatus: () => Promise<ApiKeyStatus>;
	probeRuntime: () => Promise<RuntimeHealth>;
	listConversations: () => Promise<ConversationsResponse>;
	createConversation: (title?: string) => Promise<Conversation>;
	getHistory: (input: {
		conversationId: string;
		limit: number;
		before?: number | null;
	}) => Promise<HistoryResponse>;
	getActiveJobs: (input?: {
		conversationId?: string | null;
	}) => Promise<ActiveJobsResponse>;
	sendMessage: (input: SendMessageInput) => Promise<ChatJob>;
	cancelJob: (jobId: string) => Promise<ChatJob>;
	listCommands: () => Promise<CommandsResponse>;
	fetchJobEventsJson: (input: {
		jobId: string;
		afterSeq: number;
		conversationId?: string | null;
	}) => Promise<JobEventsJsonResponse>;
	startJobEventStream: (input: {
		jobId: string;
		afterSeq: number;
		conversationId?: string | null;
	}) => Promise<EventStreamSubscription>;
	stopJobEventStream: (subscriptionId: string) => Promise<void>;
	uploadAttachment: (input: UploadAttachmentInput) => Promise<Attachment>;
	saveAttachment: (
		input: AttachmentDownloadInput,
	) => Promise<AttachmentDownloadResult>;
	previewAttachment: (
		input: AttachmentPreviewInput,
	) => Promise<AttachmentPreviewResult>;
	openHtmlPreview: (input: HtmlPreviewInput) => Promise<void>;
	listenRuntimeSse: (
		onEvent: (event: RuntimeSseEvent) => void,
		onStatus: (status: RuntimeSseStatus) => void,
	) => Promise<() => void>;
};
