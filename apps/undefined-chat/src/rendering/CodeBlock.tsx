import hljs from "highlight.js";
import { useMemo, useState } from "react";
import "./CodeBlock.css";

export type CodeBlockProps = {
	code: string;
	language?: string;
	showLineNumbers?: boolean;
	collapsible?: boolean;
	maxLines?: number;
	onPreviewHtml?: (input: { title: string; html: string }) => void;
};

/**
 * 代码高亮和折叠组件
 * - 集成 highlight.js 进行语法高亮
 * - 支持代码折叠（超过 maxLines 行自动折叠）
 * - 支持复制代码
 * - 支持 HTML 预览
 */
export function CodeBlock({
	code,
	language = "",
	showLineNumbers = false,
	collapsible = true,
	maxLines = 8,
	onPreviewHtml,
}: CodeBlockProps) {
	const [isCollapsed, setIsCollapsed] = useState(false);
	const [copied, setCopied] = useState(false);

	// 语法高亮
	const { highlightedCode, detectedLanguage } = useMemo(() => {
		const trimmedCode = code.trim();
		try {
			if (language) {
				// htm 别名映射到 html
				const normalizedLanguage =
					language.toLowerCase() === "htm" ? "html" : language;
				// 指定了语言，尝试使用指定语言高亮
				const result = hljs.highlight(trimmedCode, {
					language: normalizedLanguage,
					ignoreIllegals: true,
				});
				return {
					highlightedCode: result.value,
					detectedLanguage: normalizedLanguage,
				};
			}
			// 未指定语言，自动检测
			const result = hljs.highlightAuto(trimmedCode);
			return {
				highlightedCode: result.value,
				detectedLanguage: result.language || "plaintext",
			};
		} catch (err) {
			console.error("Highlight error:", err);
			return {
				highlightedCode: trimmedCode,
				detectedLanguage: "plaintext",
			};
		}
	}, [code, language]);

	// 计算行数
	const lineCount = useMemo(() => {
		return code.trim().split("\n").length;
	}, [code]);

	// 是否需要折叠
	const shouldCollapse = collapsible && lineCount > maxLines;

	// 初始化折叠状态（只在组件挂载时设置一次）
	const [initialized, setInitialized] = useState(false);
	if (!initialized && shouldCollapse) {
		setIsCollapsed(true);
		setInitialized(true);
	}

	// 复制代码
	async function handleCopy() {
		try {
			await navigator.clipboard.writeText(code.trim());
			setCopied(true);
			setTimeout(() => setCopied(false), 2000);
		} catch (err) {
			console.error("Failed to copy code:", err);
		}
	}

	// 切换折叠
	function toggleCollapse() {
		setIsCollapsed(!isCollapsed);
	}

	// 是否为 HTML
	const isHtml = ["html", "htm"].includes(detectedLanguage.toLowerCase());

	return (
		<div className={`runtime-code-block ${isCollapsed ? "is-collapsed" : ""}`}>
			<div className="runtime-code-toolbar">
				<span className="runtime-code-language">
					{detectedLanguage || "code"}
				</span>
				<div className="runtime-code-actions">
					{shouldCollapse && (
						<button
							type="button"
							className="runtime-code-action"
							onClick={toggleCollapse}
						>
							{isCollapsed ? "展开" : "折叠"}
						</button>
					)}
					{isHtml && onPreviewHtml && (
						<button
							type="button"
							className="runtime-code-action"
							onClick={() =>
								onPreviewHtml({
									title: "HTML 预览",
									html: code.trim(),
								})
							}
						>
							预览 HTML
						</button>
					)}
					<button
						type="button"
						className="runtime-code-action primary"
						onClick={handleCopy}
					>
						{copied ? "已复制" : "复制"}
					</button>
				</div>
			</div>
			<div className="runtime-code-body">
				<pre>
					<code
						className={`hljs ${showLineNumbers ? "line-numbers" : ""}`}
						// biome-ignore lint/security/noDangerouslySetInnerHtml: highlight.js output is sanitized
						dangerouslySetInnerHTML={{ __html: highlightedCode }}
					/>
				</pre>
			</div>
		</div>
	);
}
