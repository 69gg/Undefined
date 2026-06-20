#[cfg(target_os = "android")]
use serde::{Deserialize, Serialize};
use tauri::AppHandle;
#[cfg(target_os = "android")]
use tauri::Manager;

#[cfg(target_os = "android")]
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SecretPayload<'a> {
    key: &'a str,
}

#[cfg(target_os = "android")]
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct SetSecretPayload<'a> {
    key: &'a str,
    value: &'a str,
}

#[cfg(target_os = "android")]
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SecretResponse {
    value: Option<String>,
}

#[cfg(target_os = "android")]
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AvailabilityResponse {
    available: bool,
}

pub fn supports_android_secure_store_target(target_os: &str) -> bool {
    target_os == "android"
}

#[cfg(any(target_os = "android", test))]
pub(crate) fn android_secret_plugin_identifier(app_identifier: &str) -> &str {
    app_identifier
}

#[cfg(target_os = "android")]
pub fn init<R: tauri::Runtime>() -> tauri::plugin::TauriPlugin<R> {
    tauri::plugin::Builder::new("undefined-chat-secret")
        .setup(|app, api| {
            let handle = api.register_android_plugin(
                android_secret_plugin_identifier(&app.config().identifier),
                "SecretPlugin",
            )?;
            app.manage(handle);
            Ok(())
        })
        .build()
}

#[cfg(not(target_os = "android"))]
pub fn init<R: tauri::Runtime>() -> tauri::plugin::TauriPlugin<R> {
    tauri::plugin::Builder::new("undefined-chat-secret").build()
}

#[cfg(target_os = "android")]
fn plugin(app: &AppHandle) -> Result<tauri::plugin::PluginHandle<tauri::Wry>, String> {
    app.try_state::<tauri::plugin::PluginHandle<tauri::Wry>>()
        .map(|state| state.inner().clone())
        .ok_or_else(|| "Android secure storage plugin is not initialized".to_string())
}

#[cfg(target_os = "android")]
pub async fn is_available(app: &AppHandle) -> Result<bool, String> {
    let response = plugin(app)?
        .run_mobile_plugin_async::<AvailabilityResponse>("isAvailable", serde_json::json!({}))
        .await
        .map_err(|err| format!("Android secure storage probe failed: {err}"))?;
    Ok(response.available)
}

#[cfg(not(target_os = "android"))]
pub async fn is_available(_app: &AppHandle) -> Result<bool, String> {
    Ok(false)
}

#[cfg(target_os = "android")]
pub async fn get_secret(app: &AppHandle, key: &str) -> Result<Option<String>, String> {
    let response = plugin(app)?
        .run_mobile_plugin_async::<SecretResponse>("getSecret", SecretPayload { key })
        .await
        .map_err(|err| format!("Android secure storage read failed: {err}"))?;
    Ok(response.value)
}

#[cfg(not(target_os = "android"))]
pub async fn get_secret(_app: &AppHandle, _key: &str) -> Result<Option<String>, String> {
    Ok(None)
}

#[cfg(target_os = "android")]
pub async fn set_secret(app: &AppHandle, key: &str, value: &str) -> Result<(), String> {
    plugin(app)?
        .run_mobile_plugin_async::<serde_json::Value>("setSecret", SetSecretPayload { key, value })
        .await
        .map_err(|err| format!("Android secure storage write failed: {err}"))?;
    Ok(())
}

#[cfg(not(target_os = "android"))]
pub async fn set_secret(_app: &AppHandle, _key: &str, _value: &str) -> Result<(), String> {
    Err("Android secure storage is unavailable on this platform".to_string())
}

#[cfg(target_os = "android")]
pub async fn delete_secret(app: &AppHandle, key: &str) -> Result<(), String> {
    plugin(app)?
        .run_mobile_plugin_async::<serde_json::Value>("deleteSecret", SecretPayload { key })
        .await
        .map_err(|err| format!("Android secure storage delete failed: {err}"))?;
    Ok(())
}

#[cfg(not(target_os = "android"))]
pub async fn delete_secret(_app: &AppHandle, _key: &str) -> Result<(), String> {
    Ok(())
}
