use crate::{
    config::normalize_runtime_url,
    secret::require_api_key,
    state::{
        require_runtime_config, AppRuntimeConfig, EventStreamSubscription, NativeState,
        RuntimeRequestPath,
    },
};
use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::str;
use tauri::{async_runtime, AppHandle, Emitter, Manager, State};
use tauri_plugin_http::reqwest::{
    header::{self, HeaderName, HeaderValue},
    Client, Method, Response,
};
use uuid::Uuid;

#[derive(Debug, Clone, Serialize)]
pub struct RuntimeHealth {
    pub ok: bool,
    pub status: u16,
    pub body: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
#[serde(deny_unknown_fields)]
pub struct StartJobEventStreamInput {
    pub job_id: String,
    #[serde(default)]
    pub after_seq: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeStreamEvent {
    pub subscription_id: String,
    pub job_id: String,
    pub seq: u64,
    pub event_type: Option<String>,
    pub payload: Value,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeStreamStatusEvent {
    pub subscription_id: String,
    pub job_id: String,
    pub status: String,
    pub detail: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StartJobEventStreamResult {
    pub subscription_id: String,
    pub job_id: String,
    pub after_seq: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StopJobEventStreamResult {
    pub stopped: bool,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeRequestInput {
    pub method: String,
    pub path: String,
    #[serde(default)]
    pub body: Option<Value>,
    #[serde(default)]
    pub headers: Vec<(String, String)>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeResponse {
    pub status: u16,
    pub ok: bool,
    pub body: Value,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConversationHistoryInput {
    pub conversation_id: String,
    #[serde(default)]
    pub limit: Option<u32>,
    #[serde(default)]
    pub before: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ActiveJobsInput {
    #[serde(default)]
    pub conversation_id: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SendMessageInput {
    #[serde(default)]
    pub conversation_id: Option<String>,
    pub message: Value,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct JobIdInput {
    pub job_id: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ListCommandsInput {
    #[serde(default)]
    pub scope: Option<String>,
    #[serde(default)]
    pub q: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FetchJobEventsInput {
    pub job_id: String,
    #[serde(default)]
    pub after_seq: u64,
    #[serde(default)]
    pub conversation_id: Option<String>,
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

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ParsedSseEvent {
    pub seq: u64,
    pub event_type: Option<String>,
    pub payload: Value,
}

#[cfg(test)]
#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ParsedSseBatch {
    pub events: Vec<ParsedSseEvent>,
    pub last_seq: u64,
}

#[derive(Debug, Default)]
pub(crate) struct SseParser {
    buffer: String,
    last_seq: u64,
}

impl SseParser {
    pub(crate) fn push_str(&mut self, chunk: &str) -> Result<Vec<ParsedSseEvent>, String> {
        self.buffer.push_str(chunk);
        let mut events = Vec::new();

        while let Some(index) = self.buffer.find("\n\n") {
            let frame = self.buffer[..index].to_string();
            self.buffer.drain(..index + 2);
            if let Some(event) = parse_sse_frame(&frame, self.last_seq)? {
                self.last_seq = event.seq;
                events.push(event);
            }
        }

        Ok(events)
    }

    #[cfg(test)]
    pub(crate) fn last_seq(&self) -> u64 {
        self.last_seq
    }
}

#[cfg(test)]
pub fn parse_sse_chunks(chunks: &[&str]) -> Result<ParsedSseBatch, String> {
    let mut parser = SseParser::default();
    let mut events = Vec::new();
    for chunk in chunks {
        events.extend(parser.push_str(chunk)?);
    }
    Ok(ParsedSseBatch {
        events,
        last_seq: parser.last_seq(),
    })
}

fn parse_sse_frame(frame: &str, fallback_seq: u64) -> Result<Option<ParsedSseEvent>, String> {
    let mut seq = None;
    let mut event_type = None;
    let mut data_lines = Vec::new();

    for line in frame.lines() {
        if line.is_empty() || line.starts_with(':') {
            continue;
        }
        let (name, value) = line
            .split_once(':')
            .map(|(name, value)| (name, value.strip_prefix(' ').unwrap_or(value)))
            .unwrap_or((line, ""));
        match name {
            "id" => {
                seq = Some(
                    value
                        .parse::<u64>()
                        .map_err(|err| format!("invalid SSE event id {value:?}: {err}"))?,
                );
            }
            "event" => {
                if !value.is_empty() {
                    event_type = Some(value.to_string());
                }
            }
            "data" => data_lines.push(value.to_string()),
            _ => {}
        }
    }

    if data_lines.is_empty() {
        return Ok(None);
    }

    let payload_text = data_lines.join("\n");
    let payload = serde_json::from_str::<Value>(&payload_text).unwrap_or_else(|_| {
        json!({
            "raw": payload_text
        })
    });
    Ok(Some(ParsedSseEvent {
        seq: seq.unwrap_or(fallback_seq.saturating_add(1)),
        event_type,
        payload,
    }))
}

pub(crate) fn job_events_url(
    runtime_url: &str,
    job_id: &str,
    after_seq: u64,
) -> Result<String, String> {
    let config = AppRuntimeConfig {
        runtime_url: normalize_runtime_url(runtime_url)?,
    };
    let path = RuntimeRequestPath::new(&format!(
        "/api/v1/chat/jobs/{}/events?after={after_seq}",
        urlencoding::encode(job_id)
    ))?;
    build_runtime_url(&config, &path)
}

pub fn build_runtime_url(
    config: &AppRuntimeConfig,
    path: &RuntimeRequestPath,
) -> Result<String, String> {
    let base = normalize_runtime_url(&config.runtime_url)?;
    Ok(format!("{base}{}", path.as_str()))
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

impl RuntimeRequestInput {
    pub fn validate(&self) -> Result<(Method, RuntimeRequestPath), String> {
        let method = self
            .method
            .parse::<Method>()
            .map_err(|err| format!("invalid Runtime request method: {err}"))?;
        if !matches!(
            method,
            Method::GET | Method::POST | Method::PATCH | Method::DELETE
        ) {
            return Err("unsupported Runtime request method".to_string());
        }
        for (name, _) in &self.headers {
            let lower = name.to_ascii_lowercase();
            if lower == "x-undefined-api-key"
                || lower == "authorization"
                || lower == "host"
                || lower == "cookie"
            {
                return Err(format!("reserved header is managed by Rust: {name}"));
            }
        }
        Ok((method, RuntimeRequestPath::new(&self.path)?))
    }
}

async fn response_to_runtime_response(response: Response) -> Result<RuntimeResponse, String> {
    let status = response.status();
    let body_text = response
        .text()
        .await
        .map_err(|err| format!("Runtime response body read failed: {err}"))?;
    let body = if body_text.trim().is_empty() {
        Value::Null
    } else {
        serde_json::from_str::<Value>(&body_text).unwrap_or_else(|_| {
            json!({
                "text": body_text
            })
        })
    };
    Ok(RuntimeResponse {
        status: status.as_u16(),
        ok: status.is_success(),
        body,
    })
}

fn header_pair(name: &str, value: &str) -> Result<(HeaderName, HeaderValue), String> {
    let name = HeaderName::from_bytes(name.as_bytes())
        .map_err(|err| format!("invalid Runtime request header name {name:?}: {err}"))?;
    let value = HeaderValue::from_str(value)
        .map_err(|err| format!("invalid Runtime request header value for {name}: {err}"))?;
    Ok((name, value))
}

pub(crate) async fn send_runtime_request(
    config: &AppRuntimeConfig,
    api_key: &str,
    input: RuntimeRequestInput,
) -> Result<RuntimeResponse, String> {
    let (method, path) = input.validate()?;
    let url = build_runtime_url(config, &path)?;
    let mut request = Client::new()
        .request(method.clone(), url)
        .header("X-Undefined-API-Key", api_key);

    for (name, value) in &input.headers {
        let (name, value) = header_pair(name, value)?;
        request = request.header(name, value);
    }

    if let Some(body) = input.body {
        if matches!(method, Method::GET | Method::DELETE) {
            return Err("Runtime request body is only allowed for POST/PATCH".to_string());
        }
        let body_text = serde_json::to_string(&body)
            .map_err(|err| format!("Runtime request JSON serialization failed: {err}"))?;
        request = request
            .header(header::CONTENT_TYPE, "application/json")
            .body(body_text);
    }

    let response = request
        .send()
        .await
        .map_err(|err| format!("Runtime request failed: {err}"))?;
    response_to_runtime_response(response).await
}

async fn request_json_command(
    app: &AppHandle,
    state: &NativeState,
    input: RuntimeRequestInput,
) -> Result<RuntimeResponse, String> {
    let config = require_runtime_config(app, state).await?;
    let api_key = require_api_key(app).await?;
    send_runtime_request(&config, &api_key, input).await
}

#[tauri::command]
pub async fn runtime_request(
    app: AppHandle,
    state: State<'_, NativeState>,
    input: RuntimeRequestInput,
) -> Result<RuntimeResponse, String> {
    request_json_command(&app, &state, input).await
}

#[tauri::command]
pub async fn probe_runtime(
    app: AppHandle,
    state: State<'_, NativeState>,
) -> Result<RuntimeHealth, String> {
    let config = require_runtime_config(&app, &state).await?;
    let url = format!("{}/health", config.runtime_url);
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
pub async fn list_conversations(
    app: AppHandle,
    state: State<'_, NativeState>,
) -> Result<RuntimeResponse, String> {
    request_json_command(
        &app,
        &state,
        RuntimeRequestInput {
            method: "GET".to_string(),
            path: "/api/v1/chat/conversations".to_string(),
            body: None,
            headers: Vec::new(),
        },
    )
    .await
}

#[tauri::command]
pub async fn get_history(
    app: AppHandle,
    state: State<'_, NativeState>,
    input: ConversationHistoryInput,
) -> Result<RuntimeResponse, String> {
    let mut path = format!(
        "/api/v1/chat/history?conversation_id={}",
        urlencoding::encode(&input.conversation_id)
    );
    if let Some(limit) = input.limit {
        path.push_str(&format!("&limit={limit}"));
    }
    if let Some(before) = input.before {
        path.push_str("&before=");
        path.push_str(&urlencoding::encode(&before));
    }
    request_json_command(
        &app,
        &state,
        RuntimeRequestInput {
            method: "GET".to_string(),
            path,
            body: None,
            headers: Vec::new(),
        },
    )
    .await
}

#[tauri::command]
pub async fn get_active_jobs(
    app: AppHandle,
    state: State<'_, NativeState>,
    input: Option<ActiveJobsInput>,
) -> Result<RuntimeResponse, String> {
    let path = if let Some(conversation_id) = input.and_then(|item| item.conversation_id) {
        format!(
            "/api/v1/chat/jobs/active?conversation_id={}",
            urlencoding::encode(&conversation_id)
        )
    } else {
        "/api/v1/chat/jobs/active".to_string()
    };
    request_json_command(
        &app,
        &state,
        RuntimeRequestInput {
            method: "GET".to_string(),
            path,
            body: None,
            headers: Vec::new(),
        },
    )
    .await
}

#[tauri::command]
pub async fn send_message(
    app: AppHandle,
    state: State<'_, NativeState>,
    input: SendMessageInput,
) -> Result<RuntimeResponse, String> {
    let mut body = serde_json::Map::new();
    body.insert("message".to_string(), input.message);
    if let Some(conversation_id) = input.conversation_id {
        body.insert(
            "conversation_id".to_string(),
            Value::String(conversation_id),
        );
    }
    request_json_command(
        &app,
        &state,
        RuntimeRequestInput {
            method: "POST".to_string(),
            path: "/api/v1/chat/jobs".to_string(),
            body: Some(Value::Object(body)),
            headers: Vec::new(),
        },
    )
    .await
}

#[tauri::command]
pub async fn cancel_job(
    app: AppHandle,
    state: State<'_, NativeState>,
    input: JobIdInput,
) -> Result<RuntimeResponse, String> {
    let path = format!(
        "/api/v1/chat/jobs/{}/cancel",
        urlencoding::encode(&input.job_id)
    );
    request_json_command(
        &app,
        &state,
        RuntimeRequestInput {
            method: "POST".to_string(),
            path,
            body: None,
            headers: Vec::new(),
        },
    )
    .await
}

#[tauri::command]
pub async fn list_commands(
    app: AppHandle,
    state: State<'_, NativeState>,
    input: Option<ListCommandsInput>,
) -> Result<RuntimeResponse, String> {
    let input = input.unwrap_or(ListCommandsInput {
        scope: Some("webui".to_string()),
        q: None,
    });
    let mut query = Vec::new();
    if let Some(scope) = input.scope {
        query.push(format!("scope={}", urlencoding::encode(&scope)));
    }
    if let Some(q) = input.q {
        query.push(format!("q={}", urlencoding::encode(&q)));
    }
    let path = if query.is_empty() {
        "/api/v1/commands".to_string()
    } else {
        format!("/api/v1/commands?{}", query.join("&"))
    };
    request_json_command(
        &app,
        &state,
        RuntimeRequestInput {
            method: "GET".to_string(),
            path,
            body: None,
            headers: Vec::new(),
        },
    )
    .await
}

#[tauri::command]
pub async fn fetch_job_events_json(
    app: AppHandle,
    state: State<'_, NativeState>,
    input: FetchJobEventsInput,
) -> Result<RuntimeResponse, String> {
    let mut path = format!(
        "/api/v1/chat/jobs/{}/events?after={}&format=json",
        urlencoding::encode(&input.job_id),
        input.after_seq
    );
    if let Some(conversation_id) = input.conversation_id {
        path.push_str("&conversation_id=");
        path.push_str(&urlencoding::encode(&conversation_id));
    }
    request_json_command(
        &app,
        &state,
        RuntimeRequestInput {
            method: "GET".to_string(),
            path,
            body: None,
            headers: vec![("Accept".to_string(), "application/json".to_string())],
        },
    )
    .await
}

#[tauri::command]
pub async fn start_job_event_stream(
    app: AppHandle,
    state: State<'_, NativeState>,
    input: StartJobEventStreamInput,
) -> Result<StartJobEventStreamResult, String> {
    let config = require_runtime_config(&app, &state).await?;
    let api_key = require_api_key(&app).await?;
    let subscription_id = Uuid::new_v4().to_string();
    let job_id = input.job_id.clone();
    let after_seq = input.after_seq;
    let app_for_task = app.clone();
    let subscription_id_for_task = subscription_id.clone();
    let job_id_for_task = job_id.clone();

    let handle = async_runtime::spawn(async move {
        let result = run_sse_subscription(
            app_for_task.clone(),
            subscription_id_for_task.clone(),
            job_id_for_task.clone(),
            config,
            api_key,
            after_seq,
        )
        .await;

        if let Err(err) = result {
            let _ = app_for_task.emit(
                "runtime-sse-status",
                RuntimeStreamStatusEvent {
                    subscription_id: subscription_id_for_task.clone(),
                    job_id: job_id_for_task,
                    status: "error".to_string(),
                    detail: Some(err),
                },
            );
        }
        let _ = app_for_task
            .state::<NativeState>()
            .remove_subscription(&subscription_id_for_task);
    });

    state.insert_subscription(subscription_id.clone(), EventStreamSubscription { handle })?;

    Ok(StartJobEventStreamResult {
        subscription_id,
        job_id,
        after_seq,
    })
}

#[tauri::command]
pub fn stop_job_event_stream(
    state: State<'_, NativeState>,
    subscription_id: String,
) -> Result<StopJobEventStreamResult, String> {
    Ok(StopJobEventStreamResult {
        stopped: state.stop_subscription(&subscription_id)?,
    })
}

async fn run_sse_subscription(
    app: AppHandle,
    subscription_id: String,
    job_id: String,
    config: AppRuntimeConfig,
    api_key: String,
    after_seq: u64,
) -> Result<(), String> {
    let url = job_events_url(&config.runtime_url, &job_id, after_seq)?;
    let response = Client::new()
        .get(url)
        .header("X-Undefined-API-Key", api_key)
        .header(header::ACCEPT, "text/event-stream")
        .header("Last-Event-ID", after_seq.to_string())
        .send()
        .await
        .map_err(|err| format!("runtime SSE request failed: {err}"))?;

    let status = response.status();
    if !status.is_success() {
        return Err(format!("runtime SSE request failed with status {status}"));
    }

    app.emit(
        "runtime-sse-status",
        RuntimeStreamStatusEvent {
            subscription_id: subscription_id.clone(),
            job_id: job_id.clone(),
            status: "connected".to_string(),
            detail: None,
        },
    )
    .map_err(|err| format!("runtime SSE status emit failed: {err}"))?;

    let mut decoder = Utf8ChunkDecoder::default();
    let mut parser = SseParser::default();
    let mut stream = response.bytes_stream();
    while let Some(chunk) = stream.next().await {
        let chunk = chunk.map_err(|err| format!("runtime SSE stream read failed: {err}"))?;
        if let Some(raw) = decoder.decode_chunk(&chunk)? {
            for event in parser.push_str(&raw)? {
                app.emit(
                    "runtime-sse-event",
                    RuntimeStreamEvent {
                        subscription_id: subscription_id.clone(),
                        job_id: job_id.clone(),
                        seq: event.seq,
                        event_type: event.event_type,
                        payload: event.payload,
                    },
                )
                .map_err(|err| format!("runtime SSE event emit failed: {err}"))?;
            }
        }
    }

    decoder.finish()?;
    app.emit(
        "runtime-sse-status",
        RuntimeStreamStatusEvent {
            subscription_id,
            job_id,
            status: "closed".to_string(),
            detail: None,
        },
    )
    .map_err(|err| format!("runtime SSE status emit failed: {err}"))?;
    Ok(())
}
