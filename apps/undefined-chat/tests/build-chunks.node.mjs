import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import hljs from "highlight.js";
import { build, createLogger } from "vite";

test("production chunks preserve full highlighting without oversized or circular chunks", async () => {
	const directory = await mkdtemp(join(tmpdir(), "undefined-chat-build-"));
	try {
		const warnings = [];
		const logger = createLogger("silent");
		logger.warn = (message) => warnings.push(message);
		const result = await build({
			root: fileURLToPath(new URL("..", import.meta.url)),
			customLogger: logger,
			build: { outDir: directory, emptyOutDir: true },
		});
		assert.ok(!("close" in result), "Expected a one-shot production build");
		const outputs = Array.isArray(result) ? result : [result];
		const chunks = outputs.flatMap((output) =>
			output.output.filter((item) => item.type === "chunk"),
		);
		assert.ok(chunks.length > 1);
		assert.deepEqual(warnings, []);
		const byFile = new Map(chunks.map((chunk) => [chunk.fileName, chunk]));
		for (const chunk of chunks) {
			assert.ok(Buffer.byteLength(chunk.code) <= 500_000, chunk.fileName);
		}

		function checkImports(file, ancestors) {
			assert.ok(
				!ancestors.includes(file),
				`Circular chunk import through ${file}`,
			);
			const chunk = byFile.get(file);
			assert.ok(chunk, `Missing emitted chunk ${file}`);
			for (const dependency of [...chunk.imports, ...chunk.dynamicImports]) {
				checkImports(dependency, [...ancestors, file]);
			}
		}
		for (const chunk of chunks) checkImports(chunk.fileName, []);

		// Execute the emitted CJS wrappers and language chunks, not source imports.
		await writeFile(join(directory, "package.json"), '{"type":"module"}');
		const highlighterChunk = chunks.find((chunk) =>
			Object.keys(chunk.modules).some((id) =>
				id.endsWith("/highlight.js/lib/index.js"),
			),
		);
		assert.ok(highlighterChunk);
		const exports = await import(
			pathToFileURL(join(directory, highlighterChunk.fileName)).href
		);
		const bundled = Object.values(exports).find(
			(value) => typeof value?.listLanguages === "function",
		);
		assert.ok(bundled, "Missing initialized production highlighter");
		assert.deepEqual(bundled.listLanguages(), hljs.listLanguages());
		for (const language of hljs.listLanguages()) {
			const code = 'if (value) { return "hello"; } // test';
			assert.equal(
				bundled.highlight(code, { language, ignoreIllegals: true }).value,
				hljs.highlight(code, { language, ignoreIllegals: true }).value,
				language,
			);
		}
		const code = 'def greet(name):\n    return "hello " + name';
		assert.equal(
			bundled.highlightAuto(code).language,
			hljs.highlightAuto(code).language,
		);
		assert.equal(
			bundled.highlightAuto(code).value,
			hljs.highlightAuto(code).value,
		);
	} finally {
		await rm(directory, { recursive: true, force: true });
	}
});
