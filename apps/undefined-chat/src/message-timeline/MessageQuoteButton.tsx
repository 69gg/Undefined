export type MessageQuoteButtonProps = {
	messageId: string;
	onQuote: (messageId: string) => void;
};

export function MessageQuoteButton({
	messageId,
	onQuote,
}: MessageQuoteButtonProps) {
	return (
		<button
			className="runtime-chat-quote-btn"
			onClick={() => onQuote(messageId)}
			title="引用这条消息"
			type="button"
		>
			引用
		</button>
	);
}
