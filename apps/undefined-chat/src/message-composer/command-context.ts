import type { CommandInfo, SubcommandInfo } from "../runtime-client/types";

/** 命令面板最多展示的候选项数量（与 WebUI 一致） */
export const MAX_COMMAND_MATCHES = 8;

/** 输入框中解析出的斜杠命令上下文 */
export type CommandContext = {
	value: string;
	cursor: number;
	/** 已归一化的命令名查询（去掉前导 "/"、小写） */
	commandQuery: string;
	/** 已归一化的子命令查询 */
	subcommandQuery: string;
	mode: "command" | "subcommand";
};

/** 命令面板的一条候选项：主命令或某主命令下的子命令 */
export type CommandMatch =
	| { type: "command"; command: CommandInfo }
	| {
			type: "subcommand";
			command: CommandInfo;
			subcommand: SubcommandInfo;
			/** 用户实际键入的命令名（命令名或别名原文），用于回填时保留别名 */
			typedCommandName: string;
	  };

/** 归一化：去除首尾空白、剥离前导斜杠、转小写（对齐 WebUI normalizeChatCommandText） */
function normalize(value: string): string {
	return value.trim().replace(/^\/+/, "").toLowerCase();
}

function commandSearchText(command: CommandInfo): string {
	return [
		command.name,
		command.trigger,
		command.description,
		command.usage,
		...command.aliases,
		...command.aliasTriggers,
	]
		.map((item) => item.toLowerCase())
		.join(" ");
}

function commandMatchesQuery(command: CommandInfo, query: string): boolean {
	const normalized = normalize(query);
	if (!normalized) return true;
	if (command.name.toLowerCase().startsWith(normalized)) return true;
	if (
		command.aliases.some((alias) => alias.toLowerCase().startsWith(normalized))
	) {
		return true;
	}
	return commandSearchText(command).includes(normalized);
}

function subcommandMatchesQuery(
	subcommand: SubcommandInfo,
	query: string,
): boolean {
	const normalized = normalize(query);
	if (!normalized) return true;
	if (subcommand.name.toLowerCase().startsWith(normalized)) return true;
	const haystack = [
		subcommand.name,
		subcommand.trigger,
		subcommand.description,
		subcommand.args,
		subcommand.usage,
	]
		.map((item) => item.toLowerCase())
		.join(" ");
	return haystack.includes(normalized);
}

/** 按命令名或别名精确匹配一个命令（用于进入子命令模式 / 判断帮助卡片） */
export function findCommandByNameOrAlias(
	commands: CommandInfo[],
	query: string,
): CommandInfo | undefined {
	const normalized = normalize(query);
	if (!normalized) return undefined;
	return commands.find(
		(command) =>
			command.name.toLowerCase() === normalized ||
			command.aliases.some((alias) => alias.toLowerCase() === normalized),
	);
}

/** 返回用户键入的命令显示名：命中别名则保留别名原文，否则用规范命令名 */
function commandDisplayName(command: CommandInfo, typed: string): string {
	const normalized = normalize(typed);
	if (normalized === command.name.toLowerCase()) return command.name;
	const alias = command.aliases.find(
		(item) => item.toLowerCase() === normalized,
	);
	return alias ?? command.name;
}

/**
 * 根据输入值与光标位置解析斜杠命令上下文。
 * 规则（对齐 WebUI buildChatCommandContext）：光标前文本以 "/" 开头、单行、
 * token 数 ≤ 2（命令 + 子命令）；出现空格边界即进入子命令模式。
 */
export function buildCommandContext(
	value: string,
	cursor: number,
): CommandContext | null {
	const safeCursor = Math.max(0, Math.min(cursor, value.length));
	const before = value.slice(0, safeCursor);
	if (!before.startsWith("/")) return null;
	if (before.includes("\n")) return null;
	if (value.slice(safeCursor).includes("\n")) return null;
	// 整个输入必须是单行（命令场景），否则不触发
	const leadingLine = value.split(/\r?\n/, 1)[0] ?? value;
	if (leadingLine !== value) return null;

	const tokens = before.split(/\s+/);
	const nonEmptyCount = tokens.filter((token) => token.length > 0).length;
	if (nonEmptyCount > 2) return null;

	const commandToken = tokens[0] ?? "";
	const hasBoundary = /\s$/.test(before) || tokens.length > 1;
	const lastToken = tokens[tokens.length - 1] ?? "";
	return {
		value,
		cursor: safeCursor,
		commandQuery: normalize(commandToken),
		subcommandQuery:
			hasBoundary && tokens.length > 1 ? normalize(lastToken) : "",
		mode: hasBoundary ? "subcommand" : "command",
	};
}

