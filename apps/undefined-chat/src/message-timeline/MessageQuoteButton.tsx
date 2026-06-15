import { useTranslation } from "../i18n";

export type MessageQuoteButtonProps = {
	messageId: string;
	onQuote: (messageId: string) => void;
};

export function MessageQuoteButton({
	messageId,
	onQuote,
}: MessageQuoteButtonProps) {
	const { t } = useTranslation();
	return (
		<button
			className="runtime-chat-quote-btn"
			onClick={() => onQuote(messageId)}
			title={t("quote.title")}
			type="button"
		>
			{t("quote.button")}
		</button>
	);
}
