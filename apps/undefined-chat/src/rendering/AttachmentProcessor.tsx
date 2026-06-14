import type { Attachment } from "../runtime-client/types";

type ExtractResult = {
	cleanContent: string;
	attachmentUids: string[];
};

/**
 * 解析消息内容中的附件标签 `<attachment uid="..."/>` / `<pic uid="..."/>`，
 * 替换为占位符并收集 UID。
 *
 * 图片在 Runtime API 输出环节已统一注册为附件并改写为 `<attachment uid/>`
 * （后端 `segment_text` 重建文本，不会残留 `[CQ:image]`/`[CQ:file]` 等 CQ 码），
 * 故客户端只需处理 UID 附件标签。
 */
export function extractAttachmentTags(content: string): ExtractResult {
	const uids: string[] = [];
	let processed = content;

	const attachmentPattern =
		/<(?:attachment|pic)\s+uid=["']([^"']+)["']\s*\/?\s*>/gi;
	processed = processed.replace(attachmentPattern, (_match, uid) => {
		uids.push(uid);
		return `ATTACHMENT_PLACEHOLDER_${uids.length - 1}`;
	});

	return { cleanContent: processed, attachmentUids: uids };
}

/**
 * 将后端返回的附件 URL 解析为可直接访问的地址。
 *
 * Runtime API 返回的是相对路径（如 `/api/v1/chat/attachments/<uid>/preview`）。
 * undefined-chat 是独立 Tauri 应用，前端与 Runtime 不同源，相对路径会被解析到
 * `tauri://localhost` 而加载失败，因此根路径需补上 `runtimeUrl` 前缀。
 * 绝对地址（http/https/data:/blob:/协议相对）原样返回，避免重复前缀。
 */
export function resolveAttachmentUrl(
	url: string | null | undefined,
	runtimeUrl?: string,
): string {
	const trimmed = (url ?? "").trim();
	if (!trimmed) return "";

	if (
		trimmed.startsWith("http://") ||
		trimmed.startsWith("https://") ||
		trimmed.startsWith("data:") ||
		trimmed.startsWith("blob:") ||
		trimmed.startsWith("//")
	) {
		return trimmed;
	}

	if (trimmed.startsWith("/")) {
		const base = (runtimeUrl ?? "").replace(/\/+$/, "");
		return base ? `${base}${trimmed}` : trimmed;
	}

	return trimmed;
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

/**
 * 渲染附件占位符为实际 HTML 内容
 */
export function renderAttachmentPlaceholders(
	html: string,
	attachmentUids: string[],
	attachments: Attachment[],
	runtimeUrl?: string,
): string {
	let result = html;

	for (let i = 0; i < attachmentUids.length; i++) {
		const uid = attachmentUids[i];
		const attachment = findAttachmentByUid(attachments, uid);
		const placeholder = `ATTACHMENT_PLACEHOLDER_${i}`;

		if (attachment?.mediaType?.startsWith("image/")) {
			const src = resolveAttachmentUrl(
				attachment.previewUrl || attachment.downloadUrl,
				runtimeUrl,
			);

			const imgTag = `<img class="runtime-chat-image" src="${escapeHtml(src)}" alt="${escapeHtml(attachment.name)}" loading="lazy" decoding="async" data-attachment-id="${escapeHtml(uid)}" />`;
			result = result.replace(new RegExp(placeholder, "g"), imgTag);
		} else {
			result = result.replace(new RegExp(placeholder, "g"), "");
		}
	}

	return result;
}

function escapeHtml(str: string): string {
	const map: Record<string, string> = {
		"&": "&amp;",
		"<": "&lt;",
		">": "&gt;",
		'"': "&quot;",
		"'": "&#39;",
	};
	return str.replace(/[&<>"']/g, (char) => map[char] || char);
}
