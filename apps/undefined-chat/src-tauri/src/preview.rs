use serde::Deserialize;
use tauri::{webview::NewWindowResponse, AppHandle, Manager, WebviewUrl, WebviewWindowBuilder};
use url::Url;
use uuid::Uuid;

pub(crate) const MAX_PREVIEW_HTML_BYTES: usize = 1024 * 1024;

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
    "script-src 'none'"
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
            "<title>{}</title>",
            "</head>",
            "<body>{}</body>",
            "</html>"
        ),
        PREVIEW_CSP, escaped_title, html
    )
}

pub(crate) fn preview_navigation_allowed(url: &Url, initial_url: &Url) -> bool {
    url == initial_url || url.as_str() == "about:blank"
}

pub(crate) fn build_preview_data_url(title: &str, html: &str) -> Result<Url, String> {
    if title.len().saturating_add(html.len()) > MAX_PREVIEW_HTML_BYTES {
        return Err(format!(
            "html preview content is too large; max {MAX_PREVIEW_HTML_BYTES} bytes"
        ));
    }

    // This renders Runtime/tool HTML as-is. It is containment, not sanitization.
    let document = preview_document(title, html);
    let encoded_document = urlencoding::encode(&document);
    Url::parse(&format!("data:text/html;charset=utf-8,{encoded_document}"))
        .map_err(|err| format!("html preview URL build failed: {err}"))
}

#[tauri::command]
pub async fn open_html_preview(app: AppHandle, input: HtmlPreviewInput) -> Result<(), String> {
    let url = build_preview_data_url(&input.title, &input.html)?;
    let initial_url = url.clone();
    let label = format!("html-preview-{}", Uuid::new_v4());
    let main_window = app
        .get_webview_window("main")
        .ok_or_else(|| "main window is not available for html preview".to_string())?;

    let builder = WebviewWindowBuilder::new(&main_window, label, WebviewUrl::CustomProtocol(url))
        .title(input.title)
        .inner_size(900.0, 700.0)
        .resizable(true)
        .on_navigation(move |url| preview_navigation_allowed(url, &initial_url))
        .on_new_window(|_, _| NewWindowResponse::Deny);

    #[cfg(target_os = "android")]
    let builder = builder.activity_name("HtmlPreviewActivity");

    builder
        .build()
        .map_err(|err| format!("html preview window open failed: {err}"))?;

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
        assert!(doc.contains("<body>"));
        assert!(doc.contains("</html>"));
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
        assert!(doc.contains("<body><h1>Hello</h1></body>"));
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
}
