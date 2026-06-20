import type {
	ChatEvent,
	ChatJob,
	CommandInfo,
	ConnectionState,
	Conversation,
	HistoryItem,
	MessageReference,
	RuntimeConfig,
	RuntimeHealth,
} from "../runtime-client/types";

// 重新导出 runtime-client 类型
export type { ChatEvent, ChatJob, MessageReference };

// ============================================================================
// 基础类型
// ============================================================================

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

// ============================================================================
// 工具块系统
// ============================================================================

export type ToolBlockStatus = "running" | "done" | "error" | "cancelled";

export type TimelineEntry =
	| { type: "input"; timestamp: number; content: string }
	| { type: "output"; timestamp: number; content: string }
	| { type: "error"; timestamp: number; message: string };

export type ToolBlock = {
	webchatCallId: string;
	toolName: string;
	status: ToolBlockStatus;
	isAgent?: boolean;
	uiHint?: string;
	argumentsPreview?: string;
	resultPreview?: string;
	currentStage?: string;
	stageDetail?: string;
	children: Map<string, ToolBlock>;
	timeline: TimelineEntry[];
	startTime: number;
	endTime?: number;
};

// ============================================================================
// 命令系统
// ============================================================================

export type CommandContext = {
	conversationId: string;
	messageId?: string;
	selectedText?: string;
};

// ============================================================================
// 平台信息
// ============================================================================

export type PlatformInfo = {
	type: "desktop" | "android";
	os: string;
};

// ============================================================================
// 模态框状态
// ============================================================================

export type ImageViewerState = {
	open: boolean;
	src: string;
	alt: string;
};

export type HtmlPreviewState = {
	open: boolean;
	source: string;
	windowId?: string;
};

// ============================================================================
// 核心状态
// ============================================================================

export type ChatState = {
	// 连接与健康状态
	connectionState: ConnectionState;
	runtimeConfig: RuntimeConfig | null;
	health: RuntimeHealth | null;

	// 会话管理
	conversations: Conversation[];
	selectedConversationId: string | null;
	historyByConversation: Record<string, ConversationHistoryState>;
	/** 是否正在新建会话（用于"正在新建"提示） */
	creatingConversation: boolean;

	// 任务与事件流
	activeJobsByConversation: Record<string, ChatJob>;
	eventsByJob: Record<string, ChatEvent[]>;
	eventCursorByJob: Record<string, number>;
	jobConversationById: Record<string, string>;

	// 工具块系统
	toolBlocksByJob: Record<string, Map<string, ToolBlock>>;

	// 输入状态
	draftsByConversation: Record<string, string>;
	attachmentsByConversation: Record<string, AttachmentDraft[]>;
	referencesByConversation: Record<string, MessageReference[]>;

	// 命令系统
	commands: CommandInfo[];
	commandPaletteOpen: boolean;
	commandPaletteQuery: string;
	commandPaletteActiveIndex: number;

	// 模态框
	imageViewer: ImageViewerState | null;
	htmlPreview: HtmlPreviewState | null;

	// UI 状态
	autoScrollEnabled: boolean;

	// 平台信息
	platform: PlatformInfo | null;

	// 设置
	settings: {
		mobilePanel: "chat" | "conversations" | "settings";
	};

	// 启动与错误
	bootstrapping: boolean;
	error: string | null;
	sendError: string | null;
};

// ============================================================================
// Actions
// ============================================================================

export type ChatAction =
	// 连接状态
	| { type: "connection/set"; connectionState: ConnectionState }
	// 启动流程
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
	// 历史记录
	| { type: "history/loading"; conversationId: string }
	| { type: "history/error"; conversationId: string; error: string }
	| {
			type: "history/set";
			conversationId: string;
			items: HistoryItem[];
			hasMore: boolean;
			nextBefore: number | null;
			total: number;
	  }
	// 乐观渲染：发送时立即插入用户消息
	| {
			type: "message/optimisticUser";
			conversationId: string;
			item: HistoryItem;
	  }
	// 会话管理
	| { type: "conversation/select"; conversationId: string }
	| { type: "conversation/upsert"; conversation: Conversation }
	| {
			type: "conversation/remove";
			conversationId: string;
			nextSelectedId: string | null;
	  }
	| { type: "conversation/creating"; creating: boolean }
	// 输入状态
	| { type: "draft/set"; conversationId: string; draft: string }
	| { type: "send/error"; error: string | null }
	// 任务与事件
	| { type: "job/upsert"; job: ChatJob }
	| { type: "job/remove"; conversationId: string; jobId: string }
	| { type: "events/apply"; jobId: string; events: ChatEvent[] }
	// 工具块
	| { type: "toolBlock/upsert"; jobId: string; toolBlock: ToolBlock }
	| { type: "toolBlock/clear"; jobId: string }
	// 附件与引用
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
	// 命令列表刷新（窗口聚焦时按 TTL 重新拉取，使热重载新命令可见）
	| { type: "commands/set"; commands: CommandInfo[] }
	// 命令面板
	| { type: "commandPalette/open"; query?: string }
	| { type: "commandPalette/close" }
	| { type: "commandPalette/setQuery"; query: string }
	| { type: "commandPalette/navigate"; delta: number }
	// 图片查看器
	| { type: "imageViewer/open"; src: string; alt: string }
	| { type: "imageViewer/close" }
	// HTML 预览
	| { type: "htmlPreview/open"; source: string; windowId?: string }
	| { type: "htmlPreview/close" }
	// 自动滚动
	| { type: "autoScroll/set"; enabled: boolean }
	// 平台信息
	| { type: "platform/set"; platform: PlatformInfo }
	// 移动端面板
	| { type: "mobile-panel/set"; panel: "chat" | "conversations" | "settings" };
