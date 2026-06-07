use crate::config::normalize_runtime_url;
use serde::{Deserialize, Serialize};
use std::path::Path;
use tauri_plugin_http::reqwest::{multipart, Body, Client};
use tokio::fs::File;
use tokio_util::io::ReaderStream;

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UploadAttachmentInput {
    pub runtime_url: String,
    pub api_key: String,
    pub file_path: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UploadAttachmentResult {
    pub status: u16,
    pub body: String,
}

pub(crate) fn attachments_url(runtime_url: &str) -> Result<String, String> {
    let base = normalize_runtime_url(runtime_url)?;
    Ok(format!("{base}/api/v1/chat/attachments"))
}

pub(crate) fn attachment_file_name(path: &Path) -> String {
    path.file_name()
        .and_then(|name| name.to_str())
        .filter(|name| !name.is_empty())
        .unwrap_or("attachment")
        .to_string()
}

#[tauri::command]
pub async fn upload_attachment_streaming(
    input: UploadAttachmentInput,
) -> Result<UploadAttachmentResult, String> {
    let url = attachments_url(&input.runtime_url)?;
    let path = Path::new(&input.file_path);
    let metadata = tokio::fs::metadata(path)
        .await
        .map_err(|err| format!("attachment file metadata failed: {err}"))?;
    if !metadata.is_file() {
        return Err(format!(
            "attachment path is not a regular file: {}",
            input.file_path
        ));
    }

    let file = File::open(path)
        .await
        .map_err(|err| format!("attachment file open failed: {err}"))?;
    let stream = ReaderStream::new(file);
    let part =
        multipart::Part::stream(Body::wrap_stream(stream)).file_name(attachment_file_name(path));
    let form = multipart::Form::new().part("file", part);

    let response = Client::new()
        .post(url)
        .header("X-Undefined-API-Key", &input.api_key)
        .multipart(form)
        .send()
        .await
        .map_err(|err| format!("attachment upload request failed: {err}"))?;
    let status = response.status();
    let body = response.text().await.unwrap_or_default();

    Ok(UploadAttachmentResult {
        status: status.as_u16(),
        body,
    })
}
