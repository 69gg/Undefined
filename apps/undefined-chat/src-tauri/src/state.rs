use crate::config::normalize_runtime_url;
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
    sync::Mutex,
};
use tauri::{async_runtime::JoinHandle, AppHandle, Manager, State};
use uuid::Uuid;

pub const APP_CONFIG_FILE_NAME: &str = "runtime-config.json";
pub(crate) const RUNTIME_API_PREFIX: &str = "/api/v1/";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct AppRuntimeConfig {
    pub runtime_url: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RuntimeConfigInput {
    pub runtime_url: String,
}

impl AppRuntimeConfig {
    pub fn from_input(input: RuntimeConfigInput) -> Result<Self, String> {
        Ok(Self {
            runtime_url: normalize_runtime_url(&input.runtime_url)?,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeRequestPath {
    value: String,
}

impl RuntimeRequestPath {
    pub fn new(raw: &str) -> Result<Self, String> {
        let value = raw.trim();
        if value.is_empty() {
            return Err("runtime request path is required".to_string());
        }
        if value != raw {
            return Err("runtime request path must not include surrounding whitespace".to_string());
        }
        if value.contains("://") || value.starts_with("//") {
            return Err(
                "runtime request path must be relative to the configured Runtime".to_string(),
            );
        }
        if !value.starts_with(RUNTIME_API_PREFIX) {
            return Err(format!(
                "runtime request path must start with {RUNTIME_API_PREFIX}"
            ));
        }
        if value.contains('#') {
            return Err("runtime request path must not include a fragment".to_string());
        }
        if value.contains('\\') {
            return Err("runtime request path must not include backslashes".to_string());
        }
        if value.chars().any(|ch| ch.is_ascii_control() || ch == ' ') {
            return Err("runtime request path must be URL-encoded".to_string());
        }

        let path_part = value.split_once('?').map_or(value, |(path, _)| path);
        for segment in path_part.split('/') {
            if segment == "." || segment == ".." {
                return Err("runtime request path must not include path traversal".to_string());
            }
        }
        let lowercase = path_part.to_ascii_lowercase();
        if lowercase.contains("%2e") || lowercase.contains("%5c") {
            return Err("runtime request path must not include encoded path traversal".to_string());
        }

        Ok(Self {
            value: value.to_string(),
        })
    }

    pub fn as_str(&self) -> &str {
        &self.value
    }
}

pub(crate) struct EventStreamSubscription {
    pub handle: JoinHandle<()>,
}

#[derive(Default)]
pub struct NativeState {
    runtime_config: Mutex<Option<AppRuntimeConfig>>,
    insecure_storage_confirmed: Mutex<bool>,
    subscriptions: Mutex<HashMap<String, EventStreamSubscription>>,
}

impl NativeState {
    pub(crate) fn set_runtime_config_cache(
        &self,
        config: Option<AppRuntimeConfig>,
    ) -> Result<(), String> {
        let mut guard = self
            .runtime_config
            .lock()
            .map_err(|err| format!("runtime config state lock poisoned: {err}"))?;
        *guard = config;
        Ok(())
    }

    pub(crate) fn runtime_config_cache(&self) -> Result<Option<AppRuntimeConfig>, String> {
        self.runtime_config
            .lock()
            .map_err(|err| format!("runtime config state lock poisoned: {err}"))
            .map(|guard| guard.clone())
    }

    pub(crate) fn set_insecure_storage_confirmed(&self, value: bool) -> Result<(), String> {
        let mut guard = self
            .insecure_storage_confirmed
            .lock()
            .map_err(|err| format!("secret storage state lock poisoned: {err}"))?;
        *guard = value;
        Ok(())
    }

    pub(crate) fn insecure_storage_confirmed(&self) -> Result<bool, String> {
        self.insecure_storage_confirmed
            .lock()
            .map_err(|err| format!("secret storage state lock poisoned: {err}"))
            .map(|guard| *guard)
    }

    pub(crate) fn insert_subscription(
        &self,
        subscription_id: String,
        subscription: EventStreamSubscription,
    ) -> Result<(), String> {
        let mut guard = self
            .subscriptions
            .lock()
            .map_err(|err| format!("runtime SSE subscription lock poisoned: {err}"))?;
        guard.insert(subscription_id, subscription);
        Ok(())
    }

    pub(crate) fn stop_subscription(&self, subscription_id: &str) -> Result<bool, String> {
        let subscription = self
            .subscriptions
            .lock()
            .map_err(|err| format!("runtime SSE subscription lock poisoned: {err}"))?
            .remove(subscription_id);
        if let Some(subscription) = subscription {
            subscription.handle.abort();
            Ok(true)
        } else {
            Ok(false)
        }
    }

    pub(crate) fn remove_subscription(&self, subscription_id: &str) -> Result<(), String> {
        self.subscriptions
            .lock()
            .map_err(|err| format!("runtime SSE subscription lock poisoned: {err}"))?
            .remove(subscription_id);
        Ok(())
    }
}

pub(crate) fn app_config_file_path(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(app
        .path()
        .app_config_dir()
        .map_err(|err| format!("app config directory unavailable: {err}"))?
        .join(APP_CONFIG_FILE_NAME))
}

pub(crate) async fn write_json_file<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| "target file has no parent directory".to_string())?;
    tokio::fs::create_dir_all(parent)
        .await
        .map_err(|err| format!("config directory create failed: {err}"))?;

    let bytes = serde_json::to_vec_pretty(value)
        .map_err(|err| format!("config serialization failed: {err}"))?;
    let tmp_path = path.with_extension(format!("tmp-{}", Uuid::new_v4()));
    tokio::fs::write(&tmp_path, bytes)
        .await
        .map_err(|err| format!("config temp write failed: {err}"))?;
    tokio::fs::rename(&tmp_path, path)
        .await
        .map_err(|err| format!("config atomic rename failed: {err}"))?;
    Ok(())
}

pub(crate) async fn remove_file_if_exists(path: &Path) -> Result<(), String> {
    match tokio::fs::remove_file(path).await {
        Ok(()) => Ok(()),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(err) => Err(format!("file remove failed: {err}")),
    }
}

pub(crate) async fn read_runtime_config_file(
    app: &AppHandle,
) -> Result<Option<AppRuntimeConfig>, String> {
    let path = app_config_file_path(app)?;
    match tokio::fs::read(&path).await {
        Ok(bytes) => {
            let config: AppRuntimeConfig = serde_json::from_slice(&bytes)
                .map_err(|err| format!("runtime config parse failed: {err}"))?;
            Ok(Some(AppRuntimeConfig {
                runtime_url: normalize_runtime_url(&config.runtime_url)?,
            }))
        }
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(err) => Err(format!("runtime config read failed: {err}")),
    }
}

pub(crate) async fn load_runtime_config(
    app: &AppHandle,
    state: &NativeState,
) -> Result<Option<AppRuntimeConfig>, String> {
    if let Some(config) = state.runtime_config_cache()? {
        return Ok(Some(config));
    }
    let config = read_runtime_config_file(app).await?;
    if let Some(config) = config.clone() {
        state.set_runtime_config_cache(Some(config))?;
    }
    Ok(config)
}

pub(crate) async fn require_runtime_config(
    app: &AppHandle,
    state: &NativeState,
) -> Result<AppRuntimeConfig, String> {
    load_runtime_config(app, state)
        .await?
        .ok_or_else(|| "Runtime config is not saved".to_string())
}

#[tauri::command]
pub async fn get_runtime_config(
    app: AppHandle,
    state: State<'_, NativeState>,
) -> Result<Option<AppRuntimeConfig>, String> {
    let config = read_runtime_config_file(&app).await?;
    state.set_runtime_config_cache(config.clone())?;
    Ok(config)
}

#[tauri::command]
pub async fn save_runtime_config(
    app: AppHandle,
    state: State<'_, NativeState>,
    input: RuntimeConfigInput,
) -> Result<AppRuntimeConfig, String> {
    let config = AppRuntimeConfig::from_input(input)?;
    write_json_file(&app_config_file_path(&app)?, &config).await?;
    state.set_runtime_config_cache(Some(config.clone()))?;
    Ok(config)
}

#[tauri::command]
pub async fn clear_runtime_config(
    app: AppHandle,
    state: State<'_, NativeState>,
) -> Result<(), String> {
    remove_file_if_exists(&app_config_file_path(&app)?).await?;
    state.set_runtime_config_cache(None)?;
    Ok(())
}
