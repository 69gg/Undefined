import { useEffect, useRef, useState } from "react";
import { isJobRunning } from "../chat-store/store";
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
import { AttachmentCard } from "./AttachmentCard";
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
	onAddReference?: (messageId: string, quote: string) => void;
	onOpenImage?: (src: string, alt: string) => void;
	runtimeUrl?: string;
};

const WINDOW_SIZE = 64;

type HistoryToolCall = {
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
	const timeline: HistoryTimelineEntry[] = [];

	// 有文本时先输出文本
	if (job.reply.trim()) {
		timeline.push({ type: "message", content: job.reply });
	}

	// 输出所有工具调用
	for (const toolCall of job.currentToolCalls) {
		timeline.push({
			type: "call",
			call: convertToolCallSnapshot(toolCall),
		});
	}

	return timeline;
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
	runtimeUrl,
}: MessageTimelineProps) {
	const visibleItems = items.slice(-WINDOW_SIZE);
	const timelineRef = useRef<HTMLDivElement>(null);
	// 是否贴附底部：用户向上滚动查看历史时暂停自动滚动（智能暂停）
	const stickToBottomRef = useRef(true);

	const isCurrentlyThinking = isJobRunning(activeJob);

	// 实时用时：运行中每 200ms 刷新，完成后显示最终用时
	const [nowMs, setNowMs] = useState(() => Date.now());
	useEffect(() => {
		if (!isCurrentlyThinking) return;
		const timer = setInterval(() => setNowMs(Date.now()), 200);
		return () => clearInterval(timer);
	}, [isCurrentlyThinking]);
	const elapsedMs = activeJob
		? isCurrentlyThinking
			? Math.max(0, nowMs - activeJob.createdAt * 1000)
			: (activeJob.durationMs ?? activeJob.elapsedMs)
		: 0;
	const elapsedLabel =
		elapsedMs >= 1000
			? `${(elapsedMs / 1000).toFixed(1)}s`
			: `${Math.round(elapsedMs)}ms`;

	function handleTimelineScroll(): void {
		const el = timelineRef.current;
		if (!el) return;
		stickToBottomRef.current =
			el.scrollHeight - el.scrollTop - el.clientHeight < 80;
	}

	// 自动滚动到底部：覆盖新消息、流式回复增长、工具块/事件更新、思考展开等撑高情形；
	// 仅在贴附底部时滚动（智能暂停），并用双 rAF 等待布局与图片等异步撑高后再滚，确保彻底到底。
	const lastItemId = visibleItems[visibleItems.length - 1]?.messageId;
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
	// biome-ignore lint/correctness/useExhaustiveDependencies: 下列信号仅作为滚动触发器
	useEffect(() => {
		if (!stickToBottomRef.current) return;
		const el = timelineRef.current;
		if (!el) return;
		let raf2 = 0;
		const raf1 = requestAnimationFrame(() => {
			el.scrollTop = el.scrollHeight;
			raf2 = requestAnimationFrame(() => {
				el.scrollTop = el.scrollHeight;
			});
		});
		return () => {
			cancelAnimationFrame(raf1);
			cancelAnimationFrame(raf2);
		};
	}, [visibleItems.length, lastItemId, streamSignature]);

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

				{visibleItems.map((item) => (
					<article
						className={`message-row message-row-${item.role}`}
						data-testid="message-row"
						key={item.messageId}
					>
						{/* 头像 */}
						<div
							className={`avatar-wrapper avatar-${item.role}`}
							style={{
								background:
									item.role === "bot"
										? "var(--primary)"
										: "var(--primary-subtle)",
								color: item.role === "bot" ? "#ffffff" : "var(--primary)",
								display: "flex",
								alignItems: "center",
								justifyContent: "center",
								fontWeight: "600",
								fontSize: "0.85rem",
							}}
						>
							{item.role === "bot" ? "U" : "你"}
						</div>

						{/* 消息气泡 */}
						<div className="message-bubble">
							{item.references.length > 0 ? (
								<div className="reference-stack">
									{item.references.map((reference) => (
										<blockquote key={reference.messageId}>
											引用 {reference.quote}
										</blockquote>
									))}
								</div>
							) : null}

							{(() => {
								const timeline = item.webchat?.timeline;
								// bot 消息含工具调用/分段文本时，按统一时间线渲染（正文与工具块按序穿插，避免正文重复）
								if (item.role === "bot" && hasRenderableTimeline(timeline)) {
									return (
										<MessageTimelineContent
											timeline={timeline ?? []}
											fallbackContent={item.content}
											attachments={item.attachments}
											runtimeUrl={runtimeUrl}
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
										runtimeUrl={runtimeUrl}
										onImageClick={onOpenImage}
									/>
								);
							})()}

							{item.attachments.length > 0 ? (
								<div
									className="attachment-list"
									style={{
										display: "flex",
										flexDirection: "column",
										gap: "8px",
										marginTop: "12px",
									}}
								>
									{item.attachments.map((attachment) => (
										<AttachmentCard
											key={attachment.id || attachment.name}
											attachment={attachment}
											onPreview={(att) => {
												if (
													onOpenImage &&
													att.mediaType?.startsWith("image/")
												) {
													onOpenImage(
														att.previewUrl || att.downloadUrl || "",
														att.name,
													);
												} else {
													onPreviewAttachment(att);
												}
											}}
											onDownload={onSaveAttachment}
										/>
									))}
								</div>
							) : null}

							<div className="message-meta">
								<span>
									{item.role === "bot" ? "Undefined" : "你"}{" "}
									{typeof item.timestamp === "number"
										? new Date(item.timestamp * 1000).toLocaleTimeString([], {
												hour: "2-digit",
												minute: "2-digit",
											})
										: ""}
								</span>
								{onAddReference && item.role === "bot" ? (
									<button
										className="ghost-button"
										onClick={() => onAddReference(item.messageId, item.content)}
										style={{ padding: "2px 8px", fontSize: "0.7rem" }}
										title="引用这条消息"
										type="button"
									>
										引用
									</button>
								) : null}
							</div>
						</div>
					</article>
				))}

				{/* 流式 bot 气泡：activeJob 存在且运行中时立即显示 */}
				{activeJob && isCurrentlyThinking ? (
					<article
						className="message-row message-row-bot streaming"
						data-testid="streaming-message"
						key={`streaming-${activeJob.jobId}`}
					>
						{/* 头像 */}
						<div
							className="avatar-wrapper avatar-bot"
							style={{
								background: "var(--primary)",
								color: "#ffffff",
								display: "flex",
								alignItems: "center",
								justifyContent: "center",
								fontWeight: "600",
								fontSize: "0.85rem",
							}}
						>
							U
						</div>

						{/* 消息气泡 */}
						<div className="message-bubble">
							<MessageTimelineContent
								timeline={buildStreamingTimeline(activeJob)}
								fallbackContent={activeJob.reply || "思考中..."}
								attachments={[]}
								runtimeUrl={runtimeUrl}
								onPreviewHtml={onPreviewHtml}
								onImageClick={onOpenImage}
							/>

							<div className="message-meta">
								<span>
									Undefined{elapsedMs > 0 ? ` · ${elapsedLabel}` : ""}
								</span>
							</div>
						</div>
					</article>
				) : null}
			</div>
		</section>
	);
}
