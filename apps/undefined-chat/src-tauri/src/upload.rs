use crate::{
    config::normalize_runtime_url,
    secret::require_api_key,
    state::{require_runtime_config, NativeState},
};
use serde::{Deserialize, Serialize};
use std::path::Path;
use tauri::{AppHandle, Manager, State};
use tauri_plugin_fs::{FilePath, FsExt, OpenOptions};
use tauri_plugin_http::reqwest::{multipart, Body};
use tokio::fs::File;
use tokio_util::io::ReaderStream;

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
#[serde(deny_unknown_fields)]
pub struct UploadAttachmentInput {
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

#[cfg(test)]
pub fn upload_uses_streaming_body() -> bool {
    true
}

pub(crate) fn attachment_file_name(path: &Path) -> String {
    path.file_name()
        .and_then(|name| name.to_str())
        .filter(|name| !name.is_empty())
        .unwrap_or("attachment")
        .to_string()
}

pub(crate) fn attachment_file_name_from_input(app: &AppHandle, input: &str) -> String {
    app.path()
        .file_name(input)
        .filter(|name| !name.is_empty())
        .unwrap_or_else(|| attachment_file_name(Path::new(input)))
}

pub(crate) fn parse_file_path(input: &str) -> Result<FilePath, String> {
    input
        .parse::<FilePath>()
        .map_err(|err| format!("attachment path parse failed: {err}"))
}

pub(crate) fn requires_regular_file_check(path: &FilePath) -> bool {
    path.clone().into_path().is_ok()
}

pub(crate) async fn open_regular_attachment_file(
    app: &AppHandle,
    file_path: FilePath,
    display_path: &str,
) -> Result<std::fs::File, String> {
    let mut open_options = OpenOptions::new();
    open_options.read(true);
    let should_check_regular_file = requires_regular_file_check(&file_path);
    let file = app
        .fs()
        .open(file_path, open_options)
        .map_err(|err| format!("attachment file open failed: {err}"))?;
    if should_check_regular_file {
        let metadata = file
            .metadata()
            .map_err(|err| format!("attachment file metadata failed: {err}"))?;
        if !metadata.is_file() {
            return Err(format!(
                "attachment path is not a regular file: {display_path}"
            ));
        }
    }

    Ok(file)
}

#[tauri::command]
pub async fn upload_attachment_streaming(
    app: AppHandle,
    state: State<'_, NativeState>,
    input: UploadAttachmentInput,
) -> Result<UploadAttachmentResult, String> {
    let config = require_runtime_config(&app, &state).await?;
    let api_key = require_api_key(&app).await?;
    let url = attachments_url(&config.runtime_url)?;
    let file_path = parse_file_path(&input.file_path)?;
    let file = open_regular_attachment_file(&app, file_path, &input.file_path).await?;
    let file = File::from_std(file);
    let stream = ReaderStream::with_capacity(file, 256 * 1024);
    let part = multipart::Part::stream(Body::wrap_stream(stream))
        .file_name(attachment_file_name_from_input(&app, &input.file_path));
    let form = multipart::Form::new().part("file", part);

    let response = state
        .http_client()?
        .post(url)
        .header("X-Undefined-API-Key", api_key)
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
