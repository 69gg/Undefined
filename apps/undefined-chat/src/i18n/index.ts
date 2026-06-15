import {
	type ReactNode,
	createContext,
	createElement,
	useCallback,
	useContext,
	useMemo,
	useState,
} from "react";

export const defaultLocale = "zh-CN" as const;

export type Locale = "zh-CN" | "en";

/**
 * localStorage 持久化键。运行时语言偏好统一存于此处。
 */
export const LOCALE_STORAGE_KEY = "undefined_chat_locale";

export type TranslationKey =
	// 应用 / 顶栏 / 连接状态
	| "app.title"
	| "app.workspace.aria"
	| "app.topbar.openConversations"
	| "app.topbar.expandMenu"
	| "app.topbar.defaultConversation"
	| "app.connection.connected"
	| "app.connection.connecting"
	| "app.connection.disconnected"
	| "app.connection.idle"
	| "app.connection.json_fallback"
	| "app.connection.resuming"
	| "app.connection.streaming"
	| "app.mobile.conversations"
	// 配置 / Runtime 面板
	| "setup.dialog.connectTitle"
	| "setup.dialog.configTitle"
	| "setup.close"
	| "setup.apiKey.placeholder"
	| "setup.apiKey.masked"
	| "setup.allowInsecureFallback"
	| "setup.submit"
	| "setup.insecureHint"
	| "setup.urlLabel"
	| "setup.apiKeyLabel"
	| "setup.connectTitle"
	| "setup.connectSubtitle"
	| "setup.recent"
	| "setup.server"
	| "setup.connect"
	| "setup.hint"
	| "setup.lanHint"
	| "setup.error.needUrl"
	| "setup.error.needApiKey"
	| "setup.error.invalidUrl"
	// 附件操作（App 级 alert / 选择器）
	| "attachment.saveFailed"
	| "attachment.saved"
	| "attachment.previewFailed"
	| "attachment.pickerTitle"
	// 引用跳转
	| "reference.notLoaded"
	| "reference.notInHistory"
	// 会话重命名提示
	| "conversation.renamePrompt"
	// 通用对话框 / 确认删除
	| "dialog.confirm"
	| "dialog.cancel"
	| "dialog.delete"
	| "dialog.deleteConversationTitle"
	| "dialog.deleteConversationMessage"
	// 主题切换
	| "theme.toDark"
	| "theme.toLight"
	| "theme.moonIcon"
	| "theme.sunIcon"
	// 语言切换
	| "language.toggle"
	| "language.zh"
	| "language.en"
	// 会话列表
	| "conversation.create"
	| "conversation.creating"
	| "conversation.nav"
	| "conversation.collapseSidebar"
	| "conversation.running"
	| "conversation.messageCount"
	| "conversation.rename"
	| "conversation.renameTitle"
	| "conversation.delete"
	| "conversation.deleteTitle"
	| "conversation.user"
	| "conversation.configRuntime"
	// 输入区
	| "composer.addAttachment"
	| "composer.addFile"
	| "composer.placeholder"
	| "composer.running"
	| "composer.send"
	| "composer.messageInput"
	| "composer.attachmentQueue"
	| "composer.removeAttachment"
	// 引用 chips
	| "reference.jump"
	| "reference.cancel"
	// 命令面板
	| "command.usage"
	| "command.example"
	| "command.aliases"
	| "command.help"
	| "command.noSubcommands"
	| "command.selectSubcommand"
	| "command.filter"
	| "command.noMatch"
	| "command.noSubcommandMatch"
	| "command.unavailable"
	| "command.subcommandCount"
	// 发送 / 启动错误（逻辑层写入 state.error / state.sendError 的稳定 key）
	| "error.needConfig"
	| "error.noConversation"
	| "error.conversationRunning"
	| "error.attachmentsUploading"
	| "error.attachmentsFailed"
	// Runtime 环境级错误（非组件上下文，模块级 t 渲染）
	| "runtime.tauriRequired"
	// 时间线 / 欢迎页
	| "timeline.empty"
	| "timeline.label"
	| "timeline.previewHtml"
	| "timeline.retry"
	| "timeline.loadingConversation"
	| "timeline.welcomeTitle"
	| "timeline.welcomeSubtitle"
	| "timeline.noMessages"
	| "timeline.loadingEarlier"
	| "timeline.loadMoreEarlier"
	| "timeline.cancel"
	| "timeline.roleAi"
	| "timeline.roleYou"
	// 快捷模板
	| "shortcut.news.title"
	| "shortcut.news.desc"
	| "shortcut.news.prompt"
	| "shortcut.joke.title"
	| "shortcut.joke.desc"
	| "shortcut.joke.prompt"
	| "shortcut.polish.title"
	| "shortcut.polish.desc"
	| "shortcut.polish.prompt"
	| "shortcut.code.title"
	| "shortcut.code.desc"
	| "shortcut.code.prompt"
	// 工具调用块
	| "tool.statusRunning"
	| "tool.statusDone"
	| "tool.statusError"
	| "tool.input"
	| "tool.output"
	| "tool.error"
	// 引用按钮
	| "quote.button"
	| "quote.title"
	// 附件卡片
	| "attachment.preview"
	| "attachment.download"
	// 图片预览 / 查看器
	| "imageViewer.label"
	| "imageViewer.zoomOut"
	| "imageViewer.zoomIn"
	| "imageViewer.rotate"
	| "imageViewer.reset"
	| "imageViewer.close"
	| "imagePreview.close"
	| "image.loading"
	| "image.loadFailed"
	// 代码块
	| "code.expand"
	| "code.collapse"
	| "code.previewHtml"
	| "code.htmlPreviewTitle"
	| "code.copied"
	| "code.copy"
	// 设置
	| "settings.autoScroll";

