pub mod config;
mod secret;

#[cfg(test)]
mod poc_tests;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_stronghold::Builder::new(secret::derive_stronghold_key).build())
        .invoke_handler(tauri::generate_handler![
            secret::probe_secret_storage,
            secret::ensure_vault_password,
        ])
        .run(tauri::generate_context!())
        .expect("failed to run Undefined Chat app");
}
