import type { Attachment } from "../runtime-client/types";

type ExtractResult = {
	cleanContent: string;
	attachmentUids: string[];
};

/**
 * 解析消息内容中的附件标签 `<attachment uid="..."/>` / `<pic uid="..."/>`，
 * 替换为占位符并收集 UID。
 *
 * 占位符以空行包裹，确保后续 Markdown 渲染时作为独立块级元素，不破坏文字块结构。
 * 图片在 Runtime API 输出环节已统一注册为附件并改写为 `<attachment uid/>`
 * （后端 `segment_text` 重建文本，不会残留 `[CQ:image]`/`[CQ:file]` 等 CQ 码），
 * 故客户端只需处理 UID 附件标签；实际图片字节经 Tauri（带 auth）按 UID 拉取。
 */
export function extractAttachmentTags(content: string): ExtractResult {
	const uids: string[] = [];
	const attachmentPattern =
		/<(?:attachment|pic)\s+uid=["']([^"']+)["']\s*\/?\s*>/gi;
	const cleanContent = content.replace(attachmentPattern, (_match, uid) => {
		uids.push(uid);
		return `\n\nATTACHMENT_PLACEHOLDER_${uids.length - 1}\n\n`;
	});
	return { cleanContent, attachmentUids: uids };
}

/**
 * 从附件列表中根据 UID 查找对应附件
 */
export function findAttachmentByUid(
	attachments: Attachment[],
	uid: string,
): Attachment | null {
	return attachments.find((a) => a.id === uid) || null;
}
