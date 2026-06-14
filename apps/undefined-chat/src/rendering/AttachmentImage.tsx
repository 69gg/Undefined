import { type CSSProperties, useEffect, useState } from "react";
import { getFileIcon } from "../utils/file-icon";
import { useAttachmentImage } from "./AttachmentImageContext";

export type AttachmentImageProps = {
	uid: string;
	alt: string;
	/** 加载失败时按此 MIME 选择降级图标文本，默认按图片处理 */
	mediaType?: string;
	className?: string;
	style?: CSSProperties;
	/** 提供则图片可点击/回车打开大图，回传已加载的 blob URL */
	onOpenImage?: (src: string, alt: string) => void;
};

type LoadState =
	| { status: "loading" }
	| { status: "loaded"; url: string }
	| { status: "error" };

/**
 * 按 UID 经 Tauri（带 auth）拉取附件并以 blob URL 渲染图片。
 *
 * 三态：加载中（占位）/ 加载完成（`<img>`，可点击放大）/ 失败（文件图标降级）。
 * blob URL 由 {@link AttachmentImageProvider} 缓存与释放，本组件不自行 revoke。
 */
export function AttachmentImage({
	uid,
	alt,
	mediaType,
	className,
	style,
	onOpenImage,
}: AttachmentImageProps) {
	const { loadAttachmentBlob } = useAttachmentImage();
	const [state, setState] = useState<LoadState>({ status: "loading" });

	useEffect(() => {
		let cancelled = false;
		setState({ status: "loading" });
		loadAttachmentBlob(uid)
			.then((loaded) => {
				if (cancelled) return;
				setState(
					loaded ? { status: "loaded", url: loaded.url } : { status: "error" },
				);
			})
			.catch(() => {
				if (!cancelled) setState({ status: "error" });
			});
		return () => {
			cancelled = true;
		};
	}, [uid, loadAttachmentBlob]);

	if (state.status === "loading") {
		return (
			<div
				className={className}
				style={style}
				aria-busy="true"
				aria-label={alt || "图片加载中"}
			/>
		);
	}

	if (state.status === "error") {
		return (
			<div
				className={className}
				style={style}
				title={alt || "图片加载失败"}
				aria-label={alt || "图片加载失败"}
			>
				{getFileIcon(mediaType ?? "image/")}
			</div>
		);
	}

	const handleOpen = () => onOpenImage?.(state.url, alt);

	return (
		<img
			src={state.url}
			alt={alt}
			className={className}
			style={style}
			loading="lazy"
			decoding="async"
			onClick={onOpenImage ? handleOpen : undefined}
			onKeyDown={
				onOpenImage
					? (e) => {
							if (e.key === "Enter" || e.key === " ") {
								e.preventDefault();
								handleOpen();
							}
						}
					: undefined
			}
			role={onOpenImage ? "button" : undefined}
			tabIndex={onOpenImage ? 0 : undefined}
		/>
	);
}