type TranslationDictionary = Record<TranslationKey, string>;

export const dictionaries: Record<Locale, TranslationDictionary> = {
	"zh-CN": {
		"app.title": "Undefined Chat",
		"app.workspace.aria": "聊天",
		"app.topbar.openConversations": "打开会话列表",
		"app.topbar.expandMenu": "展开菜单",
		"app.topbar.defaultConversation": "默认会话",
		"app.connection.connected": "已连接",
		"app.connection.connecting": "正在连接",
		"app.connection.disconnected": "连接断开",
		"app.connection.idle": "待连接",
		"app.connection.json_fallback": "JSON 轮询",
		"app.connection.resuming": "正在续接",
		"app.connection.streaming": "事件流",
		"app.mobile.conversations": "会话",
		"setup.dialog.connectTitle": "连接到 Runtime",
		"setup.dialog.configTitle": "Runtime 配置",
		"setup.close": "关闭",
		"setup.apiKey.placeholder": "请输入 API Key",
		"setup.apiKey.masked": "••••••••",
		"setup.allowInsecureFallback": "允许不安全存储降级",
		"setup.submit": "保存并连接",
		"setup.insecureHint":
			"密钥优先保存在系统凭据管理器；勾选后仅在不可用时写入本地明文降级。",
		"setup.urlLabel": "Runtime URL",
		"setup.apiKeyLabel": "API Key",
		"setup.connectTitle": "连接到 Undefined Runtime",
		"setup.connectSubtitle": "请输入 Runtime 服务器地址和 API Key",
		"setup.recent": "最近使用",
		"setup.server": "服务器",
		"setup.connect": "连接",
		"setup.hint": "提示",
		"setup.lanHint":
			"提示：Runtime URL 通常是局域网 IP 地址（如 http://192.168.1.100:8788），请确保设备在同一网络下。",
		"setup.error.needUrl": "请输入 Runtime URL",
		"setup.error.needApiKey": "请输入 API Key",
		"setup.error.invalidUrl": "URL 格式不正确",
		"attachment.saveFailed": "附件保存失败",
		"attachment.saved": "已保存 {name}",
		"attachment.previewFailed": "附件无法预览",
		"attachment.pickerTitle": "选择附件",
		"reference.notLoaded": "引用消息暂未加载，请继续加载更早消息后重试",
		"reference.notInHistory": "引用消息不在当前会话历史中",
		"conversation.renamePrompt": "请输入新的会话名称：",
		"dialog.confirm": "确定",
		"dialog.cancel": "取消",
		"dialog.delete": "删除",
		"dialog.deleteConversationTitle": "删除会话",
		"dialog.deleteConversationMessage":
			"确定删除会话「{title}」？该操作不可恢复。",
		"theme.toDark": "切换到暗色模式",
		"theme.toLight": "切换到亮色模式",
		"theme.moonIcon": "月亮图标",
		"theme.sunIcon": "太阳图标",
		"language.toggle": "切换语言",
		"language.zh": "中文",
		"language.en": "English",
		"conversation.create": "新建",
		"conversation.creating": "正在新建…",
		"conversation.nav": "会话",
		"conversation.collapseSidebar": "折叠侧边栏",
		"conversation.running": "运行中",
		"conversation.messageCount": "{count} 条消息",
		"conversation.rename": "重命名会话",
		"conversation.renameTitle": "重命名会话「{title}」",
		"conversation.delete": "删除会话",
		"conversation.deleteTitle": "删除会话「{title}」",
		"conversation.user": "用户",
		"conversation.configRuntime": "配置 Runtime",
		"composer.addAttachment": "添加附件",
		"composer.addFile": "添加文件",
		"composer.placeholder": "给 Undefined 发送消息",
		"composer.running": "当前会话仍在运行",
		"composer.send": "发送",
		"composer.messageInput": "消息输入",
		"composer.attachmentQueue": "附件队列",
		"composer.removeAttachment": "移除 {name}",
		"reference.jump": "跳转到引用消息",
		"reference.cancel": "取消引用消息 {id}",
		"command.usage": "用法",
		"command.example": "示例",
		"command.aliases": "别名",
		"command.help": "命令帮助",
		"command.noSubcommands": "该命令没有子命令，直接发送即可。",
		"command.selectSubcommand": "选择子命令",
		"command.filter": "输入以筛选命令",
		"command.noMatch": "未找到匹配的命令",
		"command.noSubcommandMatch": "未找到匹配的子命令",
		"command.unavailable": "命令加载中或暂不可用",
		"command.subcommandCount": "{count} 个子命令",
		"error.needConfig": "请先配置 Runtime URL 和 API Key",
		"error.noConversation": "没有可用会话",
		"error.conversationRunning": "当前会话仍在运行",
		"error.attachmentsUploading": "附件仍在上传",
		"error.attachmentsFailed": "请先移除上传失败的附件",
		"runtime.tauriRequired":
			"请使用 Tauri 启动客户端（在终端运行 npm run tauri:dev）。当前运行在普通浏览器中，无法调用底层 Rust 原生接口。",
		"timeline.empty": "暂无消息",
		"timeline.label": "消息",
		"timeline.previewHtml": "预览 HTML",
		"timeline.retry": "重试",
		"timeline.loadingConversation": "正在加载会话…",
		"timeline.welcomeTitle": "您好，我是 Undefined",
		"timeline.welcomeSubtitle":
			"今天想让我帮您做些什么？你可以输入指令或选择下方模板：",
		"timeline.noMessages": "当前会话无消息记录",
		"timeline.loadingEarlier": "正在加载更早消息…",
		"timeline.loadMoreEarlier": "加载更早消息",
		"timeline.cancel": "取消",
		"timeline.roleAi": "AI",
		"timeline.roleYou": "You",
		"shortcut.news.title": "今日新闻",
		"shortcut.news.desc": "获取最新时事与突发热点",
		"shortcut.news.prompt": "搜索今日国内国际新闻热点",
		"shortcut.joke.title": "讲冷笑话",
		"shortcut.joke.desc": "来个冷笑话轻松幽默一下",
		"shortcut.joke.prompt": "给我讲个有创意的冷笑话吧",
		"shortcut.polish.title": "文章润色",
		"shortcut.polish.desc": "帮你改进文章段落的措辞",
		"shortcut.polish.prompt":
			"请帮我润色以下这段文字，使其读起来更加专业、优雅：\n",
		"shortcut.code.title": "代码解释",
		"shortcut.code.desc": "分析特定代码并给出优化方案",
		"shortcut.code.prompt":
			"请帮我详细分析和解释以下这段代码：\n```python\n\n```",
		"tool.statusRunning": "运行中",
		"tool.statusDone": "完成",
		"tool.statusError": "失败",
		"tool.input": "输入",
		"tool.output": "输出",
		"tool.error": "错误",
		"quote.button": "引用",
		"quote.title": "引用这条消息",
		"attachment.preview": "预览",
		"attachment.download": "下载",
		"imageViewer.label": "图片查看器",
		"imageViewer.zoomOut": "缩小",
		"imageViewer.zoomIn": "放大",
		"imageViewer.rotate": "旋转",
		"imageViewer.reset": "重置",
		"imageViewer.close": "关闭",
		"imagePreview.close": "关闭图片预览",
		"image.loading": "图片加载中",
		"image.loadFailed": "图片加载失败",
		"code.expand": "展开",
		"code.collapse": "折叠",
		"code.previewHtml": "预览 HTML",
		"code.htmlPreviewTitle": "HTML 预览",
		"code.copied": "已复制",
		"code.copy": "复制",
		"settings.autoScroll": "自动滚动",
	},
	en: {
		"app.title": "Undefined Chat",
		"app.workspace.aria": "Chat",
		"app.topbar.openConversations": "Open conversation list",
		"app.topbar.expandMenu": "Expand menu",
		"app.topbar.defaultConversation": "Default conversation",
		"app.connection.connected": "Connected",
		"app.connection.connecting": "Connecting",
		"app.connection.disconnected": "Disconnected",
		"app.connection.idle": "Idle",
		"app.connection.json_fallback": "JSON polling",
		"app.connection.resuming": "Resuming",
		"app.connection.streaming": "Event stream",
		"app.mobile.conversations": "Conversations",
		"setup.dialog.connectTitle": "Connect to Runtime",
		"setup.dialog.configTitle": "Runtime settings",
		"setup.close": "Close",
		"setup.apiKey.placeholder": "Enter API Key",
		"setup.apiKey.masked": "••••••••",
		"setup.allowInsecureFallback": "Allow insecure storage fallback",
		"setup.submit": "Save and connect",
		"setup.insecureHint":
			"The key is preferentially stored in the system credential manager; when enabled it falls back to local plaintext only if that is unavailable.",
		"setup.urlLabel": "Runtime URL",
		"setup.apiKeyLabel": "API Key",
		"setup.connectTitle": "Connect to Undefined Runtime",
		"setup.connectSubtitle": "Enter the Runtime server address and API Key",
		"setup.recent": "Recently used",
		"setup.server": "Server",
		"setup.connect": "Connect",
		"setup.hint": "Tip",
		"setup.lanHint":
			"Tip: the Runtime URL is usually a LAN IP address (e.g. http://192.168.1.100:8788). Make sure the devices are on the same network.",
		"setup.error.needUrl": "Please enter the Runtime URL",
		"setup.error.needApiKey": "Please enter the API Key",
		"setup.error.invalidUrl": "Invalid URL format",
		"attachment.saveFailed": "Failed to save attachment",
		"attachment.saved": "Saved {name}",
		"attachment.previewFailed": "Attachment cannot be previewed",
		"attachment.pickerTitle": "Select attachment",
		"reference.notLoaded":
			"The quoted message is not loaded yet. Load earlier messages and try again.",
		"reference.notInHistory":
			"The quoted message is not in the current conversation history",
		"conversation.renamePrompt": "Enter a new conversation name:",
		"dialog.confirm": "Confirm",
		"dialog.cancel": "Cancel",
		"dialog.delete": "Delete",
		"dialog.deleteConversationTitle": "Delete conversation",
		"dialog.deleteConversationMessage":
			"Delete conversation “{title}”? This action cannot be undone.",
		"theme.toDark": "Switch to dark mode",
		"theme.toLight": "Switch to light mode",
		"theme.moonIcon": "Moon icon",
		"theme.sunIcon": "Sun icon",
		"language.toggle": "Switch language",
		"language.zh": "中文",
		"language.en": "English",
		"conversation.create": "New",
		"conversation.creating": "Creating…",
		"conversation.nav": "Conversations",
		"conversation.collapseSidebar": "Collapse sidebar",
		"conversation.running": "Running",
		"conversation.messageCount": "{count} messages",
		"conversation.rename": "Rename conversation",
		"conversation.renameTitle": "Rename conversation “{title}”",
		"conversation.delete": "Delete conversation",
		"conversation.deleteTitle": "Delete conversation “{title}”",
		"conversation.user": "User",
		"conversation.configRuntime": "Configure Runtime",
		"composer.addAttachment": "Add attachment",
		"composer.addFile": "Add file",
		"composer.placeholder": "Message Undefined",
		"composer.running": "Current conversation is still running",
		"composer.send": "Send",
		"composer.messageInput": "Message input",
		"composer.attachmentQueue": "Attachment queue",
		"composer.removeAttachment": "Remove {name}",
		"reference.jump": "Jump to quoted message",
		"reference.cancel": "Remove quoted message {id}",
		"command.usage": "Usage",
		"command.example": "Example",
		"command.aliases": "Aliases",
		"command.help": "Command help",
		"command.noSubcommands": "This command has no subcommands; just send it.",
		"command.selectSubcommand": "Select a subcommand",
		"command.filter": "Type to filter commands",
		"command.noMatch": "No matching commands",
		"command.noSubcommandMatch": "No matching subcommands",
		"command.unavailable": "Commands are loading or unavailable",
		"command.subcommandCount": "{count} subcommands",
		"error.needConfig": "Please configure the Runtime URL and API Key first",
		"error.noConversation": "No conversation available",
		"error.conversationRunning": "The current conversation is still running",
		"error.attachmentsUploading": "Attachments are still uploading",
		"error.attachmentsFailed": "Please remove the failed attachments first",
		"runtime.tauriRequired":
			"Please launch the client with Tauri (run npm run tauri:dev in a terminal). You are running in a regular browser and cannot call the native Rust interface.",
		"timeline.empty": "No messages yet",
		"timeline.label": "Messages",
		"timeline.previewHtml": "Preview HTML",
		"timeline.retry": "Retry",
		"timeline.loadingConversation": "Loading conversation…",
		"timeline.welcomeTitle": "Hi, I’m Undefined",
		"timeline.welcomeSubtitle":
			"What can I help you with today? Type a command or pick a template below:",
		"timeline.noMessages": "No messages in this conversation",
		"timeline.loadingEarlier": "Loading earlier messages…",
		"timeline.loadMoreEarlier": "Load earlier messages",
		"timeline.cancel": "Cancel",
		"timeline.roleAi": "AI",
		"timeline.roleYou": "You",
		"shortcut.news.title": "Today’s news",
		"shortcut.news.desc": "Get the latest events and breaking topics",
		"shortcut.news.prompt": "Search today’s domestic and international news",
		"shortcut.joke.title": "Tell a joke",
		"shortcut.joke.desc": "A light-hearted joke to lighten the mood",
		"shortcut.joke.prompt": "Tell me a creative joke",
		"shortcut.polish.title": "Polish writing",
		"shortcut.polish.desc": "Improve the wording of your paragraphs",
		"shortcut.polish.prompt":
			"Please polish the following text so it reads more professional and elegant:\n",
		"shortcut.code.title": "Explain code",
		"shortcut.code.desc": "Analyze specific code and suggest improvements",
		"shortcut.code.prompt":
			"Please analyze and explain the following code in detail:\n```python\n\n```",
		"tool.statusRunning": "Running",
		"tool.statusDone": "Done",
		"tool.statusError": "Failed",
		"tool.input": "Input",
		"tool.output": "Output",
		"tool.error": "Error",
		"quote.button": "Quote",
		"quote.title": "Quote this message",
		"attachment.preview": "Preview",
		"attachment.download": "Download",
		"imageViewer.label": "Image viewer",
		"imageViewer.zoomOut": "Zoom out",
		"imageViewer.zoomIn": "Zoom in",
		"imageViewer.rotate": "Rotate",
		"imageViewer.reset": "Reset",
		"imageViewer.close": "Close",
		"imagePreview.close": "Close image preview",
		"image.loading": "Loading image",
		"image.loadFailed": "Failed to load image",
		"code.expand": "Expand",
		"code.collapse": "Collapse",
		"code.previewHtml": "Preview HTML",
		"code.htmlPreviewTitle": "HTML preview",
		"code.copied": "Copied",
		"code.copy": "Copy",
		"settings.autoScroll": "Auto-scroll",
	},
};

