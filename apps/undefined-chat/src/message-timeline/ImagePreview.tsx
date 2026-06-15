import { useEffect } from "react";
import { useTranslation } from "../i18n";

export type ImagePreviewProps = {
	src: string;
	alt: string;
	open: boolean;
	onClose: () => void;
};

export function ImagePreview({ src, alt, open, onClose }: ImagePreviewProps) {
	const { t } = useTranslation();
	// ESC 键关闭
	useEffect(() => {
		if (!open) return;

		function handleEsc(e: KeyboardEvent) {
			if (e.key === "Escape") {
				onClose();
			}
		}

		window.addEventListener("keydown", handleEsc);
		return () => window.removeEventListener("keydown", handleEsc);
	}, [open, onClose]);

	if (!open) return null;

	return (
		<div
			className="runtime-image-viewer"
			onClick={onClose}
			onKeyDown={(e) => {
				if (e.key === "Enter" || e.key === " ") {
					onClose();
				}
			}}
		>
			<figure
				className="runtime-image-viewer-figure"
				onClick={(e) => e.stopPropagation()}
				onKeyDown={(e) => e.stopPropagation()}
			>
				<img src={src} alt={alt} className="runtime-image-viewer-image" />
				{alt && (
					<figcaption className="runtime-image-viewer-caption">
						{alt}
					</figcaption>
				)}
			</figure>

			<button
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