/** 依据上下文计算候选项列表（单一数据源，命令面板与键盘逻辑共用） */
export function computeMatches(
	commands: CommandInfo[],
	context: CommandContext | null,
): CommandMatch[] {
	if (!context) return [];

	const commandMatchesForQuery = (query: string): CommandMatch[] =>
		commands
			.filter((command) => commandMatchesQuery(command, query))
			.slice(0, MAX_COMMAND_MATCHES)
			.map((command): CommandMatch => ({ type: "command", command }));

	if (context.mode === "subcommand") {
		const command = findCommandByNameOrAlias(commands, context.commandQuery);
		// 主命令未识别：退回按命令名继续过滤（容错）
		if (!command) {
			return commandMatchesForQuery(context.commandQuery);
		}
		// 命令存在但无子命令：返回空，由 UI 渲染帮助卡片
		if (command.subcommands.length === 0) {
			return [];
		}
		const typedCommandName = commandDisplayName(command, context.commandQuery);
		return command.subcommands
			.filter((subcommand) =>
				subcommandMatchesQuery(subcommand, context.subcommandQuery),
			)
			.slice(0, MAX_COMMAND_MATCHES)
			.map(
				(subcommand): CommandMatch => ({
					type: "subcommand",
					command,
					subcommand,
					typedCommandName,
				}),
			);
	}

	return commandMatchesForQuery(context.commandQuery);
}

/** React 列表渲染用的稳定 key */
export function matchKey(match: CommandMatch): string {
	return match.type === "command"
		? `cmd:${match.command.name}`
		: `sub:${match.command.name}:${match.subcommand.name}`;
}

/** 候选项主标签，如 "/help" 或 "/conv new" */
export function matchLabel(match: CommandMatch): string {
	if (match.type === "subcommand") {
		return `/${match.typedCommandName || match.command.name} ${match.subcommand.name}`;
	}
	return `/${match.command.name}`;
}

export function matchDescription(match: CommandMatch): string {
	return match.type === "subcommand"
		? match.subcommand.description
		: match.command.description;
}

/** 右侧 code 展示的用法文本，缺省回退到 trigger 再到主标签（对齐 WebUI commandPaletteItemUsage） */
export function matchUsage(match: CommandMatch): string {
	if (match.type === "subcommand") {
		return (
			match.subcommand.usage || match.subcommand.trigger || matchLabel(match)
		);
	}
	return match.command.usage || match.command.trigger || matchLabel(match);
}

/**
 * 右侧附加元信息（对齐 WebUI commandPaletteItemMeta）：仅命令显示，
 * 形如 “/h · 2 个子命令”（别名在前、子命令数在后，" · " 连接）；子命令无元信息。
 */
export function matchMeta(match: CommandMatch): string {
	if (match.type !== "command") return "";
	const parts: string[] = [];
	if (match.command.aliases.length > 0) {
		parts.push(match.command.aliases.map((alias) => `/${alias}`).join(", "));
	}
	if (match.command.subcommands.length > 0) {
		parts.push(`${match.command.subcommands.length} 个子命令`);
	}
	return parts.join(" · ");
}

/** 选中候选项后回填到输入框的文本；带参数用法时追加空格便于继续输入 */
export function buildReplacement(match: CommandMatch): string {
	const base =
		match.type === "subcommand"
			? `/${match.typedCommandName || match.command.name} ${match.subcommand.name}`
			: `/${match.command.name}`;
	const suffix = matchUsage(match).replace(base, "").trim();
	return suffix ? `${base} ` : base;
}
