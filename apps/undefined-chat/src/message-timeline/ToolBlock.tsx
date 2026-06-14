import type React from "react";
import { useEffect, useRef } from "react";
import type { ToolBlock as ToolBlockType } from "../chat-store/types";
import { getChatStageLabel } from "../i18n/zh-CN";
import "./ToolBlock.css";

export type ToolBlockProps = ToolBlockType;

function formatDuration(startTime: number, endTime?: number): string {
	const duration = endTime ? endTime - startTime : Date.now() - startTime;
	if (!Number.isFinite(duration) || duration <= 0) {
		return "";
	}
	if (duration < 1000) {
		return `${Math.round(duration)}ms`;
	}
	if (duration < 60000) {
		return `${(duration / 1000).toFixed(1)}s`;
	}
	return `${(duration / 60000).toFixed(1)}m`;
}

function getStatusText(status: ToolBlockType["status"]): string {
	switch (status) {
		case "running":
			return "运行中";
		case "done":
			return "完成";
		case "error":
			return "失败";
		default:
			return status;
	}
}

function renderTimelineEntry(
	entry: ToolBlockType["timeline"][number],
	index: number,
): React.ReactElement {
	const time = new Date(entry.timestamp).toLocaleTimeString([], {
		hour: "2-digit",
		minute: "2-digit",
		second: "2-digit",
	});

	switch (entry.type) {
		case "input":
			return (
				<div className="timeline-entry timeline-entry-input" key={index}>
					<span className="timeline-time">{time}</span>
					<span className="timeline-label">输入</span>
					<pre className="timeline-content">{entry.content}</pre>
				</div>
			);
		case "output":
			return (
				<div className="timeline-entry timeline-entry-output" key={index}>
					<span className="timeline-time">{time}</span>
					<span className="timeline-label">输出</span>
					<pre className="timeline-content">{entry.content}</pre>
				</div>
			);
		case "error":
			return (
				<div className="timeline-entry timeline-entry-error" key={index}>
					<span className="timeline-time">{time}</span>
					<span className="timeline-label">错误</span>
					<pre className="timeline-content">{entry.message}</pre>
				</div>
			);
		default:
			return <div key={index} />;
	}
}

/**
 * 工具调用块（对齐 WebUI renderToolBlock，runtime.js:1100-1142）
 * - running 时显示，tool_end 后变 done/error，2s 后自动折叠
 * - agent 运行中显示阶段标签（metaLabel），对齐 WebUI
 */
export function ToolBlock({
	webchatCallId,
	toolName,
	status,
	isAgent,
	uiHint,
	argumentsPreview,
	resultPreview,
	currentStage,
	children,
	timeline,
	startTime,
	endTime,
}: ToolBlockProps) {
	const detailsRef = useRef<HTMLDetailsElement>(null);
	const userInteractedRef = useRef(false);
	const collapseTimerRef = useRef<number | null>(null);

	// 初始展开：running 时 open=true（对齐 WebUI autoOpen: isStart ? true）
	useEffect(() => {
		if (detailsRef.current && status === "running") {
			detailsRef.current.open = true;
		}
	}, [status]);

	// 自动折叠：done/error 后 2s 直接操作 DOM（对齐 WebUI scheduleToolAutoCollapse）
	useEffect(() => {
		if (collapseTimerRef.current !== null) {
			clearTimeout(collapseTimerRef.current);
			collapseTimerRef.current = null;
		}

		if (
			(status === "done" || status === "error") &&
			!userInteractedRef.current
		) {
			collapseTimerRef.current = window.setTimeout(() => {
				if (detailsRef.current) detailsRef.current.open = false;
			}, 2000);
		}

		return () => {
			if (collapseTimerRef.current !== null) {
				clearTimeout(collapseTimerRef.current);
			}
		};
	}, [status]);

	// 用户手动 toggle：仅记录交互（阻止后续自动折叠），绝不翻转 state
	// （翻转会与折叠 timer 的 open 变化形成 toggle→onToggle→toggle 无限循环 = 闪烁）
	const handleToggle = () => {
		userInteractedRef.current = true;
	};

	const duration = formatDuration(startTime, endTime);
	const statusText = getStatusText(status);
	const childrenArray = Array.from(children.values());

	// agent 运行中且有阶段时，显示阶段标签（对齐 WebUI metaLabel）
	const showLiveAgentStage =
		isAgent && Boolean(currentStage) && status === "running";
	const metaLabel = showLiveAgentStage
		? getChatStageLabel(currentStage ?? "")
		: statusText;
	const hintClass = uiHint ? ` ${uiHint.replace(/_/g, "-")}` : "";
	const kindClass = isAgent ? " is-agent" : " is-tool";
	const kindLabel = isAgent ? "Agent" : "Tool";

	return (
		<details
			ref={detailsRef}
			className={`runtime-tool-block ${status}${kindClass}${hintClass}`}
			data-call-id={webchatCallId}
			onToggle={handleToggle}
		>
			<summary>
				<span className="runtime-tool-summary-main">
					<span className="runtime-tool-title">
						<code className="runtime-tool-name">{toolName}</code>
						<span
							className="runtime-tool-duration"
							data-tool-duration-for={webchatCallId}
							hidden={!duration}
						>
							{duration}
						</span>
					</span>
				</span>
				<em
					className="runtime-tool-status"
					data-tool-status-for={webchatCallId}
				>
					{metaLabel}
				</em>
				<span className="runtime-tool-kind">{kindLabel}</span>
			</summary>

			{argumentsPreview ? (
				<div className="runtime-tool-preview">
					<div className="runtime-tool-preview-label">输入</div>
					<div className="runtime-tool-preview-body">
						<pre>{argumentsPreview}</pre>
					</div>
				</div>
			) : null}
			{resultPreview ? (
				<div className="runtime-tool-preview">
					<div className="runtime-tool-preview-label">输出</div>
					<div className="runtime-tool-preview-body is-structured">
						<pre>{resultPreview}</pre>
					</div>
				</div>
			) : null}

			{childrenArray.length > 0 || timeline.length > 0 ? (
				<div className="runtime-tool-children">
					{timeline.map((entry, index) => renderTimelineEntry(entry, index))}
					{childrenArray.map((child) => (
						<ToolBlock key={child.webchatCallId} {...child} />
					))}
				</div>
			) : null}
		</details>
	);
}
