import { useEffect, useMemo, useRef, useState } from "react";
import type { AttachmentDraft } from "../chat-store/store";
import type { CommandInfo, MessageReference } from "../runtime-client/types";
import { CommandPalette } from "./CommandPalette";
import { ReferenceChips } from "./ReferenceChips";
import {
	type CommandMatch,
	buildCommandContext,
	buildReplacement,
	computeMatches,
	findCommandByNameOrAlias,
} from "./command-context";

export type MessageComposerProps = {
	attachmentQueue: AttachmentDraft[];
	commandSuggestions: CommandInfo[];
	disabled: boolean;
	draft: string;
	references: MessageReference[];
	onAddAttachment: () => void;
	onClearAttachment: (attachmentId: string) => void;
	onClearReference: (messageId: string) => void;
	onDraftChange: (draft: string) => void;
	onSend: () => void;
};

function fileSize(size: number): string {
	if (size < 1024) {
		return `${size} B`;
	}
	return `${Math.round(size / 102.4) / 10} KB`;
}

export function MessageComposer({
	attachmentQueue,
	commandSuggestions,
	disabled,
	draft,
	references,
	onAddAttachment,
	onClearAttachment,
	onClearReference,
	onDraftChange,
	onSend,
}: MessageComposerProps) {
	const [value, setValue] = useState(draft);
	const [selectionStart, setSelectionStart] = useState(draft.length);
	const [activeIndex, setActiveIndex] = useState(0);
	// 面板被关闭时（Esc 或选中候选）记录当时输入值；输入变化后自动重开
	const [escDismissedValue, setEscDismissedValue] = useState<string | null>(
		null,
	);
	const textareaRef = useRef<HTMLTextAreaElement>(null);

	// 同步外部草稿
	useEffect(() => {
		setValue(draft);
	}, [draft]);

	// 输入框高度自适应
	// biome-ignore lint/correctness/useExhaustiveDependencies: update height on value change
	useEffect(() => {
		const textarea = textareaRef.current;
		if (textarea) {
			textarea.style.height = "auto";
			textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
		}
	}, [value]);

	// 解析命令上下文与候选项（单一数据源，供展示与键盘逻辑共用）
	const commandContext = useMemo(
		() => buildCommandContext(value, selectionStart),
		[value, selectionStart],
	);
	const commandMatches = useMemo(
		() => computeMatches(commandSuggestions, commandContext),
		[commandSuggestions, commandContext],
	);
	const paletteOpen = commandContext !== null && value !== escDismissedValue;

	// 输入离开命令上下文（清空/键入普通文本）后清除关闭哨兵，
	// 使再次输入 "/" 能立即重开，避免"重输相同值仍被判为已关闭"
	useEffect(() => {
		if (commandContext === null && escDismissedValue !== null) {
			setEscDismissedValue(null);
		}
	}, [commandContext, escDismissedValue]);

	// 子命令模式下命令存在但无子命令 → 展示帮助卡片
	const helpCommand = useMemo<CommandInfo | null>(() => {
		if (!commandContext || commandContext.mode !== "subcommand") return null;
		if (commandMatches.length > 0) return null;
		const command = findCommandByNameOrAlias(
			commandSuggestions,
			commandContext.commandQuery,
		);
		return command && command.subcommands.length === 0 ? command : null;
	}, [commandContext, commandMatches, commandSuggestions]);

	const paletteHasContent = commandMatches.length > 0 || helpCommand !== null;
	const clampedActiveIndex = Math.min(
		activeIndex,
		Math.max(0, commandMatches.length - 1),
	);

	const hasReadyAttachment = attachmentQueue.some(
		(attachment) => attachment.status === "ready",
	);
	const canSend = !disabled && (value.trim().length > 0 || hasReadyAttachment);

	function update(nextValue: string): void {
		setValue(nextValue);
		// 默认光标置于末尾（输入/补全的常见情形），使命令上下文随输入立即刷新，
		// 不依赖 onChange 时可能尚未同步的 DOM selectionStart；真实光标移动由 keyup/select 校正
		setSelectionStart(nextValue.length);
		onDraftChange(nextValue);
	}

	function syncCursor(el: HTMLTextAreaElement): void {
		setSelectionStart(el.selectionStart ?? el.value.length);
	}

	function moveActive(delta: number): void {
		const len = commandMatches.length;
		if (len === 0) return;
		setActiveIndex((prev) => (prev + delta + len) % len);
	}

	function selectMatch(match: CommandMatch): void {
		const next = buildReplacement(match);
		update(next);
		setActiveIndex(0);
		// 选中"有子命令的主命令"后保持面板打开以展示其子命令；
		// 选中子命令或无子命令的命令则选完即收（对齐 WebUI 的关闭行为）
		const revealSubcommands =
			match.type === "command" && match.command.subcommands.length > 0;
		setEscDismissedValue(revealSubcommands ? null : next);
		requestAnimationFrame(() => {
			const el = textareaRef.current;
			if (el) {
				el.focus();
				el.setSelectionRange(next.length, next.length);
			}
		});
	}

	function chooseActive(): void {
		const match = commandMatches[clampedActiveIndex];
		if (match) selectMatch(match);
	}

	function dismissPalette(): void {
		setEscDismissedValue(value);
	}

	function handleKeyDown(
		event: React.KeyboardEvent<HTMLTextAreaElement>,
	): void {
		// 命令面板打开时拦截导航/补全/关闭键
		if (paletteOpen && paletteHasContent) {
			if (event.key === "Escape") {
				event.preventDefault();
				dismissPalette();
				return;
			}
			if (commandMatches.length > 0) {
				if (event.key === "ArrowDown") {
					event.preventDefault();
					moveActive(1);
					return;
				}
				if (event.key === "ArrowUp") {
					event.preventDefault();
					moveActive(-1);
					return;
				}
				if (event.key === "Tab") {
					event.preventDefault();
					chooseActive();
					return;
				}
				if (event.key === "Enter" && !event.shiftKey) {
					event.preventDefault();
					chooseActive();
					return;
				}
			}
		}

		if (event.key !== "Enter") {
			return;
		}
		if (event.shiftKey) {
			event.preventDefault();
			const target = event.currentTarget;
			const start = target.selectionStart;
			const end = target.selectionEnd;
			const nextValue = `${value.slice(0, start)}\n${value.slice(end)}`;
			update(nextValue);
			requestAnimationFrame(() => {
				target.selectionStart = start + 1;
				target.selectionEnd = start + 1;
				setSelectionStart(start + 1);
			});
			return;
		}
		event.preventDefault();
		if (canSend) {
			onSend();
		}
	}

	return (
		<div className="composer-wrapper">
			<form
				className="composer"
				onSubmit={(event) => {
					event.preventDefault();
					if (canSend) {
						onSend();
					}
				}}
			>
				{/* 引用消息 */}
				<ReferenceChips references={references} onClear={onClearReference} />

				{/* 附件队列 */}
				{attachmentQueue.length > 0 ? (
					<ul aria-label="附件队列" className="composer-attachments">
						{attachmentQueue.map((attachment) => (
							<li key={attachment.id}>
								<span style={{ fontWeight: "600" }}>{attachment.name}</span>
								<span style={{ opacity: 0.7, fontSize: "0.75rem" }}>
									{fileSize(attachment.size)}
								</span>
								<button
									aria-label={`移除 ${attachment.name}`}
									onClick={() => onClearAttachment(attachment.id)}
									type="button"
								>
									×
								</button>
							</li>
						))}
					</ul>
				) : null}

				{/* 输入控制行 */}
				<div className="composer-input-row">
					<button
						aria-label="添加附件"
						className="icon-button"
						onClick={onAddAttachment}
						title="添加文件"
						type="button"
					>
						<svg
							fill="none"
							height="18"
							stroke="currentColor"
							strokeLinecap="round"
							strokeLinejoin="round"
							strokeWidth="2.5"
							viewBox="0 0 24 24"
							width="18"
						>
							<title>添加附件</title>
							<path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
						</svg>
					</button>

					<textarea
						aria-label="消息输入"
						disabled={disabled}
						onChange={(event) => {
							update(event.currentTarget.value);
							setActiveIndex(0);
						}}
						onKeyDown={handleKeyDown}
						onKeyUp={(event) => syncCursor(event.currentTarget)}
						onSelect={(event) => syncCursor(event.currentTarget)}
						placeholder="给 Undefined 发送消息..."
						ref={textareaRef}
						rows={1}
						value={value}
					/>

					<button disabled={!canSend} title="发送" type="submit">
						<svg
							fill="none"
							height="16"
							stroke="currentColor"
							strokeLinecap="round"
							strokeLinejoin="round"
							strokeWidth="2.5"
							viewBox="0 0 24 24"
							width="16"
						>
							<title>发送</title>
							<line x1="22" x2="11" y1="2" y2="13" />
							<polygon points="22 2 15 22 11 13 2 9 22 2" />
						</svg>
					</button>
				</div>

				{/* 命令面板 */}
				<CommandPalette
					open={paletteOpen}
					matches={commandMatches}
					activeIndex={clampedActiveIndex}
					mode={commandContext?.mode ?? "command"}
					helpCommand={helpCommand}
					onSelect={selectMatch}
				/>
			</form>
			{disabled ? <p className="composer-note">当前会话仍在运行</p> : null}
		</div>
	);
}
