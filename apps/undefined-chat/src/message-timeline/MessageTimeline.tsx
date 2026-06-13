import { useState } from "react";
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
}: MessageTimelineProps) {
	const visibleItems = items.slice(-WINDOW_SIZE);
	const [isThinkingExpanded, setIsThinkingExpanded] = useState(false);

	const isCurrentlyThinking = isJobRunning(activeJob);
	const hasEventsOrActiveJob = Boolean(activeJob || events.length > 0);

	const shortcuts = [
		{
			icon: "🔍",
			title: "今日新闻",
			desc: "获取最新时事与突发热点",
			prompt: "/search 搜索今日国内国际新闻热点",
		},
		{
			icon: "❄️",
			title: "讲冷笑话",
			desc: "来个冷笑话轻松幽默一下",
			prompt: "给我讲个有创意的冷笑话吧",
		},
		{
			icon: "📝",
			title: "文章润色",
			desc: "帮你改进文章段落的措辞",
			prompt: "请帮我润色以下这段文字，使其读起来更加专业、优雅：\n",
		},
		{
			icon: "💻",
			title: "代码解释",
			desc: "分析特定代码并给出优化方案",
			prompt: "请帮我详细分析和解释以下这段代码：\n```python\n\n```",
		},
	];

	return (
		<section className="timeline-shell">
			<div aria-label="消息" className="timeline" role="log">
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
							{item.role === "bot" ? "🤖" : "👤"}
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

							<MarkdownContent
								content={item.content}
								onPreviewHtml={onPreviewHtml}
							/>

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
