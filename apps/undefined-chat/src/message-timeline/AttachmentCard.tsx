import { resolveAttachmentUrl } from "../rendering/AttachmentProcessor";
import type { Attachment } from "../runtime-client/types";
import { formatFileSize } from "../utils/file-size";

export type AttachmentCardProps = {
	attachment: Attachment;
	onPreview?: (attachment: Attachment) => void;
	onDownload?: (attachment: Attachment) => void;
	/** Runtime 地址，用于把后端返回的相对预览 URL 解析为绝对地址（非同源 Tauri 客户端必需） */
	runtimeUrl?: string;
};

/**
 * 根据 MIME 类型返回文件图标文本
 */
function getFileIcon(mediaType: string): string {
	if (mediaType.startsWith("image/")) return "IMG";
	if (mediaType.startsWith("video/")) return "VID";
	if (mediaType.startsWith("audio/")) return "AUD";
	if (mediaType.startsWith("text/")) return "TXT";
	if (mediaType.includes("pdf")) return "PDF";
	if (mediaType.includes("zip") || mediaType.includes("tar")) return "ZIP";
	if (
		mediaType.includes("json") ||
		mediaType.includes("xml") ||
		mediaType.includes("yaml")
	)
		return "DAT";
	return "FILE";
}

/**
 * 判断是否为图片附件
 */
function isImageAttachment(attachment: Attachment): boolean {
	return (
		attachment.kind === "image" || attachment.mediaType.startsWith("image/")
	);
}

/**
 * 判断是否应该内联显示图片（小于 12MB）
 */
function shouldInlineImage(attachment: Attachment): boolean {
	const MAX_INLINE_SIZE = 12 * 1024 * 1024; // 12MB
	return isImageAttachment(attachment) && attachment.size < MAX_INLINE_SIZE;
}

/**
 * 附件卡片组件：渲染图片或文件附件
 * - 图片 < 12MB：内联显示缩略图，点击预览
 * - 文件：显示图标 + 文件名 + 大小 + 下载按钮
 */
export function AttachmentCard({
	attachment,
	onPreview,
	onDownload,
	runtimeUrl,
}: AttachmentCardProps) {
	const isImage = isImageAttachment(attachment);
	const shouldInline = shouldInlineImage(attachment);
	// 仅解析实际渲染的 src；gating 仍判断原始 previewUrl，避免空 runtimeUrl 时误降级为文件卡片
	const previewSrc = resolveAttachmentUrl(attachment.previewUrl, runtimeUrl);

	// 内联图片显示
	if (shouldInline && attachment.previewUrl) {
		return (
			<button
				className="runtime-chat-image-wrapper"
				onClick={() => onPreview?.(attachment)}
				style={{
					border: "none",
					background: "transparent",
					padding: 0,
					cursor: onPreview ? "pointer" : "default",
					display: "block",
				}}
				title={attachment.name}
				type="button"
			>
				<img
					alt={attachment.name}
					className="runtime-chat-image"
					loading="lazy"
					decoding="async"
					src={previewSrc}
					style={{
						maxWidth: "100%",
						height: "auto",
						borderRadius: "8px",
						border: "1px solid var(--border-color)",
						display: "block",
					}}
				/>
			</button>
		);
	}

	// 文件卡片显示
	return (
		<div
			className="runtime-chat-file-card"
			style={{
				display: "flex",
				alignItems: "center",
				gap: "12px",
				padding: "12px",
				borderRadius: "8px",
				border: "1px solid var(--border-color)",
				background: "color-mix(in srgb, var(--bg-card) 72%, var(--bg-app))",
				transition: "border-color 0.18s ease, background 0.18s ease",
			}}
		>
			{/* 文件图标或图片缩略图 */}
			<div
				className="runtime-chat-attachment-preview"
				style={{
					display: "inline-flex",
					alignItems: "center",
					justifyContent: "center",
					width: "40px",
					height: "40px",
					flexShrink: 0,
					borderRadius: "6px",
					background: "color-mix(in srgb, var(--accent) 14%, transparent)",
					color: "var(--accent)",
					fontSize: "10px",
					fontWeight: 700,
					overflow: "hidden",
				}}
			>
				{isImage && attachment.previewUrl ? (
					<img
						alt=""
						className="runtime-chat-attachment-thumb"
						src={previewSrc}
						style={{
							width: "100%",
							height: "100%",
							objectFit: "cover",
							display: "block",
						}}
					/>
				) : (
					<span>{getFileIcon(attachment.mediaType)}</span>
				)}
			</div>

			{/* 文件信息 */}
			<div
				className="file-info"
				style={{
					flex: 1,
					minWidth: 0,
					display: "flex",
					flexDirection: "column",
					gap: "2px",
				}}
			>
				<div
					className="runtime-chat-file-name"
					style={{
						fontSize: "13px",
						fontWeight: 600,
						color: "var(--text-primary)",
						overflow: "hidden",
						textOverflow: "ellipsis",
						whiteSpace: "nowrap",
					}}
					title={attachment.name}
				>
					{attachment.name}
				</div>
				<div
					className="runtime-chat-file-size"
					style={{
						fontSize: "11px",
						color: "var(--text-tertiary)",
					}}
				>
					{formatFileSize(attachment.size)}
				</div>
			</div>

			{/* 操作按钮 */}
			<div
				className="attachment-actions"
				style={{ display: "flex", gap: "6px", flexShrink: 0 }}
			>
				{isImage && attachment.previewUrl && onPreview ? (
					<button
						className="ghost-button"
						onClick={() => onPreview(attachment)}
						style={{ padding: "6px 12px", fontSize: "12px" }}
						title="预览"
						type="button"
					>
						预览
					</button>
				) : null}
				{onDownload ? (
					<button
						className="ghost-button"
						onClick={() => onDownload(attachment)}
						style={{ padding: "6px 12px", fontSize: "12px" }}
						title="下载"
						type="button"
					>
						下载
					</button>
				) : null}
			</div>
		</div>
	);
}
