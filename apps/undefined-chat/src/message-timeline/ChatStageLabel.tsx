import { useEffect, useState } from "react";
import { getChatStageLabel } from "../i18n/zh-CN";

export type ChatStageLabelProps = {
	/** 阶段标识（如 "waiting_model"、"building_context"） */
	stage: string | null;
	/** 阶段详细信息（可选） */
	stageDetail: string | null;
	/** 阶段开始时间戳（秒） */
	startedAt: number | null;
	/** 是否为最终状态（true 时显示固定用时，false 时实时计算） */
	finalState: boolean;
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
 * 聊天阶段标签组件
 *
 * 显示当前 AI 任务的阶段和实时用时，格式为"阶段 · 用时"。
 * - `finalState=false` 时会每 500ms 自动更新用时
 * - `finalState=true` 时显示固定的最终用时，添加 "is-final" 样式类
 *
 * @example
 * ```tsx
 * <ChatStageLabel
 *   stage="waiting_model"
 *   stageDetail="Claude Opus 4.8"
 *   startedAt={1718234567}
 *   finalState={false}
 * />
 * // 渲染为: "等待模型 · 3.2s" (实时更新)
 * ```
 */
export function ChatStageLabel({
	stage,
	stageDetail,
	startedAt,
	finalState,
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
	if (startedAt !== null && typeof startedAt === "number" && !finalState) {
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
			className={`chat-stage-label${finalState ? " is-final" : ""}`}
			title={title}
		>
			{displayText}
		</span>
	);
}
