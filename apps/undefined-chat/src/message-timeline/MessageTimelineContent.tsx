import { useCallback, useState } from "react";
import type { ToolBlock as ToolBlockType } from "../chat-store/types";
import {
	type HtmlPreviewRequest,
	MarkdownContent,
} from "../rendering/MarkdownContent";
import type { Attachment } from "../runtime-client/types";
import { ImagePreview } from "./ImagePreview";
import { ToolBlock } from "./ToolBlock";
import "./ToolBlock.css";

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
	timeline?: HistoryTimelineEntry[];
};

type HistoryTimelineEntry = {
	type: string;
	content?: string;
	stage?: string;
	detail?: string;
	call?: HistoryToolCall;
	callId?: string;
	seq?: number;
};

export type MessageTimelineContentProps = {
	timeline: unknown[];
	/** 完整正文，timeline 中无任何顶层 message 文本时作为兜底渲染 */
	fallbackContent?: string;
	/** 完整时间线内的 Agent 正文也已渲染；仅调用树回退仍可使用正文兜底。 */
	completeTimeline?: boolean;
	attachments?: Attachment[];
	onPreviewHtml: (input: HtmlPreviewRequest) => void;
	/**
	 * 外部图片点击回调。提供时点击图片交由外部处理（如全局图片查看器）；
	 * 未提供时由本组件内置的 ImagePreview 本地预览。
	 */
	onImageClick?: (src: string, alt: string) => void;
};

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

function hasTimelineMessage(entries: HistoryTimelineEntry[]): boolean {
	return entries.some((entry) =>
		entry.type === "message"
			? Boolean(entry.content?.trim())
			: entry.type === "call" && isToolCall(entry.call)
				? hasCallMessage(entry.call)
				: false,
	);
}

function hasCallMessage(call: HistoryToolCall): boolean {
	return (
		hasTimelineMessage(normalizeEntries(call.timeline ?? [])) ||
		(call.children ?? []).some(hasCallMessage)
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

/**
 * 将 HistoryToolCall 转换为 ToolBlock 组件所需的格式
 */
function convertHistoryToolCallToToolBlock(
	call: HistoryToolCall,
	index: number,
): ToolBlockType {
	const status = call.status || "done";
	const mappedStatus: ToolBlockType["status"] =
		status === "error"
			? "error"
			: status === "running"
				? "running"
				: status === "cancelled"
					? "cancelled"
					: "done";

	const children = new Map<string, ToolBlockType>();
	const timeline: ToolBlockType["timeline"] = [];
	// 旧 children 与新版时间线引用同一子块，时间线保留 Agent 正文与调用的先后顺序。
	if (Array.isArray(call.children)) {
		call.children.forEach((child, idx) => {
			const childBlock = convertHistoryToolCallToToolBlock(child, idx);
			children.set(childBlock.webchatCallId, childBlock);
		});
	}
	normalizeEntries(call.timeline ?? []).forEach((entry, idx) => {
		const timestamp = entry.seq ?? idx;
		if (entry.type === "message" && entry.content) {
			timeline.push({ type: "output", timestamp, content: entry.content });
		} else if (entry.type === "call") {
			let callId = entry.callId;
			if (isToolCall(entry.call)) {
				const childBlock = convertHistoryToolCallToToolBlock(entry.call, idx);
				callId = childBlock.webchatCallId;
				children.set(callId, childBlock);
			}
			if (callId && children.has(callId))
				timeline.push({ type: "call", timestamp, callId });
		}
	});

	const now = Date.now();
	const startTime = now - (call.duration_ms || 0);
	const endTime = mappedStatus === "running" ? undefined : now;

	return {
		webchatCallId: call.id || `call-${index}-${call.name}`,
		toolName: call.name || "--",
		status: mappedStatus,
		isAgent: call.is_agent,
		uiHint: call.ui_hint,
		argumentsPreview: call.arguments_preview,
		resultPreview: call.result_preview,
		currentStage: call.current_stage,
		stageDetail: call.current_stage_detail,
		children,
		timeline,
		startTime,
		endTime,
	};
}

/**
 * 渲染一条 bot 消息的完整时间线：按顺序穿插顶层文本片段（message）与工具调用（call）。
 * 顶层文本用完整 Markdown 渲染（图片/代码/附件/引用）；工具调用用折叠块展示。
 */
export function MessageTimelineContent({
	timeline,
	fallbackContent,
	completeTimeline = false,
	attachments = [],
	onPreviewHtml,
	onImageClick,
}: MessageTimelineContentProps) {
	const entries = normalizeEntries(timeline);
	const hasMessageText =
		entries.some(
			(entry) => entry.type === "message" && Boolean(entry.content?.trim()),
		) ||
		(completeTimeline && hasTimelineMessage(entries));

	// 本地图片预览状态：仅在外部未提供 onImageClick 时启用
	const [previewImage, setPreviewImage] = useState<{
		src: string;
		alt: string;
	} | null>(null);

	// 统一的图片点击处理：优先外部回调，否则走本地预览
	// 保持本地回调稳定，避免 Markdown 图片重建后无法恢复触发元素的焦点。
	const openLocalPreview = useCallback((src: string, alt: string): void => {
		setPreviewImage({ src, alt });
	}, []);
	const handleImageClick = onImageClick ?? openLocalPreview;

	return (
		<div className="message-timeline-content">
			{entries.map((entry, idx) => {
				if (entry.type === "call" && isToolCall(entry.call)) {
					const toolBlock = convertHistoryToolCallToToolBlock(entry.call, idx);
					return (
						<ToolBlock
							key={toolBlock.webchatCallId}
							{...toolBlock}
							attachments={attachments}
							onPreviewHtml={onPreviewHtml}
							onImageClick={handleImageClick}
						/>
					);
				}
				if (entry.type === "message" && entry.content?.trim()) {
					return (
						<MarkdownContent
							// biome-ignore lint/suspicious/noArrayIndexKey: 历史记录只读不变。
							key={idx}
							content={entry.content}
							onPreviewHtml={onPreviewHtml}
							attachments={attachments}
							onImageClick={handleImageClick}
						/>
					);
				}
				return null;
			})}

			{/* 时间线完全没有正文时才兜底，避免重复展示 Agent 内正文。 */}
			{!hasMessageText && fallbackContent?.trim() ? (
				<MarkdownContent
					content={fallbackContent}
					onPreviewHtml={onPreviewHtml}
					attachments={attachments}
					onImageClick={handleImageClick}
				/>
			) : null}

			{/* 内置图片预览：仅外部未接管时由本地 state 驱动 */}
			<ImagePreview
				src={previewImage?.src ?? ""}
				alt={previewImage?.alt ?? ""}
				open={previewImage !== null}
				onClose={() => setPreviewImage(null)}
			/>
		</div>
	);
}
