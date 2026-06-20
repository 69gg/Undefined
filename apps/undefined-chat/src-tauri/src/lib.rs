pub mod config;
mod download;
mod mobile_secret;
mod platform;
mod preview;
mod runtime_client;
mod secret;
pub mod state;
mod upload;

#[cfg(test)]
mod native_tests;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(state::NativeState::default())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_stronghold::Builder::new(secret::derive_stronghold_key).build())
        .plugin(mobile_secret::init())
        .invoke_handler(tauri::generate_handler![
            state::get_runtime_config,
            state::save_runtime_config,
            state::clear_runtime_config,
            secret::save_api_key,
            secret::load_api_key_status,
            secret::delete_api_key,
            secret::unlock_vault,
            secret::confirm_insecure_storage_fallback,
            runtime_client::probe_runtime,
            runtime_client::runtime_request,
            runtime_client::list_conversations,
            runtime_client::get_history,
            runtime_client::get_active_jobs,
            runtime_client::send_message,
            runtime_client::cancel_job,
            runtime_client::list_commands,
            runtime_client::fetch_job_events_json,
            runtime_client::start_job_event_stream,
            runtime_client::stop_job_event_stream,
            download::save_attachment,
            download::preview_attachment_bytes,
            preview::open_html_preview,
            secret::probe_secret_storage,
            upload::upload_attachment_streaming,
            platform::get_platform_info,
        ])
        .run(tauri::generate_context!())
        .expect("failed to run Undefined Chat app");
}
