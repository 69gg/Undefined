import type { MessageReference } from "../runtime-client/types";

export type ReferenceChipsProps = {
	references: MessageReference[];
	onClear: (messageId: string) => void;
};

function truncateText(text: string, maxLength: number): string {
	if (text.length <= maxLength) {
		return text;
	}
	return `${text.slice(0, maxLength)}...`;
}

export function ReferenceChips({ references, onClear }: ReferenceChipsProps) {
	if (references.length === 0) {
		return null;
	}

	return (
		<div className="composer-references">
			{references.map((reference) => (
				<span className="composer-chip" key={reference.messageId}>
					<span className="chip-icon">↩</span>
					<span className="chip-preview">
						{truncateText(reference.quote, 180)}
					</span>
					<button
						aria-label={`取消引用消息 ${reference.messageId}`}
						onClick={() => onClear(reference.messageId)}
						type="button"
					>
						×
					</button>
				</span>
			))}
		</div>
	);
}
