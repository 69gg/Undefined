use serde::Deserialize;
use std::{
    path::{Path, PathBuf},
    time::{Duration, SystemTime},
};
use tauri::{
    webview::NewWindowResponse, AppHandle, Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent,
};
use url::Url;
use uuid::Uuid;

// CSP 策略：与 WebUI HTML 预览基线对齐——放开内联脚本以支持图表/动画等工具产物，
// 但通过运行时真正生效的指令维持隔离：禁止一切外联（connect-src 'none'），禁止表单提交、
// 插件对象、base 改写，仅允许 data:/blob: 内联资源与内联样式。
//
// 安全说明：放开 script-src 后，预览窗口可执行任意脚本，但其无法访问 Tauri IPC/invoke。
// IPC 隔离的唯一屏障是 capability 缺失：预览窗口 label 形如 `html-preview-*`，不匹配
// `capabilities/default.json`（`main-capability`，仅 `windows: ["main"]`）；在 Tauri v2 ACL 模型下
// 未匹配任何 capability 的 webview 完全没有 IPC 访问权（permission 缺失）。
// 注意：底层 `__TAURI_INTERNALS__` 无论 `withGlobalTauri` 取值都会注入，并非 IPC 隔离的依据；
// `withGlobalTauri` 未启用仅移除便利全局 `window.__TAURI__`，命令调用仍然只由 capability 把关。
// connect-src 'none' 进一步阻断脚本外联，防止内容外泄。
// 导航防护不依赖 CSP，而由 Rust 侧 on_navigation 守卫（`preview_navigation_allowed`）提供；
// 防嵌入由窗口隔离（预览为独立 OS 窗口而非 iframe）与 on_new_window Deny 覆盖。
// 详见 `open_html_preview` 注释与 native_tests 中的隔离断言。
const PREVIEW_CSP: &str = concat!(
    "default-src 'none'; ",
    "connect-src 'none'; ",
    "form-action 'none'; ",
    "object-src 'none'; ",
    "base-uri 'none'; ",
    // frame-ancestors 通过 <meta http-equiv> 交付时被浏览器忽略（仅 HTTP 响应头有效）。
    // 预览为独立 OS 窗口而非 iframe，防嵌入实际由窗口隔离 + on_new_window Deny 覆盖；
    // 保留此指令以便未来若改为 header 交付时即可生效。
    "frame-ancestors 'none'; ",
    // 注：曾用的 `navigate-to 'none'` 已移除——该指令已从 CSP 规范删除、浏览器从不实现，
    // 是零防护的死指令。导航防护改由上文所述的 on_navigation 守卫提供。
    "img-src data: blob:; ",
    "media-src data: blob:; ",
    "style-src 'unsafe-inline'; ",
    "font-src data:; ",
    "script-src 'unsafe-inline';"
);

#[derive(Debug, Clone, Deserialize)]
pub struct HtmlPreviewInput {
    pub title: String,
    pub html: String,
}

