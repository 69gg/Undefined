export const defaultLocale = "zh-CN" as const;

export type Locale = "zh-CN" | "en";

export type TranslationKey =
	| "app.title"
	| "app.connection.connected"
	| "app.connection.connecting"
	| "app.connection.disconnected"
	| "app.connection.idle"
	| "app.connection.json_fallback"
	| "app.connection.resuming"
	| "app.connection.streaming"
	| "app.mobile.conversations"
	| "composer.addAttachment"
	| "composer.placeholder"
	| "composer.running"
	| "composer.send"
	| "conversation.create"
	| "conversation.nav"
	| "timeline.empty"
	| "timeline.label"
	| "timeline.previewHtml";

export const dictionaries: Record<Locale, Record<TranslationKey, string>> = {
	"zh-CN": {
		"app.title": "Undefined Chat",
		"app.connection.connected": "已连接",
		"app.connection.connecting": "正在连接",
		"app.connection.disconnected": "连接断开",
		"app.connection.idle": "待连接",
		"app.connection.json_fallback": "JSON 轮询",
		"app.connection.resuming": "正在续接",
		"app.connection.streaming": "事件流",
		"app.mobile.conversations": "会话",
		"composer.addAttachment": "添加附件",
		"composer.placeholder": "给 Undefined 发送消息",
		"composer.running": "当前会话仍在运行",
		"composer.send": "发送",
		"conversation.create": "新建",
		"conversation.nav": "会话",
		"timeline.empty": "暂无消息",
		"timeline.label": "消息",
		"timeline.previewHtml": "预览 HTML",
	},
	en: {
		"app.title": "Undefined Chat",
		"app.connection.connected": "Connected",
		"app.connection.connecting": "Connecting",
		"app.connection.disconnected": "Disconnected",
		"app.connection.idle": "Idle",
		"app.connection.json_fallback": "JSON polling",
		"app.connection.resuming": "Resuming",
		"app.connection.streaming": "Event stream",
		"app.mobile.conversations": "Conversations",
		"composer.addAttachment": "Add attachment",
		"composer.placeholder": "Message Undefined",
		"composer.running": "Current conversation is still running",
		"composer.send": "Send",
		"conversation.create": "New",
		"conversation.nav": "Conversations",
		"timeline.empty": "No messages yet",
		"timeline.label": "Messages",
		"timeline.previewHtml": "Preview HTML",
	},
};

export function createTranslator(locale: Locale = defaultLocale) {
	return (key: string): string => {
		const dictionary = dictionaries[locale];
		return dictionary[key as TranslationKey] ?? key;
	};
}

export const t = createTranslator(defaultLocale);
