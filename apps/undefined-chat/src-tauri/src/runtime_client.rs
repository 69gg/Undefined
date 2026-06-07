use crate::config::normalize_runtime_url;
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use std::str;
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

#[derive(Debug, Default)]
pub(crate) struct Utf8ChunkDecoder {
    pending: Vec<u8>,
}

impl Utf8ChunkDecoder {
    pub(crate) fn decode_chunk(&mut self, chunk: &[u8]) -> Result<Option<String>, String> {
        if chunk.is_empty() {
            return Ok(None);
        }

        self.pending.extend_from_slice(chunk);
        match str::from_utf8(&self.pending) {
            Ok(value) => {
                if value.is_empty() {
                    return Ok(None);
                }

                let decoded = value.to_string();
                self.pending.clear();
                Ok(Some(decoded))
            }
            Err(err) => {
                let valid_up_to = err.valid_up_to();
                if let Some(error_len) = err.error_len() {
                    return Err(format!(
                        "runtime SSE chunk contains invalid UTF-8 at byte {valid_up_to}: length {error_len}"
                    ));
                }
                if valid_up_to == 0 {
                    return Ok(None);
                }

                let decoded = str::from_utf8(&self.pending[..valid_up_to])
                    .map_err(|err| format!("runtime SSE UTF-8 decode failed: {err}"))?
                    .to_string();
                self.pending.drain(..valid_up_to);
                Ok(Some(decoded))
            }
        }
    }

    pub(crate) fn finish(&self) -> Result<(), String> {
        if self.pending.is_empty() {
            Ok(())
        } else {
            Err("runtime SSE stream ended with incomplete UTF-8 sequence".to_string())
        }
    }
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

pub(crate) fn runtime_health_from_body_result(
    status: u16,
    ok: bool,
    body_result: Result<String, String>,
) -> RuntimeHealth {
    RuntimeHealth {
        ok,
        status,
        body: body_result.unwrap_or_default(),
    }
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
    let body_result = response
        .text()
        .await
        .map_err(|err| format!("runtime health body read failed: {err}"));

    Ok(runtime_health_from_body_result(
        status.as_u16(),
        status.is_success(),
        body_result,
    ))
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
    let mut decoder = Utf8ChunkDecoder::default();
    let mut stream = response.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|err| format!("runtime SSE stream read failed: {err}"))?;
        if let Some(raw) = decoder.decode_chunk(&chunk)? {
            app.emit(
                "runtime-sse-chunk",
                RuntimeStreamEvent {
                    job_id: job_id.clone(),
                    raw,
                },
            )
            .map_err(|err| format!("runtime SSE event emit failed: {err}"))?;
        }
    }

    decoder.finish()?;
    Ok(())
}
