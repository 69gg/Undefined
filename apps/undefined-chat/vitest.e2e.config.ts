import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
	plugins: [react()],
	test: {
		environment: "jsdom",
		globals: true,
		setupFiles: "./src/test-setup.ts",
		include: ["tests/e2e/**/*.test.ts", "tests/e2e/**/*.test.tsx"],
		testTimeout: 10000,
	},
});
