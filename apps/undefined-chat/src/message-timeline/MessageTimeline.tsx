import { useEffect, useRef, useState } from "react";
import { isJobRunning } from "../chat-store/store";
import { useTranslation } from "../i18n";
import { extractAttachmentTags } from "../rendering/AttachmentProcessor";
import {
	type HtmlPreviewRequest,
	MarkdownContent,
} from "../rendering/MarkdownContent";
import type {
	Attachment,
	ChatJob,
	ConnectionState,
	HistoryItem,
	ToolCallSnapshot,
} from "../runtime-client/types";
import { isImageAttachment } from "../utils/attachment";
import { AttachmentCard } from "./AttachmentCard";
import { ChatStageLabel } from "./ChatStageLabel";
import { MessageQuoteButton } from "./MessageQuoteButton";
import {
	MessageTimelineContent,
	hasRenderableTimeline,
} from "./MessageTimelineContent";

export type MessageTimelineProps = {
	activeJob: ChatJob | null;
	connectionState: ConnectionState;
	/** 选中会话的历史尚未加载或加载中：显示加载态而非欢迎页 */
	historyLoading?: boolean;
	/** 历史加载失败的错误信息（单会话级，非全局致命） */
	historyError?: string | null;
	/** 当前会话是否还有更早的历史可加载 */
	hasMoreHistory?: boolean;
	/** 重试加载当前会话历史 */
	onRetryHistory?: () => void;
	/** 加载更早历史；提供时渲染所有已加载消息，避免旧页被窗口化裁掉 */
	onLoadMoreHistory?: () => Promise<void> | void;
	/**
	 * 是否启用自动滚动到底部。false 时流式/历史加载完成均不自动滚底，
	 * 尊重用户上滑查看历史的意图（跨分区契约 1：由 App 传入）。默认 true。
	 */
	autoScrollEnabled?: boolean;
	items: HistoryItem[];
	onPreviewHtml: (input: HtmlPreviewRequest) => void;
	onPreviewAttachment: (attachment: Attachment) => void;
	onSaveAttachment: (attachment: Attachment) => void;
	onShortcutClick?: (prompt: string) => void;
	onAddReference?: (messageId: string) => void;
	/**
	 * 划词引用回调（跨分区契约 2）：用户在消息正文区选中文本并点击"引用"浮层时触发，
	 * App 端转调 store.addReferenceFromSelection(conversationId, text)。
	 */
	onAddSelectionReference?: (text: string) => void;
	onOpenImage?: (src: string, alt: string) => void;
	onCancelJob?: (jobId: string) => void;
};

const WINDOW_SIZE = 64;
type HistoryToolCall = {
	id?: string;
	name: string;
	is_agent?: boolean;
	status: string;
	arguments_preview?: string;
	result_preview?: string;
	ui_hint?: string;
	duration_ms?: number;
	current_stage?: string;
	current_stage_detail?: string;
	children?: HistoryToolCall[];
	timeline?: unknown[];
};

type HistoryTimelineEntry = {
	type: string;
	content?: string;
	stage?: string;
	detail?: string;
	call?: HistoryToolCall;
};

function convertToolCallSnapshot(snap: ToolCallSnapshot): HistoryToolCall {
	return {
		id: snap.id,
		name: snap.name,
		is_agent: snap.isAgent,
		status: snap.status,
		arguments_preview: snap.argumentsPreview,
		result_preview: snap.resultPreview,
		ui_hint: snap.uiHint,
		duration_ms: snap.durationMs ?? snap.elapsedMs ?? undefined,
		current_stage: snap.currentStage,
		children: snap.children?.map(convertToolCallSnapshot),
		timeline: snap.timeline,
	};
}

function buildStreamingTimeline(job: ChatJob): HistoryTimelineEntry[] {
	// 优先用 currentTimeline：按事件到达顺序，message 段与 call 交错（对齐 WebUI append 顺序）
	if (job.currentTimeline.length > 0) {
		const entries: HistoryTimelineEntry[] = [];
		for (const item of job.currentTimeline) {
			if (item.type === "message") {
				entries.push({ type: "message", content: item.content });
			} else {
				const snap = job.currentToolCalls.find(
					(s) => s.id === item.callId || (!s.id && s.name === item.callId),
				);
				if (snap) {
					entries.push({ type: "call", call: convertToolCallSnapshot(snap) });
				}
			}
		}
		return entries;
	}
	// 回退（无 currentTimeline，如旧数据）
	const timeline: HistoryTimelineEntry[] = [];
	if (job.reply.trim()) {
		timeline.push({ type: "message", content: job.reply });
	}
	for (const toolCall of job.currentToolCalls) {
		timeline.push({
			type: "call",
			call: convertToolCallSnapshot(toolCall),
		});
	}
	return timeline;
}

