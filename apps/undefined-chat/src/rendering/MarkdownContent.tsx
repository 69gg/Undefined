import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import type { Attachment } from "../runtime-client/types";
import {
	extractAttachmentTags,
	renderAttachmentPlaceholders,
} from "./AttachmentProcessor";
import { CodeBlock } from "./CodeBlock";
import "./MarkdownContent.css";

export type HtmlPreviewRequest = {
	title: string;
	html: string;
};

export type MarkdownContentProps = {
	content: string;
	onPreviewHtml: (input: HtmlPreviewRequest) => void;
	attachments?: Attachment[];
	runtimeUrl?: string;
	onImageClick?: (src: string, alt: string) => void;
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
	onImageClick?: (src: string, alt: string) => void;
};

function TextBlock({ value, onPreviewHtml, onImageClick }: TextBlockProps) {
	const components = useMemo<Components>(
		() => ({
			// 自定义链接渲染：添加 target="_blank" 和安全属性
			a: ({ href, children, ...props }) => (
				<a href={href} target="_blank" rel="noopener noreferrer" {...props}>
					{children}
				</a>
			),
			// 自定义图片渲染：支持点击预览
			// biome-ignore lint/a11y/useAltText: alt is passed from markdown content
			img: ({ src, alt, ...props }) => (
				<img
					src={src}
					alt={alt || ""}
					loading="lazy"
					decoding="async"
					style={{
						maxWidth: "100%",
						height: "auto",
						borderRadius: "8px",
						cursor: onImageClick ? "pointer" : "default",
					}}
					onClick={() => {
						if (onImageClick && src) {
							onImageClick(src, alt || "");
						}
					}}
					onKeyDown={(e) => {
						if (onImageClick && src && (e.key === "Enter" || e.key === " ")) {
							onImageClick(src, alt || "");
						}
					}}
					role={onImageClick ? "button" : undefined}
					tabIndex={onImageClick ? 0 : undefined}
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
		[onPreviewHtml, onImageClick],
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
	attachments = [],
	runtimeUrl,
	onImageClick,
}: MarkdownContentProps) {
	// 提取附件标签并替换为占位符
	const { cleanContent, attachmentUids, inlineImages } = useMemo(
		() => extractAttachmentTags(content, runtimeUrl),
		[content, runtimeUrl],
	);

	const segments = useMemo(() => splitSegments(cleanContent), [cleanContent]);

	// 处理后渲染附件占位符
	const processedSegments = useMemo(() => {
		return segments.map((segment) => {
			if (segment.type === "text") {
				const processed = renderAttachmentPlaceholders(
					segment.value,
					attachmentUids,
					inlineImages,
					attachments,
					runtimeUrl,
				);
				return { ...segment, value: processed };
			}
			return segment;
		});
	}, [segments, attachmentUids, inlineImages, attachments, runtimeUrl]);

	return (
		<div className="message-markdown">
			{processedSegments.map((segment, index) => {
				if (segment.type === "text") {
					// 如果包含附件 HTML，使用 dangerouslySetInnerHTML
					if (segment.value.includes("runtime-chat-image")) {
						return (
							<div
								key={`${index}-text-${segment.value.slice(0, 16)}`}
								className="markdown-body"
								// biome-ignore lint/security/noDangerouslySetInnerHtml: 由 renderAttachmentPlaceholders 生成的安全 HTML
								dangerouslySetInnerHTML={{ __html: segment.value }}
								onClick={(e) => {
									const target = e.target as HTMLElement;
									if (
										target.tagName === "IMG" &&
										target.classList.contains("runtime-chat-image")
									) {
										const src = target.getAttribute("src");
										const alt = target.getAttribute("alt");
										if (onImageClick && src) {
											onImageClick(src, alt || "");
										}
									}
								}}
								onKeyDown={(e) => {
									const target = e.target as HTMLElement;
									if (
										target.tagName === "IMG" &&
										target.classList.contains("runtime-chat-image") &&
										(e.key === "Enter" || e.key === " ")
									) {
										const src = target.getAttribute("src");
										const alt = target.getAttribute("alt");
										if (onImageClick && src) {
											onImageClick(src, alt || "");
										}
									}
								}}
								role="presentation"
							/>
						);
					}
					return (
						<TextBlock
							key={`${index}-text-${segment.value.slice(0, 16)}`}
							value={segment.value}
							onPreviewHtml={onPreviewHtml}
							onImageClick={onImageClick}
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
