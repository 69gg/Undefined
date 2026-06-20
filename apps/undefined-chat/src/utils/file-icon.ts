/**
 * 根据 MIME 类型返回文件图标文本（附件卡片与图片加载失败降级共用）。
 */
export function getFileIcon(mediaType: string): string {
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
