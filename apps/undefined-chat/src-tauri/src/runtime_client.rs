use crate::config::normalize_runtime_url;
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter};
use tauri_plugin_http::reqwest::{header, Client};

#[derive(Debug, Clone, Serialize)]
pub struct RuntimeHealth {
    pub ok: bool,
    pub status: u16,
    pub body: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct StartJobEventStreamInput {
    pub runtime_url: String,
    pub api_key: String,
    pub job_id: String,
    pub after_seq: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeStreamEvent {
    pub job_id: String,
    pub raw: String,
}

pub(crate) fn job_events_url(
    runtime_url: &str,
    job_id: &str,
    after_seq: u64,
) -> Result<String, String> {
    let base = normalize_runtime_url(runtime_url)?;
    let job_id = urlencoding::encode(job_id);
    Ok(format!(
        "{base}/api/v1/chat/jobs/{job_id}/events?after={after_seq}"
    ))
}

#[tauri::command]
pub async fn probe_runtime(runtime_url: String) -> Result<RuntimeHealth, String> {
    let base = normalize_runtime_url(&runtime_url)?;
    let url = format!("{base}/health");
    let response = Client::new()
        .get(url)
        .send()
        .await
        .map_err(|err| format!("runtime health request failed: {err}"))?;
    let status = response.status();
    let body = response
        .text()
        .await
        .map_err(|err| format!("runtime health body read failed: {err}"))?;

    Ok(RuntimeHealth {
        ok: status.is_success(),
        status: status.as_u16(),
        body,
    })
}

#[tauri::command]
pub async fn start_job_event_stream(
    app: AppHandle,
    input: StartJobEventStreamInput,
) -> Result<(), String> {
    let url = job_events_url(&input.runtime_url, &input.job_id, input.after_seq)?;
    let response = Client::new()
        .get(url)
        .header("X-Undefined-API-Key", &input.api_key)
        .header(header::ACCEPT, "text/event-stream")
        .header("Last-Event-ID", input.after_seq.to_string())
        .send()
        .await
        .map_err(|err| format!("runtime SSE request failed: {err}"))?;

    let status = response.status();
    if !status.is_success() {
        return Err(format!("runtime SSE request failed with status {status}"));
    }

    let job_id = input.job_id;
    let mut stream = response.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|err| format!("runtime SSE stream read failed: {err}"))?;
        let raw = String::from_utf8_lossy(&chunk).to_string();
        app.emit(
            "runtime-sse-chunk",
            RuntimeStreamEvent {
                job_id: job_id.clone(),
                raw,
            },
        )
        .map_err(|err| format!("runtime SSE event emit failed: {err}"))?;
    }

    Ok(())
}
