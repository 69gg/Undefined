import { useEffect, useRef } from "react";
import type { CommandInfo } from "../runtime-client/types";
import {
	type CommandMatch,
	matchDescription,
	matchKey,
	matchLabel,
	matchMeta,
	matchUsage,
} from "./command-context";

export type CommandPaletteProps = {
	open: boolean;
	matches: CommandMatch[];
	activeIndex: number;
	mode: "command" | "subcommand";
	/** 子命令模式下命令存在但无子命令时，传入该命令以渲染帮助卡片 */
	helpCommand: CommandInfo | null;
	onSelect: (match: CommandMatch) => void;
};

function CommandHelpCard({ command }: { command: CommandInfo }) {
	const rows: Array<[string, string]> = [];
	if (command.usage) rows.push(["用法", command.usage]);
	if (command.example) rows.push(["示例", command.example]);
	if (command.aliases.length > 0) {
		rows.push(["别名", command.aliases.map((alias) => `/${alias}`).join(", ")]);
	}
	return (
		<div className="runtime-chat-command-help">
			<div className="runtime-chat-command-help-head">
				<span className="runtime-chat-command-help-name">/{command.name}</span>
				<span className="runtime-chat-command-help-kicker">命令帮助</span>
			</div>
			{command.description ? (
				<div className="runtime-chat-command-help-desc">
					{command.description}
				</div>
			) : null}
			{rows.length > 0 ? (
				<div className="runtime-chat-command-help-grid">
					{rows.map(([key, val]) => (
						<div className="runtime-chat-command-help-row" key={key}>
							<span className="runtime-chat-command-help-key">{key}</span>
							<code className="runtime-chat-command-help-val">{val}</code>
						</div>
					))}
				</div>
			) : null}
			<div className="runtime-chat-command-help-note">
				该命令没有子命令，直接发送即可。
			</div>
		</div>
	);
}

export function CommandPalette({
	open,
	matches,
	activeIndex,
	mode,
	helpCommand,
	onSelect,
}: CommandPaletteProps) {
	const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

	// 键盘导航时让选中项滚动进可视区
	useEffect(() => {
		itemRefs.current[activeIndex]?.scrollIntoView({ block: "nearest" });
	}, [activeIndex]);

	if (!open) {
		return null;
	}

	// 子命令模式下命令无子命令：展示帮助卡片
	if (matches.length === 0) {
		if (helpCommand) {
			return (
				<div className="runtime-chat-command-palette is-open">
					<CommandHelpCard command={helpCommand} />
				</div>
			);
		}
		return null;
	}

	const headText = mode === "subcommand" ? "选择子命令" : "输入以筛选命令";

	return (
		<div
			className="runtime-chat-command-palette is-open"
			role="listbox"
			tabIndex={-1}
		>
			<div className="runtime-chat-command-head">{headText}</div>
			{matches.map((match, index) => {
				const meta = matchMeta(match);
				return (
					<button
						type="button"
						key={matchKey(match)}
						ref={(el) => {
							itemRefs.current[index] = el;
						}}
						className={`runtime-chat-command-item ${index === activeIndex ? "active" : ""}`}
						role="option"
						aria-selected={index === activeIndex}
						onClick={() => onSelect(match)}
					>
						<span className="runtime-chat-command-main">
							<span className="runtime-chat-command-name">
								{matchLabel(match)}
							</span>
							<span className="runtime-chat-command-desc">
								{matchDescription(match)}
							</span>
						</span>
						<span className="runtime-chat-command-side">
							<code>{matchUsage(match)}</code>
							{meta ? (
								<span className="runtime-chat-command-meta">{meta}</span>
							) : null}
						</span>
					</button>
				);
			})}
		</div>
	);
}
