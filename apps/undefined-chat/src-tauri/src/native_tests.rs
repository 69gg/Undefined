use crate::config::normalize_runtime_url;
use crate::preview::{
    build_preview_data_url, preview_document, preview_document_checked, preview_navigation_allowed,
    MAX_PREVIEW_HTML_BYTES,
};
use crate::runtime_client::{
    build_runtime_url, job_events_url, parse_sse_chunks, runtime_health_from_body_result,
    RuntimeRequestInput, StartJobEventStreamInput, Utf8ChunkDecoder,
};
use crate::secret::{
    api_key_status_from_storage, classify_secret_storage, derive_stronghold_key,
    load_api_key_status_from_value, supports_system_keyring_target,
};
use crate::state::{
    AppRuntimeConfig, RuntimeConfigInput, RuntimeRequestPath, APP_CONFIG_FILE_NAME,
};
use crate::{
    download::test_safe_file_name,
    upload::{
        attachment_file_name, attachments_url, parse_file_path, requires_regular_file_check,
        upload_uses_streaming_body, UploadAttachmentInput,
    },
};

#[test]
fn normalize_runtime_url_removes_trailing_slashes() {
    let value = normalize_runtime_url("http://127.0.0.1:8788///").unwrap();
    assert_eq!(value, "http://127.0.0.1:8788");
}

#[test]
fn normalize_runtime_url_rejects_empty_input() {
    let err = normalize_runtime_url(" ").unwrap_err();
    assert!(err.contains("runtime_url is required"));
}

#[test]
fn normalize_runtime_url_rejects_query() {
    let err = normalize_runtime_url("http://127.0.0.1:8788?debug=true").unwrap_err();
    assert!(err.contains("runtime_url must not include a query"));
}

#[test]
fn normalize_runtime_url_rejects_fragment() {
    let err = normalize_runtime_url("http://127.0.0.1:8788#runtime").unwrap_err();
    assert!(err.contains("runtime_url must not include a fragment"));
}

#[test]
fn normalize_runtime_url_rejects_path_and_credentials() {
    let path_err = normalize_runtime_url("http://127.0.0.1:8788/api").unwrap_err();
    assert!(path_err.contains("runtime_url must be an origin"));

    let credentials_err = normalize_runtime_url("http://user:pass@127.0.0.1:8788").unwrap_err();
    assert!(credentials_err.contains("runtime_url must not include credentials"));
}

#[test]
fn normalize_runtime_url_rejects_non_http_origins() {
    for value in [
        "file:///tmp/runtime.sock",
        "data:text/plain,hello",
        "javascript:alert(1)",
        "ws://127.0.0.1:8788",
    ] {
        let err = normalize_runtime_url(value).unwrap_err();
        assert!(err.contains("unsupported runtime_url scheme"));
    }
}

#[test]
fn runtime_config_input_normalizes_runtime_origin() {
    let config = AppRuntimeConfig::from_input(RuntimeConfigInput {
        runtime_url: " http://127.0.0.1:8788/// ".to_string(),
    })
    .unwrap();

    assert_eq!(config.runtime_url, "http://127.0.0.1:8788");
}

#[test]
fn runtime_config_file_name_is_stable() {
    assert_eq!(APP_CONFIG_FILE_NAME, "runtime-config.json");
}

#[test]
fn job_events_url_uses_normalized_runtime_base_and_after_sequence() {
    let value = job_events_url("http://127.0.0.1:8788///", "job-123", 42).unwrap();
    assert_eq!(
        value,
        "http://127.0.0.1:8788/api/v1/chat/jobs/job-123/events?after=42"
    );
}

#[test]
fn job_events_url_rejects_empty_runtime_url() {
    let err = job_events_url(" ", "job-123", 0).unwrap_err();
    assert!(err.contains("runtime_url is required"));
}

#[test]
fn job_events_url_encodes_job_id_path_segment() {
    let value = job_events_url("http://127.0.0.1:8788", "job /secret", 7).unwrap();
    assert_eq!(
        value,
        "http://127.0.0.1:8788/api/v1/chat/jobs/job%20%2Fsecret/events?after=7"
    );
}