fn escape_html_text(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

pub(crate) fn preview_document(title: &str, html: &str) -> String {
    let escaped_title = escape_html_text(title);

    format!(
        concat!(
            "<!doctype html>",
            "<html>",
            "<head>",
            "<meta charset=\"utf-8\">",
            "<meta http-equiv=\"Content-Security-Policy\" content=\"{}\">",
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
            "<meta http-equiv=\"X-UA-Compatible\" content=\"IE=edge\">",
            "<title>{}</title>",
            "<style>",
            "* {{ box-sizing: border-box; }}",
            "body {{ margin: 0; padding: 16px; font-family: system-ui, -apple-system, 'Segoe UI', sans-serif; background: white; color: black; line-height: 1.5; }}",
            "body.empty {{ display: flex; align-items: center; justify-content: center; min-height: 100vh; }}",
            "body.empty::before {{ content: '内容为空或加载失败'; color: #999; }}",
            "img {{ max-width: 100%; height: auto; }}",
            "table {{ border-collapse: collapse; width: 100%; }}",
            "pre {{ overflow-x: auto; }}",
            "</style>",
            "</head>",
            "<body class=\"{}\">{}</body>",
            "</html>"
        ),
        PREVIEW_CSP,
        escaped_title,
        if html.trim().is_empty() { "empty" } else { "" },
        html
    )
}

pub(crate) fn preview_navigation_allowed(url: &Url, initial_url: &Url) -> bool {
    url == initial_url || url.as_str() == "about:blank"
}

pub(crate) const MAX_PREVIEW_HTML_BYTES: usize = 1024 * 1024;
/// 预览窗口的 label 前缀（label 形如 `html-preview-{uuid}`）。
/// 该前缀同时用作临时文件名前缀，并且是 IPC 隔离的安全锚点：
/// `capabilities/default.json` 仅授权 `windows: ["main"]`，此前缀的窗口不匹配任何 capability。
pub(crate) const PREVIEW_WINDOW_LABEL_PREFIX: &str = "html-preview-";
const PREVIEW_TEMP_PREFIX: &str = PREVIEW_WINDOW_LABEL_PREFIX;
const PREVIEW_TEMP_EXTENSION: &str = "html";
const PREVIEW_TEMP_TTL: Duration = Duration::from_secs(24 * 60 * 60);

pub(crate) fn validate_preview_input(title: &str, html: &str) -> Result<(), String> {
    if title.len().saturating_add(html.len()) > MAX_PREVIEW_HTML_BYTES {
        return Err(format!(
            "html preview content is too large; max {MAX_PREVIEW_HTML_BYTES} bytes"
        ));
    }
    Ok(())
}

pub(crate) fn preview_document_checked(title: &str, html: &str) -> Result<String, String> {
    validate_preview_input(title, html)?;
    // This renders Runtime/tool HTML as-is. It is containment, not sanitization.
    Ok(preview_document(title, html))
}

pub(crate) fn is_preview_temp_file(path: &Path) -> bool {
    let Some(file_name) = path.file_name().and_then(|name| name.to_str()) else {
        return false;
    };
    path.extension().and_then(|ext| ext.to_str()) == Some(PREVIEW_TEMP_EXTENSION)
        && file_name.starts_with(PREVIEW_TEMP_PREFIX)
}

fn remove_preview_temp_file(path: &Path) {
    if !is_preview_temp_file(path) {
        return;
    }
    // 临时文件清理失败是非致命的：TTL 过期扫描（cleanup_stale_preview_temp_files）会作为兜底，
    // 这里静默忽略以避免生产环境 stderr 噪音，且不暴露临时路径。
    let _ = std::fs::remove_file(path);
}

struct PreviewTempFile {
    path: PathBuf,
    cleanup_on_drop: bool,
}

impl PreviewTempFile {
    fn new(path: PathBuf) -> Self {
        Self {
            path,
            cleanup_on_drop: true,
        }
    }

    fn path(&self) -> &Path {
        &self.path
    }

    #[cfg(test)]
    fn persist_for_test(mut self) -> PathBuf {
        self.cleanup_on_drop = false;
        self.path.clone()
    }

    fn into_window_cleanup(mut self) -> PathBuf {
        self.cleanup_on_drop = false;
        self.path.clone()
    }
}

impl Drop for PreviewTempFile {
    fn drop(&mut self) {
        if self.cleanup_on_drop {
            remove_preview_temp_file(&self.path);
        }
    }
}

fn is_stale_preview_temp_file(path: &Path, now: SystemTime) -> bool {
    if !is_preview_temp_file(path) {
        return false;
    }
    let Ok(metadata) = std::fs::metadata(path) else {
        return true;
    };
    let Ok(modified) = metadata.modified() else {
        return true;
    };
    now.duration_since(modified)
        .is_ok_and(|age| age > PREVIEW_TEMP_TTL)
}

pub(crate) fn cleanup_stale_preview_temp_files(temp_dir: &Path) -> Result<usize, String> {
    cleanup_preview_temp_files_before(temp_dir, SystemTime::now())
}

fn cleanup_preview_temp_files_before(temp_dir: &Path, now: SystemTime) -> Result<usize, String> {
    let entries = match std::fs::read_dir(temp_dir) {
        Ok(entries) => entries,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(0),
        Err(err) => return Err(format!("Failed to scan temp dir: {err}")),
    };

    let mut removed = 0;
    for entry in entries {
        let entry = entry.map_err(|err| format!("Failed to read temp dir entry: {err}"))?;
        let path = entry.path();
        if !is_stale_preview_temp_file(&path, now) {
            continue;
        }
        match std::fs::remove_file(&path) {
            Ok(()) => removed += 1,
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => {}
            Err(err) => {
                return Err(format!(
                    "Failed to remove temp preview file {path:?}: {err}"
                ))
            }
        }
    }

    Ok(removed)
}

pub(crate) fn preview_temp_path(temp_dir: &Path, label: &str) -> PathBuf {
    temp_dir.join(format!("{label}.{PREVIEW_TEMP_EXTENSION}"))
}

// 保留用于测试和未来可能的 data URL 回退
#[allow(dead_code)]
pub(crate) fn build_preview_data_url(title: &str, html: &str) -> Result<Url, String> {
    let document = preview_document_checked(title, html)?;
    let encoded_document = urlencoding::encode(&document);
    Url::parse(&format!("data:text/html;charset=utf-8,{encoded_document}"))
        .map_err(|err| format!("html preview URL build failed: {err}"))
}

#[tauri::command]
pub async fn open_html_preview(app: AppHandle, input: HtmlPreviewInput) -> Result<(), String> {
    use std::fs;

    let document = preview_document_checked(&input.title, &input.html)?;
    let label = format!("{PREVIEW_WINDOW_LABEL_PREFIX}{}", Uuid::new_v4());

    // 写入临时 HTML 文件
    let temp_dir = app
        .path()
        .temp_dir()
        .map_err(|e| format!("Failed to get temp dir: {}", e))?;
    // 过期临时文件清理失败不影响本次预览：非致命，静默忽略（下次预览会再次尝试清理）。
    let _ = cleanup_stale_preview_temp_files(&temp_dir);
    let html_file = preview_temp_path(&temp_dir, &label);

    fs::write(&html_file, document).map_err(|e| format!("Failed to write HTML file: {}", e))?;
    let temp_file = PreviewTempFile::new(html_file);

    let url = Url::from_file_path(temp_file.path()).map_err(|_| {
        format!(
            "Failed to convert HTML preview path to file URL: {:?}",
            temp_file.path()
        )
    })?;
    let initial_url = url.clone();

    // 尝试获取主窗口
    let main_window = app
        .get_webview_window("main")
        .or_else(|| app.webview_windows().into_values().next())
        .ok_or_else(|| "no parent window is available for html preview".to_string())?;

    // 安全：预览窗口加载外部 file:// URL，label 形如 `html-preview-*`，不匹配任何 capability
    // （`capabilities/default.json` 即 `main-capability`，仅授权 `windows: ["main"]`），因此该
    // webview 没有任何 Tauri IPC/invoke 权限——这正是 IPC 隔离的唯一屏障，即便 CSP 放开脚本，
    // 也因 capability 缺失而无法回调 Rust 命令或读取主窗口数据。
    // （`withGlobalTauri` 未启用只是移除便利全局 `window.__TAURI__`；底层 `__TAURI_INTERNALS__`
    // 无论如何都会注入，故隔离不能寄托于此。导航防护由下方 on_navigation 守卫提供。）
    let builder = WebviewWindowBuilder::new(&main_window, label, WebviewUrl::External(url))
        .title(input.title)
        .inner_size(900.0, 700.0)
        .resizable(true)
        .on_navigation(move |url| preview_navigation_allowed(url, &initial_url))
        .on_new_window(|_, _| NewWindowResponse::Deny);

    #[cfg(target_os = "android")]
    let builder = builder.activity_name("HtmlPreviewActivity");

    let window = builder
        .build()
        .map_err(|err| format!("html preview window open failed: {err}"))?;
    let html_file_for_cleanup = temp_file.into_window_cleanup();
    window.on_window_event(move |event| {
        if matches!(
            event,
            WindowEvent::CloseRequested { .. } | WindowEvent::Destroyed
        ) {
            remove_preview_temp_file(&html_file_for_cleanup);
        }
    });

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_escape_html_text() {
        assert_eq!(escape_html_text("hello"), "hello");
        assert_eq!(escape_html_text("<script>"), "&lt;script&gt;");
        assert_eq!(escape_html_text("a & b"), "a &amp; b");
        assert_eq!(
            escape_html_text("<div>a & b</div>"),
            "&lt;div&gt;a &amp; b&lt;/div&gt;"
        );
    }

    #[test]
    fn test_preview_document_structure() {
        let doc = preview_document("Test", "<p>content</p>");
        assert!(doc.contains("<!doctype html>"));
        assert!(doc.contains("<html>"));
        assert!(doc.contains("<head>"));
        assert!(doc.contains("<body"));
        assert!(doc.contains("</html>"));
        assert!(doc.contains("<style>"));
    }

    #[test]
    fn test_preview_document_escapes_title() {
        let doc = preview_document("<script>alert('xss')</script>", "<p>safe</p>");
        assert!(doc.contains("&lt;script&gt;"));
        assert!(!doc.contains("<script>alert"));
    }

    #[test]
    fn test_preview_document_preserves_html_content() {
        let doc = preview_document("Page", "<h1>Hello</h1>");
        assert!(doc.contains("<h1>Hello</h1>"));
        assert!(doc.contains("<body"));
    }

    #[test]
    fn test_preview_document_includes_csp() {
        let doc = preview_document("Test", "<p>test</p>");
        assert!(doc.contains("Content-Security-Policy"));
        assert!(doc.contains(PREVIEW_CSP));
    }

    #[test]
    fn test_preview_document_includes_viewport() {
        let doc = preview_document("Test", "<p>test</p>");
        assert!(doc.contains("width=device-width, initial-scale=1"));
    }

    #[test]
    fn test_preview_document_checked_rejects_oversized_input() {
        let large_html = "x".repeat(MAX_PREVIEW_HTML_BYTES + 1);
        let result = preview_document_checked("Test", &large_html);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("too large"));
    }

    #[test]
    fn test_preview_temp_file_detection() {
        assert!(is_preview_temp_file(std::path::Path::new(
            "/tmp/html-preview-abc.html"
        )));
        assert!(!is_preview_temp_file(std::path::Path::new(
            "/tmp/not-preview.html"
        )));
        assert!(!is_preview_temp_file(std::path::Path::new(
            "/tmp/html-preview-abc.txt"
        )));
    }

    #[test]
    fn test_cleanup_preview_temp_files_keeps_fresh_preview_html() {
        let temp_dir = std::env::temp_dir().join(format!(
            "undefined-chat-preview-test-{}",
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir_all(&temp_dir).unwrap();
        let fresh_preview_file = temp_dir.join("html-preview-fresh.html");
        let other_file = temp_dir.join("html-preview-old.txt");
        std::fs::write(&fresh_preview_file, "preview").unwrap();
        std::fs::write(&other_file, "other").unwrap();

        let removed = cleanup_stale_preview_temp_files(&temp_dir).unwrap();

        assert_eq!(removed, 0);
        assert!(fresh_preview_file.exists());
        assert!(other_file.exists());
        std::fs::remove_file(fresh_preview_file).unwrap();
        std::fs::remove_file(other_file).unwrap();
        std::fs::remove_dir(temp_dir).unwrap();
    }

    #[test]
    fn test_cleanup_preview_temp_files_only_removes_stale_preview_html() {
        let temp_dir = std::env::temp_dir().join(format!(
            "undefined-chat-preview-test-{}",
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir_all(&temp_dir).unwrap();
        let stale_preview_file = temp_dir.join("html-preview-old.html");
        let other_file = temp_dir.join("html-preview-old.txt");
        std::fs::write(&stale_preview_file, "preview").unwrap();
        std::fs::write(&other_file, "other").unwrap();

        let now = std::fs::metadata(&stale_preview_file)
            .unwrap()
            .modified()
            .unwrap()
            + PREVIEW_TEMP_TTL
            + Duration::from_secs(1);
        let removed = cleanup_preview_temp_files_before(&temp_dir, now).unwrap();

        assert_eq!(removed, 1);
        assert!(!stale_preview_file.exists());
        assert!(other_file.exists());
        std::fs::remove_file(other_file).unwrap();
        std::fs::remove_dir(temp_dir).unwrap();
    }

    #[test]
    fn test_preview_temp_file_removes_file_on_error_path() {
        let temp_dir = std::env::temp_dir().join(format!(
            "undefined-chat-preview-guard-{}",
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir_all(&temp_dir).unwrap();
        let preview_file = preview_temp_path(&temp_dir, "html-preview-guard");
        std::fs::write(&preview_file, "preview").unwrap();

        {
            let _temp_file = PreviewTempFile::new(preview_file.clone());
            assert!(preview_file.exists());
        }

        assert!(!preview_file.exists());
        std::fs::remove_dir(temp_dir).unwrap();
    }

    #[test]
    fn test_preview_temp_file_can_be_transferred_to_window_cleanup() {
        let temp_dir = std::env::temp_dir().join(format!(
            "undefined-chat-preview-guard-{}",
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir_all(&temp_dir).unwrap();
        let preview_file = preview_temp_path(&temp_dir, "html-preview-window");
        std::fs::write(&preview_file, "preview").unwrap();

        let transferred = PreviewTempFile::new(preview_file.clone()).persist_for_test();

        assert_eq!(transferred, preview_file);
        assert!(preview_file.exists());
        remove_preview_temp_file(&preview_file);
        std::fs::remove_dir(temp_dir).unwrap();
    }

    #[test]
    fn test_build_preview_data_url_success() {
        let result = build_preview_data_url("Test", "<p>Hello</p>");
        assert!(result.is_ok());
        let url = result.unwrap();
        assert_eq!(url.scheme(), "data");
        assert!(url.as_str().contains("text/html"));
        assert!(url.as_str().contains("charset=utf-8"));
    }

    #[test]
    fn test_build_preview_data_url_size_limit() {
        let large_html = "x".repeat(MAX_PREVIEW_HTML_BYTES + 1);
        let result = build_preview_data_url("Test", &large_html);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("too large"));
    }

    #[test]
    fn test_build_preview_data_url_encoding() {
        let result = build_preview_data_url("Test & Title", "<p>Test & Content</p>");
        assert!(result.is_ok());
        let url = result.unwrap();
        // URL should be percent-encoded
        assert!(url.as_str().contains("%26")); // & becomes %26
    }

    #[test]
    fn test_preview_navigation_allowed_initial() {
        let initial = Url::parse("data:text/html,test").unwrap();
        assert!(preview_navigation_allowed(&initial, &initial));
    }

    #[test]
    fn test_preview_navigation_allowed_about_blank() {
        let initial = Url::parse("data:text/html,test").unwrap();
        let about_blank = Url::parse("about:blank").unwrap();
        assert!(preview_navigation_allowed(&about_blank, &initial));
    }

    #[test]
    fn test_preview_navigation_blocked_different_url() {
        let initial = Url::parse("data:text/html,test").unwrap();
        let different = Url::parse("https://example.com").unwrap();
        assert!(!preview_navigation_allowed(&different, &initial));
    }

    #[test]
    fn test_csp_allows_inline_scripts_but_blocks_eval() {
        // 与 WebUI 基线对齐：放开内联脚本以支持图表/动画，但不放开 eval。
        assert!(PREVIEW_CSP.contains("script-src 'unsafe-inline'"));
        assert!(!PREVIEW_CSP.contains("unsafe-eval"));
        assert!(!PREVIEW_CSP.contains("script-src 'none'"));
    }

    #[test]
    fn test_csp_keeps_isolation_directives() {
        // 仅断言运行时真正生效的隔离指令：即便放开脚本，外联/表单/插件对象/base 改写仍被禁止。
        assert!(PREVIEW_CSP.contains("default-src 'none'"));
        assert!(PREVIEW_CSP.contains("connect-src 'none'"));
        assert!(PREVIEW_CSP.contains("form-action 'none'"));
        assert!(PREVIEW_CSP.contains("object-src 'none'"));
        assert!(PREVIEW_CSP.contains("base-uri 'none'"));
        assert!(PREVIEW_CSP.contains("img-src data: blob:"));
        assert!(PREVIEW_CSP.contains("script-src 'unsafe-inline'"));
        assert!(!PREVIEW_CSP.contains("unsafe-eval"));
        // 已从规范移除、浏览器从不实现的死指令不得再充当隔离证据。
        assert!(!PREVIEW_CSP.contains("navigate-to"));
        // 导航防护的真实证据是 on_navigation 守卫单测（见 test_preview_navigation_*）。
    }

    /// 安全回归：预览窗口（label `html-preview-*`）必须无法访问 Tauri IPC/invoke。
    ///
    /// Tauri v2 ACL 模型：未匹配任何 capability 的 webview 完全没有 IPC 访问权。
    /// 本测试核对 `capabilities/default.json` 把权限限定到 `windows: ["main"]`，
    /// 且没有任何 capability 用通配/前缀覆盖到预览窗口的 label，从而保证脚本即便被放开
    /// 也无法回调 Rust 命令。若有人误把 capability 放宽到 `*` 或 `html-preview-*`，本测试会失败。
    #[test]
    fn test_preview_window_has_no_ipc_capability() {
        use serde_json::Value;

        let manifest_dir = env!("CARGO_MANIFEST_DIR");
        let capabilities_dir = std::path::Path::new(manifest_dir).join("capabilities");
        let entries =
            std::fs::read_dir(&capabilities_dir).expect("capabilities directory should exist");

        // 模拟一个真实的预览窗口 label，逐个 capability 校验其 windows 作用域不会命中。
        let preview_label = format!("{PREVIEW_WINDOW_LABEL_PREFIX}deadbeef");
        let mut checked_any = false;

        for entry in entries {
            let path = entry.unwrap().path();
            let is_capability = matches!(
                path.extension().and_then(|ext| ext.to_str()),
                Some("json") | Some("toml")
            );
            if !is_capability {
                continue;
            }
            // 仅解析 JSON 形式（本项目使用 JSON capability）。
            if path.extension().and_then(|ext| ext.to_str()) != Some("json") {
                continue;
            }
            let raw = std::fs::read_to_string(&path).unwrap();
            let value: Value = serde_json::from_str(&raw).unwrap();
            let windows = value
                .get("windows")
                .and_then(Value::as_array)
                .expect("capability must explicitly scope windows (never default to all)");

            for pattern in windows {
                let pattern = pattern.as_str().expect("window pattern must be a string");
                // 绝不允许全局通配把权限授予所有窗口。
                assert_ne!(
                    pattern, "*",
                    "capability {path:?} must not grant permissions to all windows"
                );
                // 预览窗口 label 不得被任何 capability 的 windows 作用域命中。
                assert!(
                    !window_pattern_matches(pattern, &preview_label),
                    "capability {path:?} pattern {pattern:?} must not cover preview window {preview_label:?}"
                );
            }
            checked_any = true;
        }

        assert!(
            checked_any,
            "expected at least one JSON capability to validate IPC isolation"
        );
    }

    /// 近似 Tauri 的 window label glob 匹配（`*` 通配单段/多段）。
    /// 用于测试断言：仅需覆盖精确匹配与简单前缀通配两种现实形态。
    fn window_pattern_matches(pattern: &str, label: &str) -> bool {
        if pattern == "*" {
            return true;
        }
        if let Some(prefix) = pattern.strip_suffix('*') {
            return label.starts_with(prefix);
        }
        pattern == label
    }

    #[test]
    fn test_csp_allows_inline_styles() {
        // CSP should allow inline styles
        assert!(PREVIEW_CSP.contains("style-src 'unsafe-inline'"));
    }

    #[test]
    fn test_csp_allows_data_images() {
        // CSP should allow data: URIs for images
        assert!(PREVIEW_CSP.contains("img-src data:"));
    }

    #[test]
    fn test_csp_blocks_connections() {
        // CSP should block network connections
        assert!(PREVIEW_CSP.contains("connect-src 'none'"));
    }

    #[test]
    fn test_preview_document_empty_content() {
        let doc = preview_document("Empty Test", "");
        assert!(doc.contains("class=\"empty\""));
        assert!(doc.contains("<style>"));
    }

    #[test]
    fn test_preview_document_whitespace_only() {
        let doc = preview_document("Whitespace", "   \n\t  ");
        assert!(doc.contains("class=\"empty\""));
    }

    #[test]
    fn test_preview_document_non_empty_content() {
        let doc = preview_document("Test", "<p>Hello</p>");
        assert!(!doc.contains("class=\"empty\""));
        assert!(doc.contains("<p>Hello</p>"));
    }
}
