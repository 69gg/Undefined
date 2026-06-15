import { useTranslation } from "../i18n";
import { LanguageToggle } from "../i18n/LanguageToggle";
import type { Conversation } from "../runtime-client/types";
import { ThemeToggle } from "../theme/ThemeToggle";

export type ConversationListProps = {
	id?: string;
	conversations: Conversation[];
	selectedConversationId: string | null;
	onCreate: () => void;
	onDelete: (conversationId: string) => void;
	onRename: (conversationId: string) => void;
	onSelect: (conversationId: string) => void;
	/** 是否正在新建会话（新建按钮显示加载态） */
	creating: boolean;
	isCollapsed: boolean;
	onToggleCollapse: () => void;
	onOpenSettings: () => void;
	isMobileActive?: boolean;
};

export function ConversationList({
	id,
	conversations,
	selectedConversationId,
	onCreate,
	onDelete,
	onRename,
	onSelect,
	creating,
	isCollapsed,
	onToggleCollapse,
	onOpenSettings,
	isMobileActive = false,
}: ConversationListProps) {
	const { t } = useTranslation();
	const navLabel = t("conversation.nav");

	return (
		<nav
			id={id}
			aria-label={navLabel}
			className={`conversation-list ${isCollapsed ? "collapsed" : ""} ${isMobileActive ? "active" : ""}`}
			role={isMobileActive ? "dialog" : undefined}
			aria-modal={isMobileActive ? true : undefined}
		>
			<header className="rail-header">
				<h1>Undefined</h1>
				<button
					className="icon-button"
					onClick={onToggleCollapse}
					title={t("conversation.collapseSidebar")}
					type="button"
				>
					<svg
						fill="none"
						height="16"
						stroke="currentColor"
						strokeLinecap="round"
						strokeLinejoin="round"
						strokeWidth="2"
						viewBox="0 0 24 24"
						width="16"
					>
						<title>{t("conversation.collapseSidebar")}</title>
						<rect height="18" rx="2" ry="2" width="18" x="3" y="3" />
						<line x1="9" x2="9" y1="3" y2="21" />
					</svg>
				</button>
			</header>

			{/* 新建会话大按钮 */}
			<button
				className="ghost-button new-chat-btn"
				disabled={creating}
				onClick={onCreate}
				type="button"
			>
				{creating ? (
					<span aria-hidden="true" className="btn-spinner" />
				) : (
					<svg
						aria-hidden="true"
						fill="none"
						height="16"
						stroke="currentColor"
						strokeLinecap="round"
						strokeLinejoin="round"
						strokeWidth="2.5"
						viewBox="0 0 24 24"
						width="16"
					>
						<title>{t("conversation.create")}</title>
						<line x1="12" x2="12" y1="5" y2="19" />
						<line x1="5" x2="19" y1="12" y2="12" />
					</svg>
				)}
				{creating ? t("conversation.creating") : t("conversation.create")}
			</button>

			{/* 滚动会话列表 */}
			<div className="conversation-scroll">
				{conversations.map((conversation) => (
					<div className="conversation-item-wrap" key={conversation.id}>
						<button
							aria-current={
								conversation.id === selectedConversationId ? "page" : undefined
							}
							className="conversation-item"
							onClick={() => onSelect(conversation.id)}
							type="button"
						>
							<span className="conversation-title-row">
								<span className="conversation-title">
									{conversation.title || t("app.topbar.defaultConversation")}
								</span>
								{conversation.isRunning ? (
									<span className="running-dot">
										{t("conversation.running")}
									</span>
								) : null}
							</span>
							<span className="conversation-meta">
								<span>
									{t("conversation.messageCount", {
										count: conversation.messageCount,
									})}
								</span>
							</span>
						</button>
						<button
							aria-label={t("conversation.rename")}
							className="conversation-rename"
							onClick={() => onRename(conversation.id)}
							title={t("conversation.renameTitle", {
								title: conversation.title,
							})}
							type="button"
						>
							<svg
								aria-hidden="true"
								fill="none"
								height="15"
								stroke="currentColor"
								strokeLinecap="round"
								strokeLinejoin="round"
								strokeWidth="2"
								viewBox="0 0 24 24"
								width="15"
							>
								<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
								<path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
							</svg>
						</button>
						<button
							aria-label={t("conversation.delete")}
							className="conversation-delete"
							onClick={() => onDelete(conversation.id)}
							title={t("conversation.deleteTitle", {
								title: conversation.title,
							})}
							type="button"
						>
							<svg
								aria-hidden="true"
								fill="none"
								height="15"
								stroke="currentColor"
								strokeLinecap="round"
								strokeLinejoin="round"
								strokeWidth="2"
								viewBox="0 0 24 24"
								width="15"
							>
								<polyline points="3 6 5 6 21 6" />
								<path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
							</svg>
						</button>
					</div>
				))}
			</div>

			{/* 侧边栏底部设置区 */}
			<div className="sidebar-footer">
				<div className="sidebar-footer-row">
					<div className="user-badge">
						<div className="user-avatar">UD</div>
						<span style={{ fontSize: "0.85rem", fontWeight: "600" }}>
							{t("conversation.user")}
						</span>
					</div>
					<div style={{ display: "flex", gap: "8px" }}>
						<ThemeToggle />
						<LanguageToggle />
						<button
							className="icon-button"
							onClick={onOpenSettings}
							title={t("conversation.configRuntime")}
							type="button"
						>
							<svg
								fill="none"
								height="16"
								stroke="currentColor"
								strokeLinecap="round"
								strokeLinejoin="round"
								strokeWidth="2"
								viewBox="0 0 24 24"
								width="16"
							>
								<title>{t("conversation.configRuntime")}</title>
								<circle cx="12" cy="12" r="3" />
								<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
							</svg>
						</button>
					</div>
				</div>
			</div>
		</nav>
	);
}
