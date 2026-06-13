/**
 * 中文（简体）国际化文件
 * 包含聊天阶段状态的文字映射
 */

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
 * 聊天阶段状态的中文标签映射
 */
const chatStageLabels: Record<ChatStage, string> = {
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
};

/**
 * 获取聊天阶段的中文标签
 * @param stage 阶段标识符
 * @returns 对应的中文标签，若未找到则返回原始 stage
 */
export function getChatStageLabel(stage: string): string {
	return chatStageLabels[stage as ChatStage] ?? stage;
}

/**
 * 默认导出所有国际化资源
 */
export default {
	chatStageLabels,
	getChatStageLabel,
};
