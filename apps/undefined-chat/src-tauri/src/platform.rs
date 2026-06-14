use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PlatformInfo {
    pub os: String,
    pub family: String,
    pub arch: String,
    pub debug: bool,
    pub supports_system_keyring: bool,
    pub supports_secure_api_key_storage: bool,
    pub supports_sse: bool,
    pub supports_html_preview: bool,
}

pub(crate) fn platform_info_for_target(os: &str, family: &str, arch: &str) -> PlatformInfo {
    PlatformInfo {
        supports_system_keyring: crate::secret::supports_system_keyring_target(os),
        supports_secure_api_key_storage: crate::secret::supports_secure_api_key_target(os),
        os: os.to_string(),
        family: family.to_string(),
        arch: arch.to_string(),
        debug: cfg!(debug_assertions),
        supports_sse: true,
        supports_html_preview: true,
    }
}

#[tauri::command]
pub fn get_platform_info() -> PlatformInfo {
    platform_info_for_target(
        std::env::consts::OS,
        std::env::consts::FAMILY,
        std::env::consts::ARCH,
    )
}