/**
 * 历史 webchat 记录的原始事件条目（对齐后端 _finalize_webchat_history_events）。
 * 仅在 timeline 缺失需从 calls/events 回退重建时使用。
 */
type HistoryEvent = {
	seq?: number;
	event?: string;
	payload?: {
		content?: string;
		message?: string;
		name?: string;
		api_name?: string;
		is_agent?: boolean;
		status?: string;
		ok?: boolean;
		arguments_preview?: string;
		result_preview?: string;
		ui_hint?: string;
		duration_ms?: number;
		current_stage?: string;
		current_stage_detail?: string;
		webchat_call_id?: string;
		parent_webchat_call_id?: string;
	};
};

/**
 * 后端 calls 树节点（_call_preview_node）以 webchat_call_id 标识、含 current_stage_detail，
 * 统一归一化为 MessageTimelineContent 可消费的 HistoryToolCall（id/current_stage_detail 兼容）。
 */
function normalizeCallNode(node: Record<string, unknown>): HistoryToolCall {
	const children = Array.isArray(node.children)
		? (node.children as Record<string, unknown>[]).map(normalizeCallNode)
		: undefined;
	return {
		id: String(node.webchat_call_id ?? node.id ?? "") || undefined,
		name: String(node.name ?? "--"),
		is_agent: Boolean(node.is_agent),
		status: String(node.status ?? "done"),
		arguments_preview: node.arguments_preview
			? String(node.arguments_preview)
			: undefined,
		result_preview: node.result_preview
			? String(node.result_preview)
			: undefined,
		ui_hint: node.ui_hint ? String(node.ui_hint) : undefined,
		duration_ms:
			typeof node.duration_ms === "number" ? node.duration_ms : undefined,
		current_stage: node.current_stage ? String(node.current_stage) : undefined,
		current_stage_detail: node.current_stage_detail
			? String(node.current_stage_detail)
			: undefined,
		children,
		timeline: Array.isArray(node.timeline) ? node.timeline : undefined,
	};
}

/**
 * 从原始 events 重建顶层时间线：顺序提取顶层 message 文本与 tool/agent 调用。
 * 简化处理——仅重建顶层（parent 为空）的 call/message，子调用经 tool_end 的
 * result_preview/status 落到对应节点；不深挖嵌套层级（calls 缺失通常意味着旧/简单记录）。
 */
function buildTimelineFromEvents(
	events: HistoryEvent[],
): HistoryTimelineEntry[] {
	const entries: HistoryTimelineEntry[] = [];
	const callIndexById = new Map<string, number>();
	for (const item of events) {
		const event = String(item.event ?? "");
		const payload = item.payload ?? {};
		if (event === "message") {
			if (String(payload.parent_webchat_call_id ?? "").trim()) {
				continue; // 仅顶层文本
			}
			const content = String(payload.content ?? payload.message ?? "");
			if (content.trim()) {
				entries.push({ type: "message", content });
			}
			continue;
		}
		if (event === "tool_start" || event === "agent_start") {
			if (String(payload.parent_webchat_call_id ?? "").trim()) {
				continue; // 仅重建顶层调用
			}
			const callId = String(payload.webchat_call_id ?? "");
			const call: HistoryToolCall = {
				id: callId || undefined,
				name: String(payload.name ?? payload.api_name ?? "--"),
				is_agent: Boolean(payload.is_agent),
				status: "running",
				arguments_preview: payload.arguments_preview,
				ui_hint: payload.ui_hint,
				current_stage: payload.current_stage,
				current_stage_detail: payload.current_stage_detail,
			};
			if (callId) {
				callIndexById.set(callId, entries.length);
			}
			entries.push({ type: "call", call });
			continue;
		}
		if (event === "tool_end" || event === "agent_end") {
			const callId = String(payload.webchat_call_id ?? "");
			const index = callId ? callIndexById.get(callId) : undefined;
			if (index === undefined) {
				continue;
			}
			const existing = entries[index]?.call;
			if (!existing) {
				continue;
			}
			existing.status = String(
				payload.status ?? (payload.ok === false ? "error" : "done"),
			);
			if (payload.result_preview) {
				existing.result_preview = String(payload.result_preview);
			}
			if (typeof payload.duration_ms === "number") {
				existing.duration_ms = payload.duration_ms;
			}
			if (payload.ui_hint) {
				existing.ui_hint = String(payload.ui_hint);
			}
		}
	}
	return entries;
}

