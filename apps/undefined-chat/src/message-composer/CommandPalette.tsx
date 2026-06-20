import { useEffect, useRef } from "react";
import { useTranslation } from "../i18n";
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
	/** 是否已加载到任何命令；为 false 时面板提示命令尚不可用，而非静默无匹配 */
	hasCommands: boolean;
	onSelect: (match: CommandMatch) => void;
};

function CommandHelpCard({ command }: { command: CommandInfo }) {
	const { t } = useTranslation();
	const rows: Array<[string, string]> = [];
	if (command.usage) rows.push([t("command.usage"), command.usage]);
	if (command.example) rows.push([t("command.example"), command.example]);
	if (command.aliases.length > 0) {
		rows.push([
			t("command.aliases"),
			command.aliases.map((alias) => `/${alias}`).join(", "),
		]);
	}
	return (
		<div className="runtime-chat-command-help">
			<div className="runtime-chat-command-help-head">
				<span className="runtime-chat-command-help-name">/{command.name}</span>
				<span className="runtime-chat-command-help-kicker">
					{t("command.help")}
				</span>
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
				{t("command.noSubcommands")}
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
	hasCommands,
	onSelect,
}: CommandPaletteProps) {
	const { t } = useTranslation();
	const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

	// 键盘导航时让选中项滚动进可视区
	useEffect(() => {
		itemRefs.current[activeIndex]?.scrollIntoView({ block: "nearest" });
	}, [activeIndex]);

	if (!open) {
		return null;
	}

	// 无候选项：区分并给出明确空态反馈，避免面板静默消失让用户误以为坏掉
	if (matches.length === 0) {
		// 子命令模式下命令存在但无子命令：展示帮助卡片
		if (helpCommand) {
			return (
				<div className="runtime-chat-command-palette is-open">
					<CommandHelpCard command={helpCommand} />
				</div>
			);
		}
		// 命令尚未加载 / 暂不可用（如连接初期 listCommands 未返回）
		// 与“已加载但筛选无结果”区分开
		let emptyText: string;
		if (!hasCommands) {
			emptyText = t("command.unavailable");
		} else if (mode === "subcommand") {
			emptyText = t("command.noSubcommandMatch");
		} else {
			emptyText = t("command.noMatch");
		}
		return (
			<div className="runtime-chat-command-palette is-open">
				<div className="runtime-chat-command-head" role="status">
					{emptyText}
				</div>
			</div>
		);
	}

	const headText =
		mode === "subcommand" ? t("command.selectSubcommand") : t("command.filter");

	return (
		<div
			className="runtime-chat-command-palette is-open"
			role="listbox"
			tabIndex={-1}
		>
			<div className="runtime-chat-command-head">{headText}</div>
			{matches.map((match, index) => {
				const meta = matchMeta(match);
				// 组装本地化元信息：别名（语言无关）在前、子命令数（本地化）在后，" · " 连接
				const metaParts: string[] = [];
				if (meta) {
					if (meta.aliases) {
						metaParts.push(meta.aliases);
					}
					if (meta.subcommandCount > 0) {
						metaParts.push(
							t("command.subcommandCount", { count: meta.subcommandCount }),
						);
					}
				}
				const metaText = metaParts.join(" · ");
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
							{metaText ? (
								<span className="runtime-chat-command-meta">{metaText}</span>
							) : null}
						</span>
					</button>
				);
			})}
		</div>
	);
}
