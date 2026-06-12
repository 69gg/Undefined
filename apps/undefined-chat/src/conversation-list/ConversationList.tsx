import type { Conversation } from "../runtime-client/types";
import { ThemeToggle } from "../theme/ThemeToggle";

export type ConversationListProps = {
	conversations: Conversation[];
	selectedConversationId: string | null;
	onCreate: () => void;
	onSelect: (conversationId: string) => void;
};

function messageCountLabel(count: number): string {
	return `${count} 条消息`;
}

export function ConversationList({
	conversations,
	selectedConversationId,
	onCreate,
	onSelect,
}: ConversationListProps) {
	return (
		<nav aria-label="会话" className="conversation-list">
			<header className="rail-header">
				<h1>Undefined Chat</h1>
				<div style={{ display: "flex", gap: "8px" }}>
					<ThemeToggle />
					<button className="ghost-button" type="button" onClick={onCreate}>
						新建
					</button>
				</div>
			</header>
			<div className="conversation-scroll">
				{conversations.map((conversation) => (
					<button
						aria-current={
							conversation.id === selectedConversationId ? "page" : undefined
						}
						className="conversation-item"
						key={conversation.id}
						onClick={() => onSelect(conversation.id)}
						type="button"
					>
						<span className="conversation-title-row">
							<span className="conversation-title">{conversation.title}</span>
							{conversation.isRunning ? (
								<span className="running-dot">运行中</span>
							) : null}
						</span>
						<span className="conversation-meta">
							{messageCountLabel(conversation.messageCount)}
						</span>
					</button>
				))}
			</div>
		</nav>
	);
}
