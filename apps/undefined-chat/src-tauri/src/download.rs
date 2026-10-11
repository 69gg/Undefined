use crate::{
    secret::require_api_key,
    state::{require_runtime_config, NativeState, RuntimeRequestPath},
};
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use tauri::{AppHandle, Manager, State};
use tauri_plugin_http::reqwest::Response;
use tokio::io::AsyncWriteExt;

const MAX_PREVIEW_BYTES: usize = 10 * 1024 * 1024;
pub(crate) const MAX_DOWNLOAD_NAME_CANDIDATES: usize = 1000;

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
#[serde(deny_unknown_fields)]
pub struct DownloadAttachmentInput {
    pub attachment_id: String,
    #[serde(default)]
    pub file_name: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DownloadAttachmentResult {
    pub status: u16,
    pub ok: bool,
    pub saved_file_name: Option<String>,
    pub bytes_written: u64,
    pub media_type: Option<String>,
    pub body: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
#[serde(deny_unknown_fields)]
pub struct PreviewAttachmentInput {
    pub attachment_id: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PreviewAttachmentResult {
    pub status: u16,
    pub ok: bool,
    pub media_type: Option<String>,
    pub bytes: Vec<u8>,
    pub body: Option<String>,
}

fn validate_attachment_id(value: &str) -> Result<(), String> {
    if value.is_empty() {
        return Err("attachment_id is required".to_string());
    }
    if value.len() > 160 {
        return Err("attachment_id is too long".to_string());
    }
    if !value
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '_' | '-' | '.'))
    {
        return Err("attachment_id contains unsupported characters".to_string());
    }
    if value == "." || value == ".." || value.contains("..") {
        return Err("attachment_id must not include path traversal".to_string());
    }
    Ok(())
}

fn attachment_path(attachment_id: &str, preview: bool) -> Result<RuntimeRequestPath, String> {
    validate_attachment_id(attachment_id)?;
    let encoded = urlencoding::encode(attachment_id);
    let path = if preview {
        format!("/api/v1/chat/attachments/{encoded}/preview")
    } else {
        format!("/api/v1/chat/attachments/{encoded}")
    };
    RuntimeRequestPath::new(&path)
}

fn safe_file_name(input: Option<&str>, attachment_id: &str) -> String {
    let candidate = input
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(attachment_id);
    let mut value = String::with_capacity(candidate.len());
    for ch in candidate.chars() {
        if ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | '.' | ' ') {
            value.push(ch);
        } else {
            value.push('_');
        }
    }
    let trimmed = value.trim_matches(['.', ' ']).trim().to_string();
    if trimmed.is_empty() {
        "attachment".to_string()
    } else {
        trimmed
    }
}

async fn attachment_response(
    app: &AppHandle,
    state: &NativeState,
    attachment_id: &str,
    preview: bool,
) -> Result<Response, String> {
    let config = require_runtime_config(app, state).await?;
    let api_key = require_api_key(app).await?;
    let path = attachment_path(attachment_id, preview)?;
    let url = format!("{}{}", config.runtime_url, path.as_str());
    state
        .http_client()?
        .get(url)
        .header("X-Undefined-API-Key", api_key)
        .send()
        .await
        .map_err(|err| format!("attachment request failed: {err}"))
}

fn media_type_from_response(response: &Response) -> Option<String> {
    response
        .headers()
        .get("content-type")
        .and_then(|value| value.to_str().ok())
        .map(ToString::to_string)
}

#[tauri::command]
pub async fn save_attachment(
    app: AppHandle,
    state: State<'_, NativeState>,
    input: DownloadAttachmentInput,
) -> Result<DownloadAttachmentResult, String> {
    let response = attachment_response(&app, &state, &input.attachment_id, false).await?;
    let status = response.status();
    let media_type = media_type_from_response(&response);
    if !status.is_success() {
        return Ok(DownloadAttachmentResult {
            status: status.as_u16(),
            ok: false,
            saved_file_name: None,
            bytes_written: 0,
            media_type,
            body: Some(response.text().await.unwrap_or_default()),
        });
    }

    let download_dir = app
        .path()
        .download_dir()
        .map_err(|err| format!("download directory unavailable: {err}"))?;
    tokio::fs::create_dir_all(&download_dir)
        .await
        .map_err(|err| format!("download directory create failed: {err}"))?;
    let path = download_dir.join(safe_file_name(
        input.file_name.as_deref(),
        &input.attachment_id,
    ));
    let (path, mut file) = create_unique_file(path)
        .await
        .map_err(|err| format!("attachment output create failed: {err}"))?;
    let mut bytes_written = 0u64;
    let mut stream = response.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|err| format!("attachment stream read failed: {err}"))?;
        bytes_written = bytes_written.saturating_add(chunk.len() as u64);
        file.write_all(&chunk)
            .await
            .map_err(|err| format!("attachment output write failed: {err}"))?;
    }
    file.flush()
        .await
        .map_err(|err| format!("attachment output flush failed: {err}"))?;

    Ok(DownloadAttachmentResult {
        status: status.as_u16(),
        ok: true,
        saved_file_name: path
            .file_name()
            .and_then(|value| value.to_str())
            .map(ToString::to_string),
        bytes_written,
        media_type,
        body: None,
    })
}

#[tauri::command]
pub async fn preview_attachment_bytes(
    app: AppHandle,
    state: State<'_, NativeState>,
    input: PreviewAttachmentInput,
) -> Result<PreviewAttachmentResult, String> {
    let response = attachment_response(&app, &state, &input.attachment_id, true).await?;
    let status = response.status();
    let media_type = media_type_from_response(&response);
    let bytes = response
        .bytes()
        .await
        .map_err(|err| format!("attachment preview read failed: {err}"))?;
    if !status.is_success() {
        return Ok(PreviewAttachmentResult {
            status: status.as_u16(),
            ok: false,
            media_type,
            body: Some(String::from_utf8_lossy(&bytes).to_string()),
            bytes: Vec::new(),
        });
    }
    if bytes.len() > MAX_PREVIEW_BYTES {
        return Err(format!(
            "attachment preview is too large; max {MAX_PREVIEW_BYTES} bytes"
        ));
    }

    Ok(PreviewAttachmentResult {
        status: status.as_u16(),
        ok: true,
        media_type,
        bytes: bytes.to_vec(),
        body: None,
    })
}

pub(crate) async fn create_unique_file(
    path: PathBuf,
) -> std::io::Result<(PathBuf, tokio::fs::File)> {
    let parent = path
        .parent()
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."));
    let stem = path
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or("attachment");
    let extension = path.extension().and_then(|value| value.to_str());
    for index in 0..MAX_DOWNLOAD_NAME_CANDIDATES {
        let candidate = if index == 0 {
            path.clone()
        } else {
            let file_name = if let Some(extension) = extension {
                format!("{stem} ({index}).{extension}")
            } else {
                format!("{stem} ({index})")
            };
            parent.join(file_name)
        };
        match tokio::fs::File::create_new(&candidate).await {
            Ok(file) => return Ok((candidate, file)),
            Err(err) if err.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(err) => return Err(err),
        }
    }
    Err(std::io::Error::new(
        std::io::ErrorKind::AlreadyExists,
        "no unused attachment download file name is available",
    ))
}

#[cfg(test)]
pub(crate) fn test_safe_file_name(input: Option<&str>, attachment_id: &str) -> String {
    safe_file_name(input, attachment_id)
}
