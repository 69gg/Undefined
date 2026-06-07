use serde::Deserialize;
use tauri::{webview::NewWindowResponse, AppHandle, WebviewUrl, WebviewWindowBuilder};
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

pub(crate) fn preview_navigation_allowed(url: &Url) -> bool {
    matches!(url.scheme(), "data" | "about")
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
    let label = format!("html-preview-{}", Uuid::new_v4());

    WebviewWindowBuilder::new(&app, label, WebviewUrl::CustomProtocol(url))
        .title(input.title)
        .inner_size(900.0, 700.0)
        .resizable(true)
        .on_navigation(|url| preview_navigation_allowed(url))
        .on_new_window(|_, _| NewWindowResponse::Deny)
        .build()
        .map_err(|err| format!("html preview window open failed: {err}"))?;

    Ok(())
}
