import type { Attachment } from "../runtime-client/types";

type ExtractResult = {
	cleanContent: string;
	attachmentUids: string[];
	inlineImages: { placeholder: string; src: string }[];
};

/**
 * 解析 CQ 属性字符串 "key1=value1,key2=value2"
 */
function parseCqAttributes(attrStr: string): Record<string, string> {
	const attrs: Record<string, string> = {};
	for (const pair of attrStr.split(",")) {
		const eqIdx = pair.indexOf("=");
		if (eqIdx > 0) {
			attrs[pair.slice(0, eqIdx).trim()] = pair.slice(eqIdx + 1).trim();
		}
	}
	return attrs;
}

/**
 * 解析消息内容中的各类图片/附件标签
 * 支持 <attachment uid="..."/>, <pic uid="..."/>, [CQ:image,...], [CQ:file,...]
 */
export function extractAttachmentTags(
	content: string,
	runtimeUrl?: string,
): ExtractResult {
	const uids: string[] = [];
	const inlineImages: { placeholder: string; src: string }[] = [];
	let processed = content;

	// 1. 处理 <attachment uid="..."/> 和 <pic uid="..."/>
	const attachmentPattern =
		/<(?:attachment|pic)\s+uid=["']([^"']+)["']\s*\/?\s*>/gi;
	processed = processed.replace(attachmentPattern, (_match, uid) => {
		uids.push(uid);
		return `ATTACHMENT_PLACEHOLDER_${uids.length - 1}`;
	});

	// 2. 处理 [CQ:image,...] 码
	const imagePattern = /\[CQ:image,([^\]]+)\]/g;
	processed = processed.replace(imagePattern, (_match, attrStr) => {
		const attrs = parseCqAttributes(attrStr);
		const src = resolveCQImageUrl(attrs.url || attrs.file || "", runtimeUrl);
		if (src) {
			const placeholder = `CQ_IMAGE_PLACEHOLDER_${inlineImages.length}`;
			inlineImages.push({ placeholder, src });
			return placeholder;
		}
		return _match;
	});

	// 3. 处理 [CQ:file,...] 码 — 直接移除（已由 attachments 展示）
	processed = processed.replace(/\[CQ:file,[^\]]+\]/g, "");

	return { cleanContent: processed, attachmentUids: uids, inlineImages };
}

/**
 * 将 CQ 图片码中的 URL 转换为可访问的地址
 */
export function resolveCQImageUrl(
	url: string,
	runtimeUrl?: string,
): string | null {
	const trimmed = url.trim();
	if (!trimmed) return null;

	if (trimmed.startsWith("base64://")) {
		const payload = trimmed.slice("base64://".length).trim();
		return payload ? `data:image/png;base64,${payload}` : null;
	}

	if (trimmed.startsWith("file://")) {
		const localPath = trimmed.slice("file://".length).trim();
		const base = runtimeUrl || "";
		return localPath
			? `${base}/api/runtime/chat/image?path=${encodeURIComponent(localPath)}`
			: null;
	}

	if (trimmed.startsWith("/") || /^[A-Za-z]:[\\/]/.test(trimmed)) {
		const base = runtimeUrl || "";
		return `${base}/api/runtime/chat/image?path=${encodeURIComponent(trimmed)}`;
	}

	if (
		trimmed.startsWith("http://") ||
		trimmed.startsWith("https://") ||
		trimmed.startsWith("data:image/")
	) {
		return trimmed;
	}

	return null;
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
 * 渲染附件和内联图片占位符为实际 HTML 内容
 */
export function renderAttachmentPlaceholders(
	html: string,
	attachmentUids: string[],
	inlineImages: { placeholder: string; src: string }[],
	attachments: Attachment[],
	runtimeUrl?: string,
): string {
	let result = html;

	// 处理附件标签占位符
	for (let i = 0; i < attachmentUids.length; i++) {
		const uid = attachmentUids[i];
		const attachment = findAttachmentByUid(attachments, uid);
		const placeholder = `ATTACHMENT_PLACEHOLDER_${i}`;

		if (attachment?.mediaType?.startsWith("image/")) {
			const src =
				attachment.previewUrl ||
				attachment.downloadUrl ||
				(runtimeUrl
					? `${runtimeUrl}/api/runtime/attachments/${encodeURIComponent(uid)}/preview`
					: "");

			const imgTag = `<img class="runtime-chat-image" src="${escapeHtml(src)}" alt="${escapeHtml(attachment.name)}" loading="lazy" decoding="async" data-attachment-id="${escapeHtml(uid)}" />`;
			result = result.replace(new RegExp(placeholder, "g"), imgTag);
		} else {
			result = result.replace(new RegExp(placeholder, "g"), "");
		}
	}

	// 处理 CQ 图片占位符
	for (const img of inlineImages) {
		const imgTag = `<img class="runtime-chat-image" src="${escapeHtml(img.src)}" alt="image" loading="lazy" decoding="async" />`;
		result = result.replace(new RegExp(img.placeholder, "g"), imgTag);
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
