import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode, useState } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { ImageViewerState } from "../chat-store/types";
import { LanguageProvider } from "../i18n";
import { ImageViewerModal } from "../image-viewer/ImageViewerModal";
import { runtimeClientStub } from "../test-fixtures";
import { AttachmentImage } from "./AttachmentImage";
import { AttachmentImageProvider } from "./AttachmentImageContext";

function Gallery({
	images,
	removeOnOpen = false,
}: {
	images: { id: string; uid: string }[];
	removeOnOpen?: boolean;
}) {
	const [viewer, setViewer] = useState<ImageViewerState | null>(null);
	const [hideThumbnails, setHideThumbnails] = useState(false);
	return (
		<>
			{!hideThumbnails &&
				images.map(({ id, uid }) => (
					<AttachmentImage
						key={id}
						uid={uid}
						alt={id}
						onOpenImage={(src, alt) => {
							setViewer({ open: true, src, alt });
							if (removeOnOpen) setHideThumbnails(true);
						}}
					/>
				))}
			<ImageViewerModal imageViewer={viewer} onClose={() => setViewer(null)} />
		</>
	);
}

describe("active image blob lifetimes", () => {
	afterEach(() => vi.restoreAllMocks());

	test("61 mounted images keep their URLs, and an open viewer retains a removed thumbnail", async () => {
		const revoke = vi.spyOn(URL, "revokeObjectURL").mockClear();
		const client = runtimeClientStub();
		const uids = Array.from({ length: 61 }, (_, index) => `pic_${index}`);
		const tree = (shown: string[]) => (
			<LanguageProvider>
				<AttachmentImageProvider client={client}>
					<Gallery images={shown.map((uid) => ({ id: uid, uid }))} />
				</AttachmentImageProvider>
			</LanguageProvider>
		);
		const { rerender, unmount } = render(tree(uids.slice(0, 1)));
		const first = (await screen.findByAltText("pic_0")) as HTMLImageElement;
		const firstUrl = first.src;
		rerender(tree(uids));
		await waitFor(() =>
			expect(document.querySelectorAll("img")).toHaveLength(61),
		);
		expect(screen.getByAltText("pic_0")).toBe(first);
		expect(first).toHaveAttribute("src", firstUrl);
		expect(revoke).not.toHaveBeenCalled();
		expect(firstUrl).toMatch(/^blob:/);
		expect((await (await fetch(firstUrl)).arrayBuffer()).byteLength).toBe(4);
		fireEvent.click(first);
		expect(screen.getByRole("dialog").querySelector("img")).toHaveAttribute(
			"src",
			firstUrl,
		);
		rerender(tree(uids.slice(1)));
		expect(first.isConnected).toBe(false);
		expect(revoke).not.toHaveBeenCalledWith(firstUrl);
		expect((await (await fetch(firstUrl)).arrayBuffer()).byteLength).toBe(4);
		fireEvent.click(screen.getByRole("button", { name: "关闭" }));
		expect(revoke).toHaveBeenCalledWith(firstUrl);
		expect(revoke).toHaveBeenCalledTimes(1);
		await expect(fetch(firstUrl)).rejects.toThrow();
		unmount();
		expect(revoke).toHaveBeenCalledTimes(61);
	});

	test("two consumers sharing a UID retain it until both unmount", async () => {
		const revoke = vi.spyOn(URL, "revokeObjectURL").mockClear();
		const client = runtimeClientStub();
		const tree = (count: number) => (
			<LanguageProvider>
				<AttachmentImageProvider client={client} maxCacheSize={0}>
					<Gallery
						images={["first", "second"].slice(0, count).map((id) => ({
							id,
							uid: "pic_shared",
						}))}
					/>
				</AttachmentImageProvider>
			</LanguageProvider>
		);
		const { rerender } = render(tree(2));
		const first = await screen.findByAltText("first");
		const second = await screen.findByAltText("second");
		const url = first.getAttribute("src");
		expect(second).toHaveAttribute("src", url);
		expect(client.previewAttachment).toHaveBeenCalledTimes(1);
		rerender(tree(1));
		expect(revoke).not.toHaveBeenCalledWith(url);
		rerender(tree(0));
		expect(revoke).toHaveBeenCalledWith(url);
	});

	test("opening a viewer and removing its source in the same render transfers the reference", async () => {
		const revoke = vi.spyOn(URL, "revokeObjectURL").mockClear();
		render(
			<LanguageProvider>
				<AttachmentImageProvider client={runtimeClientStub()} maxCacheSize={0}>
					<Gallery
						images={[{ id: "handoff", uid: "pic_handoff" }]}
						removeOnOpen
					/>
				</AttachmentImageProvider>
			</LanguageProvider>,
		);
		const thumbnail = await screen.findByAltText("handoff");
		const url = thumbnail.getAttribute("src");
		fireEvent.click(thumbnail);
		expect(thumbnail.isConnected).toBe(false);
		expect(screen.getByRole("dialog").querySelector("img")).toHaveAttribute(
			"src",
			url,
		);
		expect(revoke).not.toHaveBeenCalledWith(url);
		fireEvent.click(screen.getByRole("button", { name: "关闭" }));
		expect(revoke).toHaveBeenCalledWith(url);
	});

	test("StrictMode cleanup does not discard the current consumer's blob", async () => {
		const revoke = vi.spyOn(URL, "revokeObjectURL").mockClear();
		const { unmount } = render(
			<StrictMode>
				<LanguageProvider>
					<AttachmentImageProvider
						client={runtimeClientStub()}
						maxCacheSize={0}
					>
						<Gallery images={[{ id: "strict", uid: "pic_strict" }]} />
					</AttachmentImageProvider>
				</LanguageProvider>
			</StrictMode>,
		);
		const thumbnail = await screen.findByAltText("strict");
		const url = thumbnail.getAttribute("src");
		expect(revoke).not.toHaveBeenCalledWith(url);
		unmount();
		expect(revoke).toHaveBeenCalledWith(url);
	});
});
