import { Fragment, type ReactNode, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import type { Attachment } from "../runtime-client/types";
import { AttachmentImage } from "./AttachmentImage";
import {
	extractAttachmentTags,
	findAttachmentByUid,
} from "./AttachmentProcessor";
import { CodeBlock } from "./CodeBlock";
import { markdownRehypePlugins } from "./sanitize";
import "./MarkdownContent.css";

export type HtmlPreviewRequest = {
	title: string;
	html: string;
};

export type MarkdownContentProps = {
	content: string;
	onPreviewHtml: (input: HtmlPreviewRequest) => void;
	attachments?: Attachment[];
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
			// 自定义图片渲染：Markdown ![](url) 外链图，支持点击预览
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
				// rehype-raw 解析正文原始 HTML，rehype-sanitize 紧随其后按白名单清洗，
				// 顺序不可调换：先解析再清洗，确保脚本/事件/危险协议被剥离。
				rehypePlugins={markdownRehypePlugins}
				components={components}
			>
				{value}
			</ReactMarkdown>
		</div>
	);
}

const PLACEHOLDER_SPLIT = /(ATTACHMENT_PLACEHOLDER_\d+)/;
const PLACEHOLDER_MATCH = /^ATTACHMENT_PLACEHOLDER_(\d+)$/;

/**
 * 将含附件占位符的文字段渲染为「文字块 + 内联附件图片」交错序列。
 * 图片附件渲染为 {@link AttachmentImage}（经 Tauri 带 auth 拉取转 blob）；
 * 非图片附件移除（由附件区展示）；纯文字仍走 {@link TextBlock}（含 Markdown）。
 */
function renderTextWithAttachments(
	value: string,
	keyPrefix: string,
	attachmentUids: string[],
	attachments: Attachment[],
	onPreviewHtml: (input: HtmlPreviewRequest) => void,
	onImageClick?: (src: string, alt: string) => void,
): ReactNode[] {
	const nodes: ReactNode[] = [];
	value.split(PLACEHOLDER_SPLIT).forEach((part, idx) => {
		const match = PLACEHOLDER_MATCH.exec(part);
		if (match) {
			const uid = attachmentUids[Number(match[1])];
			const attachment = uid ? findAttachmentByUid(attachments, uid) : null;
			if (
				attachment &&
				(attachment.kind === "image" ||
					attachment.mediaType.startsWith("image/"))
			) {
				nodes.push(
					<AttachmentImage
						// biome-ignore lint/suspicious/noArrayIndexKey: 静态只读消息片段，不增删重排
						key={`${keyPrefix}-img-${idx}`}
						uid={attachment.id}
						alt={attachment.name}
						mediaType={attachment.mediaType}
						className="runtime-chat-image"
						onOpenImage={onImageClick}
					/>,
				);
			}
			return;
		}
		if (!part.trim()) return;
		nodes.push(
			<TextBlock
				// biome-ignore lint/suspicious/noArrayIndexKey: 静态只读消息片段，不增删重排
				key={`${keyPrefix}-text-${idx}`}
				value={part}
				onPreviewHtml={onPreviewHtml}
				onImageClick={onImageClick}
			/>,
		);
	});
	return nodes;
}

export function MarkdownContent({
	content,
	onPreviewHtml,
	attachments = [],
	onImageClick,
}: MarkdownContentProps) {
	// 提取附件标签并替换为占位符（占位符以空行包裹，作为独立块级元素）
	const { cleanContent, attachmentUids } = useMemo(
		() => extractAttachmentTags(content),
		[content],
	);

	const segments = useMemo(() => splitSegments(cleanContent), [cleanContent]);

	return (
		<div className="message-markdown">
			{segments.map((segment, index) => {
				if (segment.type === "code") {
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
				}
				return (
					<Fragment key={`${index}-text-${segment.value.slice(0, 16)}`}>
						{renderTextWithAttachments(
							segment.value,
							String(index),
							attachmentUids,
							attachments,
							onPreviewHtml,
							onImageClick,
						)}
					</Fragment>
				);
			})}
		</div>
	);
}