#[test]
fn runtime_url_builder_accepts_only_relative_runtime_api_paths() {
    let base = AppRuntimeConfig {
        runtime_url: "http://127.0.0.1:8788".to_string(),
    };
    let input = RuntimeRequestPath::new("/api/v1/chat/history?conversation_id=abc").unwrap();
    let value = build_runtime_url(&base, &input).unwrap();

    assert_eq!(
        value,
        "http://127.0.0.1:8788/api/v1/chat/history?conversation_id=abc"
    );
}

#[test]
fn runtime_url_builder_rejects_absolute_and_non_api_paths() {
    let base = AppRuntimeConfig {
        runtime_url: "http://127.0.0.1:8788".to_string(),
    };

    for path in [
        "https://evil.example/api/v1/chat/history",
        "//evil.example/api/v1/chat/history",
        "/admin",
        "api/v1/chat/history",
        "/api/../secret",
    ] {
        assert!(RuntimeRequestPath::new(path).is_err());
    }

    let path = RuntimeRequestPath::new("/api/v1/chat/history").unwrap();
    let built = build_runtime_url(&base, &path).unwrap();
    assert!(built.starts_with("http://127.0.0.1:8788/"));
}

#[test]
fn runtime_request_input_rejects_secret_headers_from_react() {
    let input = RuntimeRequestInput {
        method: "GET".to_string(),
        path: "/api/v1/chat/history".to_string(),
        body: None,
        headers: vec![("X-Undefined-API-Key".to_string(), "leak".to_string())],
    };

    let err = input.validate().unwrap_err();
    assert!(err.contains("reserved header"));
}

#[test]
fn attachments_url_uses_normalized_runtime_base() {
    let value = attachments_url("http://127.0.0.1:8788///").unwrap();
    assert_eq!(value, "http://127.0.0.1:8788/api/v1/chat/attachments");
}

#[test]
fn attachments_url_rejects_query_and_fragment() {
    let query_err = attachments_url("http://127.0.0.1:8788?debug=true").unwrap_err();
    assert!(query_err.contains("runtime_url must not include a query"));

    let fragment_err = attachments_url("http://127.0.0.1:8788#runtime").unwrap_err();
    assert!(fragment_err.contains("runtime_url must not include a fragment"));
}

#[test]
fn html_preview_csp_blocks_network_and_eval() {
    let document = preview_document("Report", "<p>Hello</p>");

    assert!(document.contains("default-src 'none'"));
    assert!(document.contains("connect-src 'none'"));
    assert!(document.contains("form-action 'none'"));
    assert!(document.contains("object-src 'none'"));
    assert!(document.contains("base-uri 'none'"));
    assert!(document.contains("frame-ancestors 'none'"));
    assert!(document.contains("navigate-to 'none'"));
    assert!(document.contains("img-src data: blob:"));
    assert!(document.contains("media-src data: blob:"));
    assert!(document.contains("style-src 'unsafe-inline'"));
    assert!(document.contains("script-src 'none'"));
    assert!(!document.contains("script-src 'unsafe-inline'"));
    assert!(!document.contains("unsafe-eval"));
}

#[test]
fn html_preview_navigation_guard_allows_only_initial_url() {
    let initial_url = build_preview_data_url("Report", "<p>Hello</p>").unwrap();

    assert!(preview_navigation_allowed(&initial_url, &initial_url));
    assert!(preview_navigation_allowed(
        &url::Url::parse("about:blank").unwrap(),
        &initial_url
    ));
    assert!(!preview_navigation_allowed(
        &url::Url::parse("data:text/html;charset=utf-8,%3Cscript%3Ealert(1)%3C%2Fscript%3E")
            .unwrap(),
        &initial_url
    ));
    assert!(!preview_navigation_allowed(
        &url::Url::parse("https://example.com").unwrap(),
        &initial_url
    ));
    let initial_file_url = url::Url::parse("file:///tmp/html-preview-safe.html").unwrap();
    assert!(preview_navigation_allowed(
        &initial_file_url,
        &initial_file_url
    ));
    assert!(!preview_navigation_allowed(
        &url::Url::parse("file:///tmp/other-preview.html").unwrap(),
        &initial_file_url
    ));
}

