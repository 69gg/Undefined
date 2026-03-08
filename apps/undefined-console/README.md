# Undefined Console

A `Tauri v2` management client for Undefined that targets the remote Management API and Runtime API.

## Goals

- Desktop builds for `Windows`, `macOS`, and `Linux`
- Android build support from the same codebase
- Mobile-friendly shell for connecting to remote instances
- Separate connection profiles for `Management` and `Runtime-only` modes

## Scripts

```bash
npm install
npm run dev           # Vite web shell
npm run build         # Shared frontend bundle
npm run tauri:dev     # Desktop development shell
npm run tauri:build   # Desktop production bundles
npm run tauri:android -- --apk
```

## Connection model

- **Management mode**: connect with `management_url` and a password/token flow.
- **Runtime-only mode**: connect with `runtime_url` and `X-Undefined-API-Key` compatible credentials.

This scaffold intentionally keeps the frontend shell lightweight. It is suitable for embedding into both browser-hosted WebUI and Tauri clients.

## Android notes

The release workflow expects the Android SDK and Java 17. If signing secrets are configured, the workflow should be upgraded to emit a signed release APK/AAB. The current scaffold always emits an installable APK artifact and makes signing expectations explicit in the CI comments.
