#!/usr/bin/env bash
# Run from an app directory, with RUNNER_OS supplied by GitHub Actions.
set -euo pipefail

bundles="${1:?Usage: build_tauri_desktop.sh <bundles> [rust-target]}"
rust_target="${2:-}"
: "${RUNNER_OS:?RUNNER_OS must identify the GitHub Actions runner}"

export CI=true
tauri_args=(--ci --bundles "$bundles")
if [[ -n "$rust_target" ]]; then
  tauri_args+=(--target "$rust_target")
fi
if [[ "$RUNNER_OS" == "Linux" ]]; then
  export NO_STRIP=true
elif [[ "$RUNNER_OS" == "macOS" ]]; then
  # Tauri otherwise hides the failing bundle_dmg.sh command's output.
  tauri_args+=(--verbose)
fi

build_log="$(mktemp)"
trap 'rm -f "$build_log"' EXIT
if npm run tauri:build -- "${tauri_args[@]}" 2>&1 | tee "$build_log"; then
  exit 0
else
  build_status=$?
fi

if [[ "$RUNNER_OS" != "macOS" || "$bundles" != "dmg" ]] \
  || ! grep -Fq 'error running bundle_dmg.sh' "$build_log"; then
  exit "$build_status"
fi

echo 'DMG script failed; retrying packaging once in 5 seconds without recompiling.' >&2
sleep 5
npm run tauri -- bundle "${tauri_args[@]}"
