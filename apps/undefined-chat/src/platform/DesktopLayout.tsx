import type { ReactNode } from "react";

/**
 * DesktopLayout - 桌面端特定布局包装器
 *
 * 提供桌面端特有的布局增强，包括：
 * - 窗口拖拽区域（未来）
 * - 原生菜单栏集成（未来）
 * - 平台特定样式调整
 *
 * 当前版本保持简单包装，为未来扩展预留结构。
 */

export interface DesktopLayoutProps {
	children: ReactNode;
	/** 是否启用桌面端特定样式（如自定义标题栏） */
	enableCustomTitleBar?: boolean;
}

export function DesktopLayout({
	children,
	enableCustomTitleBar = false,
}: DesktopLayoutProps) {
	// 未来可在此处添加：
	// - 自定义标题栏（data-tauri-drag-region）
	// - 原生菜单栏触发器
	// - 平台特定的 CSS 类名
	//
	// 当前作为透明语义包装：用 display:contents 让自身盒子从布局中消失，
	// 子元素直接参与父容器（.chat-workspace）的 flex 布局，避免破坏现有列布局。

	return (
		<div
			className="desktop-layout"
			data-custom-titlebar={enableCustomTitleBar ? "true" : undefined}
			style={{ display: "contents" }}
		>
			{children}
		</div>
	);
}
