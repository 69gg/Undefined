use serde::Deserialize;
use std::path::{Path, PathBuf};
use tauri::{
    webview::NewWindowResponse, AppHandle, Manager, WebviewUrl, WebviewWindowBuilder, WindowEvent,
};
use url::Url;
use uuid::Uuid;

// CSP 策略：禁止脚本和网络连接，允许内联样式和本地资源
const PREVIEW_CSP: &str = concat!(
    "default-src 'none'; ",
    "connect-src 'none'; ",
    "form-action 'none'; ",
    "object-src 'none'; ",
    "base-uri 'none'; ",
    "frame-ancestors 'none'; ",
    "navigate-to 'none'; ",
    "img-src data: blob:; ",
    "media-src data: blob:; ",
    "style-src 'unsafe-inline'; ",
    "font-src data:; ",
    "script-src 'none';"
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
const PREVIEW_TEMP_PREFIX: &str = "html-preview-";
const PREVIEW_TEMP_EXTENSION: &str = "html";

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
    if let Err(err) = std::fs::remove_file(path) {
        if err.kind() != std::io::ErrorKind::NotFound {
            eprintln!("[preview] Failed to remove temp file {path:?}: {err}");
        }
    }
}

pub(crate) fn cleanup_preview_temp_files(temp_dir: &Path) -> Result<usize, String> {
    let entries = match std::fs::read_dir(temp_dir) {
        Ok(entries) => entries,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(0),
        Err(err) => return Err(format!("Failed to scan temp dir: {err}")),
    };

    let mut removed = 0;
    for entry in entries {
        let entry = entry.map_err(|err| format!("Failed to read temp dir entry: {err}"))?;
        let path = entry.path();
        if !is_preview_temp_file(&path) {
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
    let label = format!("html-preview-{}", Uuid::new_v4());

    // 写入临时 HTML 文件
    let temp_dir = app
        .path()
        .temp_dir()
        .map_err(|e| format!("Failed to get temp dir: {}", e))?;
    if let Err(err) = cleanup_preview_temp_files(&temp_dir) {
        eprintln!("[preview] Failed to clean stale preview files: {err}");
    }
    let html_file = preview_temp_path(&temp_dir, &label);

    fs::write(&html_file, document).map_err(|e| format!("Failed to write HTML file: {}", e))?;

    let url = Url::from_file_path(&html_file)
        .map_err(|_| format!("Failed to convert HTML preview path to file URL: {html_file:?}"))?;
    let initial_url = url.clone();

    // 尝试获取主窗口
    let main_window = app
        .get_webview_window("main")
        .or_else(|| app.webview_windows().into_values().next())
        .ok_or_else(|| "no parent window is available for html preview".to_string())?;

    eprintln!("[preview] Creating HTML preview window: {}", label);
    eprintln!("[preview] Title: {}", input.title);
    eprintln!("[preview] HTML size: {} bytes", input.html.len());
    eprintln!("[preview] File URL: {}", url);

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
    let html_file_for_cleanup = html_file.clone();
    window.on_window_event(move |event| {
        if matches!(
            event,
            WindowEvent::CloseRequested { .. } | WindowEvent::Destroyed
        ) {
            remove_preview_temp_file(&html_file_for_cleanup);
        }
    });

    eprintln!(
        "[preview] Window created successfully: {:?}",
        window.label()
    );

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
    fn test_cleanup_preview_temp_files_only_removes_preview_html() {
        let temp_dir = std::env::temp_dir().join(format!(
            "undefined-chat-preview-test-{}",
            uuid::Uuid::new_v4()
        ));
        std::fs::create_dir_all(&temp_dir).unwrap();
        let preview_file = temp_dir.join("html-preview-old.html");
        let other_file = temp_dir.join("html-preview-old.txt");
        std::fs::write(&preview_file, "preview").unwrap();
        std::fs::write(&other_file, "other").unwrap();

        let removed = cleanup_preview_temp_files(&temp_dir).unwrap();

        assert_eq!(removed, 1);
        assert!(!preview_file.exists());
        assert!(other_file.exists());
        std::fs::remove_file(other_file).unwrap();
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
    fn test_csp_blocks_scripts() {
        // CSP should include script-src 'none'
        assert!(PREVIEW_CSP.contains("script-src 'none'"));
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
