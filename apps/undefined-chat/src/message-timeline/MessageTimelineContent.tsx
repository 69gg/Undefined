import {
	type HtmlPreviewRequest,
	MarkdownContent,
} from "../rendering/MarkdownContent";
import type { Attachment } from "../runtime-client/types";
import "./ToolBlock.css";

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
	timeline?: HistoryTimelineEntry[];
};

type HistoryTimelineEntry = {
	type: string;
	content?: string;
	stage?: string;
	detail?: string;
	call?: HistoryToolCall;
};

export type MessageTimelineContentProps = {
	timeline: unknown[];
	/** 完整正文，timeline 中无任何顶层 message 文本时作为兜底渲染 */
	fallbackContent?: string;
	attachments?: Attachment[];
	runtimeUrl?: string;
	onPreviewHtml: (input: HtmlPreviewRequest) => void;
	onImageClick?: (src: string, alt: string) => void;
};

function formatDurationMs(ms: number | undefined): string {
	if (ms === undefined || ms <= 0) return "";
	if (ms < 1000) return `${Math.round(ms)}ms`;
	const seconds = ms / 1000;
	if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
	const minutes = Math.floor(seconds / 60);
	const remainder = Math.floor(seconds % 60);
	return `${minutes}m ${remainder}s`;
}

function statusLabel(status: string): string {
	switch (status) {
		case "done":
			return "完成";
		case "error":
			return "失败";
		case "cancelled":
			return "已取消";
		case "running":
			return "运行中";
		default:
			return status;
	}
}

function isToolCall(node: unknown): node is HistoryToolCall {
	return (
		node !== null &&
		typeof node === "object" &&
		"name" in (node as Record<string, unknown>)
	);
}

function normalizeEntries(timeline: unknown[]): HistoryTimelineEntry[] {
	if (!Array.isArray(timeline)) return [];
	return timeline.filter(
		(e): e is HistoryTimelineEntry =>
			e !== null && typeof e === "object" && "type" in e,
	);
}

/**
 * 判断 timeline 是否包含可渲染的工具调用或消息片段。
 * 仅在为真时才走统一时间线渲染模式。
 */
export function hasRenderableTimeline(
	timeline: unknown[] | undefined,
): boolean {
	const entries = normalizeEntries(timeline ?? []);
	return entries.some(
		(e) =>
			(e.type === "call" && isToolCall(e.call)) ||
			(e.type === "message" && Boolean(e.content?.trim())),
	);
}

/** 工具块内部的子时间线条目（轻量纯文本展示，对齐 webui runtime-tool-message） */
function RenderNestedEntry({ entry }: { entry: HistoryTimelineEntry }) {
	if (entry.type === "call" && isToolCall(entry.call)) {
		return <RenderToolCall call={entry.call} />;
	}
	if (entry.type === "message" && entry.content?.trim()) {
		return <div className="runtime-tool-message">{entry.content}</div>;
	}
	return null;
}

function RenderToolCall({ call }: { call: HistoryToolCall }) {
	const duration = formatDurationMs(call.duration_ms);
	const status = call.status || "done";
	const kindClass = call.is_agent ? " is-agent" : " is-tool";
	const kindLabel = call.is_agent ? "Agent" : "工具";
	const meta = statusLabel(status);

	const childTimeline = Array.isArray(call.timeline)
		? call.timeline.filter(
				(e): e is HistoryTimelineEntry => e !== null && typeof e === "object",
			)
		: [];
	const childCalls = Array.isArray(call.children)
		? call.children.filter(isToolCall)
		: [];

	const nestedContent: HistoryTimelineEntry[] =
		childTimeline.length > 0
			? childTimeline
			: childCalls.map((c) => ({ type: "call", call: c }));

	return (
		<details className={`runtime-tool-block ${status}${kindClass}`}>
			<summary>
				<span className="runtime-tool-summary-main">
					<span className="runtime-tool-title">
						<code className="runtime-tool-name">{call.name || "--"}</code>
						{duration && (
							<span className="runtime-tool-duration">{duration}</span>
						)}
					</span>
				</span>
				<em className="runtime-tool-status">{meta}</em>
				<span className="runtime-tool-kind">{kindLabel}</span>
			</summary>

			{call.arguments_preview && (
				<div className="runtime-tool-preview">
					<div className="runtime-tool-preview-label">输入</div>
					<pre className="runtime-tool-preview-body">
						{call.arguments_preview}
					</pre>
				</div>
			)}

			{nestedContent.length > 0 && (
				<div className="runtime-tool-children">
					{nestedContent.map((entry, idx) => (
						// biome-ignore lint/suspicious/noArrayIndexKey: 历史记录只读不变
						<RenderNestedEntry key={idx} entry={entry} />
					))}
				</div>
			)}

			{call.result_preview && (
				<div className="runtime-tool-preview">
					<div className="runtime-tool-preview-label">输出</div>
					<pre className="runtime-tool-preview-body">{call.result_preview}</pre>
				</div>
			)}
		</details>
	);
}

/**
 * 渲染一条 bot 消息的完整时间线：按顺序穿插顶层文本片段（message）与工具调用（call）。
 * 顶层文本用完整 Markdown 渲染（图片/代码/附件/引用）；工具调用用折叠块展示。
 */
export function MessageTimelineContent({
	timeline,
	fallbackContent,
	attachments = [],
	runtimeUrl,
	onPreviewHtml,
	onImageClick,
}: MessageTimelineContentProps) {
	const entries = normalizeEntries(timeline);
	const hasMessageText = entries.some(
		(e) => e.type === "message" && Boolean(e.content?.trim()),
	);

	return (
		<div className="message-timeline-content">
			{entries.map((entry, idx) => {
				if (entry.type === "call" && isToolCall(entry.call)) {
					return (
						// biome-ignore lint/suspicious/noArrayIndexKey: 历史记录只读不变
						<RenderToolCall key={idx} call={entry.call} />
					);
				}
				if (entry.type === "message" && entry.content?.trim()) {
					return (
						<MarkdownContent
							// biome-ignore lint/suspicious/noArrayIndexKey: 历史记录只读不变
							key={idx}
							content={entry.content}
							onPreviewHtml={onPreviewHtml}
							attachments={attachments}
							runtimeUrl={runtimeUrl}
							onImageClick={onImageClick}
						/>
					);
				}
				return null;
			})}

			{/* timeline 中无任何顶层文本时，用完整正文兜底 */}
			{!hasMessageText && fallbackContent?.trim() ? (
				<MarkdownContent
					content={fallbackContent}
					onPreviewHtml={onPreviewHtml}
					attachments={attachments}
					runtimeUrl={runtimeUrl}
					onImageClick={onImageClick}
				/>
			) : null}
		</div>
	);
}
