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

/// 各平台是否支持原生 HTML 预览窗口。
///
/// - 桌面端（windows/macos/linux）：通过 `WebviewWindowBuilder` 弹出独立预览窗口。
/// - android：有专用的 `HtmlPreviewActivity` 承载预览窗口（见 `preview::open_html_preview`）。
/// - ios：缺少对应 Activity，无法承载外部预览窗口，诚实降级为不支持。
pub(crate) fn supports_html_preview_target(os: &str) -> bool {
    matches!(os, "windows" | "macos" | "linux" | "android")
}

/// 各平台是否支持 SSE 流式（基于 HTTP 流，全平台可用）。
pub(crate) fn supports_sse_target(os: &str) -> bool {
    let _ = os;
    true
}

pub(crate) fn platform_info_for_target(os: &str, family: &str, arch: &str) -> PlatformInfo {
    PlatformInfo {
        supports_system_keyring: crate::secret::supports_system_keyring_target(os),
        supports_secure_api_key_storage: crate::secret::supports_secure_api_key_target(os),
        os: os.to_string(),
        family: family.to_string(),
        arch: arch.to_string(),
        debug: cfg!(debug_assertions),
        supports_sse: supports_sse_target(os),
        supports_html_preview: supports_html_preview_target(os),
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
