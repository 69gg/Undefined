pub mod config;
mod preview;
mod runtime_client;
mod secret;
mod upload;

#[cfg(test)]
mod poc_tests;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_stronghold::Builder::new(secret::derive_stronghold_key).build())
        .invoke_handler(tauri::generate_handler![
            runtime_client::probe_runtime,
            runtime_client::start_job_event_stream,
            preview::open_html_preview,
            secret::probe_secret_storage,
            secret::ensure_vault_password,
            upload::upload_attachment_streaming,
        ])
        .run(tauri::generate_context!())
        .expect("failed to run Undefined Chat app");
}
