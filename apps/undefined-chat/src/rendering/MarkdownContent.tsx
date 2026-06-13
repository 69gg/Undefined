import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { CodeBlock } from "./CodeBlock";
import "./MarkdownContent.css";

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

type TextBlockProps = {
	value: string;
	onPreviewHtml: (input: HtmlPreviewRequest) => void;
};

function TextBlock({ value, onPreviewHtml }: TextBlockProps) {
	const components = useMemo<Components>(
		() => ({
			// 自定义链接渲染：添加 target="_blank" 和安全属性
			a: ({ href, children, ...props }) => (
				<a href={href} target="_blank" rel="noopener noreferrer" {...props}>
					{children}
				</a>
			),
			// 自定义图片渲染：支持点击预览（未来扩展）
			// biome-ignore lint/a11y/useAltText: alt is passed from markdown content
			img: ({ src, alt, ...props }) => (
				<img
					src={src}
					alt={alt || ""}
					loading="lazy"
					style={{ maxWidth: "100%", height: "auto" }}
					{...props}
				/>
			),
			// 自定义表格渲染
			table: ({ children, ...props }) => (
				<div style={{ overflowX: "auto" }}>
					<table {...props}>{children}</table>
				</div>
			),
			// 自定义代码块渲染：应用折叠逻辑
			code: ({ className, children, ...props }) => {
				const match = /language-(\w+)/.exec(className || "");
				const codeString = String(children).replace(/\n$/, "");

				// 检查是否为代码块（有 language- 前缀且有换行符）
				if (match && codeString.includes("\n")) {
					return (
						<CodeBlock
							code={codeString}
							language={match[1]}
							collapsible={true}
							maxLines={8}
							onPreviewHtml={onPreviewHtml}
						/>
					);
				}

				return (
					<code className={className} {...props}>
						{children}
					</code>
				);
			},
		}),
		[onPreviewHtml],
	);

	return (
		<div className="markdown-body">
			<ReactMarkdown
				remarkPlugins={[remarkGfm, remarkBreaks]}
				components={components}
			>
				{value}
			</ReactMarkdown>
		</div>
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
							onPreviewHtml={onPreviewHtml}
						/>
					);
				}
				return (
					<CodeBlock
						key={`${index}-code-${segment.value.slice(0, 16)}`}
						code={segment.value}
						language={segment.language}
						collapsible={true}
						maxLines={8}
						onPreviewHtml={onPreviewHtml}
					/>
				);
			})}
		</div>
	);
}
