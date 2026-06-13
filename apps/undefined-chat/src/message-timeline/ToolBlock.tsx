import type React from "react";
import { useEffect, useRef, useState } from "react";
import type { ToolBlock as ToolBlockType } from "../chat-store/types";
import "./ToolBlock.css";

export type ToolBlockProps = ToolBlockType;

function formatDuration(startTime: number, endTime?: number): string {
	const duration = endTime ? endTime - startTime : Date.now() - startTime;
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

export function ToolBlock({
	webchatCallId,
	toolName,
	status,
	children,
	timeline,
	startTime,
	endTime,
}: ToolBlockProps) {
	const [isOpen, setIsOpen] = useState(status === "running");
	const [userInteracted, setUserInteracted] = useState(false);
	const collapseTimerRef = useRef<number | null>(null);

	useEffect(() => {
		if (collapseTimerRef.current !== null) {
			clearTimeout(collapseTimerRef.current);
			collapseTimerRef.current = null;
		}

		if ((status === "done" || status === "error") && !userInteracted) {
			collapseTimerRef.current = window.setTimeout(() => {
				setIsOpen(false);
			}, 2000);
		}

		return () => {
			if (collapseTimerRef.current !== null) {
				clearTimeout(collapseTimerRef.current);
			}
		};
	}, [status, userInteracted]);

	const handleToggle = () => {
		setUserInteracted(true);
		setIsOpen((prev) => !prev);
	};

	const duration = formatDuration(startTime, endTime);
	const statusText = getStatusText(status);
	const childrenArray = Array.from(children.values());

	return (
		<details
			open={isOpen}
			className={`runtime-tool-block is-tool ${status}`}
			data-call-id={webchatCallId}
			onToggle={handleToggle}
		>
			<summary>
				<div className="runtime-tool-summary-main">
					<div className="runtime-tool-title">
						<span className="runtime-tool-name">{toolName}</span>
					</div>
				</div>
				<span className="runtime-tool-duration">{duration}</span>
				<span className="runtime-tool-status">{statusText}</span>
			</summary>

			{timeline.length > 0 && (
				<div className="runtime-tool-preview">
					<div className="runtime-tool-preview-label">时间线</div>
					<div className="runtime-tool-preview-body">
						{timeline.map((entry, index) => renderTimelineEntry(entry, index))}
					</div>
				</div>
			)}

			{childrenArray.length > 0 && (
				<div className="runtime-tool-children">
					{childrenArray.map((child) => (
						<ToolBlock key={child.webchatCallId} {...child} />
					))}
				</div>
			)}
		</details>
	);
}