/**
 * 历史 bot 消息的可渲染时间线，按可用性回退：
 * 1. webchat.timeline（首选，后端已交错好的完整时间线）；
 * 2. webchat.calls（仅有调用树时，逐根节点包成 call 条目，正文走 fallbackContent 兜底）；
 * 3. webchat.events（最原始，重建顶层 message + call）。
 * 三者皆空时返回 null，由调用方走普通正文渲染。
 */
function buildHistoryTimeline(
	webchat: HistoryItem["webchat"],
): unknown[] | null {
	if (!webchat) {
		return null;
	}
	if (hasRenderableTimeline(webchat.timeline)) {
		return webchat.timeline ?? null;
	}
	const calls = Array.isArray(webchat.calls) ? webchat.calls : [];
	if (calls.length > 0) {
		return calls.map((node) => ({
			type: "call",
			call: normalizeCallNode(node as Record<string, unknown>),
		}));
	}
	const events = Array.isArray(webchat.events)
		? (webchat.events as HistoryEvent[])
		: [];
	if (events.length > 0) {
		const rebuilt = buildTimelineFromEvents(events);
		if (rebuilt.some((entry) => entry.type === "call")) {
			return rebuilt;
		}
	}
	return null;
}

/**
 * 格式化消息时间戳为 "HH:MM"。HistoryItem.timestamp 为 string，
 * 兼容 Unix 秒/毫秒数字字符串与 ISO 字符串。
 * WebUI 无显式时间戳元素，此函数仅用于保留用户要求的轻量时间戳。
 */
