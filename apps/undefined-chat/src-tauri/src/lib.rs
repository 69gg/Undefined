fn derive_stronghold_key(password: &str) -> Vec<u8> {
    use sha2::{Digest, Sha256};
    Sha256::digest(password.as_bytes()).to_vec()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_stronghold::Builder::new(derive_stronghold_key).build())
        .run(tauri::generate_context!())
        .expect("failed to run Undefined Chat app");
}
