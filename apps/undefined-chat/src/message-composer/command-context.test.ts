import { describe, expect, test } from "vitest";
import type { CommandInfo } from "../runtime-client/types";
import { commandInfo as cmd, subcommandInfo as sub } from "../test-fixtures";
import {
	type CommandMatch,
	MAX_COMMAND_MATCHES,
	buildCommandContext,
	buildReplacement,
	computeMatches,
	findCommandByNameOrAlias,
	matchLabel,
	matchMeta,
	matchUsage,
} from "./command-context";

const convNew = sub({
	name: "new",
	trigger: "/conv new",
	usage: "/conv new [标题]",
	args: "[标题]",
	description: "新建会话",
});
const convList = sub({
	name: "list",
	trigger: "/conv list",
	usage: "/conv list",
	args: "",
	description: "列出会话",
});
const convRename = sub({
	name: "rename",
	trigger: "/conv rename",
	usage: "/conv rename <标题>",
	args: "<标题>",
	description: "重命名会话",
});

const help = cmd({
	name: "help",
	description: "显示帮助",
	usage: "/help",
	aliases: ["h"],
	aliasTriggers: ["/h"],
});
const conv = cmd({
	name: "conv",
	trigger: "/conv",
	description: "管理会话",
	usage: "/conv <子命令>",
	aliases: ["c"],
	aliasTriggers: ["/c"],
	subcommands: [convNew, convList, convRename],
});
const clear = cmd({
	name: "clear",
	trigger: "/clear",
	description: "清空当前会话历史记录",
	usage: "/clear",
});
const commands: CommandInfo[] = [help, conv, clear];

describe("buildCommandContext", () => {
	test("单独斜杠进入命令模式、查询为空", () => {
		const context = buildCommandContext("/", 1);
		expect(context).not.toBeNull();
		expect(context?.mode).toBe("command");
		expect(context?.commandQuery).toBe("");
	});

	test("输入命令名进入命令模式并归一化查询", () => {
		const context = buildCommandContext("/He", 3);
		expect(context?.mode).toBe("command");
		expect(context?.commandQuery).toBe("he");
		expect(context?.subcommandQuery).toBe("");
	});

	test("出现空格边界进入子命令模式", () => {
		const context = buildCommandContext("/conv ", 6);
		expect(context?.mode).toBe("subcommand");
		expect(context?.commandQuery).toBe("conv");
		expect(context?.subcommandQuery).toBe("");
	});

	test("子命令模式携带子命令查询", () => {
		const context = buildCommandContext("/conv ne", 8);
		expect(context?.mode).toBe("subcommand");
		expect(context?.commandQuery).toBe("conv");
		expect(context?.subcommandQuery).toBe("ne");
	});

	test("超过两个 token 不再触发", () => {
		expect(buildCommandContext("/conv new extra", 15)).toBeNull();
	});

	test("非斜杠开头不触发", () => {
		expect(buildCommandContext("hello", 5)).toBeNull();
	});

	test("光标前包含换行不触发", () => {
		expect(buildCommandContext("/conv\nx", 7)).toBeNull();
	});

	test("光标后存在换行（多行输入）不触发", () => {
		expect(buildCommandContext("/help\n", 5)).toBeNull();
	});

	test("光标在斜杠之前不触发", () => {
		expect(buildCommandContext("/help", 0)).toBeNull();
	});

	test("基于光标位置解析：光标在命令名中间", () => {
		// 完整值为 "/help"，但光标停在第 3 位 → 仅解析 "/he"
		const context = buildCommandContext("/help", 3);
		expect(context?.mode).toBe("command");
		expect(context?.commandQuery).toBe("he");
	});
});

describe("findCommandByNameOrAlias", () => {
	test("按命令名精确匹配", () => {
		expect(findCommandByNameOrAlias(commands, "conv")).toBe(conv);
	});

	test("按别名匹配", () => {
		expect(findCommandByNameOrAlias(commands, "h")).toBe(help);
	});

	test("带前导斜杠也能匹配", () => {
		expect(findCommandByNameOrAlias(commands, "/conv")).toBe(conv);
	});

	test("未知命令返回 undefined", () => {
		expect(findCommandByNameOrAlias(commands, "xyz")).toBeUndefined();
	});

	test("空查询返回 undefined", () => {
		expect(findCommandByNameOrAlias(commands, "")).toBeUndefined();
	});
});

