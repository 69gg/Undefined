import { useEffect, useRef } from "react";
import { isJobRunning } from "../chat-store/store";
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
	/** 重试加载当前会话历史 */
	onRetryHistory?: () => void;
	items: HistoryItem[];
	onPreviewHtml: (input: HtmlPreviewRequest) => void;
	onPreviewAttachment: (attachment: Attachment) => void;
	onSaveAttachment: (attachment: Attachment) => void;
	onShortcutClick?: (prompt: string) => void;
	onAddReference?: (messageId: string) => void;
	onOpenImage?: (src: string, alt: string) => void;
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
	onRetryHistory,
	items,
	onPreviewAttachment,
	onPreviewHtml,
	onSaveAttachment,
	onShortcutClick,
	onAddReference,
	onOpenImage,
}: MessageTimelineProps) {
	const visibleItems = items.slice(-WINDOW_SIZE);
	const timelineRef = useRef<HTMLDivElement>(null);
	// 是否贴附底部：用户向上滚动查看历史时暂停自动滚动（智能暂停）
	const stickToBottomRef = useRef(true);
	// 程序化滚动标志：避免程序化滚动触发 handleTimelineScroll 重置 stickToBottom
	const isProgrammaticScrollRef = useRef(false);
	// 历史加载状态：用于检测"加载完成"时刻（true → false）触发滚底
	const prevHistoryLoadingRef = useRef(false);

	const isCurrentlyThinking = isJobRunning(activeJob);

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
		if (isProgrammaticScrollRef.current) return; // 程序化滚动不更新 stickToBottom
		const el = timelineRef.current;
		if (!el) return;
		stickToBottomRef.current =
			el.scrollHeight - el.scrollTop - el.clientHeight < 80;
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
	}, [streamSignature, activeJob]);

	// 初次加载历史/切换会话完成：滚到底部（监听 historyLoading 从 true → false）
	// biome-ignore lint/correctness/useExhaustiveDependencies: historyLoading 作为加载完成信号
	useEffect(() => {
		const prev = prevHistoryLoadingRef.current;
		const current = Boolean(historyLoading);
		prevHistoryLoadingRef.current = current;
		if (prev && !current && visibleItems.length > 0) {
			// 历史加载完成：滚底 + 恢复跟随
			stickToBottomRef.current = true;
			const raf = requestAnimationFrame(scrollToBottom);
			return () => cancelAnimationFrame(raf);
		}
	}, [historyLoading]);

	// 切换会话：滚到底部（覆盖"点击进入有缓存的对话"场景，此时 historyLoading 无 true→false 转换）
	// biome-ignore lint/correctness/useExhaustiveDependencies: key 作为切换信号（MessageTimeline 用 key={conversationId}）
	useEffect(() => {
		if (visibleItems.length > 0) {
			stickToBottomRef.current = true;
			const raf = requestAnimationFrame(scrollToBottom);
			return () => cancelAnimationFrame(raf);
		}
	}, []);

	const shortcuts = [
		{
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
			title: "今日新闻",
			desc: "获取最新时事与突发热点",
			prompt: "搜索今日国内国际新闻热点",
		},
		{
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
			title: "讲冷笑话",
			desc: "来个冷笑话轻松幽默一下",
			prompt: "给我讲个有创意的冷笑话吧",
		},
		{
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
			title: "文章润色",
			desc: "帮你改进文章段落的措辞",
			prompt: "请帮我润色以下这段文字，使其读起来更加专业、优雅：\n",
		},
		{
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
			title: "代码解释",
			desc: "分析特定代码并给出优化方案",
			prompt: "请帮我详细分析和解释以下这段代码：\n```python\n\n```",
		},
	];

	return (
		<section className="timeline-shell">
			<div
				aria-label="消息"
				className="timeline"
				onScroll={handleTimelineScroll}
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
								重试
							</button>
						) : null}
					</div>
				) : historyLoading && visibleItems.length === 0 && !activeJob ? (
					<div className="timeline-loading">
						<span aria-hidden="true" className="timeline-spinner" />
						<p>正在加载会话…</p>
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
							<h2>您好，我是 Undefined</h2>
							<p>今天想让我帮您做些什么？你可以输入指令或选择下方模板：</p>
						</div>
						<div className="shortcut-grid">
							{shortcuts.map((card) => (
								<button
									className="shortcut-card"
									key={card.title}
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
						当前会话无消息记录
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
									{isBot ? "AI" : "You"}
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
									const timeline = item.webchat?.timeline;
									// bot 消息含工具调用/分段文本时，按统一时间线渲染（正文与工具块按序穿插，避免正文重复）
									if (isBot && hasRenderableTimeline(timeline)) {
										return (
											<MessageTimelineContent
												timeline={timeline ?? []}
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
							<span className="runtime-chat-role-label">AI</span>
							<ChatStageLabel
								stage={activeJob.currentStage}
								stageDetail={activeJob.currentStageDetail ?? null}
								startedAt={activeJob.currentStageStartedAt ?? null}
								finalState={activeJob.status === "done"}
							/>
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
		</section>
	);
}
