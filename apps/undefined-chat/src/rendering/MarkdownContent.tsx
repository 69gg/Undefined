import type { ReactNode } from "react";

export type HtmlPreviewRequest = {
	title: string;
	html: string;
};

export type MarkdownContentProps = {
	content: string;
	onPreviewHtml: (input: HtmlPreviewRequest) => void;
};

type Segment =
	| { type: "text"; value: string }
	| { type: "code"; language: string; value: string };

function splitSegments(content: string): Segment[] {
	const segments: Segment[] = [];
	const pattern = /```([A-Za-z0-9_-]*)\n?([\s\S]*?)```/g;
	let cursor = 0;
	for (const match of content.matchAll(pattern)) {
		const index = match.index ?? 0;
		if (index > cursor) {
			segments.push({ type: "text", value: content.slice(cursor, index) });
		}
		segments.push({
			type: "code",
			language: match[1]?.trim().toLowerCase() ?? "",
			value: match[2] ?? "",
		});
		cursor = index + match[0].length;
	}
	if (cursor < content.length) {
		segments.push({ type: "text", value: content.slice(cursor) });
	}
	return segments.length > 0 ? segments : [{ type: "text", value: content }];
}

function renderInline(text: string): ReactNode[] {
	const nodes: ReactNode[] = [];
	const pattern = /(`[^`]+`|\*\*[^*]+\*\*)/g;
	let cursor = 0;
	for (const match of text.matchAll(pattern)) {
		const index = match.index ?? 0;
		if (index > cursor) {
			nodes.push(text.slice(cursor, index));
		}
		const value = match[0];
		if (value.startsWith("**")) {
			nodes.push(<strong key={`${index}-strong`}>{value.slice(2, -2)}</strong>);
		} else {
			nodes.push(<code key={`${index}-code`}>{value.slice(1, -1)}</code>);
		}
		cursor = index + value.length;
	}
	if (cursor < text.length) {
		nodes.push(text.slice(cursor));
	}
	return nodes;
}

function TextBlock({ value }: { value: string }) {
	return (
		<>
			{value
				.split(/\n{2,}/)
				.filter((paragraph) => paragraph.trim().length > 0)
				.map((paragraph, index) => (
					<p key={`${index}-${paragraph.slice(0, 12)}`}>
						{renderInline(paragraph)}
					</p>
				))}
		</>
	);
}

export function MarkdownContent({
	content,
	onPreviewHtml,
}: MarkdownContentProps) {
	return (
		<div className="message-markdown">
			{splitSegments(content).map((segment, index) => {
				if (segment.type === "text") {
					return (
						<TextBlock
							key={`${index}-text-${segment.value.slice(0, 12)}`}
							value={segment.value}
						/>
					);
				}
				const isHtml = ["html", "htm"].includes(segment.language);
				return (
					<figure
						className="code-block"
						key={`${index}-code-${segment.value.slice(0, 12)}`}
					>
						<figcaption>
							<span>{segment.language || "text"}</span>
							{isHtml ? (
								<button
									type="button"
									onClick={() =>
										onPreviewHtml({
											title: "HTML 预览",
											html: segment.value.trim(),
										})
									}
								>
									预览 HTML
								</button>
							) : null}
						</figcaption>
						<pre>
							<code>{segment.value.trim()}</code>
						</pre>
					</figure>
				);
			})}
		</div>
	);
}
