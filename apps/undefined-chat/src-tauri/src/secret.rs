use serde::Serialize;
use sha2::{Digest, Sha256};
use uuid::Uuid;

const KEYRING_SERVICE: &str = "com.undefined.chat";
const KEYRING_USER: &str = "stronghold-vault";

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
    Sha256::digest(password.as_bytes()).to_vec()
}

fn vault_entry() -> Result<keyring::Entry, String> {
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
        Err(err) => classify_secret_storage(false, &format!("keyring unavailable: {err}")),
    }
}

#[tauri::command]
pub fn ensure_vault_password() -> Result<String, String> {
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
