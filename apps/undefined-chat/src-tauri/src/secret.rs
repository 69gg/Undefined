use crate::{
    mobile_secret,
    state::{remove_file_if_exists, write_json_file, NativeState},
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    path::PathBuf,
    sync::{Mutex, OnceLock},
};
use tauri::{AppHandle, Manager, State};
use uuid::Uuid;

const KEYRING_SERVICE: &str = "com.undefined.chat";
const KEYRING_USER: &str = "stronghold-vault";
const API_KEY_USER: &str = "runtime-api-key";
const INSECURE_API_KEY_FILE_NAME: &str = "runtime-api-key.insecure.json";
static VAULT_PASSWORD_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

#[derive(Debug, Clone, Serialize)]
pub struct SecretStatus {
    pub available: bool,
    pub degraded: bool,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ApiKeyStatus {
    pub available: bool,
    pub storage: String,
    pub degraded: bool,
    pub key_preview: Option<String>,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct VaultUnlockStatus {
    pub unlocked: bool,
    pub storage: String,
    pub degraded: bool,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct InsecureApiKeyFile {
    api_key: String,
}

#[derive(Debug, Clone)]
pub(crate) struct StoredApiKey {
    pub value: String,
    pub storage: &'static str,
    pub degraded: bool,
    pub detail: String,
}

pub fn classify_secret_storage(available: bool, detail: &str) -> SecretStatus {
    SecretStatus {
        available,
        degraded: !available,
        detail: detail.to_string(),
    }
}

pub fn derive_stronghold_key(password: &str) -> Vec<u8> {
    // Stronghold receives a high-entropy random vault secret from keyring, not a user password.
    Sha256::digest(password.as_bytes()).to_vec()
}

pub fn supports_system_keyring_target(target_os: &str) -> bool {
    matches!(target_os, "linux" | "macos" | "windows" | "ios")
}

pub fn supports_secure_api_key_target(target_os: &str) -> bool {
    supports_system_keyring_target(target_os)
        || mobile_secret::supports_android_secure_store_target(target_os)
}

fn insecure_api_key_file_path(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(app
        .path()
        .app_config_dir()
        .map_err(|err| format!("app config directory unavailable: {err}"))?
        .join(INSECURE_API_KEY_FILE_NAME))
}

fn unsupported_keyring_detail(target_os: &str) -> String {
    format!(
        "system keyring unsupported for target_os={target_os}; configure platform secure storage before saving secrets on this target"
    )
}

fn vault_entry() -> Result<keyring::Entry, String> {
    if !supports_system_keyring_target(std::env::consts::OS) {
        return Err(unsupported_keyring_detail(std::env::consts::OS));
    }

    keyring::Entry::new(KEYRING_SERVICE, KEYRING_USER)
        .map_err(|err| format!("keyring unavailable: {err}"))
}

fn api_key_entry() -> Result<keyring::Entry, String> {
    if !supports_system_keyring_target(std::env::consts::OS) {
        return Err(unsupported_keyring_detail(std::env::consts::OS));
    }

    keyring::Entry::new(KEYRING_SERVICE, API_KEY_USER)
        .map_err(|err| format!("keyring unavailable: {err}"))
}

#[tauri::command]
pub async fn probe_secret_storage(app: AppHandle) -> SecretStatus {
    if mobile_secret::supports_android_secure_store_target(std::env::consts::OS) {
        return match mobile_secret::is_available(&app).await {
            Ok(true) => classify_secret_storage(true, "Android secure storage available"),
            Ok(false) => classify_secret_storage(false, "Android secure storage unavailable"),
            Err(err) => classify_secret_storage(false, &err),
        };
    }

    match vault_entry() {
        Ok(entry) => match entry.get_password() {
            Ok(_) => classify_secret_storage(true, "system keyring available"),
            Err(keyring::Error::NoEntry) => classify_secret_storage(
                true,
                "system keyring available; vault password not initialized",
            ),
            Err(err) => classify_secret_storage(false, &format!("keyring read failed: {err}")),
        },
        Err(err) => classify_secret_storage(false, &err),
    }
}

pub(crate) fn ensure_vault_password() -> Result<String, String> {
    let lock = VAULT_PASSWORD_LOCK.get_or_init(|| Mutex::new(()));
    let _guard = lock
        .lock()
        .map_err(|err| format!("vault password lock poisoned: {err}"))?;

    let entry = vault_entry()?;
    match entry.get_password() {
        Ok(password) => Ok(password),
        Err(keyring::Error::NoEntry) => {
            let password = Uuid::new_v4().to_string();
            entry
                .set_password(&password)
                .map_err(|err| format!("keyring write failed: {err}"))?;
            Ok(password)
        }
        Err(err) => Err(format!("keyring read failed: {err}")),
    }
}

async fn read_insecure_api_key(app: &AppHandle) -> Result<Option<String>, String> {
    let path = insecure_api_key_file_path(app)?;
    match tokio::fs::read(&path).await {
        Ok(bytes) => {
            let stored: InsecureApiKeyFile = serde_json::from_slice(&bytes)
                .map_err(|err| format!("insecure API key fallback parse failed: {err}"))?;
            let value = stored.api_key.trim().to_string();
            if value.is_empty() {
                Ok(None)
            } else {
                Ok(Some(value))
            }
        }
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(err) => Err(format!("insecure API key fallback read failed: {err}")),
    }
}

async fn write_insecure_api_key(app: &AppHandle, api_key: &str) -> Result<(), String> {
    write_json_file(
        &insecure_api_key_file_path(app)?,
        &InsecureApiKeyFile {
            api_key: api_key.to_string(),
        },
    )
    .await
    .map_err(|err| format!("insecure API key fallback write failed: {err}"))
}

async fn delete_insecure_api_key(app: &AppHandle) -> Result<(), String> {
    remove_file_if_exists(&insecure_api_key_file_path(app)?)
        .await
        .map_err(|err| format!("insecure API key fallback delete failed: {err}"))
}

fn api_key_preview(value: &str) -> String {
    let mut chars = value.chars();
    let prefix: String = chars.by_ref().take(4).collect();
    let suffix_chars: Vec<char> = value.chars().rev().take(4).collect();
    let suffix: String = suffix_chars.into_iter().rev().collect();
    if value.chars().count() <= 8 {
        "****".to_string()
    } else {
        format!("{prefix}...{suffix}")
    }
}

pub fn api_key_status_from_storage(
    value: Option<&str>,
    storage: &str,
    degraded: bool,
    detail: &str,
) -> ApiKeyStatus {
    match value {
        Some(api_key) if !api_key.is_empty() => ApiKeyStatus {
            available: true,
            storage: storage.to_string(),
            degraded,
            key_preview: Some(api_key_preview(api_key)),
            detail: detail.to_string(),
        },
        _ => ApiKeyStatus {
            available: false,
            storage: storage.to_string(),
            degraded,
            key_preview: None,
            detail: detail.to_string(),
        },
    }
}

pub fn load_api_key_status_from_value(value: Option<&str>) -> ApiKeyStatus {
    api_key_status_from_storage(
        value,
        "system-keyring",
        false,
        if value.is_some() {
            "Runtime API key saved"
        } else {
            "Runtime API key is not saved"
        },
    )
}

pub(crate) fn empty_api_key_status_for_target(target_os: &str) -> ApiKeyStatus {
    api_key_status_from_storage(
        None,
        if mobile_secret::supports_android_secure_store_target(target_os) {
            "android-secure-store"
        } else {
            "system-keyring"
        },
        false,
        "Runtime API key is not saved",
    )
}

pub(crate) async fn load_api_key_with_storage(
    app: &AppHandle,
) -> Result<Option<StoredApiKey>, String> {
    if mobile_secret::supports_android_secure_store_target(std::env::consts::OS) {
        match mobile_secret::get_secret(app, API_KEY_USER).await {
            Ok(Some(value)) => {
                return Ok(Some(StoredApiKey {
                    value,
                    storage: "android-secure-store",
                    degraded: false,
                    detail: "Runtime API key saved in Android secure storage".to_string(),
                }));
            }
            Ok(None) => {
                return Ok(read_insecure_api_key(app).await?.map(|value| StoredApiKey {
                    value,
                    storage: "insecure-file",
                    degraded: true,
                    detail: "Runtime API key loaded from explicitly confirmed insecure fallback"
                        .to_string(),
                }));
            }
            Err(err) => {
                let fallback = read_insecure_api_key(app).await?;
                if let Some(value) = fallback {
                    return Ok(Some(StoredApiKey {
                        value,
                        storage: "insecure-file",
                        degraded: true,
                        detail: format!(
                            "Runtime API key loaded from insecure fallback after Android secure storage read failed: {err}"
                        ),
                    }));
                }
                return Err(err);
            }
        }
    }

    match api_key_entry() {
        Ok(entry) => match entry.get_password() {
            Ok(value) => Ok(Some(StoredApiKey {
                value,
                storage: "system-keyring",
                degraded: false,
                detail: "Runtime API key saved".to_string(),
            })),
            Err(keyring::Error::NoEntry) => read_insecure_api_key(app)
                .await?
                .map(|value| StoredApiKey {
                    value,
                    storage: "insecure-file",
                    degraded: true,
                    detail: "Runtime API key loaded from explicitly confirmed insecure fallback"
                        .to_string(),
                })
                .map_or(Ok(None), |value| Ok(Some(value))),
            Err(err) => {
                let fallback = read_insecure_api_key(app).await?;
                if let Some(value) = fallback {
                    Ok(Some(StoredApiKey {
                        value,
                        storage: "insecure-file",
                        degraded: true,
                        detail: format!(
                            "Runtime API key loaded from insecure fallback after keyring read failed: {err}"
                        ),
                    }))
                } else {
                    Err(format!("keyring read failed: {err}"))
                }
            }
        },
        Err(err) => {
            let fallback = read_insecure_api_key(app).await?;
            if let Some(value) = fallback {
                Ok(Some(StoredApiKey {
                    value,
                    storage: "insecure-file",
                    degraded: true,
                    detail: format!(
                        "Runtime API key loaded from insecure fallback after keyring unavailable: {err}"
                    ),
                }))
            } else {
                Err(err)
            }
        }
    }
}

pub(crate) async fn require_api_key(app: &AppHandle) -> Result<String, String> {
    load_api_key_with_storage(app)
        .await?
        .map(|stored| stored.value)
        .ok_or_else(|| "Runtime API key is not saved".to_string())
}

#[tauri::command]
pub async fn save_api_key(
    app: AppHandle,
    state: State<'_, NativeState>,
    api_key: String,
) -> Result<ApiKeyStatus, String> {
    let trimmed = api_key.trim();
    if trimmed.is_empty() {
        return Err("api_key is required".to_string());
    }
    if trimmed != api_key {
        return Err("api_key must not include surrounding whitespace".to_string());
    }

    match api_key_entry() {
        Err(_) if mobile_secret::supports_android_secure_store_target(std::env::consts::OS) => {
            match mobile_secret::set_secret(&app, API_KEY_USER, trimmed).await {
                Ok(()) => {
                    let _ = delete_insecure_api_key(&app).await;
                    Ok(api_key_status_from_storage(
                        Some(trimmed),
                        "android-secure-store",
                        false,
                        "Runtime API key saved in Android secure storage",
                    ))
                }
                Err(err) => {
                    if state.insecure_storage_confirmed()? {
                        write_insecure_api_key(&app, trimmed).await?;
                        Ok(api_key_status_from_storage(
                            Some(trimmed),
                            "insecure-file",
                            true,
                            &format!(
                                "Runtime API key saved to explicitly confirmed insecure fallback after Android secure storage write failed: {err}"
                            ),
                        ))
                    } else {
                        Err(format!(
                            "{err}; explicitly confirm insecure storage fallback to save a local plaintext API key"
                        ))
                    }
                }
            }
        }
        Ok(entry) => match entry.set_password(trimmed) {
            Ok(()) => {
                let _ = delete_insecure_api_key(&app).await;
                Ok(load_api_key_status_from_value(Some(trimmed)))
            }
            Err(err) => {
                if state.insecure_storage_confirmed()? {
                    write_insecure_api_key(&app, trimmed).await?;
                    Ok(api_key_status_from_storage(
                        Some(trimmed),
                        "insecure-file",
                        true,
                        &format!(
                            "Runtime API key saved to explicitly confirmed insecure fallback after keyring write failed: {err}"
                        ),
                    ))
                } else {
                    Err(format!(
                        "keyring write failed: {err}; explicitly confirm insecure storage fallback to save a local plaintext API key"
                    ))
                }
            }
        },
        Err(err) => {
            if state.insecure_storage_confirmed()? {
                write_insecure_api_key(&app, trimmed).await?;
                Ok(api_key_status_from_storage(
                    Some(trimmed),
                    "insecure-file",
                    true,
                    &format!(
                        "Runtime API key saved to explicitly confirmed insecure fallback after keyring unavailable: {err}"
                    ),
                ))
            } else {
                Err(format!(
                    "{err}; explicitly confirm insecure storage fallback to save a local plaintext API key"
                ))
            }
        }
    }
}

#[tauri::command]
pub async fn load_api_key_status(app: AppHandle) -> Result<ApiKeyStatus, String> {
    match load_api_key_with_storage(&app).await {
        Ok(Some(stored)) => Ok(api_key_status_from_storage(
            Some(&stored.value),
            stored.storage,
            stored.degraded,
            &stored.detail,
        )),
        Ok(None) => Ok(empty_api_key_status_for_target(std::env::consts::OS)),
        Err(err) => Ok(api_key_status_from_storage(
            None,
            "system-keyring",
            true,
            &err,
        )),
    }
}

#[tauri::command]
pub async fn delete_api_key(app: AppHandle) -> Result<ApiKeyStatus, String> {
    let mut delete_errors = Vec::new();
    if let Err(err) = mobile_secret::delete_secret(&app, API_KEY_USER).await {
        delete_errors.push(err);
    }
    if let Ok(entry) = api_key_entry() {
        match entry.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => {}
            Err(err) => delete_errors.push(format!("keyring delete failed: {err}")),
        }
    }
    if let Err(err) = delete_insecure_api_key(&app).await {
        delete_errors.push(err);
    }
    if delete_errors.is_empty() {
        Ok(empty_api_key_status_for_target(std::env::consts::OS))
    } else {
        Ok(api_key_status_from_storage(
            None,
            "unknown",
            true,
            &format!(
                "API key delete completed with storage errors: {}",
                delete_errors.join("; ")
            ),
        ))
    }
}

#[tauri::command]
pub fn unlock_vault() -> Result<VaultUnlockStatus, String> {
    ensure_vault_password().map(|_| VaultUnlockStatus {
        unlocked: true,
        storage: "system-keyring".to_string(),
        degraded: false,
        detail: "Stronghold vault key is initialized".to_string(),
    })
}

#[tauri::command]
pub async fn confirm_insecure_storage_fallback(
    app: AppHandle,
    state: State<'_, NativeState>,
) -> Result<ApiKeyStatus, String> {
    state.set_insecure_storage_confirmed(true)?;
    Ok(api_key_status_from_storage(
        read_insecure_api_key(&app).await?.as_deref(),
        "insecure-file",
        true,
        "Insecure storage fallback confirmed for this app session",
    ))
}
