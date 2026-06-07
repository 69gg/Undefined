use serde::Deserialize;
use tauri::{AppHandle, WebviewUrl, WebviewWindowBuilder};
use url::Url;
use uuid::Uuid;

const PREVIEW_CSP: &str = concat!(
    "default-src 'none'; ",
    "connect-src 'none'; ",
    "form-action 'none'; ",
    "object-src 'none'; ",
    "base-uri 'none'; ",
    "frame-ancestors 'none'; ",
    "img-src data: blob:; ",
    "media-src data: blob:; ",
    "style-src 'unsafe-inline'; ",
    "script-src 'unsafe-inline'"
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

#[tauri::command]
pub async fn open_html_preview(app: AppHandle, input: HtmlPreviewInput) -> Result<(), String> {
    let document = preview_document(&input.title, &input.html);
    let encoded_document = urlencoding::encode(&document);
    let url = Url::parse(&format!("data:text/html;charset=utf-8,{encoded_document}"))
        .map_err(|err| format!("html preview URL build failed: {err}"))?;
    let label = format!("html-preview-{}", Uuid::new_v4());

    WebviewWindowBuilder::new(&app, label, WebviewUrl::CustomProtocol(url))
        .title(input.title)
        .inner_size(900.0, 700.0)
        .resizable(true)
        .build()
        .map_err(|err| format!("html preview window open failed: {err}"))?;

    Ok(())
}
