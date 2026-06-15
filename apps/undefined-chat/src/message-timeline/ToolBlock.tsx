import type React from "react";
import { useEffect, useRef } from "react";
import type { ToolBlock as ToolBlockType } from "../chat-store/types";
import { useChatClock } from "../hooks/useChatClock";
import { type TranslateFn, useTranslation } from "../i18n";
import { getChatStageLabel } from "../i18n/zh-CN";
import "./ToolBlock.css";

export type ToolBlockProps = ToolBlockType;

function formatDuration(
	startTime: number,
	now: number,
	endTime?: number,
): string {
	const duration = endTime ? endTime - startTime : now - startTime;
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

function getStatusText(
	status: ToolBlockType["status"],
	t: TranslateFn,
): string {
	switch (status) {
		case "running":
			return t("tool.statusRunning");
		case "done":
			return t("tool.statusDone");
		case "error":
			return t("tool.statusError");
		default:
			return status;
	}
}

/**
 * 尝试将工具结果预览解析为 JSON。仅当文本是合法 JSON 对象/数组时返回解析值，
 * 否则返回 null 以回退为纯文本展示。
 */
function tryParseJson(text: string): unknown {
	const trimmed = text.trim();
	if (!trimmed) {
		return null;
	}
	const first = trimmed[0];
	// 只对对象/数组尝试解析，避免把裸数字/字符串/布尔当作"结构化结果"。
	if (first !== "{" && first !== "[") {
		return null;
	}
	try {
		const parsed: unknown = JSON.parse(trimmed);
		return parsed !== null && typeof parsed === "object" ? parsed : null;
	} catch {
		return null;
	}
}

function renderTimelineEntry(
	entry: ToolBlockType["timeline"][number],
	index: number,
	t: TranslateFn,
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
					<span className="timeline-label">{t("tool.input")}</span>
					<pre className="timeline-content">{entry.content}</pre>
				</div>
			);
		case "output":
			return (
				<div className="timeline-entry timeline-entry-output" key={index}>
					<span className="timeline-time">{time}</span>
					<span className="timeline-label">{t("tool.output")}</span>
					<pre className="timeline-content">{entry.content}</pre>
				</div>
			);
		case "error":
			return (
				<div className="timeline-entry timeline-entry-error" key={index}>
					<span className="timeline-time">{time}</span>
					<span className="timeline-label">{t("tool.error")}</span>
					<pre className="timeline-content">{entry.message}</pre>
				</div>
			);
		default:
			return <div key={index} />;
	}
}

/**
 * 将单个 JSON 标量值渲染为字符串。
 */
function formatScalar(value: unknown): string {
	if (value === null) {
		return "null";
	}
	if (typeof value === "string") {
		return value;
	}
	return JSON.stringify(value);
}

/**
 * 结构化展示工具结果：对象渲染为 key-value 列表，数组渲染为带序号的项，
 * 嵌套对象/数组缩进递归。仅在 resultPreview 为合法 JSON 对象/数组时启用。
 */
function StructuredResult({ value }: { value: unknown }): React.ReactElement {
	if (Array.isArray(value)) {
		return (
			<ul className="runtime-tool-json runtime-tool-json-array">
				{value.map((item, index) => (
					// biome-ignore lint/suspicious/noArrayIndexKey: 只读结果，顺序稳定
					<li className="runtime-tool-json-item" key={index}>
						{item !== null && typeof item === "object" ? (
							<StructuredResult value={item} />
						) : (
							<span className="runtime-tool-json-value">
								{formatScalar(item)}
							</span>
						)}
					</li>
				))}
			</ul>
		);
	}
	const entries = Object.entries(value as Record<string, unknown>);
	return (
		<dl className="runtime-tool-json runtime-tool-json-object">
			{entries.map(([key, item]) => (
				<div className="runtime-tool-json-row" key={key}>
					<dt className="runtime-tool-json-key">{key}</dt>
					<dd className="runtime-tool-json-value">
						{item !== null && typeof item === "object" ? (
							<StructuredResult value={item} />
						) : (
							formatScalar(item)
						)}
					</dd>
				</div>
			))}
		</dl>
	);
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
	stageDetail,
	children,
	timeline,
	startTime,
	endTime,
}: ToolBlockProps) {
	const { t, locale } = useTranslation();
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

	// 运行中用时实时刷新：复用统一时钟，每 500ms 推进 now；非运行态停止定时器。
	const clockNow = useChatClock(status === "running");
	const duration = formatDuration(startTime, clockNow, endTime);
	const statusText = getStatusText(status, t);
	const childrenArray = Array.from(children.values());

	// agent 运行中且有阶段时，显示阶段标签（对齐 WebUI metaLabel）
	const showLiveAgentStage =
		isAgent && Boolean(currentStage) && status === "running";
	const stageLabel = getChatStageLabel(currentStage ?? "", locale);
	// 阶段 detail：有则在阶段标签后补充展示（如模型名 / 子步骤）
	const stageDetailText = (stageDetail ?? "").trim();
	const metaLabel = showLiveAgentStage
		? stageDetailText
			? `${stageLabel} · ${stageDetailText}`
			: stageLabel
		: statusText;
	const metaTitle =
		showLiveAgentStage && stageDetailText
			? `${stageLabel} · ${stageDetailText}`
			: undefined;
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
					title={metaTitle}
				>
					{metaLabel}
				</em>
				<span className="runtime-tool-kind">{kindLabel}</span>
			</summary>

			{argumentsPreview ? (
				<div className="runtime-tool-preview">
					<div className="runtime-tool-preview-label">{t("tool.input")}</div>
					<div className="runtime-tool-preview-body">
						<pre>{argumentsPreview}</pre>
					</div>
				</div>
			) : null}
			{resultPreview
				? (() => {
						// 可解析为 JSON 对象/数组时结构化展示，否则回退 <pre>
						const parsed = tryParseJson(resultPreview);
						return (
							<div className="runtime-tool-preview">
								<div className="runtime-tool-preview-label">
									{t("tool.output")}
								</div>
								<div className="runtime-tool-preview-body is-structured">
									{parsed !== null ? (
										<StructuredResult value={parsed} />
									) : (
										<pre>{resultPreview}</pre>
									)}
								</div>
							</div>
						);
					})()
				: null}

			{childrenArray.length > 0 || timeline.length > 0 ? (
				<div className="runtime-tool-children">
					{timeline.map((entry, index) => renderTimelineEntry(entry, index, t))}
					{childrenArray.map((child) => (
						<ToolBlock key={child.webchatCallId} {...child} />
					))}
				</div>
			) : null}
		</details>
	);
}
