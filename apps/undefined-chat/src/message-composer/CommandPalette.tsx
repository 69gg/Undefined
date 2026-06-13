import type { CommandInfo } from "../runtime-client/types";

export type CommandPaletteProps = {
	open: boolean;
	query: string;
	commands: CommandInfo[];
	activeIndex: number;
	onSelect: (command: CommandInfo) => void;
	onClose: () => void;
	onNavigate: (delta: number) => void;
};

const MAX_MATCHES = 8;

function normalizeQuery(text: string): string {
	return text.toLowerCase().trim();
}

function matchCommand(command: CommandInfo, query: string): boolean {
	const normalizedQuery = normalizeQuery(query);
	if (!normalizedQuery) {
		return true;
	}
	return command.name.toLowerCase().includes(normalizedQuery);
}

function scoreCommand(command: CommandInfo, query: string): number {
	const normalizedQuery = normalizeQuery(query);
	if (!normalizedQuery) {
		return 0;
	}
	const name = command.name.toLowerCase();
	// 完全匹配
	if (name === normalizedQuery) {
		return 100;
	}
	// 前缀匹配
	if (name.startsWith(normalizedQuery)) {
		return 50;
	}
	// 包含匹配
	return 10;
}

export function CommandPalette({
	open,
	query,
	commands,
	activeIndex,
	onSelect,
	onClose,
	onNavigate,
}: CommandPaletteProps) {
	// 过滤和排序命令
	const normalizedQuery = normalizeQuery(query);
	const matches = commands
		.filter((cmd) => matchCommand(cmd, query))
		.map((cmd, originalIndex) => ({
			cmd,
			score: scoreCommand(cmd, query),
			originalIndex,
		}))
		.sort((a, b) => {
			// query 为空时保持原始顺序
			if (!normalizedQuery) {
				return a.originalIndex - b.originalIndex;
			}
			// 先按分数降序
			if (b.score !== a.score) {
				return b.score - a.score;
			}
			// 分数相同按名称字母顺序
			return a.cmd.name.localeCompare(b.cmd.name);
		})
		.slice(0, MAX_MATCHES)
		.map((item) => item.cmd);

	// 键盘事件处理
	function handleKeyDown(event: React.KeyboardEvent): void {
		if (event.key === "ArrowUp") {
			event.preventDefault();
			onNavigate(-1);
		} else if (event.key === "ArrowDown") {
			event.preventDefault();
			onNavigate(1);
		} else if (event.key === "Enter") {
			event.preventDefault();
			if (matches[activeIndex]) {
				onSelect(matches[activeIndex]);
			}
		} else if (event.key === "Escape") {
			event.preventDefault();
			onClose();
		}
	}

	if (!open || matches.length === 0) {
		return null;
	}

	return (
		<div
			className={`runtime-chat-command-palette ${open ? "is-open" : ""}`}
			onKeyDown={handleKeyDown}
			role="listbox"
			tabIndex={-1}
		>
			{matches.map((cmd, index) => (
				<div
					key={cmd.name}
					className={`runtime-chat-command-item ${index === activeIndex ? "active" : ""}`}
					onClick={() => onSelect(cmd)}
					onKeyDown={(e) => {
						if (e.key === "Enter") {
							onSelect(cmd);
						}
					}}
					role="option"
					aria-selected={index === activeIndex}
					tabIndex={0}
				>
					<div className="runtime-chat-command-main">
						<div className="runtime-chat-command-name">/{cmd.name}</div>
						<div className="runtime-chat-command-desc">{cmd.description}</div>
					</div>
					<div className="runtime-chat-command-side">
						<code>{cmd.name}</code>
					</div>
				</div>
			))}
		</div>
	);
}
