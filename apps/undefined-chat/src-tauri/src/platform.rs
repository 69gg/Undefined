use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PlatformInfo {
    pub os: String,
    pub family: String,
    pub arch: String,
    pub debug: bool,
    pub supports_system_keyring: bool,
    pub supports_sse: bool,
    pub supports_html_preview: bool,
}

#[tauri::command]
pub fn get_platform_info() -> PlatformInfo {
    let os = std::env::consts::OS.to_string();
    PlatformInfo {
        supports_system_keyring: crate::secret::supports_system_keyring_target(&os),
        os,
        family: std::env::consts::FAMILY.to_string(),
        arch: std::env::consts::ARCH.to_string(),
        debug: cfg!(debug_assertions),
        supports_sse: true,
        supports_html_preview: true,
    }
}
