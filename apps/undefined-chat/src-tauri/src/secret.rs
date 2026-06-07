use serde::Serialize;
use sha2::{Digest, Sha256};
use std::sync::{Mutex, OnceLock};
use uuid::Uuid;

const KEYRING_SERVICE: &str = "com.undefined.chat";
const KEYRING_USER: &str = "stronghold-vault";
static VAULT_PASSWORD_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

#[derive(Debug, Clone, Serialize)]
pub struct SecretStatus {
    pub available: bool,
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
    // The PoC hashes a high-entropy random vault secret from keyring, not a user password.
    Sha256::digest(password.as_bytes()).to_vec()
}

pub fn supports_system_keyring_target(target_os: &str) -> bool {
    matches!(target_os, "linux" | "macos" | "windows")
}

fn unsupported_keyring_detail(target_os: &str) -> String {
    format!(
        "system keyring unsupported for target_os={target_os}; mobile secure storage is not implemented in this PoC"
    )
}

fn vault_entry() -> Result<keyring::Entry, String> {
    if !supports_system_keyring_target(std::env::consts::OS) {
        return Err(unsupported_keyring_detail(std::env::consts::OS));
    }

    keyring::Entry::new(KEYRING_SERVICE, KEYRING_USER)
        .map_err(|err| format!("keyring unavailable: {err}"))
}

#[tauri::command]
pub fn probe_secret_storage() -> SecretStatus {
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

#[tauri::command]
pub fn ensure_vault_password() -> Result<String, String> {
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
