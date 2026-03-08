import { defineConfig } from "vite";

export default defineConfig({
	server: {
		port: 1420,
		strictPort: true,
	},
	preview: {
		port: 4173,
		strictPort: true,
	},
	build: {
		target: ["es2022", "chrome110", "safari16"],
	},
});
