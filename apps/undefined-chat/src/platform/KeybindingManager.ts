/**
 * KeybindingManager - 桌面端快捷键管理器
 *
 * 统一管理应用内快捷键绑定，支持：
 * - Ctrl/Cmd、Alt、Shift 组合键
 * - 单键绑定（如 Escape）
 * - 运行时注册/注销
 * - 自动防止默认浏览器行为
 */

export type KeybindingHandler = () => void;

export class KeybindingManager {
	private bindings = new Map<string, KeybindingHandler>();
	private boundListener: ((event: KeyboardEvent) => void) | null = null;

	/**
	 * 注册快捷键
	 * @param key 标准化的键名（如 "Ctrl+N"、"Escape"）
	 * @param handler 触发时的回调函数
	 */
	register(key: string, handler: KeybindingHandler): void {
		this.bindings.set(key, handler);
	}

	/**
	 * 注销快捷键
	 * @param key 标准化的键名
	 */
	unregister(key: string): void {
		this.bindings.delete(key);
	}

	/**
	 * 清空所有绑定
	 */
	clear(): void {
		this.bindings.clear();
	}

	/**
	 * 开始监听键盘事件（通常在组件挂载时调用）
	 */
	startListening(): void {
		if (this.boundListener) {
			return; // 已在监听
		}
		this.boundListener = (event: KeyboardEvent) => {
			this.handleKeyDown(event);
		};
		window.addEventListener("keydown", this.boundListener);
	}

	/**
	 * 停止监听键盘事件（通常在组件卸载时调用）
	 */
	stopListening(): void {
		if (this.boundListener) {
			window.removeEventListener("keydown", this.boundListener);
			this.boundListener = null;
		}
	}

	/**
	 * 处理键盘按下事件
	 */
	private handleKeyDown(event: KeyboardEvent): void {
		// 忽略输入框内的快捷键（除了 Escape）
		if (
			event.key !== "Escape" &&
			(event.target instanceof HTMLInputElement ||
				event.target instanceof HTMLTextAreaElement)
		) {
			return;
		}

		const key = this.normalizeKey(event);
		const handler = this.bindings.get(key);
		if (handler) {
			event.preventDefault();
			event.stopPropagation();
			handler();
		}
	}

	/**
	 * 标准化键盘事件为统一的键名字符串
	 * 格式：[Ctrl+][Alt+][Shift+]Key
	 *
	 * 注意：
	 * - macOS 上的 Cmd 键会统一映射为 Ctrl（metaKey）
	 * - 修饰键按 Ctrl → Alt → Shift 的顺序排列
	 */
	private normalizeKey(event: KeyboardEvent): string {
		const parts: string[] = [];

		// Ctrl 或 Cmd（macOS）
		if (event.ctrlKey || event.metaKey) {
			parts.push("Ctrl");
		}

		// Alt/Option
		if (event.altKey) {
			parts.push("Alt");
		}

		// Shift
		if (event.shiftKey) {
			parts.push("Shift");
		}

		// 主键（统一为大写）
		const mainKey =
			event.key.length === 1 ? event.key.toUpperCase() : event.key;
		parts.push(mainKey);

		return parts.join("+");
	}

	/**
	 * 获取当前所有绑定的键名列表（用于调试）
	 */
	getRegisteredKeys(): string[] {
		return Array.from(this.bindings.keys());
	}
}
