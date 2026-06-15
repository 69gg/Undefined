import { useTranslation } from "../i18n";
import { AttachmentImage } from "../rendering/AttachmentImage";
import type { Attachment } from "../runtime-client/types";
import { isImageAttachment } from "../utils/attachment";
import { getFileIcon } from "../utils/file-icon";
import { formatFileSize } from "../utils/file-size";

export type AttachmentCardProps = {
	attachment: Attachment;
	/** 文件卡片「预览」按钮：在新窗口打开（内联图片走 onOpenImage 放大） */
	onPreview?: (attachment: Attachment) => void;
	onDownload?: (attachment: Attachment) => void;
	/** 内联图片点击放大，回传已加载的 blob URL */
	onOpenImage?: (src: string, alt: string) => void;
};

/**
 * 判断是否应该内联显示图片（小于 12MB）
 */
function shouldInlineImage(attachment: Attachment): boolean {
	const MAX_INLINE_SIZE = 12 * 1024 * 1024; // 12MB
	return isImageAttachment(attachment) && attachment.size < MAX_INLINE_SIZE;
}

/**
 * 附件卡片组件：渲染图片或文件附件
 * - 图片 < 12MB：内联显示缩略图（经 Tauri 带 auth 拉取转 blob），点击放大
 * - 文件：显示图标 + 文件名 + 大小 + 下载按钮
 */
export function AttachmentCard({
	attachment,
	onPreview,
	onDownload,
	onOpenImage,
}: AttachmentCardProps) {
	const { t } = useTranslation();
	const isImage = isImageAttachment(attachment);
	const shouldInline = shouldInlineImage(attachment);

	// 内联图片显示（blob 渲染，加载失败由 AttachmentImage 降级为图标）
	if (shouldInline) {
		return (
			<AttachmentImage
				uid={attachment.id}
				alt={attachment.name}
				mediaType={attachment.mediaType}
				className="runtime-chat-image"
				style={{
					maxWidth: "100%",
					height: "auto",
					borderRadius: "8px",
					border: "1px solid var(--border-color)",
					display: "block",
				}}
				onOpenImage={onOpenImage}
			/>
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
				{isImage ? (
					<AttachmentImage
						uid={attachment.id}
						alt=""
						mediaType={attachment.mediaType}
						className="runtime-chat-attachment-thumb"
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
				{isImage && onPreview ? (
					<button
						className="ghost-button"
						onClick={() => onPreview(attachment)}
						style={{ padding: "6px 12px", fontSize: "12px" }}
						title={t("attachment.preview")}
						type="button"
					>
						{t("attachment.preview")}
					</button>
				) : null}
				{onDownload ? (
					<button
						className="ghost-button"
						onClick={() => onDownload(attachment)}
						style={{ padding: "6px 12px", fontSize: "12px" }}
						title={t("attachment.download")}
						type="button"
					>
						{t("attachment.download")}
					</button>
				) : null}
			</div>
		</div>
	);
}
