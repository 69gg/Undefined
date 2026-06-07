use url::Url;

pub fn normalize_runtime_url(raw: &str) -> Result<String, String> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err("runtime_url is required".to_string());
    }

    let parsed = Url::parse(trimmed).map_err(|err| format!("invalid runtime_url: {err}"))?;
    match parsed.scheme() {
        "http" | "https" => {}
        scheme => return Err(format!("unsupported runtime_url scheme: {scheme}")),
    }

    let mut normalized = parsed.to_string();
    while normalized.ends_with('/') {
        normalized.pop();
    }
    Ok(normalized)
}
