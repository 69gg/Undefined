/**
 * 格式化文件大小为人类可读的字符串
 * @param bytes 字节数
 * @returns 格式化的文件大小字符串（如 "1.5 MB"）
 */
export function formatFileSize(bytes: number): string {
	if (bytes <= 0) {
		return "0 B";
	}
	if (bytes < 1024) {
		return `${bytes} B`;
	}
	if (bytes < 1024 * 1024) {
		return `${Math.round((bytes / 1024) * 10) / 10} KB`;
	}
	if (bytes < 1024 * 1024 * 1024) {
		return `${Math.round((bytes / 1024 / 1024) * 10) / 10} MB`;
	}
	return `${Math.round((bytes / 1024 / 1024 / 1024) * 10) / 10} GB`;
}