/**
 * 翻译函数签名：支持 `{name}` 风格插值。未知 key 运行时回退为 key 本身（不抛错）。
 */
export type TranslateFn = (
	key: string,
	params?: Record<string, string | number>,
) => string;

/**
 * 对模板字符串执行 `{name}` 占位符插值。缺失的占位符保持原样。
 */
function interpolate(
	template: string,
	params?: Record<string, string | number>,
): string {
	if (!params) {
		return template;
	}
	return template.replace(/\{(\w+)\}/g, (match, name: string) => {
		const value = params[name];
		return value === undefined ? match : String(value);
	});
}

/**
 * 创建指定 locale 的翻译函数。
 * 未知 key 直接返回 key 本身，保证渲染不抛错（向后兼容现有测试）。
 */
export function createTranslator(locale: Locale = defaultLocale): TranslateFn {
	const dictionary = dictionaries[locale];
	return (key, params) => {
		const template = dictionary[key as TranslationKey] ?? key;
		return interpolate(template, params);
	};
}

/**
 * 模块级默认翻译函数，固定使用 {@link defaultLocale}。
 * 供非组件上下文（如纯函数、测试）使用；组件内请使用 {@link useTranslation}。
 */
export const t = createTranslator(defaultLocale);

/**
 * 检测首次启动时应使用的语言：`navigator.language` 以 "zh" 开头 → "zh-CN"，否则 "en"。
 */
