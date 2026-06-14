import { useEffect, useRef, useState } from "react";
import type { ImageViewerState } from "../chat-store/types";

export type ImageViewerModalProps = {
	imageViewer: ImageViewerState | null;
	onClose: () => void;
};

export function ImageViewerModal({
	imageViewer,
	onClose,
}: ImageViewerModalProps) {
	const previousActiveElementRef = useRef<HTMLElement | null>(null);
	const [zoom, setZoom] = useState(1);
	const [rotation, setRotation] = useState(0);

	useEffect(() => {
		if (imageViewer?.open) {
			setZoom(1);
			setRotation(0);
		}
	}, [imageViewer?.open]);

	// 焦点管理：打开时保存，关闭时恢复
	useEffect(() => {
		if (imageViewer?.open) {
			previousActiveElementRef.current =
				document.activeElement as HTMLElement | null;
		} else if (previousActiveElementRef.current) {
			previousActiveElementRef.current.focus();
			previousActiveElementRef.current = null;
		}
	}, [imageViewer?.open]);

	// ESC 键关闭
	useEffect(() => {
		if (!imageViewer?.open) return;

		const handleKeyDown = (e: KeyboardEvent) => {
			if (e.key === "Escape") {
				onClose();
			}
		};

		document.addEventListener("keydown", handleKeyDown);
		return () => document.removeEventListener("keydown", handleKeyDown);
	}, [imageViewer?.open, onClose]);

	// 阻止背景滚动
	useEffect(() => {
		if (imageViewer?.open) {
			document.body.style.overflow = "hidden";
		} else {
			document.body.style.overflow = "";
		}
		return () => {
			document.body.style.overflow = "";
		};
	}, [imageViewer?.open]);

	if (!imageViewer?.open) {
		return null;
	}

	return (
		<div
			className="runtime-image-viewer"
			onClick={onClose}
			onKeyDown={(e) => {
				if (e.key === "Escape") {
					onClose();
				}
			}}
			role="dialog"
			aria-modal="true"
			aria-label="图片查看器"
		>
			<div
				className="runtime-image-viewer-stage"
				onClick={(e) => e.stopPropagation()}
				onKeyDown={(e) => e.stopPropagation()}
			>
				<figure className="runtime-image-viewer-figure">
					<img
						src={imageViewer.src}
						alt={imageViewer.alt}
						style={{ transform: `scale(${zoom}) rotate(${rotation}deg)` }}
					/>
					{imageViewer.alt ? (
						<figcaption className="runtime-image-viewer-caption">
							{imageViewer.alt}
						</figcaption>
					) : null}
				</figure>
			</div>
			<div
				className="runtime-image-viewer-toolbar"
				onClick={(e) => e.stopPropagation()}
				onKeyDown={(e) => e.stopPropagation()}
			>
				<button
					onClick={() => setZoom((value) => Math.max(0.25, value - 0.25))}
					type="button"
					aria-label="缩小"
					title="缩小"
				>
					-
				</button>
				<button
					onClick={() => setZoom((value) => Math.min(4, value + 0.25))}
					type="button"
					aria-label="放大"
					title="放大"
				>
					+
				</button>
				<button
					onClick={() => setRotation((value) => (value + 90) % 360)}
					type="button"
					aria-label="旋转"
					title="旋转"
				>
					R
				</button>
				<button
					onClick={() => {
						setZoom(1);
						setRotation(0);
					}}
					type="button"
					aria-label="重置"
					title="重置"
				>
					1:1
				</button>
			</div>
			<button
				className="image-viewer-close-button"
				onClick={(e) => {
					e.stopPropagation();
					onClose();
				}}
				type="button"
				aria-label="关闭"
			>
				<svg
					width="24"
					height="24"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					strokeWidth="2"
					strokeLinecap="round"
					strokeLinejoin="round"
				>
					<title>关闭</title>
					<line x1="18" y1="6" x2="6" y2="18" />
					<line x1="6" y1="6" x2="18" y2="18" />
				</svg>
			</button>
		</div>
	);
}
