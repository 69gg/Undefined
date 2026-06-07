use crate::config::normalize_runtime_url;
use crate::runtime_client::job_events_url;
use crate::secret::{
    classify_secret_storage, derive_stronghold_key, supports_system_keyring_target,
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