describe("computeMatches - 命令模式", () => {
	test("空上下文返回空数组", () => {
		expect(computeMatches(commands, null)).toEqual([]);
	});

	test("空查询返回全部命令并保留后端顺序（不按字母排序）", () => {
		const matches = computeMatches(commands, buildCommandContext("/", 1));
		expect(matches.map(matchLabel)).toEqual(["/help", "/conv", "/clear"]);
		expect(matches.every((m) => m.type === "command")).toBe(true);
	});

	test("按命令名前缀过滤", () => {
		const matches = computeMatches(commands, buildCommandContext("/h", 2));
		expect(matches.map(matchLabel)).toEqual(["/help"]);
	});

	test("命令名前缀命中多个时保留输入顺序", () => {
		const matches = computeMatches(commands, buildCommandContext("/c", 2));
		expect(matches.map(matchLabel)).toEqual(["/conv", "/clear"]);
	});

	test("全文（描述）包含降级匹配", () => {
		const matches = computeMatches(commands, buildCommandContext("/历史", 3));
		expect(matches.map(matchLabel)).toEqual(["/clear"]);
	});

	test("截断到 MAX_COMMAND_MATCHES", () => {
		const many = Array.from({ length: 12 }, (_, i) =>
			cmd({ name: `cmd${i}`, trigger: `/cmd${i}`, usage: `/cmd${i}` }),
		);
		const matches = computeMatches(many, buildCommandContext("/", 1));
		expect(matches).toHaveLength(MAX_COMMAND_MATCHES);
	});
});

describe("computeMatches - 子命令模式", () => {
	test("命令存在且有子命令：返回全部子命令", () => {
		const matches = computeMatches(commands, buildCommandContext("/conv ", 6));
		expect(matches.map(matchLabel)).toEqual([
			"/conv new",
			"/conv list",
			"/conv rename",
		]);
		expect(matches.every((m) => m.type === "subcommand")).toBe(true);
	});

	test("按子命令查询过滤", () => {
		const matches = computeMatches(
			commands,
			buildCommandContext("/conv ne", 8),
		);
		expect(matches.map(matchLabel)).toEqual(["/conv new"]);
	});

	test("通过别名进入子命令模式并保留别名原文", () => {
		const matches = computeMatches(commands, buildCommandContext("/c ", 3));
		expect(matches.map(matchLabel)).toEqual(["/c new", "/c list", "/c rename"]);
	});

	test("命令无子命令：返回空（交由帮助卡片展示）", () => {
		expect(computeMatches(commands, buildCommandContext("/help ", 6))).toEqual(
			[],
		);
	});

	test("主命令未识别：退回按命令名过滤", () => {
		const matches = computeMatches(commands, buildCommandContext("/xyz ", 5));
		expect(matches).toEqual([]);
	});
});

describe("matchLabel / matchUsage / matchMeta", () => {
	const helpMatch: CommandMatch = { type: "command", command: help };
	const clearMatch: CommandMatch = { type: "command", command: clear };
	const convMatch: CommandMatch = { type: "command", command: conv };
	const newMatch: CommandMatch = {
		type: "subcommand",
		command: conv,
		subcommand: convNew,
		typedCommandName: "conv",
	};
	const aliasNewMatch: CommandMatch = {
		type: "subcommand",
		command: conv,
		subcommand: convNew,
		typedCommandName: "c",
	};

	test("matchLabel 命令与子命令", () => {
		expect(matchLabel(helpMatch)).toBe("/help");
		expect(matchLabel(newMatch)).toBe("/conv new");
		expect(matchLabel(aliasNewMatch)).toBe("/c new");
	});

	test("matchUsage 优先 usage，回退 trigger", () => {
		expect(matchUsage(convMatch)).toBe("/conv <子命令>");
		expect(matchUsage(newMatch)).toBe("/conv new [标题]");
		// usage 缺省时回退到 trigger
		const noUsage: CommandMatch = {
			type: "command",
			command: cmd({ name: "ping", trigger: "/ping", usage: "" }),
		};
		expect(matchUsage(noUsage)).toBe("/ping");
	});

	test("matchMeta：命令显示别名与子命令数，子命令为空", () => {
		expect(matchMeta(convMatch)).toBe("/c · 3 个子命令");
		expect(matchMeta(helpMatch)).toBe("/h");
		expect(matchMeta(clearMatch)).toBe("");
		expect(matchMeta(newMatch)).toBe("");
	});
});

describe("buildReplacement", () => {
	test("无参数命令不追加空格", () => {
		const match: CommandMatch = { type: "command", command: help };
		expect(buildReplacement(match)).toBe("/help");
	});

	test("带参数命令追加空格", () => {
		const match: CommandMatch = { type: "command", command: conv };
		expect(buildReplacement(match)).toBe("/conv ");
	});

	test("带参数子命令追加空格", () => {
		const match: CommandMatch = {
			type: "subcommand",
			command: conv,
			subcommand: convNew,
			typedCommandName: "conv",
		};
		expect(buildReplacement(match)).toBe("/conv new ");
	});

	test("无参数子命令不追加空格", () => {
		const match: CommandMatch = {
			type: "subcommand",
			command: conv,
			subcommand: convList,
			typedCommandName: "conv",
		};
		expect(buildReplacement(match)).toBe("/conv list");
	});

	test("别名回填保留用户键入的别名原文", () => {
		const match: CommandMatch = {
			type: "subcommand",
			command: conv,
			subcommand: convNew,
			typedCommandName: "c",
		};
		expect(buildReplacement(match)).toBe("/c new ");
	});
});