#[test]
fn html_preview_rejects_oversized_html() {
    let html = "a".repeat(MAX_PREVIEW_HTML_BYTES + 1);
    let err = build_preview_data_url("Too large", &html).unwrap_err();

    assert!(err.contains("html preview content is too large"));
    let err = preview_document_checked("Too large", &html).unwrap_err();
    assert!(err.contains("html preview content is too large"));
}

#[test]
fn html_preview_escapes_title() {
    let document = preview_document("A&B <C>", "<p>Hello</p>");
    let title = document
        .split_once("<title>")
        .and_then(|(_, rest)| rest.split_once("</title>"))
        .map(|(value, _)| value)
        .expect("preview document should include a title element");

    assert_eq!(title, "A&amp;B &lt;C&gt;");
    assert!(!title.contains("<C>"));
}

#[test]
fn attachment_file_name_uses_file_name_or_fallback() {
    assert_eq!(
        attachment_file_name(std::path::Path::new("/tmp/report.txt")),
        "report.txt"
    );
    assert_eq!(
        attachment_file_name(std::path::Path::new("/")),
        "attachment"
    );
}

#[test]
fn attachment_save_file_name_sanitizes_path_like_input() {
    assert_eq!(
        test_safe_file_name(Some("..\\evil\"/photo.png"), "attachment123"),
        "_evil__photo.png"
    );
    assert_eq!(
        test_safe_file_name(Some(".."), "attachment123"),
        "attachment"
    );
}

#[test]
fn upload_file_path_parser_keeps_android_content_uri_as_url() {
    let path = parse_file_path("content://media/external/images/media/42").unwrap();
    assert!(path.as_path().is_none());
    assert_eq!(path.to_string(), "content://media/external/images/media/42");
}

#[test]
fn upload_file_path_parser_accepts_file_uri_and_plain_path() {
    let file_uri = parse_file_path("file:///tmp/report.txt").unwrap();
    assert!(file_uri.as_path().is_none());
    assert_eq!(
        file_uri.clone().into_path().unwrap(),
        std::path::PathBuf::from("/tmp/report.txt")
    );

    let plain_path = parse_file_path("/tmp/report.txt").unwrap();
    assert_eq!(
        plain_path.as_path(),
        Some(std::path::Path::new("/tmp/report.txt"))
    );
}

#[test]
fn upload_input_rejects_runtime_url_and_api_key_from_react() {
    let err = serde_json::from_value::<UploadAttachmentInput>(serde_json::json!({
        "runtimeUrl": "http://127.0.0.1:8788",
        "apiKey": "secret-api-key",
        "filePath": "/tmp/report.txt"
    }))
    .unwrap_err();

    assert!(err.to_string().contains("unknown field"));
    assert!(!err.to_string().contains("secret-api-key"));
}

#[test]
fn sse_input_rejects_runtime_url_and_api_key_from_react() {
    let err = serde_json::from_value::<StartJobEventStreamInput>(serde_json::json!({
        "runtimeUrl": "http://127.0.0.1:8788",
        "apiKey": "secret-api-key",
        "jobId": "job-123",
        "afterSeq": 0
    }))
    .unwrap_err();

    assert!(err.to_string().contains("unknown field"));
    assert!(!err.to_string().contains("secret-api-key"));
}

#[test]
fn utf8_chunk_decoder_preserves_split_multibyte_sequence() {
    let mut decoder = Utf8ChunkDecoder::default();
    let value = "data: 中文\n\n".as_bytes();

    assert_eq!(
        decoder.decode_chunk(&value[..7]).unwrap(),
        Some("data: ".to_string())
    );
    assert_eq!(decoder.decode_chunk(&value[7..8]).unwrap(), None);
    assert_eq!(
        decoder.decode_chunk(&value[8..]).unwrap(),
        Some("中文\n\n".to_string())
    );
}

