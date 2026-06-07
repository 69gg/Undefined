use crate::config::normalize_runtime_url;
use crate::runtime_client::{job_events_url, runtime_health_from_body_result, Utf8ChunkDecoder};
use crate::secret::{
    classify_secret_storage, derive_stronghold_key, supports_system_keyring_target,
};
use crate::upload::{attachment_file_name, attachments_url};

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
fn system_keyring_guard_rejects_mobile_targets_for_this_poc() {
    assert!(!supports_system_keyring_target("android"));
    assert!(!supports_system_keyring_target("ios"));
}
