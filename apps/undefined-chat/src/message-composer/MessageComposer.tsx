import { useEffect, useMemo, useRef, useState } from "react";
import type { AttachmentDraft } from "../chat-store/store";
import type { CommandInfo, MessageReference } from "../runtime-client/types";
import { CommandPalette } from "./CommandPalette";
import { ReferenceChips } from "./ReferenceChips";

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
	const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
	const [commandPaletteActiveIndex, setCommandPaletteActiveIndex] = useState(0);
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

	// 命令面板查询文本
	const commandQuery = useMemo(() => {
		if (!value.startsWith("/")) {
			return "";
		}
		// 提取 / 后到第一个空格前的内容
		const match = value.match(/^\/(\S*)/);
		return match ? match[1] : "";
	}, [value]);

	// 监听输入变化，决定是否打开命令面板
	useEffect(() => {
		if (value.startsWith("/") && !value.includes(" ")) {
			setCommandPaletteOpen(true);
			setCommandPaletteActiveIndex(0);
		} else {
			setCommandPaletteOpen(false);
		}
	}, [value]);

	const filteredCommands = useMemo(() => {
		if (!value.startsWith("/")) {
			return [];
		}
		return commandSuggestions.filter((command) =>
			command.name.toLowerCase().startsWith(value.toLowerCase()),
		);
	}, [commandSuggestions, value]);

	const hasReadyAttachment = attachmentQueue.some(
		(attachment) => attachment.status === "ready",
	);
	const canSend = !disabled && (value.trim().length > 0 || hasReadyAttachment);

	function update(nextValue: string): void {
		setValue(nextValue);
		onDraftChange(nextValue);
	}

	function handleKeyDown(
		event: React.KeyboardEvent<HTMLTextAreaElement>,
	): void {
		// 命令面板打开时，拦截导航键
		if (commandPaletteOpen) {
			if (event.key === "ArrowUp" || event.key === "ArrowDown") {
				event.preventDefault();
				handleCommandPaletteNavigate(event.key === "ArrowUp" ? -1 : 1);
				return;
			}
			if (event.key === "Enter" && !event.shiftKey) {
				event.preventDefault();
				const matches = commandSuggestions.filter((cmd) =>
					cmd.name.toLowerCase().includes(commandQuery.toLowerCase()),
				);
				if (matches[commandPaletteActiveIndex]) {
					handleCommandSelect(matches[commandPaletteActiveIndex]);
				}
				return;
			}
			if (event.key === "Escape") {
				event.preventDefault();
				setCommandPaletteOpen(false);
				return;
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
			});
			return;
		}
		event.preventDefault();
		if (canSend) {
			onSend();
		}
	}

	function handleCommandSelect(command: CommandInfo): void {
		update(`/${command.name} `);
		setCommandPaletteOpen(false);
		textareaRef.current?.focus();
	}

	function handleCommandPaletteNavigate(delta: number): void {
		const matches = commandSuggestions.filter((cmd) =>
			cmd.name.toLowerCase().includes(commandQuery.toLowerCase()),
		);
		const maxIndex = Math.min(matches.length - 1, 7); // MAX_MATCHES - 1
		setCommandPaletteActiveIndex((prev) => {
			const next = prev + delta;
			if (next < 0) {
				return maxIndex;
			}
			if (next > maxIndex) {
				return 0;
			}
			return next;
		});
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
						onChange={(event) => update(event.currentTarget.value)}
						onKeyDown={handleKeyDown}
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
					open={commandPaletteOpen}
					query={commandQuery}
					commands={commandSuggestions}
					activeIndex={commandPaletteActiveIndex}
					onSelect={handleCommandSelect}
					onClose={() => setCommandPaletteOpen(false)}
					onNavigate={handleCommandPaletteNavigate}
				/>

				{/* 联想词建议（保持向后兼容） */}
				{filteredCommands.length > 0 && !commandPaletteOpen ? (
					<ul aria-label="命令建议" className="command-suggestions">
						{filteredCommands.map((command) => (
							<li
								key={command.name}
								onClick={() => update(`${command.name} `)}
								onKeyDown={(e) => {
									if (e.key === "Enter") {
										update(`${command.name} `);
									}
								}}
								role="presentation"
							>
								<span>{command.name}</span>
								<span>{command.description}</span>
							</li>
						))}
					</ul>
				) : null}
			</form>
			{disabled ? <p className="composer-note">当前会话仍在运行</p> : null}
		</div>
	);
}
