import { useEffect, useRef, useState } from "react";
import { isJobRunning } from "../chat-store/store";
import {
	type HtmlPreviewRequest,
	MarkdownContent,
} from "../rendering/MarkdownContent";
import type {
	Attachment,
	ChatEvent,
	ChatJob,
	ConnectionState,
	HistoryItem,
} from "../runtime-client/types";
import { AttachmentCard } from "./AttachmentCard";
import {
	MessageTimelineContent,
	hasRenderableTimeline,
} from "./MessageTimelineContent";

export type MessageTimelineProps = {
	activeJob: ChatJob | null;
	connectionState: ConnectionState;
	events: ChatEvent[];
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

function eventLabel(event: ChatEvent): string {
	const payload = event.payload;
	if (typeof payload.error === "string") {
		return payload.error;
	}
	const name =
		typeof payload.name === "string"
			? payload.name
			: typeof payload.agent_name === "string"
				? payload.agent_name
				: typeof payload.stage === "string"
					? payload.stage
					: event.event;
	const detail =
		typeof payload.result_preview === "string"
			? payload.result_preview
			: typeof payload.detail === "string"
				? payload.detail
				: "";
	return detail ? `${name} ${detail}` : name;
}

export function MessageTimeline({
	activeJob,
	events,
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
	const [isThinkingExpanded, setIsThinkingExpanded] = useState(false);
	const timelineRef = useRef<HTMLDivElement>(null);
	// 是否贴附底部：用户向上滚动查看历史时暂停自动滚动（智能暂停）
	const stickToBottomRef = useRef(true);

	const isCurrentlyThinking = isJobRunning(activeJob);
	const hasEventsOrActiveJob = Boolean(activeJob || events.length > 0);

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
	}, [
		visibleItems.length,
		lastItemId,
		streamSignature,
		events.length,
		isThinkingExpanded,
	]);

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
			prompt: "/search 搜索今日国内国际新闻热点",
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
				{visibleItems.length === 0 && !activeJob ? (
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

				{/* 思考中...折叠手风琴 */}
				{hasEventsOrActiveJob ? (
					<div
						className={`thinking-box ${isThinkingExpanded ? "expanded" : ""}`}
						style={{ animation: "fadeInUp 0.3s ease" }}
					>
						<button
							className="thinking-header"
							onClick={() => setIsThinkingExpanded(!isThinkingExpanded)}
							type="button"
							style={{
								width: "100%",
								border: "none",
								outline: "none",
								boxShadow: "none",
								background: "transparent",
								cursor: "pointer",
								padding: 0,
							}}
						>
							<div className="thinking-title-block">
								{isCurrentlyThinking ? (
									<div className="thinking-dot-spinner" />
								) : (
									<svg
										fill="none"
										height="14"
										stroke="var(--status-success)"
										strokeLinecap="round"
										strokeLinejoin="round"
										strokeWidth="2.5"
										viewBox="0 0 24 24"
										width="14"
									>
										<title>完成</title>
										<polyline points="20 6 9 17 4 12" />
									</svg>
								)}
								<span>
									{isCurrentlyThinking ? "思考中..." : "思考完成"}
									{activeJob?.currentStage
										? ` (${activeJob.currentStage})`
										: ""}
								</span>
								{activeJob?.currentStageDetail ? (
									<span style={{ marginLeft: "4px" }}>
										{activeJob.currentStageDetail}
									</span>
								) : null}
							</div>
							<svg
								className="thinking-chevron"
								fill="none"
								height="16"
								stroke="currentColor"
								strokeLinecap="round"
								strokeLinejoin="round"
								strokeWidth="2"
								viewBox="0 0 24 24"
								width="16"
							>
								<title>展开/收起</title>
								<polyline points="6 9 12 15 18 9" />
							</svg>
						</button>

						<div className="thinking-content">
							{/* 工具/Agent子状态指示器 */}
							{(activeJob?.currentToolCalls &&
								activeJob.currentToolCalls.length > 0) ||
							(activeJob?.currentAgentStages &&
								activeJob.currentAgentStages.length > 0) ? (
								<div
									className="runtime-timeline"
									style={{
										display: "flex",
										gap: "6px",
										marginBottom: "12px",
										flexWrap: "wrap",
									}}
								>
									{activeJob?.currentToolCalls?.map((call) => (
										<div className="runtime-pill" key={call.id}>
											<span style={{ fontWeight: "600" }}>{call.name}</span>
											<span style={{ opacity: 0.7, fontSize: "0.75rem" }}>
												{call.status}
											</span>
										</div>
									))}
									{activeJob?.currentAgentStages?.map((stage) => (
										<div className="runtime-pill" key={stage.id}>
											<span style={{ fontWeight: "600" }}>{stage.name}</span>
											<span style={{ opacity: 0.7, fontSize: "0.75rem" }}>
												{stage.stage}
											</span>
										</div>
									))}
								</div>
							) : null}

							{/* 事件流详细输出 */}
							{events.length > 0 ? (
								<ol className="event-list">
									{events.map((event) => (
										<li
											className={`event-item event-${event.event}`}
											key={event.seq}
										>
											<span className="event-type-badge">{event.event}</span>
											<span>{eventLabel(event)}</span>
										</li>
									))}
								</ol>
							) : (
								<div
									style={{ color: "var(--text-tertiary)", fontSize: "0.8rem" }}
								>
									无运行日志
								</div>
							)}
						</div>
					</div>
				) : null}
			</div>
		</section>
	);
}
