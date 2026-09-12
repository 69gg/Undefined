import {
	type KeyboardEvent as ReactKeyboardEvent,
	useCallback,
	useEffect,
	useRef,
} from "react";
import { useTranslation } from "../i18n";

export type ImagePreviewProps = {
	src: string;
	alt: string;
	open: boolean;
	onClose: () => void;
};

export function ImagePreview({ src, alt, open, onClose }: ImagePreviewProps) {
	const { t } = useTranslation();
	const closeButtonRef = useRef<HTMLButtonElement>(null);

	// 只随开关状态保存和恢复焦点，避免 onClose 的引用变化打断预览。
	useEffect(() => {
		if (!open) return;
		const previousFocus = document.activeElement;
		closeButtonRef.current?.focus();
		return () => {
			if (previousFocus instanceof HTMLElement && previousFocus.isConnected) {
				previousFocus.focus();
			}
		};
	}, [open]);

	const handleKeyDown = useCallback(
		(event: KeyboardEvent | ReactKeyboardEvent<HTMLDivElement>): void => {
			if (event.key === "Escape") {
				event.preventDefault();
				event.stopPropagation();
				onClose();
			} else if (event.key === "Tab") {
				// 预览只有一个可交互控件，正反向 Tab 均停留在关闭按钮。
				event.preventDefault();
				event.stopPropagation();
				closeButtonRef.current?.focus();
			}
		},
		[onClose],
	);

	useEffect(() => {
		if (!open) return;
		// 点击不可聚焦的图片后焦点可能落到 body，仍需处理 Escape 和 Tab。
		document.addEventListener("keydown", handleKeyDown, true);
		return () => document.removeEventListener("keydown", handleKeyDown, true);
	}, [open, handleKeyDown]);

	if (!open) return null;

	return (
		<div
			className="runtime-image-viewer"
			role="dialog"
			aria-modal="true"
			aria-label={alt || t("imageViewer.label")}
			onClick={(event) => {
				if (event.target === event.currentTarget) {
					onClose();
				}
			}}
			onKeyDown={handleKeyDown}
		>
			<figure className="runtime-image-viewer-figure">
				<img src={src} alt={alt} className="runtime-image-viewer-image" />
				{alt && (
					<figcaption className="runtime-image-viewer-caption">
						{alt}
					</figcaption>
				)}
			</figure>

			<button
				ref={closeButtonRef}
				type="button"
				className="runtime-image-viewer-close"
				onClick={onClose}
				aria-label={t("imagePreview.close")}
			>
				✕
			</button>
		</div>
	);
}