#[test]
fn runtime_health_preserves_status_when_body_read_fails() {
    let health = runtime_health_from_body_result(503, false, Err("body read failed".to_string()));

    assert!(!health.ok);
    assert_eq!(health.status, 503);
    assert_eq!(health.body, "");
}

#[test]
fn sse_parser_emits_typed_events_and_tracks_last_sequence() {
    let parsed = parse_sse_chunks(&[
        "id: 2\nevent: progress\ndata: {\"stage\":\"thinking\"}\n\n",
        ": keepalive\n\nid: 3\ndata: {\"message\":\"done\"}\n\n",
    ])
    .unwrap();

    assert_eq!(parsed.last_seq, 3);
    assert_eq!(parsed.events.len(), 2);
    assert_eq!(parsed.events[0].seq, 2);
    assert_eq!(parsed.events[0].event_type.as_deref(), Some("progress"));
    assert_eq!(parsed.events[0].payload["stage"], "thinking");
    assert_eq!(parsed.events[1].seq, 3);
    assert_eq!(parsed.events[1].payload["message"], "done");
}

#[test]
fn sse_parser_buffers_incomplete_frames_across_chunks() {
    let parsed = parse_sse_chunks(&[
        "id: 9\ndata: {\"message\":\"hel",
        "lo\"}\n\nid: 10\ndata: {\"message\":\"next\"}\n\n",
    ])
    .unwrap();

    assert_eq!(parsed.last_seq, 10);
    assert_eq!(parsed.events.len(), 2);
    assert_eq!(parsed.events[0].payload["message"], "hello");
    assert_eq!(parsed.events[1].payload["message"], "next");
}

#[test]
fn secret_status_marks_degraded_detail() {
    let status = classify_secret_storage(false, "no native store");
    assert!(!status.available);
    assert!(status.degraded);
    assert_eq!(status.detail, "no native store");
}

#[test]
fn stronghold_key_derivation_returns_32_bytes() {
    let derived = derive_stronghold_key("vault-password");
    assert_eq!(derived.len(), 32);
    assert_ne!(derived, b"vault-password".to_vec());
}

#[test]
fn system_keyring_guard_allows_supported_desktop_targets() {
    assert!(supports_system_keyring_target("linux"));
    assert!(supports_system_keyring_target("macos"));
    assert!(supports_system_keyring_target("windows"));
}

#[test]
fn system_keyring_guard_rejects_targets_without_system_keyring_support() {
    assert!(!supports_system_keyring_target("android"));
    assert!(!supports_system_keyring_target("ios"));
}

#[test]
fn api_key_status_does_not_return_secret_material() {
    let status = load_api_key_status_from_value(Some("runtime-secret-key"));

    assert!(status.available);
    assert_eq!(status.key_preview.as_deref(), Some("runt...-key"));
    let serialized = serde_json::to_string(&status).unwrap();
    assert!(!serialized.contains("runtime-secret-key"));
}

#[test]
fn insecure_api_key_status_marks_degraded_without_returning_secret_material() {
    let status = api_key_status_from_storage(
        Some("runtime-secret-key"),
        "insecure-file",
        true,
        "local plaintext fallback",
    );

    assert!(status.available);
    assert!(status.degraded);
    assert_eq!(status.storage, "insecure-file");
    assert_eq!(status.detail, "local plaintext fallback");
    assert_eq!(status.key_preview.as_deref(), Some("runt...-key"));
    let serialized = serde_json::to_string(&status).unwrap();
    assert!(!serialized.contains("runtime-secret-key"));
}

#[test]
fn upload_skips_regular_file_metadata_check_for_android_content_uri() {
    let content_uri = parse_file_path("content://media/external/images/media/42").unwrap();
    assert!(!requires_regular_file_check(&content_uri));

    let plain_path = parse_file_path("/tmp/report.txt").unwrap();
    assert!(requires_regular_file_check(&plain_path));
}

#[test]
fn upload_command_uses_streaming_body() {
    assert!(upload_uses_streaming_body());
}
