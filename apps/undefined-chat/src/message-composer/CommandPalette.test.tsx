import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { LOCALE_STORAGE_KEY, LanguageProvider } from "../i18n";
import { commandInfo, subcommandInfo } from "../test-fixtures";
import { CommandPalette } from "./CommandPalette";
import { buildCommandContext, computeMatches } from "./command-context";

// 固定为简体中文，使断言不受测试环境 navigator.language 影响
beforeEach(() => {
	window.localStorage.setItem(LOCALE_STORAGE_KEY, "zh-CN");
});

const help = commandInfo({
	name: "help",
	description: "显示帮助",
	usage: "/help",
	aliases: ["h"],
	aliasTriggers: ["/h"],
});
const conv = commandInfo({
	name: "conv",
	trigger: "/conv",
	description: "管理会话",
	usage: "/conv <子命令>",
	subcommands: [
		subcommandInfo({
			name: "new",
			trigger: "/conv new",
			usage: "/conv new [标题]",
			description: "新建会话",
		}),
		subcommandInfo({
			name: "list",
			trigger: "/conv list",
			usage: "/conv list",
			args: "",
			description: "列出会话",
		}),
	],
});
const clear = commandInfo({
	name: "clear",
	trigger: "/clear",
	description: "清空会话",
	usage: "/clear",
});
const commands = [help, conv, clear];

// 借助纯函数生成与运行时一致的候选项
const commandMatches = computeMatches(commands, buildCommandContext("/", 1));
const subMatches = computeMatches(commands, buildCommandContext("/conv ", 6));

function renderPalette(
	props: Partial<ComponentProps<typeof CommandPalette>> = {},
) {
	return render(
		<LanguageProvider>
			<CommandPalette
				open
				matches={commandMatches}
				activeIndex={0}
				mode="command"
				helpCommand={null}
				hasCommands
				onSelect={vi.fn()}
				{...props}
			/>
		</LanguageProvider>,
	);
}

describe("CommandPalette", () => {
	test("关闭时不渲染", () => {
		const { container } = renderPalette({ open: false });
		expect(container.firstChild).toBeNull();
	});

	test("命令模式无匹配时展示空态提示而非静默消失", () => {
		const { container } = renderPalette({ matches: [], helpCommand: null });
		// 面板仍渲染（提供反馈），且带 role=status 的空态文案
		expect(container.firstChild).not.toBeNull();
		expect(screen.getByRole("status")).toBeInTheDocument();
		expect(screen.queryAllByRole("option")).toHaveLength(0);
	});

	test("子命令模式无匹配且无帮助命令时展示空态提示", () => {
		renderPalette({ matches: [], helpCommand: null, mode: "subcommand" });
		expect(screen.getByRole("status")).toBeInTheDocument();
	});

	test("命令尚未加载时提示命令暂不可用", () => {
		renderPalette({ matches: [], helpCommand: null, hasCommands: false });
		expect(screen.getByRole("status")).toBeInTheDocument();
	});

	test("渲染命令候选并显示命令模式提示", () => {
		renderPalette();
		const options = screen.getAllByRole("option");
		expect(options).toHaveLength(3);
		expect(options[0]).toHaveTextContent("/help");
		expect(options[1]).toHaveTextContent("/conv");
		expect(options[2]).toHaveTextContent("/clear");
		expect(screen.getByText("输入以筛选命令")).toBeInTheDocument();
	});

	test("高亮当前选中项", () => {
		renderPalette({ activeIndex: 1 });
		const options = screen.getAllByRole("option");
		expect(options[0]).not.toHaveClass("active");
		expect(options[1]).toHaveClass("active");
	});

	test("点击候选项回传对应 match", async () => {
		const onSelect = vi.fn();
		renderPalette({ onSelect });
		await userEvent.click(screen.getAllByRole("option")[1]);
		expect(onSelect).toHaveBeenCalledWith(commandMatches[1]);
	});

	test("子命令模式渲染子命令候选与提示", () => {
		renderPalette({ matches: subMatches, mode: "subcommand" });
		const options = screen.getAllByRole("option");
		expect(options[0]).toHaveTextContent("/conv new");
		expect(options[1]).toHaveTextContent("/conv list");
		expect(screen.getByText("选择子命令")).toBeInTheDocument();
	});

	test("命令无子命令时渲染帮助卡片", () => {
		const { container } = renderPalette({
			matches: [],
			mode: "subcommand",
			helpCommand: help,
		});
		expect(screen.queryAllByRole("option")).toHaveLength(0);
		expect(screen.getByText("命令帮助")).toBeInTheDocument();
		expect(screen.getByText("显示帮助")).toBeInTheDocument();
		expect(
			screen.getByText("该命令没有子命令，直接发送即可。"),
		).toBeInTheDocument();
		expect(
			container.querySelector(".runtime-chat-command-help-name")?.textContent,
		).toBe("/help");
	});
});