function detectSystemLocale(): Locale {
	if (typeof navigator === "undefined") {
		return defaultLocale;
	}
	const language = navigator.language ?? "";
	return language.toLowerCase().startsWith("zh") ? "zh-CN" : "en";
}

/**
 * 读取持久化的语言偏好；无存储时回退到系统语言检测。
 */
function readStoredLocale(): Locale {
	if (typeof window === "undefined") {
		return defaultLocale;
	}
	try {
		const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
		if (stored === "zh-CN" || stored === "en") {
			return stored;
		}
	} catch {
		// localStorage 不可用（隐私模式等）：回退到系统检测
	}
	return detectSystemLocale();
}

/**
 * 持久化语言偏好；localStorage 不可用时静默忽略。
 */
function persistLocale(locale: Locale): void {
	if (typeof window === "undefined") {
		return;
	}
	try {
		window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
	} catch {
		// 忽略写入失败
	}
}

export type LanguageContextValue = {
	locale: Locale;
	setLocale: (locale: Locale) => void;
	t: TranslateFn;
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

export type LanguageProviderProps = {
	children: ReactNode;
};

/**
 * 语言上下文 Provider：包裹 App，提供运行时语言切换、持久化与插值翻译。
 *
 * 初始 locale 优先取 localStorage（key={@link LOCALE_STORAGE_KEY}），
 * 无存储时按 `navigator.language` 检测系统语言。
 */
export function LanguageProvider({ children }: LanguageProviderProps) {
	const [locale, setLocaleState] = useState<Locale>(readStoredLocale);

	const setLocale = useCallback((next: Locale): void => {
		setLocaleState(next);
		persistLocale(next);
	}, []);

	const value = useMemo<LanguageContextValue>(
		() => ({
			locale,
			setLocale,
			t: createTranslator(locale),
		}),
		[locale, setLocale],
	);

	return createElement(LanguageContext.Provider, { value }, children);
}

/**
 * 翻译 Hook：返回 `{ t, locale, setLocale }`。必须在 {@link LanguageProvider} 内使用。
 *
 * @example
 * const { t, locale, setLocale } = useTranslation();
 * <button>{t("composer.send")}</button>
 * <span>{t("conversation.messageCount", { count: 12 })}</span>
 */
export function useTranslation(): LanguageContextValue {
	const context = useContext(LanguageContext);
	if (!context) {
		throw new Error("useTranslation must be used within a LanguageProvider");
	}
	return context;
}
