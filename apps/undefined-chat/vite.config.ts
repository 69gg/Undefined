import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

function manualChunks(id: string): string | undefined {
	// Keep CJS helpers independent so vendor chunks never need to import the app.
	if (id.includes("commonjsHelpers.js")) return "vendor-helpers";
	const language = id.match(/\/highlight\.js\/lib\/languages\/([^/.]+)\.js/);
	if (language) {
		// Keep every language synchronously registered, in bounded stable groups.
		const initial = language[1][0];
		const group =
			initial < "g"
				? "a-f"
				: initial < "m"
					? "g-l"
					: initial < "s"
						? "m-r"
						: "s-z";
		return `highlight-languages-${group}`;
	}
	if (id.includes("/node_modules/highlight.js/")) return "highlight";
	if (/\/node_modules\/(react|react-dom|scheduler)\//.test(id)) return "react";
	if (id.includes("/node_modules/")) return "vendor";
}

export default defineConfig({
	plugins: [react()],
	server: {
		port: 1430,
		strictPort: true,
	},
	preview: {
		port: 4183,
		strictPort: true,
	},
	build: {
		target: ["es2022", "chrome110", "safari16"],
		rollupOptions: {
			output: {
				manualChunks,
				onlyExplicitManualChunks: true,
			},
		},
	},
	test: {
		environment: "jsdom",
		globals: true,
		setupFiles: "./src/test-setup.ts",
	},
});
