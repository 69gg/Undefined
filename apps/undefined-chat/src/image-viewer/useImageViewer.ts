import { useCallback } from "react";
import type { ChatStore } from "../chat-store/store";

export type UseImageViewerReturn = {
	openImage: (src: string, alt: string) => void;
	closeImage: () => void;
};

export function useImageViewer(store: ChatStore): UseImageViewerReturn {
	const openImage = useCallback(
		(src: string, alt: string) => {
			store.dispatch({
				type: "imageViewer/open",
				src,
				alt,
			});
		},
		[store],
	);

	const closeImage = useCallback(() => {
		store.dispatch({
			type: "imageViewer/close",
		});
	}, [store]);

	return { openImage, closeImage };
}
