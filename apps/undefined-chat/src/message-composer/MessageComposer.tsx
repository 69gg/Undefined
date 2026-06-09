import { useEffect, useMemo, useState } from "react";
import type { AttachmentDraft } from "../chat-store/store";
import type { CommandInfo, MessageReference } from "../runtime-client/types";

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

	useEffect(() => {
		setValue(draft);
	}, [draft]);

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

	return (
		<form
			className="composer"
			onSubmit={(event) => {
				event.preventDefault();
				if (canSend) {
					onSend();
				}
			}}
		>
			{references.length > 0 ? (
				<div className="composer-references">
					{references.map((reference) => (
						<span className="composer-chip" key={reference.messageId}>
							<span>{reference.quote}</span>
							<button
								aria-label={`取消引用 ${reference.messageId}`}
								type="button"
								onClick={() => onClearReference(reference.messageId)}
							>
								×
							</button>
						</span>
					))}
				</div>
			) : null}
			{attachmentQueue.length > 0 ? (
				<ul aria-label="附件队列" className="composer-attachments">
					{attachmentQueue.map((attachment) => (
						<li key={attachment.id}>
							<span>{attachment.name}</span>
							<span>{fileSize(attachment.size)}</span>
							<button
								aria-label={`移除 ${attachment.name}`}
								type="button"
								onClick={() => onClearAttachment(attachment.id)}
							>
								×
							</button>
						</li>
					))}
				</ul>
			) : null}
			<div className="composer-input-row">
				<button
					aria-label="添加附件"
					className="icon-button"
					type="button"
					onClick={onAddAttachment}
				>
					+
				</button>
				<textarea
					aria-label="消息输入"
					disabled={disabled}
					onChange={(event) => update(event.currentTarget.value)}
					onKeyDown={handleKeyDown}
					placeholder="给 Undefined 发送消息"
					rows={3}
					value={value}
				/>
				<button disabled={!canSend} type="submit">
					发送
				</button>
			</div>
			{filteredCommands.length > 0 ? (
				<ul aria-label="命令建议" className="command-suggestions">
					{filteredCommands.map((command) => (
						<li key={command.name}>
							<span>{command.name}</span>
							<span>{command.description}</span>
						</li>
					))}
				</ul>
			) : null}
			{disabled ? <p className="composer-note">当前会话仍在运行</p> : null}
		</form>
	);
}
