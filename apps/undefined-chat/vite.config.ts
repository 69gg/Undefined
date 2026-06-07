import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

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
	},
	test: {
		environment: "jsdom",
		globals: true,
	},
});
