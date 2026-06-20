/**
 * 聊天阶段状态的国际化文件
 * 包含聊天阶段状态的中英文字映射
 */

import { type Locale, defaultLocale } from "./index";

export type ChatStage =
	| "received"
	| "waiting_model"
	| "running_command"
	| "building_context"
	| "context_ready"
	| "selecting_model"
	| "checking_long_term_memory"
	| "searching_cognitive_memory"
	| "preparing_tools"
	| "loading_chat_history"
	| "sending_message"
	| "waiting_tools"
	| "retrying_model"
	| "finalizing"
	| "processing"
	| "done";

/**
 * 聊天阶段状态的标签映射（按语言）
 */
const chatStageLabels: Record<Locale, Record<ChatStage, string>> = {
	"zh-CN": {
		received: "已接收",
		waiting_model: "等待模型",
		running_command: "正在调用工具",
		building_context: "构建上下文",
		context_ready: "上下文准备完毕",
		selecting_model: "选择模型",
		checking_long_term_memory: "查询长期记忆",
		searching_cognitive_memory: "检索认知记忆",
		preparing_tools: "准备工具",
		loading_chat_history: "加载对话历史",
		sending_message: "发送消息",
		waiting_tools: "等待工具返回",
		retrying_model: "模型重试",
		finalizing: "收尾",
		processing: "处理中",
		done: "完成",
	},
	en: {
		received: "Received",
		waiting_model: "Waiting for model",
		running_command: "Calling tool",
		building_context: "Building context",
		context_ready: "Context ready",
		selecting_model: "Selecting model",
		checking_long_term_memory: "Checking long-term memory",
		searching_cognitive_memory: "Searching cognitive memory",
		preparing_tools: "Preparing tools",
		loading_chat_history: "Loading chat history",
		sending_message: "Sending message",
		waiting_tools: "Waiting for tools",
		retrying_model: "Retrying model",
		finalizing: "Finalizing",
		processing: "Processing",
		done: "Done",
	},
};

/**
 * 获取聊天阶段的本地化标签
 * @param stage 阶段标识符
 * @param locale 目标语言，缺省时使用默认语言（向后兼容单参调用）
 * @returns 对应语言的标签，若未找到则返回原始 stage
 */
export function getChatStageLabel(
	stage: string,
	locale: Locale = defaultLocale,
): string {
	const labels = chatStageLabels[locale] ?? chatStageLabels[defaultLocale];
	return labels[stage as ChatStage] ?? stage;
}

/**
 * 默认导出所有国际化资源
 */
export default {
	chatStageLabels,
	getChatStageLabel,
};
