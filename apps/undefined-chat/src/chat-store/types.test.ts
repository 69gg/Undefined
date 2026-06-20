import { describe, expect, test } from "vitest";
import { commandInfo } from "../test-fixtures";
import { chatReducer, createInitialChatState } from "./store";
import type { ChatState, ToolBlock } from "./types";

describe("chat-store types extension", () => {
	test("初始状态包含所有新增字段", () => {
		const state = createInitialChatState();

		// 工具块系统
		expect(state.toolBlocksByJob).toEqual({});

		// 命令面板
		expect(state.commandPaletteOpen).toBe(false);
		expect(state.commandPaletteQuery).toBe("");
		expect(state.commandPaletteActiveIndex).toBe(0);

		// 模态框
		expect(state.imageViewer).toBeNull();
		expect(state.htmlPreview).toBeNull();

		// UI 状态
		expect(state.autoScrollEnabled).toBe(true);

		// 平台信息
		expect(state.platform).toBeNull();
	});

	test("toolBlock/upsert 添加工具块", () => {
		const state = createInitialChatState();
		const toolBlock: ToolBlock = {
			webchatCallId: "call_123",
			toolName: "search",
			status: "running",
			children: new Map(),
			timeline: [{ type: "input", timestamp: Date.now(), content: "query" }],
			startTime: Date.now(),
		};

		const nextState = chatReducer(state, {
			type: "toolBlock/upsert",
			jobId: "job_1",
			toolBlock,
		});

		expect(nextState.toolBlocksByJob.job_1).toBeDefined();
		expect(nextState.toolBlocksByJob.job_1?.get("call_123")).toEqual(toolBlock);
	});

	test("toolBlock/clear 清除工具块", () => {
		const state = createInitialChatState();
		const toolBlock: ToolBlock = {
			webchatCallId: "call_123",
			toolName: "search",
			status: "done",
			children: new Map(),
			timeline: [],
			startTime: Date.now(),
			endTime: Date.now(),
		};

		let nextState = chatReducer(state, {
			type: "toolBlock/upsert",
			jobId: "job_1",
			toolBlock,
		});

		nextState = chatReducer(nextState, {
			type: "toolBlock/clear",
			jobId: "job_1",
		});

		expect(nextState.toolBlocksByJob.job_1).toBeUndefined();
	});

	test("commandPalette actions", () => {
		let state = createInitialChatState();
		// 添加一些命令用于导航测试
		state.commands = [
			commandInfo({ name: "help", description: "帮助" }),
			commandInfo({ name: "search", description: "搜索" }),
			commandInfo({ name: "clear", description: "清除" }),
		];

		// 打开命令面板
		state = chatReducer(state, {
			type: "commandPalette/open",
			query: "/help",
		});
		expect(state.commandPaletteOpen).toBe(true);
		expect(state.commandPaletteQuery).toBe("/help");
		expect(state.commandPaletteActiveIndex).toBe(0);

		// 更新查询
		state = chatReducer(state, {
			type: "commandPalette/setQuery",
			query: "/search",
		});
		expect(state.commandPaletteQuery).toBe("/search");

		// 向下导航
		state = chatReducer(state, {
			type: "commandPalette/navigate",
			delta: 1,
		});
		expect(state.commandPaletteActiveIndex).toBe(1);

		// 再向下导航
		state = chatReducer(state, {
			type: "commandPalette/navigate",
			delta: 1,
		});
		expect(state.commandPaletteActiveIndex).toBe(2);

		// 尝试超出边界（应该停在最后一个）
		state = chatReducer(state, {
			type: "commandPalette/navigate",
			delta: 10,
		});
		expect(state.commandPaletteActiveIndex).toBe(2);

		// 向上导航
		state = chatReducer(state, {
			type: "commandPalette/navigate",
			delta: -1,
		});
		expect(state.commandPaletteActiveIndex).toBe(1);

		// 尝试超出边界（应该停在第一个）
		state = chatReducer(state, {
			type: "commandPalette/navigate",
			delta: -10,
		});
		expect(state.commandPaletteActiveIndex).toBe(0);

		// 关闭命令面板
		state = chatReducer(state, { type: "commandPalette/close" });
		expect(state.commandPaletteOpen).toBe(false);
		expect(state.commandPaletteQuery).toBe("");
		expect(state.commandPaletteActiveIndex).toBe(0);
	});

	test("imageViewer actions", () => {
		let state = createInitialChatState();

		// 打开图片查看器
		state = chatReducer(state, {
			type: "imageViewer/open",
			src: "https://example.com/image.png",
			alt: "Example Image",
		});
		expect(state.imageViewer).toEqual({
			open: true,
			src: "https://example.com/image.png",
			alt: "Example Image",
		});

		// 关闭图片查看器
		state = chatReducer(state, { type: "imageViewer/close" });
		expect(state.imageViewer).toBeNull();
	});

	test("htmlPreview actions", () => {
		let state = createInitialChatState();

		// 打开 HTML 预览
		state = chatReducer(state, {
			type: "htmlPreview/open",
			source: "<html><body>Test</body></html>",
			windowId: "preview-1",
		});
		expect(state.htmlPreview).toEqual({
			open: true,
			source: "<html><body>Test</body></html>",
			windowId: "preview-1",
		});

		// 关闭 HTML 预览
		state = chatReducer(state, { type: "htmlPreview/close" });
		expect(state.htmlPreview).toBeNull();
	});

	test("autoScroll/set action", () => {
		let state = createInitialChatState();
		expect(state.autoScrollEnabled).toBe(true);

		state = chatReducer(state, { type: "autoScroll/set", enabled: false });
		expect(state.autoScrollEnabled).toBe(false);

		state = chatReducer(state, { type: "autoScroll/set", enabled: true });
		expect(state.autoScrollEnabled).toBe(true);
	});

	test("platform/set action", () => {
		let state = createInitialChatState();
		expect(state.platform).toBeNull();

		state = chatReducer(state, {
			type: "platform/set",
			platform: { type: "desktop", os: "Linux" },
		});
		expect(state.platform).toEqual({ type: "desktop", os: "Linux" });

		state = chatReducer(state, {
			type: "platform/set",
			platform: { type: "android", os: "Android 14" },
		});
		expect(state.platform).toEqual({ type: "android", os: "Android 14" });
	});

	test("向后兼容：保持所有现有字段", () => {
		const state: ChatState = createInitialChatState();

		// 验证现有字段仍然存在
		expect(state).toHaveProperty("connectionState");
		expect(state).toHaveProperty("runtimeConfig");
		expect(state).toHaveProperty("health");
		expect(state).toHaveProperty("conversations");
		expect(state).toHaveProperty("selectedConversationId");
		expect(state).toHaveProperty("historyByConversation");
		expect(state).toHaveProperty("activeJobsByConversation");
		expect(state).toHaveProperty("eventsByJob");
		expect(state).toHaveProperty("eventCursorByJob");
		expect(state).toHaveProperty("jobConversationById");
		expect(state).toHaveProperty("draftsByConversation");
		expect(state).toHaveProperty("attachmentsByConversation");
		expect(state).toHaveProperty("referencesByConversation");
		expect(state).toHaveProperty("commands");
		expect(state).toHaveProperty("settings");
		expect(state).toHaveProperty("bootstrapping");
		expect(state).toHaveProperty("error");
		expect(state).toHaveProperty("sendError");
	});
});