function formatMessageTime(timestamp: string): string {
	if (!timestamp) return "";
	const trimmed = timestamp.trim();
	// 纯数字字符串：Unix 时间戳（秒或毫秒）
	if (/^\d+$/.test(trimmed)) {
		const n = Number(trimmed);
		const ms = n > 1e12 ? n : n * 1000;
		const d = new Date(ms);
		return Number.isNaN(d.getTime())
			? ""
			: d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
	}
	// ISO 字符串
	const d = new Date(timestamp);
	return Number.isNaN(d.getTime())
		? ""
		: d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function MessageTimeline({
	activeJob,
	historyLoading,
	historyError,
	hasMoreHistory = false,
	onRetryHistory,
	onLoadMoreHistory,
	autoScrollEnabled = true,
	items,
	onPreviewAttachment,
	onPreviewHtml,
	onSaveAttachment,
	onShortcutClick,
	onAddReference,
	onAddSelectionReference,
	onOpenImage,
	onCancelJob,
}: MessageTimelineProps) {
	const { t } = useTranslation();
	// 始终窗口化：仅渲染最近 visibleCount 条已加载消息，避免长历史全量渲染卡顿。
	// 用户上滑/点击加载更早时同时增大 visibleCount 展开更多本地已加载项。
	const [visibleCount, setVisibleCount] = useState(WINDOW_SIZE);
	const visibleItems =
		items.length > visibleCount ? items.slice(-visibleCount) : items;
	const timelineRef = useRef<HTMLDivElement>(null);
	// 是否贴附底部：用户向上滚动查看历史时暂停自动滚动（智能暂停）
	const stickToBottomRef = useRef(true);
	// 程序化滚动标志：避免程序化滚动触发 handleTimelineScroll 重置 stickToBottom
	const isProgrammaticScrollRef = useRef(false);
	// 历史加载状态：用于检测"加载完成"时刻（true → false）触发滚底
	const prevHistoryLoadingRef = useRef(false);
	const loadingMoreRef = useRef(false);

	const isCurrentlyThinking = isJobRunning(activeJob);
	// 本地是否还有已加载但被窗口裁掉、未展示的更早消息
	const hasHiddenLocalItems = items.length > visibleItems.length;
	// 加载更早控件可用：本地有未展开项，或后端还有更早历史
	const canLoadMore = hasHiddenLocalItems || hasMoreHistory;

	// 锚定滚动位置：在 mutate（展开 visibleCount / 拉取后端）前后保持顶部锚点不跳动
	function withScrollAnchor(mutate: () => void): void {
		const el = timelineRef.current;
		const previousScrollHeight = el?.scrollHeight ?? 0;
		const previousScrollTop = el?.scrollTop ?? 0;
		mutate();
		requestAnimationFrame(() => {
			const nextEl = timelineRef.current;
			if (nextEl) {
				nextEl.scrollTop =
					nextEl.scrollHeight - previousScrollHeight + previousScrollTop;
			}
		});
	}

	async function loadMoreHistory(): Promise<void> {
		// 优先展开本地已加载项（无需访问后端）
		if (hasHiddenLocalItems) {
			withScrollAnchor(() => {
				setVisibleCount((count) => count + WINDOW_SIZE);
			});
			return;
		}
		if (!hasMoreHistory || historyLoading || !onLoadMoreHistory) {
			return;
		}
		const el = timelineRef.current;
		const previousScrollHeight = el?.scrollHeight ?? 0;
		const previousScrollTop = el?.scrollTop ?? 0;
		loadingMoreRef.current = true;
		try {
			await onLoadMoreHistory();
		} finally {
			requestAnimationFrame(() => {
				// 拉取到的更早消息已 prepend 到 items，同步扩大窗口让其可见
				setVisibleCount((count) => count + WINDOW_SIZE);
				const nextEl = timelineRef.current;
				if (nextEl) {
					nextEl.scrollTop =
						nextEl.scrollHeight - previousScrollHeight + previousScrollTop;
				}
				loadingMoreRef.current = false;
			});
		}
	}

	function scrollToBottom(): void {
		const el = timelineRef.current;
		if (!el) return;
		isProgrammaticScrollRef.current = true;
		el.scrollTop = el.scrollHeight;
		requestAnimationFrame(() => {
			isProgrammaticScrollRef.current = false;
		});
	}

	function handleTimelineScroll(): void {
		// 滚动后选区浮层位置失效（fixed 视口坐标），随滚动关闭
		if (selectionRef) {
			setSelectionRef(null);
		}
		if (isProgrammaticScrollRef.current) return; // 程序化滚动不更新 stickToBottom
		const el = timelineRef.current;
		if (!el) return;
		stickToBottomRef.current =
			el.scrollHeight - el.scrollTop - el.clientHeight < 80;
		if (
			el.scrollTop < 72 &&
			canLoadMore &&
			!historyLoading &&
			!loadingMoreRef.current
		) {
			void loadMoreHistory();
		}
	}

	// 流式滚动：新工具调用/文本变化时滚底（发送后也由此滚底，无需单独"发送滚顶"）
	const streamSignature = activeJob
		? [
				activeJob.jobId,
				activeJob.reply.length,
				activeJob.currentStage,
				activeJob.currentStageDetail,
				activeJob.currentToolCalls.length,
				activeJob.currentAgentStages.length,
			].join(":")
		: "";
	const prevSigRef = useRef<{ jobId: string | null; toolCount: number }>({
		jobId: null,
		toolCount: 0,
	});
	// biome-ignore lint/correctness/useExhaustiveDependencies: streamSignature + activeJob 作为流式信号
	useEffect(() => {
		if (!activeJob) return;
		const jobId = activeJob.jobId;
		const toolCount = activeJob.currentToolCalls.length;
		const prev = prevSigRef.current;
		const isNewJob = jobId !== prev.jobId;
		if (isNewJob) {
			// 新 job：重置基线
			prev.jobId = jobId;
			prev.toolCount = toolCount;
		}
		// 尊重外部自动滚动开关（契约 1）：关闭时仅更新基线，不自动滚底
		if (!autoScrollEnabled) {
			prev.toolCount = toolCount;
			return;
		}
		const raf = requestAnimationFrame(() => {
			if (isNewJob || toolCount > prev.toolCount) {
				// 新 job 或新工具调用：强制滚底 + 恢复跟随
				stickToBottomRef.current = true;
				scrollToBottom();
			} else if (stickToBottomRef.current) {
				// 文本/阶段变化：贴底跟随
				scrollToBottom();
			}
			prev.toolCount = toolCount;
		});
		return () => cancelAnimationFrame(raf);
	}, [streamSignature, activeJob, autoScrollEnabled]);

	// 初次加载历史/切换会话完成：滚到底部（监听 historyLoading 从 true → false）
	// biome-ignore lint/correctness/useExhaustiveDependencies: historyLoading 作为加载完成信号
	useEffect(() => {
		const prev = prevHistoryLoadingRef.current;
		const current = Boolean(historyLoading);
		prevHistoryLoadingRef.current = current;
		if (prev && !current && visibleItems.length > 0) {
			if (loadingMoreRef.current || !autoScrollEnabled) {
				return;
			}
			// 历史加载完成：滚底 + 恢复跟随
			stickToBottomRef.current = true;
			const raf = requestAnimationFrame(scrollToBottom);
			return () => cancelAnimationFrame(raf);
		}
	}, [historyLoading]);

	// 切换会话：滚到底部（覆盖"点击进入有缓存的对话"场景，此时 historyLoading 无 true→false 转换）
	// biome-ignore lint/correctness/useExhaustiveDependencies: key 作为切换信号（MessageTimeline 用 key={conversationId}）
	useEffect(() => {
		if (visibleItems.length > 0 && autoScrollEnabled) {
			stickToBottomRef.current = true;
			const raf = requestAnimationFrame(scrollToBottom);
			return () => cancelAnimationFrame(raf);
		}
	}, []);

	// 快捷模板：稳定 id 作 React key（不随 locale 变化），title/desc/prompt 走 i18n
	const shortcuts = [
		{
			id: "shortcut.news",
			icon: (
				<svg
					aria-hidden="true"
					fill="none"
					height="20"
					stroke="currentColor"
					strokeLinecap="round"
					strokeLinejoin="round"
					strokeWidth="2"
					viewBox="0 0 24 24"
					width="20"
				>
					<circle cx="11" cy="11" r="8" />
					<line x1="21" x2="16.65" y1="21" y2="16.65" />
				</svg>
			),
			title: t("shortcut.news.title"),
			desc: t("shortcut.news.desc"),
			prompt: t("shortcut.news.prompt"),
		},
		{
			id: "shortcut.joke",
			icon: (
				<svg
					aria-hidden="true"
					fill="none"
					height="20"
					stroke="currentColor"
					strokeLinecap="round"
					strokeLinejoin="round"
					strokeWidth="2"
					viewBox="0 0 24 24"
					width="20"
				>
					<circle cx="12" cy="12" r="10" />
					<path d="M8 14s1.5 2 4 2 4-2 4-2" />
					<line x1="9" x2="9.01" y1="9" y2="9" />
					<line x1="15" x2="15.01" y1="9" y2="9" />
				</svg>
			),
			title: t("shortcut.joke.title"),
			desc: t("shortcut.joke.desc"),
			prompt: t("shortcut.joke.prompt"),
		},
		{
			id: "shortcut.polish",
			icon: (
				<svg
					aria-hidden="true"
					fill="none"
					height="20"
					stroke="currentColor"
					strokeLinecap="round"
					strokeLinejoin="round"
					strokeWidth="2"
					viewBox="0 0 24 24"
					width="20"
				>
					<path d="M12 20h9" />
					<path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
				</svg>
			),
			title: t("shortcut.polish.title"),
			desc: t("shortcut.polish.desc"),
			prompt: t("shortcut.polish.prompt"),
		},
		{
			id: "shortcut.code",
			icon: (
				<svg
					aria-hidden="true"
					fill="none"
					height="20"
					stroke="currentColor"
					strokeLinecap="round"
					strokeLinejoin="round"
					strokeWidth="2"
					viewBox="0 0 24 24"
					width="20"
				>
					<polyline points="16 18 22 12 16 6" />
					<polyline points="8 6 2 12 8 18" />
				</svg>
			),
			title: t("shortcut.code.title"),
			desc: t("shortcut.code.desc"),
			prompt: t("shortcut.code.prompt"),
		},
	];

	// 划词引用浮层（契约 2）：选中正文文本时显示"引用"按钮，点击回传选区文本。
	// 仅在 App 提供 onAddSelectionReference 时启用。
	const [selectionRef, setSelectionRef] = useState<{
		text: string;
		top: number;
		left: number;
	} | null>(null);

	function clearSelectionRef(): void {
		setSelectionRef(null);
	}

	function handleSelectionPointerUp(): void {
		if (!onAddSelectionReference) {
			return;
		}
		const selection = window.getSelection();
		const text = selection?.toString().trim() ?? "";
		const container = timelineRef.current;
		if (!selection || selection.rangeCount === 0 || !text || !container) {
			clearSelectionRef();
			return;
		}
		const range = selection.getRangeAt(0);
		// 选区必须落在时间线容器内（避免选到输入框/侧栏等区域）
		if (!container.contains(range.commonAncestorContainer)) {
			clearSelectionRef();
			return;
		}
		// 视口坐标 + position:fixed，不依赖容器是否为定位上下文（CSS 归 WF1/其他分区）。
		// getBoundingClientRect 在部分环境（如 jsdom）未实现，缺失时退化为左上角定位。
		const rect =
			typeof range.getBoundingClientRect === "function"
				? range.getBoundingClientRect()
				: null;
		setSelectionRef({
			text,
			top: rect?.top ?? 0, // 浮层显示在选区上方
			left: (rect?.left ?? 0) + (rect?.width ?? 0) / 2,
		});
	}

	function confirmSelectionRef(): void {
		if (selectionRef) {
			onAddSelectionReference?.(selectionRef.text);
		}
		window.getSelection()?.removeAllRanges();
		clearSelectionRef();
	}

	return (
		<section className="timeline-shell">
			<div
				aria-label={t("timeline.label")}
				className="timeline"
				onScroll={handleTimelineScroll}
				onMouseUp={handleSelectionPointerUp}
				role="log"
				ref={timelineRef}
			>
				{historyError && visibleItems.length === 0 && !activeJob ? (
					<div className="timeline-error">
						<p className="timeline-error-text">{historyError}</p>
						{onRetryHistory ? (
							<button
								className="ghost-button"
								onClick={onRetryHistory}
								type="button"
							>
								{t("timeline.retry")}
							</button>
						) : null}
					</div>
				) : historyLoading && visibleItems.length === 0 && !activeJob ? (
					<div className="timeline-loading">
						<span aria-hidden="true" className="timeline-spinner" />
						<p>{t("timeline.loadingConversation")}</p>
					</div>
				) : visibleItems.length === 0 && !activeJob ? (
					<div className="welcome-container">
						<div className="welcome-logo">
							<svg
								aria-hidden="true"
								fill="none"
								height="36"
								stroke="currentColor"
								strokeLinecap="round"
								strokeLinejoin="round"
								strokeWidth="2.5"
								viewBox="0 0 24 24"
								width="36"
							>
								<title>Undefined Logo</title>
								<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
							</svg>
						</div>
						<div className="welcome-header">
							<h2>{t("timeline.welcomeTitle")}</h2>
							<p>{t("timeline.welcomeSubtitle")}</p>
						</div>
						<div className="shortcut-grid">
							{shortcuts.map((card) => (
								<button
									className="shortcut-card"
									key={card.id}
									onClick={() => onShortcutClick?.(card.prompt)}
									type="button"
								>
									<span className="icon">{card.icon}</span>
									<span className="title">{card.title}</span>
									<span className="desc">{card.desc}</span>
								</button>
							))}
						</div>
					</div>
				) : null}

				{visibleItems.length === 0 && activeJob ? (
					<div
						style={{
							margin: "auto",
							textAlign: "center",
							color: "var(--text-tertiary)",
							fontSize: "0.9rem",
						}}
					>
						{t("timeline.noMessages")}
					</div>
				) : null}

				{visibleItems.length > 0 && (canLoadMore || historyLoading) ? (
					<div className="timeline-load-more">
						<button
							className="ghost-button"
							disabled={!canLoadMore || Boolean(historyLoading)}
							onClick={() => {
								void loadMoreHistory();
							}}
							type="button"
						>
							{historyLoading
								? t("timeline.loadingEarlier")
								: t("timeline.loadMoreEarlier")}
						</button>
					</div>
				) : null}

				{visibleItems.map((item) => {
					const isBot = item.role === "bot";
					const durationMs = item.webchat?.durationMs ?? null;
					const hasDuration =
						typeof durationMs === "number" &&
						Number.isFinite(durationMs) &&
						durationMs >= 0;
					const timeText = formatMessageTime(item.timestamp);
					return (
						<article
							className={`runtime-chat-item ${item.role}`}
							data-message-id={item.messageId}
							data-testid="message-row"
							key={item.messageId}
						>
							<div className="runtime-chat-role">
								<span className="runtime-chat-role-label">
									{isBot ? t("timeline.roleAi") : t("timeline.roleYou")}
								</span>
								{isBot && hasDuration ? (
									<ChatStageLabel
										stage="done"
										stageDetail={null}
										startedAt={null}
										finalState
										elapsedMsOverride={durationMs}
									/>
								) : null}
								{onAddReference && isBot ? (
									<MessageQuoteButton
										messageId={item.messageId}
										onQuote={onAddReference}
									/>
								) : null}
								{timeText ? (
									<span className="runtime-chat-time">{timeText}</span>
								) : null}
							</div>
							<div
								className={`runtime-chat-content${isBot ? " markdown" : ""}`}
							>
								{item.references.length > 0
									? item.references.map((reference) => (
											<blockquote
												className="runtime-quote-block"
												key={reference.messageId}
											>
												{reference.quote}
											</blockquote>
										))
									: null}
								{(() => {
									// bot 消息含工具调用/分段文本时，按统一时间线渲染（正文与工具块按序穿插，避免正文重复）。
									// timeline 缺失时回退 calls/events 重建（buildHistoryTimeline 内部已按优先级处理）。
									const timeline = isBot
										? buildHistoryTimeline(item.webchat)
										: null;
									if (timeline) {
										return (
											<MessageTimelineContent
												timeline={timeline}
												fallbackContent={item.content}
												attachments={item.attachments}
												onPreviewHtml={onPreviewHtml}
												onImageClick={onOpenImage}
											/>
										);
									}
									// 普通消息：直接渲染正文
									return (
										<MarkdownContent
											content={item.content}
											onPreviewHtml={onPreviewHtml}
											attachments={item.attachments}
											onImageClick={onOpenImage}
										/>
									);
								})()}
								{(() => {
									// 正文已内联渲染的图片 uid（避免与附件区重复）；
									// 未在正文引用的图片（如用户上传）仍在附件区展示。
									const inlinedUids = new Set(
										extractAttachmentTags(item.content).attachmentUids,
									);
									return item.attachments
										.filter(
											(attachment) =>
												!(
													isImageAttachment(attachment) &&
													inlinedUids.has(attachment.id)
												),
										)
										.map((attachment) => (
											<AttachmentCard
												attachment={attachment}
												key={attachment.id || attachment.name}
												onPreview={onPreviewAttachment}
												onDownload={onSaveAttachment}
												onOpenImage={onOpenImage}
											/>
										));
								})()}
							</div>
						</article>
					);
				})}

				{/* 流式 bot 气泡：activeJob 存在且运行中时立即显示 */}
				{activeJob && isCurrentlyThinking ? (
					<article
						className="runtime-chat-item bot streaming"
						data-testid="streaming-message"
						key={`streaming-${activeJob.jobId}`}
					>
						<div className="runtime-chat-role">
							<span className="runtime-chat-role-label">
								{t("timeline.roleAi")}
							</span>
							<ChatStageLabel
								stage={activeJob.currentStage}
								stageDetail={activeJob.currentStageDetail ?? null}
								startedAt={activeJob.currentStageStartedAt ?? null}
								finalState={activeJob.status === "done"}
							/>
							{onCancelJob ? (
								<button
									className="runtime-chat-quote-btn is-visible"
									onClick={() => onCancelJob(activeJob.jobId)}
									type="button"
								>
									{t("timeline.cancel")}
								</button>
							) : null}
							{onAddReference ? (
								<MessageQuoteButton
									messageId={activeJob.jobId}
									onQuote={onAddReference}
								/>
							) : null}
						</div>
						<div className="runtime-chat-content markdown">
							<MessageTimelineContent
								timeline={buildStreamingTimeline(activeJob)}
								fallbackContent={activeJob.reply || ""}
								attachments={[]}
								onPreviewHtml={onPreviewHtml}
								onImageClick={onOpenImage}
							/>
						</div>
					</article>
				) : null}
			</div>

			{/* 划词引用浮层（契约 2）：选中正文文本后浮现的"引用"按钮 */}
			{selectionRef ? (
				<button
					className="timeline-selection-quote"
					onMouseDown={(e) => {
						// 阻止默认行为，避免点击按钮时清空当前文本选区
						e.preventDefault();
					}}
					onClick={confirmSelectionRef}
					style={{
						position: "fixed",
						top: Math.max(8, selectionRef.top - 40),
						left: selectionRef.left,
						transform: "translateX(-50%)",
						zIndex: 30,
					}}
					type="button"
				>
					{t("quote.button")}
				</button>
			) : null}
		</section>
	);
}
