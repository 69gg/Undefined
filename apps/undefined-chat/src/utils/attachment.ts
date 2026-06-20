import type { Attachment } from "../runtime-client/types";

/**
 * 判断附件是否为图片（按粗分类 kind 或 MIME media_type）。
 */
export function isImageAttachment(attachment: Attachment): boolean {
	return (
		attachment.kind === "image" || attachment.mediaType.startsWith("image/")
	);
}
