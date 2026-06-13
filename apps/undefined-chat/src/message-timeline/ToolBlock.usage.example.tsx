/**
 * ToolBlock 使用示例
 *
 * 展示如何在 MessageTimeline 或其他组件中使用 ToolBlock
 */

import type { ToolBlock as ToolBlockType } from "../chat-store/types";
import { ToolBlock } from "./ToolBlock";

// 示例 1: 基本使用
export function BasicExample() {
	const toolBlock: ToolBlockType = {
		webchatCallId: "call-123",
		toolName: "search",
		status: "done",
		children: new Map(),
		timeline: [
			{
				type: "input",
				timestamp: Date.now() - 2000,
				content: '{"query": "React hooks"}',
			},
			{
				type: "output",
				timestamp: Date.now() - 1000,
				content: "Found 5 results",
			},
		],
		startTime: Date.now() - 2000,
		endTime: Date.now(),
	};

	return <ToolBlock {...toolBlock} />;
}

// 示例 2: 嵌套工具调用
export function NestedExample() {
	const childTool: ToolBlockType = {
		webchatCallId: "call-456",
		toolName: "fetch_url",
		status: "done",
		children: new Map(),
		timeline: [
			{
				type: "input",
				timestamp: Date.now() - 1500,
				content: "https://example.com",
			},
			{
				type: "output",
				timestamp: Date.now() - 500,
				content: "200 OK",
			},
		],
		startTime: Date.now() - 1500,
		endTime: Date.now() - 500,
	};

	const parentTool: ToolBlockType = {
		webchatCallId: "call-789",
		toolName: "web_search",
		status: "done",
		children: new Map([["call-456", childTool]]),
		timeline: [
			{
				type: "input",
				timestamp: Date.now() - 3000,
				content: '{"query": "TypeScript"}',
			},
		],
		startTime: Date.now() - 3000,
		endTime: Date.now(),
	};

	return <ToolBlock {...parentTool} />;
}

// 示例 3: 运行中的工具
export function RunningExample() {
	const toolBlock: ToolBlockType = {
		webchatCallId: "call-running",
		toolName: "long_task",
		status: "running",
		children: new Map(),
		timeline: [
			{
				type: "input",
				timestamp: Date.now() - 5000,
				content: "Processing...",
			},
		],
		startTime: Date.now() - 5000,
		// endTime 为 undefined 表示仍在运行
	};

	return <ToolBlock {...toolBlock} />;
}

// 示例 4: 错误状态
export function ErrorExample() {
	const toolBlock: ToolBlockType = {
		webchatCallId: "call-error",
		toolName: "failing_tool",
		status: "error",
		children: new Map(),
		timeline: [
			{
				type: "input",
				timestamp: Date.now() - 1000,
				content: "invalid input",
			},
			{
				type: "error",
				timestamp: Date.now() - 500,
				message: "ValueError: Invalid parameter",
			},
		],
		startTime: Date.now() - 1000,
		endTime: Date.now() - 500,
	};

	return <ToolBlock {...toolBlock} />;
}

// 示例 5: 在 MessageTimeline 中集成
export function MessageTimelineIntegration() {
	// 从 store 获取工具块
	const toolBlocksMap = new Map<string, ToolBlockType>(); // 从 store 获取

	return (
		<div className="thinking-content">
			{/* 工具块列表 */}
			{Array.from(toolBlocksMap.values()).map((toolBlock) => (
				<ToolBlock key={toolBlock.webchatCallId} {...toolBlock} />
			))}
		</div>
	);
}
