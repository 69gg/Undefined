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
npm run tauri:dev           # Desktop development shell
npm run tauri:build         # Desktop production bundles
npm run tauri:build:no-strip # Linux 本地打包失败时的 workaround
npm run tauri:android -- --apk
```

## Linux local build note

On some newer Linux distributions, local AppImage packaging may fail during the `linuxdeploy` stage due to `strip` compatibility. If that happens, use:

```bash
NO_STRIP=true npm run tauri:build
```

or:

```bash
npm run tauri:build:no-strip
```

## Connection model

- **Management mode**: connect with `management_url` and a password/token flow.
- **Runtime-only mode**: connect with `runtime_url` and `X-Undefined-API-Key` compatible credentials.

This scaffold intentionally keeps the frontend shell lightweight. It is suitable for embedding into both browser-hosted WebUI and Tauri clients.

## Android notes

The release workflow expects the Android SDK, Java 17, and Android signing secrets. It emits signed release APK artifacts per ABI.

## Android release signing

The Android application identifier is `com.undefined.console`.

The release workflow now expects these GitHub Actions secrets in the `release` environment:

- `ANDROID_KEYSTORE_BASE64`
- `ANDROID_KEYSTORE_PASSWORD`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`

Generate a keystore locally, for example:

```bash
keytool -genkeypair \
  -v \
  -keystore undefined-console-release.jks \
  -alias undefined-console \
  -keyalg RSA \
  -keysize 4096 \
  -validity 3650
```

Encode it for GitHub Secrets:

```bash
base64 -w 0 undefined-console-release.jks
```

Then store the resulting single-line Base64 string in `ANDROID_KEYSTORE_BASE64`, and put the matching passwords and alias into the other three secrets.

During the release workflow, CI will:

1. Decode the keystore into the runner temp directory.
2. Write `src-tauri/gen/android/keystore.properties`.
3. Patch the generated Android Gradle app module to attach the release signing config.
4. Build signed release APKs, one per ABI.
