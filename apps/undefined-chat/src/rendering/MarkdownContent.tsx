import { marked } from "marked";
import { useMemo, useState } from "react";

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

// 选项配置 marked，使其解析换行和符合 GFM 标准
marked.setOptions({
	gfm: true,
	breaks: true,
});

function TextBlock({ value }: { value: string }) {
	const htmlContent = useMemo(() => {
		try {
			// marked.parse 返回 string
			return marked.parse(value) as string;
		} catch (err) {
			console.error("Markdown parse error:", err);
			return value;
		}
	}, [value]);

	return (
		<div
			className="markdown-body"
			// biome-ignore lint/security/noDangerouslySetInnerHtml: trust marked output for rendering messages
			dangerouslySetInnerHTML={{ __html: htmlContent }}
		/>
	);
}

function CodeBlock({
	language,
	value,
	onPreviewHtml,
}: {
	language: string;
	value: string;
	onPreviewHtml: (input: HtmlPreviewRequest) => void;
}) {
	const [copied, setCopied] = useState(false);
	const isHtml = ["html", "htm"].includes(language);

	async function handleCopy() {
		try {
			await navigator.clipboard.writeText(value);
			setCopied(true);
			setTimeout(() => setCopied(false), 2000);
		} catch (err) {
			console.error("Failed to copy code:", err);
		}
	}

	return (
		<figure className="code-block">
			<figcaption>
				<span>{language || "code"}</span>
				<div style={{ display: "flex", gap: "8px" }}>
					{isHtml ? (
						<button
							type="button"
							onClick={() =>
								onPreviewHtml({
									title: "HTML 预览",
									html: value.trim(),
								})
							}
						>
							预览 HTML
						</button>
					) : null}
					<button type="button" onClick={handleCopy}>
						{copied ? "已复制" : "复制"}
					</button>
				</div>
			</figcaption>
			<pre>
				<code>{value.trim()}</code>
			</pre>
		</figure>
	);
}

export function MarkdownContent({
	content,
	onPreviewHtml,
}: MarkdownContentProps) {
	const segments = useMemo(() => splitSegments(content), [content]);

	return (
		<div className="message-markdown">
			{segments.map((segment, index) => {
				if (segment.type === "text") {
					return (
						<TextBlock
							key={`${index}-text-${segment.value.slice(0, 16)}`}
							value={segment.value}
						/>
					);
				}
				return (
					<CodeBlock
						key={`${index}-code-${segment.value.slice(0, 16)}`}
						language={segment.language}
						value={segment.value}
						onPreviewHtml={onPreviewHtml}
					/>
				);
			})}
		</div>
	);
}
