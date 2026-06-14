import { useEffect, useState } from "react";
import { getChatStageLabel } from "../i18n/zh-CN";

export type ChatStageLabelProps = {
	/** 阶段标识（如 "waiting_model"、"building_context"、"done"） */
	stage: string | null;
	/** 阶段详细信息（可选） */
	stageDetail: string | null;
	/** 阶段开始时间戳（秒）；仅 finalState=false 且未提供 elapsedMsOverride 时用于实时计算 */
	startedAt: number | null;
	/** 是否为最终状态（true 时显示固定用时并添加 "is-final" 样式类） */
	finalState: boolean;
	/** 固定用时（毫秒）；finalState=true 时直接使用，对齐 WebUI setChatStage 的 baseMs 机制（历史/已完成消息的"完成 · 用时"） */
	elapsedMsOverride?: number;
};

/**
 * 格式化持续时间（毫秒）为人类可读的字符串
 * @param ms 毫秒数
 * @returns 格式化的时间字符串（如 "3.2s"、"125ms"、"1.5m"）
 */
function formatDurationMs(ms: number): string {
	if (!Number.isFinite(ms) || ms <= 0) {
		return "";
	}

	if (ms < 1000) {
		return `${Math.max(1, Math.round(ms))}ms`;
	}

	const seconds = ms / 1000;
	if (seconds < 60) {
		return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
	}

	const minutes = Math.floor(seconds / 60);
	const remainder = Math.floor(seconds % 60);
	return `${minutes}m ${remainder}s`;
}

/**
 * 聊天阶段标签组件（对齐 WebUI runtime.js 的 setChatStage / updateChatStageDisplay）
 *
 * 显示当前 AI 任务的阶段和用时，格式为"阶段 · 用时"。
 * - `finalState=false` 且无 `elapsedMsOverride`：从 `startedAt` 实时计算用时，每 500ms 更新（流式阶段）
 * - `finalState=true` 且提供 `elapsedMsOverride`：显示固定用时，添加 "is-final" 样式类（完成/历史消息）
 *
 * @example 流式阶段（实时）
 * ```tsx
 * <ChatStageLabel stage="waiting_model" stageDetail="Claude Opus 4.8" startedAt={1718234567} finalState={false} />
 * // 渲染为: "等待模型 · 3.2s" (实时更新)
 * ```
 * @example 历史/完成消息（固定用时）
 * ```tsx
 * <ChatStageLabel stage="done" stageDetail={null} startedAt={null} finalState elapsedMsOverride={2300} />
 * // 渲染为: "完成 · 2.3s" (is-final 样式)
 * ```
 */
export function ChatStageLabel({
	stage,
	stageDetail,
	startedAt,
	finalState,
	elapsedMsOverride,
}: ChatStageLabelProps) {
	// 实时时钟：从 store 读取 chatClockNow（当前使用本地 Date.now()）
	// TODO: 集成 store 的全局 chatClockNow 以统一所有用时显示的更新频率
	const [chatClockNow, setChatClockNow] = useState(() => Date.now());

	// 非最终状态时定期更新时钟（500ms 间隔）
	useEffect(() => {
		if (finalState) return;

		const timer = setInterval(() => {
			setChatClockNow(Date.now());
		}, 500);

		return () => clearInterval(timer);
	}, [finalState]);

	// 如果没有阶段信息，不渲染
	if (!stage) {
		return null;
	}

	// 获取本地化的阶段标签
	const label = getChatStageLabel(stage);
	if (!label) {
		return null;
	}

	// 计算用时（毫秒）
	let elapsedMs = 0;
	if (finalState && typeof elapsedMsOverride === "number") {
		// 历史/完成消息：固定用时（对齐 WebUI setChatStage 的 baseMs）
		elapsedMs = elapsedMsOverride;
	} else if (
		!finalState &&
		startedAt !== null &&
		typeof startedAt === "number"
	) {
		// 流式阶段：实时计算
		const startMs = startedAt * 1000;
		elapsedMs = Math.max(0, chatClockNow - startMs);
	}

	// 格式化用时
	const durationLabel = formatDurationMs(elapsedMs);

	// 构建显示文本："阶段 · 用时" 或仅 "阶段"
	const displayText = durationLabel ? `${label} · ${durationLabel}` : label;

	// 构建 title（悬停提示）：包含详细信息
	const title = stageDetail ? `${label} · ${stageDetail}` : label;

	return (
		<span
			className={`runtime-chat-stage${finalState ? " is-final" : ""}`}
			title={title}
			hidden={!stage}
		>
			{displayText}
		</span>
	);
}
