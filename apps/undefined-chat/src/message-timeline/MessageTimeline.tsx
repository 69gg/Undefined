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

export type MessageTimelineProps = {
	activeJob: ChatJob | null;
	connectionState: ConnectionState;
	events: ChatEvent[];
	items: HistoryItem[];
	onPreviewHtml: (input: HtmlPreviewRequest) => void;
	onPreviewAttachment: (attachment: Attachment) => void;
	onSaveAttachment: (attachment: Attachment) => void;
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

function roleLabel(role: HistoryItem["role"]): string {
	if (role === "bot") {
		return "Undefined";
	}
	if (role === "system") {
		return "系统";
	}
	return "你";
}

function formatAttachmentSize(size: number): string {
	if (size <= 0) {
		return "";
	}
	if (size < 1024) {
		return `${size} B`;
	}
	if (size < 1024 * 1024) {
		return `${Math.round(size / 102.4) / 10} KB`;
	}
	return `${Math.round(size / 1024 / 102.4) / 10} MB`;
}

export function MessageTimeline({
	activeJob,
	connectionState,
	events,
	items,
	onPreviewAttachment,
	onPreviewHtml,
	onSaveAttachment,
}: MessageTimelineProps) {
	const visibleItems = items.slice(-WINDOW_SIZE);

	return (
		<section className="timeline-shell">
			<header className="timeline-header">
				<div>
					<strong>消息</strong>
					<span>{connectionStateLabel(connectionState)}</span>
				</div>
				{activeJob ? (
					<div className="job-status">
						<span>{activeJob.currentStage}</span>
						{activeJob.currentStageDetail ? (
							<span>{activeJob.currentStageDetail}</span>
						) : null}
					</div>
				) : null}
			</header>
			<div aria-label="消息" className="timeline" role="log">
				{visibleItems.length === 0 ? (
					<p className="empty-state">暂无消息</p>
				) : null}
				{visibleItems.map((item) => (
					<article
						className={`message-row message-row-${item.role}`}
						data-testid="message-row"
						key={item.messageId}
					>
						<div className="message-author">{roleLabel(item.role)}</div>
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
								<ul aria-label="附件" className="attachment-list">
									{item.attachments.map((attachment) => (
										<li key={attachment.id || attachment.name}>
											<span>{attachment.name}</span>
											<span>{formatAttachmentSize(attachment.size)}</span>
											<div className="attachment-actions">
												{attachment.previewUrl ? (
													<button
														type="button"
														onClick={() => onPreviewAttachment(attachment)}
													>
														预览
													</button>
												) : null}
												<button
													type="button"
													onClick={() => onSaveAttachment(attachment)}
												>
													保存
												</button>
											</div>
										</li>
									))}
								</ul>
							) : null}
						</div>
					</article>
				))}
				{activeJob ? (
					<section className="runtime-timeline" aria-label="运行状态">
						{activeJob.currentToolCalls.map((call) => (
							<div className="runtime-pill" key={call.id}>
								<span>{call.name}</span>
								<span>{call.status}</span>
							</div>
						))}
						{activeJob.currentAgentStages.map((stage) => (
							<div className="runtime-pill" key={stage.id}>
								<span>{stage.name}</span>
								<span>{stage.stage}</span>
							</div>
						))}
					</section>
				) : null}
				{events.length > 0 ? (
					<ol className="event-list">
						{events.map((event) => (
							<li className={`event-item event-${event.event}`} key={event.seq}>
								<span>{event.event}</span>
								<span>{eventLabel(event)}</span>
							</li>
						))}
					</ol>
				) : null}
			</div>
		</section>
	);
}

function connectionStateLabel(state: ConnectionState): string {
	const labels: Record<ConnectionState, string> = {
		idle: "待连接",
		connecting: "正在连接",
		connected: "已连接",
		streaming: "事件流",
		resuming: "正在续接",
		json_fallback: "JSON 轮询",
		disconnected: "连接断开",
	};
	return labels[state];
}
