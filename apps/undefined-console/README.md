# Undefined Console

A `Tauri v2` management client for Undefined that targets the remote Management API and Runtime API.

## Goals

- Desktop builds for `Windows`, `macOS`, and `Linux`
- Android build support from the same codebase
- Mobile-friendly shell for connecting to remote instances
- Local connection profiles with separate Management and Runtime protocol/port settings

## Scripts

Biome is pinned to **2.5.10**, matching Chat and the root WebUI configuration. Use `npm ci` for reproducible installs and `npm run check` for the complete validation suite. The app's `biome.json` is an independent nested configuration (`root: false`); see [build documentation](../../docs/build.md#6-git-hook-集成).

```bash
npm ci
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

- **Management**: open the configured WebUI, optionally logging in with its management password before navigation.
- **Runtime**: probe the configured Runtime's `/health` and `/openapi.json`. Chat authentication is configured in Undefined Chat or the WebUI.

The connection editor stores a host and separate protocol/port choices for Management and Runtime. New profiles use HTTP by default; select HTTPS for TLS endpoints. Existing profiles using `managementUrl` / `runtimeUrl` are migrated with their original HTTP/HTTPS protocols and ports. IPv6 hosts accept either `::1` or `[::1]` and produce a URL with a single pair of brackets. Saving and reloading a migrated profile preserves these choices.

`npm test` runs the connection migration, save/reload, probe, and login regressions with in-memory storage and network/navigation stubs. It is included in `npm run check` and never contacts a real instance.

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
