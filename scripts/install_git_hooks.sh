#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

git config core.hooksPath .githooks

echo "已设置 git hooksPath -> .githooks"
echo "当前 pre-commit: .githooks/pre-commit"
